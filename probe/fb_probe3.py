"""Round 3: does replaying Facebook's own feed request work, and what does it cost?

1. Open one readable group and scroll, capturing the GraphQL request the page
   itself sends to load more posts (friendly name ...Feed...PaginationQuery).
2. For every group: find its numeric id, then re-send that request from inside
   the page (same session, same proxy) with cursor=None and chronological order,
   i.e. "give me the newest posts".
3. Count wire bytes with Chrome's own counter and check what came back:
   number of posts, whether they have text, how old the newest one is.

Public repo: only counts/ages are printed, never names, URLs or text.
"""
import json
import os
import re
import time
from urllib.parse import parse_qsl, urlparse

from playwright.sync_api import sync_playwright

from fb_probe import load_cookies, proxy_cfg
from fb_probe2 import DESKTOP_UA, WireCounter

BLOCK_TYPES = {"image", "media", "font"}


def find_posts(obj, out):
    """Collect story-like dicts: they carry a creation_time and a message text somewhere below."""
    if isinstance(obj, dict):
        if "creation_time" in obj and isinstance(obj["creation_time"], int):
            s = json.dumps(obj)
            m = re.search(r'"message":\s*\{[^{}]*?"text":\s*"((?:[^"\\]|\\.)*)"', s)
            out.append({"t": obj["creation_time"], "text_len": len(m.group(1)) if m else 0})
        for v in obj.values():
            find_posts(v, out)
    elif isinstance(obj, list):
        for v in obj:
            find_posts(v, out)


def parse_stream(body):
    posts = []
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("for (;;);"):
            line = line[9:]
        if not line.startswith("{"):
            continue
        try:
            find_posts(json.loads(line), posts)
        except json.JSONDecodeError:
            pass
    uniq = {(p["t"], p["text_len"]) for p in posts}
    return sorted(uniq, reverse=True)


def main():
    shares = [g.strip() for g in os.environ["FB_GROUPS"].splitlines() if g.strip()]
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, proxy=proxy_cfg())
        ctx = browser.new_context(user_agent=DESKTOP_UA, locale="it-IT",
                                  viewport={"width": 1280, "height": 900})
        ctx.add_cookies(load_cookies())
        ctx.route("**/*", lambda r: r.abort() if r.request.resource_type in BLOCK_TYPES else r.continue_())
        page = ctx.new_page()
        wc = WireCounter(page)

        # numeric group ids (one full page load per group; in production this runs once and is cached)
        gids, setup_bytes = [], 0
        for s in shares:
            wc.bytes = 0
            page.goto(s, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(2500)
            m = re.search(r'"groupID":"(\d+)"', page.content())
            gids.append(m.group(1) if m else None)
            setup_bytes += wc.bytes
            time.sleep(3)
        print("numeric ids found:", sum(1 for g in gids if g), "/", len(gids),
              f"| one-time setup {setup_bytes / 1024 / 1024:.1f} MB", flush=True)

        # capture the feed pagination request from the first group that has one
        captured, seen_names = {}, set()

        def on_req(req):
            if "/api/graphql" in req.url and req.method == "POST":
                seen_names.add(req.headers.get("x-fb-friendly-name", "?"))
            if "/api/graphql" in req.url and req.method == "POST" and not captured:
                name = req.headers.get("x-fb-friendly-name", "")
                if "Feed" in name and "Pagination" in name:
                    captured.update(name=name, headers=req.headers, form=dict(parse_qsl(req.post_data or "")))
        page.on("request", on_req)
        for gid in gids:
            if not gid or captured:
                continue
            page.goto(f"https://www.facebook.com/groups/{gid}/?sorting_setting=CHRONOLOGICAL",
                      wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(4000)
            path0 = urlparse(page.url).path.strip("/").split("/")[0]
            feed = page.locator('div[role="feed"]').count()
            for _ in range(8):
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.mouse.wheel(0, 2500)
                page.wait_for_timeout(2000)
                if captured:
                    break
            print(f"diag: landed on /{path0}/ feed_divs={feed} articles={page.locator('[role=article]').count()} "
                  f"height={page.evaluate('document.body.scrollHeight')}", flush=True)
        print("graphql names seen:", sorted(seen_names), flush=True)
        if not captured:
            print("RESULT: no feed pagination request seen -> replay approach not possible as built")
            return
        variables = json.loads(captured["form"]["variables"])
        print("captured:", captured["name"], "| variable keys:", sorted(variables), flush=True)

        rows = []
        for i, gid in enumerate(gids, 1):
            if not gid:
                rows.append({"group": i, "id": False})
                continue
            v = dict(variables, id=gid, cursor=None, count=10)
            if "sortingSetting" in v:
                v["sortingSetting"] = "CHRONOLOGICAL"
            form = dict(captured["form"], variables=json.dumps(v))
            hdr = {k: v for k, v in captured["headers"].items()
                   if k.lower() in ("x-fb-friendly-name", "x-fb-lsd", "x-asbd-id", "content-type")}
            wc.bytes = 0
            res = page.evaluate("""async ([form, hdr]) => {
                const r = await fetch('/api/graphql/', {method: 'POST', headers: hdr,
                    body: new URLSearchParams(form).toString(), credentials: 'include'});
                return {status: r.status, body: await r.text()};
            }""", [form, hdr])
            page.wait_for_timeout(500)
            posts = parse_stream(res["body"])
            now = time.time()
            row = {"group": i, "status": res["status"], "wire_kb": round(wc.bytes / 1024, 1),
                   "body_kb": round(len(res["body"]) / 1024, 1), "posts": len(posts),
                   "with_text": sum(1 for _, n in posts if n > 20),
                   "newest_age_h": round((now - posts[0][0]) / 3600, 1) if posts else None,
                   "error_in_body": '"errors"' in res["body"][:3000]}
            rows.append(row)
            print(json.dumps(row), flush=True)
            time.sleep(4)
        ok = [r for r in rows if r.get("posts")]
        if ok:
            kb = sum(r["wire_kb"] for r in ok) / len(ok)
            print(f"\nRESULT: replay works for {len(ok)}/{len(rows)} groups; avg {kb:.0f} KB per check")
        else:
            print("\nRESULT: replay returned no posts")
        browser.close()


if __name__ == "__main__":
    main()
