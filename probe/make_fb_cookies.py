"""Build fb_cookies.json from values copied out of Chrome DevTools, one at a time.

Run on labsrv7:  python3 /extra/malmasik/house-hunt/probe/make_fb_cookies.py
Input is hidden (like a password prompt). Writes ~/fb_cookies.json, readable only by you.
"""
import getpass
import json
import os
import time

NAMES = ["c_user", "xs", "datr", "fr", "sb"]
REQUIRED = {"c_user", "xs"}
HTTP_ONLY = {"xs", "datr", "fr", "sb"}

cookies = []
for name in NAMES:
    val = getpass.getpass(f"paste value of {name}{'' if name in REQUIRED else ' (Enter to skip)'}: ").strip()
    if not val:
        if name in REQUIRED:
            raise SystemExit(f"{name} is required; start again")
        continue
    cookies.append({"name": name, "value": val, "domain": ".facebook.com", "path": "/",
                    "secure": True, "httpOnly": name in HTTP_ONLY, "sameSite": "no_restriction",
                    "expirationDate": int(time.time()) + 180 * 86400})

path = os.path.expanduser("~/fb_cookies.json")
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w") as f:
    json.dump(cookies, f)
print(f"saved {len(cookies)} cookies to {path}; c_user looks like a user id: {cookies[0]['value'].isdigit()}")
