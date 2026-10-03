"""Read new posts from the user's Facebook groups, gently, and email them to the bot inbox.

Runs on GitHub Actions inside one long session (one browser, one cookie jar):
  xvfb-run -a python watcher/fb_watch.py --minutes 340 --every 20

What keeps it gentle (see project notes for why each matters):
  - real Google Chrome, headed (on a virtual screen), patchright, no custom user agent
  - Italian locale and Europe/Rome timezone, matching the proxy's Padova exit IP
  - the full cookie set (c_user, xs, datr, fr, sb) so Facebook sees a known device
  - ONE page per check (the combined "your groups" feed), every ~20 min with jitter
  - nothing between 00:00 and 09:00 Rome time
  - the first login / checkpoint / bot-check page stops everything (exit code 3)

The log is public: it prints counts and sizes only. Post text goes only to the
private Gmail inbox, where the cluster picks it up.
"""
import argparse
import hashlib
import json
import os
import random
import re
import smtplib
import sys
import tempfile
import time
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import quote, urlparse
from zoneinfo import ZoneInfo

from patchright.sync_api import sync_playwright

ROME = ZoneInfo("Europe/Rome")
ACTIVE_HOURS = range(9, 24)
FEED = "https://www.facebook.com/groups/feed/"
STATE = Path("state/seen.json")
PAUSED = 3
SAMESITE = {"no_restriction": "None", "none": "None", "lax": "Lax", "strict": "Strict", "unspecified": "Lax"}
FLAG_WORDS = ("checkpoint", "/login", "two_step_verification", "/recover")
SEE_MORE = ("Altro", "Mostra altro", "See more")


def log(*a):
    print(datetime.now(ROME).strftime("%H:%M:%S"), *a, flush=True)


def cookies():
    out = []
    for c in json.loads(os.environ["FB_COOKIES"]):
        ck = {"name": c["name"], "value": c["value"], "domain": c.get("domain", ".facebook.com"),
              "path": c.get("path", "/"), "secure": True, "httpOnly": c.get("httpOnly", False),
              "sameSite": SAMESITE.get(str(c.get("sameSite", "lax")).lower(), "Lax")}
        if c.get("expirationDate"):
            ck["expires"] = int(c["expirationDate"])
        out.append(ck)
    return out


def proxy(session):
    """Residential exit in Padova (DataImpulse wants the English "padua"), kept on one IP for the session id (DataImpulse sessid)."""
    u = urlparse(os.environ["PROXY_URL"])
    login = u.username.split("__")[0] + os.environ.get("PROXY_PARAMS", "__cr.it;city.padua") + f";sessid.{session}"
    return {"server": f"http://{u.hostname}:{u.port}", "username": login, "password": u.password}


def mail(subject, body):
    msg = EmailMessage()
    msg["From"] = msg["To"] = os.environ["GMAIL_ADDRESS"]
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=60) as s:
        s.login(os.environ["GMAIL_ADDRESS"], os.environ["GMAIL_APP_PASSWORD"])
        s.send_message(msg)


EXTRACT_JS = r"""
() => {
  const out = [];
  const feed = document.querySelector('div[role="feed"]');
  if (!feed) return out;
  for (const art of feed.querySelectorAll(':scope > div')) {
    const msgEl = art.querySelector('[data-ad-rendering-role="story_message"], [data-ad-preview="message"], [data-ad-comet-preview="message"]');
    let text = msgEl ? msgEl.innerText : '';
    if (!text) {  // fallback: the longest block of post-like text
      for (const d of art.querySelectorAll('div[dir="auto"]')) if (d.innerText.length > text.length) text = d.innerText;
    }
    let group = '', groupUrl = '', url = '';
    for (const a of art.querySelectorAll('a[href*="/groups/"]')) {
      const h = a.href.split('?')[0];
      if (!url && /\/groups\/[^/]+\/(posts|permalink)\/\d+/.test(h)) url = h;
      else if (!groupUrl && /\/groups\/[^/]+\/?$/.test(h) && a.innerText.trim()) { groupUrl = h; group = a.innerText.trim(); }
    }
    out.push({text: text.trim(), group, groupUrl, url});
  }
  return out;
}
"""


