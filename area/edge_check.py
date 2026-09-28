"""Classify Padova zone names as inside/outside the drawn area (for the post filter)."""
import json
import time
import requests
from matplotlib.path import Path

poly = json.load(open("area/area_polygon.json"))["polygon_latlon"]
path = Path([(lo, la) for la, lo in poly])
UA = {"User-Agent": "house-hunt/0.1 (amindoala@gmail.com)"}

# every place node in a wider box around the city
q = """[out:json][timeout:60];node["place"~"suburb|quarter|neighbourhood|hamlet|village"](45.36,11.80,45.46,11.96);out;"""
els = requests.post("https://overpass-api.de/api/interpreter", data={"data": q}, headers=UA, timeout=90).json()["elements"]
res = {}
for e in els:
    res[e["tags"]["name"]] = ("osm-place", bool(path.contains_point((e["lon"], e["lat"]))), round(e["lat"], 4), round(e["lon"], 4))

# colloquial zone names used in rental posts, geocoded one by one
for z in ["Centro Storico", "Portello", "Basilica del Santo", "Prato della Valle", "Santa Croce",
          "Via Savonarola", "Palestro", "Città Giardino", "Stazione Padova", "Porta Trento",
          "Pontecorvo", "Specola", "Piazza dei Signori", "Via Belzoni", "Ospedale Giustinianeo",
          "Piazzale Stanga", "Fiera di Padova", "Bassanello", "Guizza", "Voltabarozzo",
          "Mortise", "Brusegana", "Chiesanuova", "Montà", "Camin", "Terranegra", "Salboro",
          "Paltana", "Mandria", "Pontevigodarzere", "Altichiero", "Sacro Cuore", "Via Tiziano Aspetti"]:
    d = requests.get("https://nominatim.openstreetmap.org/search", params={
        "q": z + ", Padova", "format": "json", "limit": 1}, headers=UA, timeout=30).json()
    time.sleep(1.1)
    if d:
        la, lo = float(d[0]["lat"]), float(d[0]["lon"])
        res[z] = ("geocoded", bool(path.contains_point((lo, la))), round(la, 4), round(lo, 4))
json.dump(res, open("area/zones_inout.json", "w"), indent=1, ensure_ascii=False)
for k, v in sorted(res.items(), key=lambda kv: (not kv[1][1], kv[0])):
    print("IN " if v[1] else "out", k, v[2:])
