"""The always-on loop: inbox -> judge -> Telegram, once a minute.

  python -m hh.run --model /extra/malmasik/hf_models/Qwen3.5-4B

Everything it decides is appended to data/judged.jsonl (one line per post), which
is also how the duplicate check survives a restart. Alerts that could not be
sent stay in data/pending.jsonl and are retried on the next round.
"""
import argparse
import json
import os
import time
import traceback
from datetime import date
from pathlib import Path

from .extract import LocalLLM
from .judge import Judge
from .mail import Inbox
from .notify import find_chat_id, format_alert, send

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
ENV = Path(os.path.expanduser("~/.config/house-hunt.env"))


def load_env():
    return dict(l.rstrip("\n").split("=", 1) for l in open(ENV) if "=" in l)


def log(*a):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), *a, flush=True)


def channels(env, profiles):
    """profile name -> (bot token, chat id); ids are cached once found."""
    cache_path = DATA / "channel_ids.json"
    cache = json.load(open(cache_path)) if cache_path.exists() else {}
    out = {}
    for i, p in enumerate(profiles, 1):
        token, title = env.get(f"BOT_TOKEN_{i}"), env.get(f"CHANNEL_{i}")
        if not token:
            continue
        if p["name"] not in cache and title:
            cid = find_chat_id(token, title)
            if cid:
                cache[p["name"]] = cid
                json.dump(cache, open(cache_path, "w"))
                log(f"found channel for {p['name']}")
        if p["name"] in cache:
            out[p["name"]] = (token, cache[p["name"]])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--every", type=int, default=60, help="seconds between inbox checks")
    args = ap.parse_args()

    DATA.mkdir(exist_ok=True)
    env = load_env()
    profiles = json.load(open(ROOT / "profiles/profiles.json"))
    inbox = Inbox(env["GMAIL_ADDRESS"], env["GMAIL_APP_PASSWORD"])
    judge = Judge(LocalLLM(args.model), profiles, date.today().isoformat())
    judged_path, pending_path = DATA / "judged.jsonl", DATA / "pending.jsonl"
    if judged_path.exists():
        for line in open(judged_path):
            r = json.loads(line)
            if "text" in r:
                judge.dedup.add(r["id"], r["text"])
    log(f"ready: model={judge.llm.name}, {len(judge.dedup.seen)} earlier posts loaded for dedup")

    failures = 0
    while True:
        try:
            judge.today = date.today().isoformat()
            chans = channels(env, profiles)
            pending = [json.loads(l) for l in open(pending_path)] if pending_path.exists() else []
            for post in inbox.fetch_new():
                r = judge(post["id"], post["text"])
                r.update({k: post[k] for k in ("text", "group", "url", "uid", "date")})
                with open(judged_path, "a") as f:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
                if "duplicate_of" in r:
                    log(f"{post['id']} duplicate of {r['duplicate_of']}")
                    continue
                for name, (verdict, reasons) in r["decisions"].items():
                    log(f"{post['id']} {name}: {verdict} {'; '.join(reasons)}")
                    if verdict in ("match", "maybe"):
                        pending.append({"name": name, "text": format_alert(
                            verdict, reasons, post, r["facts"], r["area_hits"])})
            still = []
            for a in pending:
                if a["name"] not in chans:
                    still.append(a)
                    continue
                try:
                    send(*chans[a["name"]], a["text"])
                except Exception as e:
                    log("send failed:", e)
                    still.append(a)
            with open(pending_path, "w") as f:
                f.writelines(json.dumps(a, ensure_ascii=False) + "\n" for a in still)
            if still:
                log(f"{len(still)} alerts waiting (no channel yet or send failed)")
            failures = 0
            (DATA / "heartbeat").touch()  # touched only after a fully successful round
        except Exception:
            failures += 1
            log(f"round failed ({failures} in a row):\n{traceback.format_exc()}")
            if failures == 10:
                for token, cid in channels(env, profiles).values():
                    try:
                        send(token, cid, "⚠️ house-hunt: the inbox check has failed 10 times in a row. Check logs/.")
                    except Exception:
                        pass
        time.sleep(args.every)


if __name__ == "__main__":
    main()
