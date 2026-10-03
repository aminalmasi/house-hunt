"""Does DataImpulse give us a Padova-area IP, and how long does it stay the same?

No Facebook here: asks ip-api.com where each exit IP is. Prints city/region/ISP
and a short hash of the IP only (public log).
"""
import hashlib
import os
import time
from urllib.parse import urlparse, quote

import requests

u = urlparse(os.environ["PROXY_URL"])
login = u.username.split("__")[0]
VARIANTS = {  # a different session id per variant, so one can't inherit another's IP
    "it+city.padua+sessid": "__cr.it;city.padua;sessid.a{n}",
    "it+state.veneto+city.padua+sessid": "__cr.it;state.veneto;city.padua;sessid.b{n}",
    "it+state.veneto+sessid": "__cr.it;state.veneto;sessid.c{n}",
}
LONG = "it+state.veneto+sessid"


def where(params):
    proxy = f"http://{quote(login + params)}:{quote(u.password)}@{u.hostname}:{u.port}"
    try:
        d = requests.get("http://ip-api.com/json/?fields=status,city,regionName,isp,mobile,hosting,query",
                         proxies={"http": proxy, "https": proxy}, timeout=40).json()
    except Exception as e:
        return f"error {type(e).__name__}"
    ip = hashlib.sha256(d.get("query", "").encode()).hexdigest()[:6]
    return f"ip#{ip} {d.get('city')} / {d.get('regionName')} / {d.get('isp')} mobile={d.get('mobile')} hosting={d.get('hosting')}"


n = int(time.time()) % 100000
for name, tmpl in VARIANTS.items():
    print(f"== {name}", flush=True)
    for k in range(3):
        print(f"  t+{k * 60:>3}s", where(tmpl.format(n=n)), flush=True)
        if k < 2:
            time.sleep(60)
# stickiness over a longer stretch, for the variant that targets Padova
print(f"== long stickiness ({LONG}), every 5 min for 40 min", flush=True)
for k in range(9):
    print(f"  t+{k * 5:>2}min", where(VARIANTS[LONG].format(n=n + 1)), flush=True)
    if k < 8:
        time.sleep(300)