class Watcher:
    def __init__(self, page, dry):
        self.page, self.dry = page, dry
        self.flagged = None
        self.wire = 0
        cdp = page.context.new_cdp_session(page)
        cdp.send("Network.enable")
        cdp.on("Network.loadingFinished", lambda e: setattr(self, "wire", self.wire + e.get("encodedDataLength", 0)))
        page.on("request", self._watch_request)
        self.seen = set(json.load(open(STATE))) if STATE.exists() else set()

    def _watch_request(self, req):
        name = req.headers.get("x-fb-friendly-name", "")
        if "Interstitial" in name or "Checkpoint" in name:
            self.flagged = f"bot-check request ({name})"

    def _flag_from_url(self):
        url = self.page.url
        if any(w in url for w in FLAG_WORDS):
            self.flagged = "redirected to " + urlparse(url).path.split("/")[1]
        return self.flagged

    def _expand(self):
        for label in SEE_MORE:
            for b in self.page.locator(f'div[role="feed"] div[role="button"]:text-is("{label}")').all()[:15]:
                try:
                    b.click(timeout=2000)
                    self.page.wait_for_timeout(random.randint(300, 700))
                except Exception:
                    pass

    def check(self):
        self.wire = 0
        self.page.goto(FEED, wait_until="domcontentloaded", timeout=90000)
        self.page.wait_for_timeout(random.randint(4000, 7000))
        if self._flag_from_url() or self.flagged:
            return None
        for _ in range(random.randint(3, 5)):  # read down the feed like a person
            self.page.mouse.wheel(0, random.randint(700, 1300))
            self.page.wait_for_timeout(random.randint(1500, 3500))
        self._expand()
        if self._flag_from_url() or self.flagged:
            return None
        posts = self.page.evaluate(EXTRACT_JS)
        new = []
        for p in posts:
            if len(p["text"]) < 40:
                continue
            key = p["url"] or hashlib.sha256(re.sub(r"\s+", " ", p["text"]).encode()).hexdigest()
            if key in self.seen:
                continue
            self.seen.add(key)
            new.append(p)
        log(f"check: {len(posts)} feed items, {sum(1 for p in posts if len(p['text']) >= 40)} with text, "
            f"{sum(1 for p in posts if p['url'])} with link, {sum(1 for p in posts if p['group'])} with group, "
            f"{len(new)} new, {self.wire / 1024:.0f} KB")
        if not self.dry:
            for p in new:
                mail(f"[hh-post] {p['group'][:80]}", json.dumps({**p, "seen_at": datetime.now(ROME).isoformat()},
                                                               ensure_ascii=False))
            STATE.parent.mkdir(exist_ok=True)
            json.dump(sorted(self.seen)[-5000:], open(STATE, "w"))
        return new


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=340, help="stop after this long (Actions jobs end at 6 h)")
    ap.add_argument("--every", type=float, default=20, help="minutes between checks, jittered +-15%%")
    ap.add_argument("--dry", action="store_true", help="one check, no emails: just test the selectors")
    args = ap.parse_args()
    end = time.time() + args.minutes * 60
    session = f"hh{int(time.time())}"

    with sync_playwright() as pw, tempfile.TemporaryDirectory() as profile:
        ctx = pw.chromium.launch_persistent_context(
            profile, channel="chrome", headless=False, no_viewport=True,
            locale="it-IT", timezone_id="Europe/Rome", proxy=proxy(session),
            args=["--blink-settings=imagesEnabled=false", "--autoplay-policy=user-gesture-required"])
        ctx.add_cookies(cookies())
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        w = Watcher(page, args.dry)
        while time.time() < end:
            if datetime.now(ROME).hour not in ACTIVE_HOURS and not args.dry:
                time.sleep(300)
                continue
            try:
                w.check()
            except Exception as e:
                log("check failed:", type(e).__name__)
            if w.flagged:
                log("STOPPING: Facebook showed a security page:", w.flagged)
                if not args.dry:
                    mail("[hh-alert] Facebook reader paused",
                         f"The Facebook reader stopped because Facebook showed: {w.flagged}.\n"
                         "Open Facebook on your phone, complete any check it asks for, then close the "
                         "'fb-paused' issue on GitHub to resume.")
                ctx.close()
                sys.exit(PAUSED)
            if args.dry:
                break
            time.sleep(args.every * 60 * random.uniform(0.85, 1.15))
        ctx.close()


if __name__ == "__main__":
    main()
