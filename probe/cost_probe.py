"""Measure what each rental portal costs to poll, in bytes, and whether it blocks us.

For every portal we try up to four ways of fetching the Padova room-search page:
  http-direct   plain GET from the GitHub runner (free, but datacenter IP)
  http-proxy    plain GET through the residential proxy (cheapest paid option)
  pw-direct     Playwright browser, images/fonts/media/css blocked
  pw-proxy      same, through the proxy; loaded twice to see the warm-cache cost

Only sizes, status codes and yes/no signals are printed. Page content, cookies
and the proxy URL never reach the log (this repo is public).
"""
import json
import os
import re
import sys
import time
from urllib.parse import urlparse

import requests
from playwright.sync_api import sync_playwright

TARGETS = {
    "idealista": "https://www.idealista.it/affitto-stanze/padova-padova/",
    "immobiliare": "https://www.immobiliare.it/affitto-stanze/padova/",
    "subito": "https://www.subito.it/annunci-veneto/affitto/camere-posti-letto/padova/padova/",
    "spotahome": "https://www.spotahome.com/it/s/padova/for-rent:rooms",
}

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
           "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"}
BLOCK_TYPES = {"image", "media", "font", "stylesheet"}
BLOCK_WORDS = ("captcha-delivery", "datadome", "px-captcha", "access denied",
               "verify you are human", "cf-challenge", "attention required")

PROXY_URL = os.environ.get("PROXY_URL", "")


def signals(html):
    low = html.lower()
    return {
        "blocked": any(w in low for w in BLOCK_WORDS),
        # rough "did we get listings" signals, never the content itself
        "price_hits": len(re.findall(r"€\s?\d{3}|\d{3}\s?€", html)),
        "next_data": "__next_data__" in low,
        "json_ld": "application/ld+json" in low,
    }


def http_fetch(url, proxy):
    proxies = {"http": proxy, "https": proxy} if proxy else None
    t = time.time()
    try:
        r = requests.get(url, headers=HEADERS, proxies=proxies, timeout=45)
    except Exception as e:
        return {"error": type(e).__name__}
    # len(content) is decompressed; the wire size is what the proxy bills
    wire = int(r.headers.get("content-length") or 0) or len(r.content)
    return {"status": r.status_code, "wire_kb": round(wire / 1024, 1),
            "html_kb": round(len(r.content) / 1024, 1),
            "secs": round(time.time() - t, 1), **signals(r.text)}


def pw_proxy_cfg():
    u = urlparse(PROXY_URL)
    return {"server": f"http://{u.hostname}:{u.port}",
            "username": u.username, "password": u.password}


def pw_fetch(pw, url, proxy, loads=2):
    browser = pw.chromium.launch(headless=True,
                                 proxy=pw_proxy_cfg() if proxy else None)
    ctx = browser.new_context(user_agent=UA, locale="it-IT")
    ctx.route("**/*", lambda route: route.abort()
              if route.request.resource_type in BLOCK_TYPES else route.continue_())
    page = ctx.new_page()
    out = []
    for i in range(loads):
        total = {"bytes": 0, "reqs": 0, "third_party": 0}
        host = urlparse(url).hostname.split(".")[-2]

        def done(req):
            try:
                s = req.sizes()
                total["bytes"] += s["responseBodySize"] + s["responseHeadersSize"] \
                    + s["requestHeadersSize"] + s["requestBodySize"]
            except Exception:
                pass
            total["reqs"] += 1
            if host not in (urlparse(req.url).hostname or ""):
                total["third_party"] += 1

        page.on("requestfinished", done)
        t = time.time()
        status = None
        try:
            resp = page.goto(url, wait_until="domcontentloaded", timeout=60000)
            status = resp.status if resp else None
            page.wait_for_timeout(6000)  # let XHR-loaded listings arrive
            html = page.content()
        except Exception as e:
            out.append({"load": i + 1, "error": type(e).__name__})
            page.remove_listener("requestfinished", done)
            continue
        page.remove_listener("requestfinished", done)
        out.append({"load": i + 1, "status": status,
                    "wire_kb": round(total["bytes"] / 1024, 1),
                    "reqs": total["reqs"], "third_party_reqs": total["third_party"],
                    "secs": round(time.time() - t, 1), **signals(html)})
    browser.close()
    return out


def main():
    only = sys.argv[1:] or list(TARGETS)
    results = {}
    with sync_playwright() as pw:
        for name in only:
            url = TARGETS[name]
            r = {"http-direct": http_fetch(url, None),
                 "pw-direct": pw_fetch(pw, url, None, loads=1)}
            if PROXY_URL:
                r["http-proxy"] = http_fetch(url, PROXY_URL)
                r["pw-proxy"] = pw_fetch(pw, url, PROXY_URL, loads=2)
            results[name] = r
            print(f"== {name}", json.dumps(r, indent=1), flush=True)
    with open("probe_results.json", "w") as f:
        json.dump(results, f, indent=1)


if __name__ == "__main__":
    main()
