"""Label every named street in the Comune di Padova as in/edge/out of the drawn area,
by the share of its points inside (>=70% in, <=20% out, else edge).
"""
import json
import requests
from matplotlib.path import Path

poly = json.load(open("area/area_polygon.json"))["polygon_latlon"]
path = Path([(lo, la) for la, lo in poly])
q = """[out:json][timeout:120];
area["boundary"="administrative"]["name"="Padova"]["admin_level"="8"]->.pd;
way["highway"]["name"](area.pd);
out tags geom;"""
for ep in ("https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter",
           "https://maps.mail.ru/osm/tools/overpass/api/interpreter"):
    r = requests.post(ep, data={"data": q}, headers={"User-Agent": "house-hunt/0.1"}, timeout=180)
    print(ep, r.status_code, len(r.content))
    if r.ok and r.text.lstrip().startswith("{"):
        els = r.json()["elements"]
        break
else:
    raise SystemExit("all Overpass endpoints failed")
acc = {}
for e in els:
    name = e["tags"]["name"]
    pts = [(g["lon"], g["lat"]) for g in e.get("geometry", [])]
    inside = [path.contains_point(p) for p in pts]
    a = acc.setdefault(name, [0, 0])
    a[0] += sum(inside)
    a[1] += len(inside) - sum(inside)
# by share of the street's points inside: long roads that only start in the area count as out
out = {}
for n, (i, o) in acc.items():
    f = i / (i + o)
    out[n] = "in" if f >= 0.7 else "out" if f <= 0.2 else "edge"
json.dump(out, open("area/streets_inout.json", "w"), indent=0, ensure_ascii=False, sort_keys=True)
from collections import Counter
print(Counter(out.values()))
