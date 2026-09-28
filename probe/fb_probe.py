"""Can we read each Facebook group with the user's session, and what does one check cost?

Inputs (repo secrets, never printed):
  FB_COOKIES  cookie JSON exported from a logged-in browser (Cookie-Editor format)
  FB_GROUPS   the group share links, one per line
  PROXY_URL   residential proxy (optional; without it we go direct)

Output: per group index -> resolved?, member?, posts visible, KB per load (cold
and warm cache). Group names, URLs and post text stay out of the log because
this repo is public; the resolved URLs go into an encrypted-at-rest secret later.
"""
import json
import os
import time
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")
BLOCK_TYPES = {"image", "media", "font"}
SAMESITE = {"no_restriction": "None", "none": "None", "lax": "Lax",
            "strict": "Strict", "unspecified": "Lax"}


def load_cookies():
    raw = json.loads(os.environ["FB_COOKIES"])
    out = []
    for c in raw:
        ck = {"name": c["name"], "value": c["value"],
              "domain": c.get("domain", ".facebook.com"), "path": c.get("path", "/"),
              "secure": c.get("secure", True), "httpOnly": c.get("httpOnly", False),
              "sameSite": SAMESITE.get(str(c.get("sameSite", "lax")).lower(), "Lax")}
        if c.get("expirationDate"):
            ck["expires"] = int(c["expirationDate"])
        out.append(ck)
    return out


def proxy_cfg():
    url = os.environ.get("PROXY_URL")
    if not url:
        return None
    u = urlparse(url)
    return {"server": f"http://{u.hostname}:{u.port}", "username": u.username, "password": u.password}


def main():
    groups = [g.strip() for g in os.environ["FB_GROUPS"].splitlines() if g.strip()]
    results = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, proxy=proxy_cfg())
        ctx = browser.new_context(user_agent=UA, locale="it-IT",
                                  viewport={"width": 1280, "height": 900})
        ctx.add_cookies(load_cookies())
        ctx.route("**/*", lambda r: r.abort()
                  if r.request.resource_type in BLOCK_TYPES else r.continue_())
        page = ctx.new_page()
        counter = {"bytes": 0}

        def done(req):
            try:
                s = req.sizes()
                counter["bytes"] += sum(s.values())
            except Exception:
                pass
        page.on("requestfinished", done)

        # 1) session check
        page.goto("https://www.facebook.com/", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(4000)
        logged_in = "login" not in page.url and page.locator('input[name="email"]').count() == 0
        print("logged_in:", logged_in, "| checkpoint:", "checkpoint" in page.url, flush=True)
        if not logged_in:
            return

        for i, share in enumerate(groups, 1):
            row = {"group": i}
            try:
                # resolve the share link to the real group URL (id or slug)
                page.goto(share, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(2500)
                path = urlparse(page.url).path.strip("/").split("/")
                row["resolved"] = len(path) >= 2 and path[0] == "groups"
                if not row["resolved"]:
                    results.append(row)
                    print(json.dumps(row), flush=True)
                    continue
                feed = f"https://www.facebook.com/groups/{path[1]}/?sorting_setting=CHRONOLOGICAL"
                for load in ("cold", "warm"):
                    counter["bytes"] = 0
                    t = time.time()
                    page.goto(feed, wait_until="domcontentloaded", timeout=60000)
                    page.wait_for_timeout(5000)
                    page.mouse.wheel(0, 3000)          # pull a second screen of posts
                    page.wait_for_timeout(3000)
                    row[f"{load}_kb"] = round(counter["bytes"] / 1024)
                    row[f"{load}_s"] = round(time.time() - t, 1)
                posts = page.locator('div[role="feed"] > div')
                row["posts_visible"] = posts.count()
                row["join_button"] = page.get_by_role("button", name="Unisciti al gruppo").count() \
                    + page.get_by_role("button", name="Join group").count() > 0
                row["checkpoint"] = "checkpoint" in page.url
            except Exception as e:
                row["error"] = type(e).__name__
            results.append(row)
            print(json.dumps(row), flush=True)
            time.sleep(8)                              # be slow, like a person
        browser.close()

    ok = [r for r in results if r.get("posts_visible")]
    if ok:
        warm = sum(r["warm_kb"] for r in ok) / len(ok)
        per_month_gb = warm * len(groups) * (24 * 60 / 15) * 30 / 1024 / 1024
        print(f"\nreadable groups: {len(ok)}/{len(groups)}; avg warm check {warm:.0f} KB/group; "
              f"all groups every 15 min = {per_month_gb:.1f} GB/month (~${per_month_gb:.1f} at $1/GB)")


if __name__ == "__main__":
    main()
