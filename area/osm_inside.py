"""Ask OpenStreetMap (Overpass) which neighbourhoods and streets lie inside the drawn area."""
import json
import requests

poly = json.load(open("area/area_polygon.json"))["polygon_latlon"]
P = " ".join(f"{la} {lo}" for la, lo in poly)
q = f"""[out:json][timeout:90];
(
  node["place"~"suburb|quarter|neighbourhood"](poly:"{P}");
  relation["boundary"="administrative"]["admin_level"~"9|10"](poly:"{P}");
)->.places;
.places out tags center;
way["highway"]["name"](poly:"{P}");
out tags center;
"""
r = requests.post("https://overpass-api.de/api/interpreter", data={"data": q},
                  headers={"User-Agent": "house-hunt/0.1"}, timeout=120)
r.raise_for_status()
els = r.json()["elements"]
places = sorted({(e["tags"].get("name"), e["tags"].get("place") or "admin" + e["tags"].get("admin_level", ""))
                 for e in els if e["type"] in ("node", "relation")})
streets = {}
for e in els:
    if e["type"] == "way":
        streets.setdefault(e["tags"]["name"], e["tags"]["highway"])
json.dump({"places": places, "streets": sorted(streets)}, open("area/area_osm.json", "w"), indent=1, ensure_ascii=False)
for p in places:
    print(p)
print(len(streets), "named streets")
