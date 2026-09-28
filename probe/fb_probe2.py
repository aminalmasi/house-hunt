"""Round 2: real network bytes per Facebook group check, desktop vs mobile site.

Round 1 summed Playwright's request sizes, which may include cache hits. Here we
count Chrome's own encodedDataLength from the DevTools protocol (bytes that
actually crossed the wire, cache hits = 0), and we try m.facebook.com with a
phone user agent, which serves much lighter pages.

We also explain the zero-post groups with yes/no signals only (public repo:
no names, URLs or post text in the log).
"""
import json
import os
import re
import time
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

from fb_probe import load_cookies, proxy_cfg

DESKTOP_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")
MOBILE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
             "(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1")
BLOCK_TYPES = {"image", "media", "font"}
PHRASES = {  # lower-cased substrings -> signal name
    "unisciti al gruppo": "join", "join group": "join",
    "gruppo privato": "private", "private group": "private",
    "contenuto non disponibile": "unavailable", "content isn't available": "unavailable",
    "richiesta inviata": "pending", "cancel request": "pending", "annulla richiesta": "pending",
    "nessun post": "no_posts", "no posts": "no_posts",
}


class WireCounter:
    def __init__(self, page):
        self.bytes = 0
        cdp = page.context.new_cdp_session(page)
        cdp.send("Network.enable")
        cdp.on("Network.loadingFinished", lambda e: self._add(e.get("encodedDataLength", 0)))

    def _add(self, n):
        self.bytes += n


def group_ids(page, shares):
    ids = []
    for s in shares:
        page.goto(s, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2000)
        p = urlparse(page.url).path.strip("/").split("/")
        ids.append(p[1] if len(p) >= 2 and p[0] == "groups" else None)
    return ids


def measure(pw, variant, gids):
    mobile = variant == "mobile"
    browser = pw.chromium.launch(headless=True, proxy=proxy_cfg())
    ctx = browser.new_context(user_agent=MOBILE_UA if mobile else DESKTOP_UA, locale="it-IT",
                              is_mobile=mobile, has_touch=mobile,
                              viewport={"width": 390, "height": 844} if mobile else {"width": 1280, "height": 900})
    ctx.add_cookies(load_cookies())
    ctx.route("**/*", lambda r: r.abort() if r.request.resource_type in BLOCK_TYPES else r.continue_())
    page = ctx.new_page()
    wc = WireCounter(page)
    host = "https://m.facebook.com" if mobile else "https://www.facebook.com"
    rows = []
    for i, gid in enumerate(gids, 1):
        if not gid:
            rows.append({"group": i, "resolved": False})
            continue
        row = {"group": i, "variant": variant}
        for load in ("first", "repeat"):
            wc.bytes = 0
            page.goto(f"{host}/groups/{gid}/?sorting_setting=CHRONOLOGICAL",
                      wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(5000)
            row[f"{load}_kb"] = round(wc.bytes / 1024)
        html = page.content().lower()
        row["articles"] = page.locator('[role="article"]').count()
        row["feed_children"] = page.locator('div[role="feed"] > div').count()
        row["price_hits"] = len(re.findall(r"€\s?\d{3}|\d{3}\s?€|\d{3}\s?euro", html))
        row["signals"] = sorted({v for k, v in PHRASES.items() if k in html})
        row["final_host_is_groups"] = "/groups/" in page.url
        rows.append(row)
        print(json.dumps(row), flush=True)
        time.sleep(6)
    browser.close()
    return rows


def main():
    shares = [g.strip() for g in os.environ["FB_GROUPS"].splitlines() if g.strip()]
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True, proxy=proxy_cfg())
        ctx = b.new_context(user_agent=DESKTOP_UA)
        ctx.add_cookies(load_cookies())
        gids = group_ids(ctx.new_page(), shares)
        b.close()
        print("resolved:", sum(1 for g in gids if g), "/", len(gids), flush=True)
        summary = {}
        for variant in ("desktop", "mobile"):
            rows = [r for r in measure(pw, variant, gids) if "repeat_kb" in r]
            if rows:
                avg = sum(r["repeat_kb"] for r in rows) / len(rows)
                gb = avg * len(gids) * 96 * 30 / 1024 / 1024
                summary[variant] = f"avg repeat check {avg:.0f} KB/group -> all groups every 15 min = {gb:.1f} GB/month"
    print("\n".join(f"{k}: {v}" for k, v in summary.items()))


if __name__ == "__main__":
    main()
