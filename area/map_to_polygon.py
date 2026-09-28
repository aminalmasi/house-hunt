"""Turn the hand-drawn red border on the Google Maps screenshot into a lat/lon polygon.

Georeferencing: north-up map, 1 km scale bar = ~121 px, anchored on the
Cappella degli Scrovegni pin (340,597); Gran Teatro Geox (120,500) cross-checks
the scale to within a few percent.
"""
import json
import cv2
import numpy as np

ANCHOR_PX = (340, 597)
ANCHOR_LL = (45.4118663, 11.8795176)          # Scrovegni (OSM)
PX_PER_KM = 121.0
KM_PER_DEG_LAT = 111.2
KM_PER_DEG_LON = 111.32 * np.cos(np.radians(ANCHOR_LL[0]))


def px_to_ll(x, y):
    lat = ANCHOR_LL[0] - (y - ANCHOR_PX[1]) / PX_PER_KM / KM_PER_DEG_LAT
    lon = ANCHOR_LL[1] + (x - ANCHOR_PX[0]) / PX_PER_KM / KM_PER_DEG_LON
    return round(lat, 6), round(lon, 6)


im = cv2.imread("area/area_map.jpeg")
hsv = cv2.cvtColor(im, cv2.COLOR_BGR2HSV)
red = cv2.inRange(hsv, (0, 150, 150), (8, 255, 255)) | cv2.inRange(hsv, (172, 150, 150), (180, 255, 255))
red[:260] = 0                                   # ignore the UI chrome at the top
red = cv2.morphologyEx(red, cv2.MORPH_CLOSE, np.ones((25, 25), np.uint8))
# the stroke runs off the right edge; close it along the edge so it's one region
red[:, -6:] = np.where(np.arange(red.shape[0])[:, None].__ge__(480) & np.arange(red.shape[0])[:, None].__le__(700), 255, red[:, -6:])
cnts, hier = cv2.findContours(red, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
# the inner hole of the ring = the area inside the drawn line
holes = [cnts[i] for i in range(len(cnts)) if hier[0][i][3] != -1]
inner = max(holes, key=cv2.contourArea)
inner = cv2.approxPolyDP(inner, 3, True)[:, 0, :]
poly = [px_to_ll(int(x), int(y)) for x, y in inner]
area_km2 = cv2.contourArea(inner) / PX_PER_KM ** 2
json.dump({"polygon_latlon": poly, "area_km2": round(area_km2, 2)}, open("area/area_polygon.json", "w"), indent=1)
dbg = im.copy()
cv2.polylines(dbg, [inner.reshape(-1, 1, 2)], True, (255, 0, 0), 3)
cv2.imwrite("area/area_debug.jpg", dbg)
print(len(poly), "vertices, area", round(area_km2, 2), "km2")
