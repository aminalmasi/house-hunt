"""Run the judge over tests/sample_posts.jsonl and score it against expected verdicts.

  python scripts/test_judge.py MODEL_PATH [MODEL_PATH ...]

Expected verdicts live in profiles/expected_<name>.json (not in git).
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hh.extract import LocalLLM  # noqa: E402
from hh.judge import Judge  # noqa: E402

TODAY = "2026-10-03"


def run(model_path):
    posts = [json.loads(l) for l in open(ROOT / "tests/sample_posts.jsonl")]
    profiles = json.load(open(ROOT / "profiles/profiles.json"))
    expected = {p["name"]: json.load(open(ROOT / f"profiles/expected_{p['name'].lower()}.json")) for p in profiles}
    t0 = time.time()
    llm = LocalLLM(model_path)
    print(f"\n===== {llm.name} (load {time.time() - t0:.0f}s)", flush=True)
    judge = Judge(llm, profiles, TODAY)
    score = {p["name"]: 0 for p in profiles}
    t1 = time.time()
    for post in posts:
        r = judge(post["id"], post["text"])
        for p in profiles:
            name = p["name"]
            want, _, need = expected[name][post["id"]].partition(":")
            if "duplicate_of" in r:
                got, why = "duplicate", [f"same as {r['duplicate_of']}"]
            else:
                got, why = r["decisions"][name]
            ok = got == want and (not need or any(need in w for w in why))
            want = want + (f" + '{need}'" if need else "")
            score[name] += ok
            print(f"{'OK ' if ok else 'XX '} {post['id']} {name}: {got:<9} (want {want:<20}) {'; '.join(why)}", flush=True)
            if not ok and "facts" in r:
                f = r["facts"] or {}
                print(f"      area={r['area']} {r['area_hits']} facts={json.dumps({k: f.get(k) for k in ('kind', 'units', 'available_from', 'gender', 'tenant', 'room_location', 'nearby')}, ensure_ascii=False)}")
                if r.get("raw"):
                    print("      raw:", r["raw"][:400].replace("\n", " "))
    n = len(posts)
    per = (time.time() - t1) / n
    print(f"RESULT {llm.name}: " + ", ".join(f"{k} {v}/{n}" for k, v in score.items()) + f" | {per:.1f}s per post", flush=True)
    del judge, llm
    import gc, torch
    gc.collect(); torch.cuda.empty_cache()


if __name__ == "__main__":
    for m in sys.argv[1:]:
        run(m)
