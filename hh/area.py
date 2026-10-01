"""Is a post's location inside the area drawn on the map?

Two sources, both built by area/*.py from OpenStreetMap and kept out of git:
  area/streets_inout.json   every named street in Padova -> in / edge / out
  ZONES below               the zone names people actually write in rental posts

Returns "in", "edge", "out" or "unknown" plus what matched, so an alert can say why.
"""
import json
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Zone names as written in posts (lower case, no accents). Checked against the
# drawn polygon with area/edge_check.py; towns around Padova are all "out".
ZONES = {
    "in": [
        "centro", "centro storico", "portello", "santo", "basilica del santo", "pontecorvo",
        "prato della valle", "prato", "santa croce", "savonarola", "porta trento", "palestro",
        "san giuseppe", "sacra famiglia", "specola", "citta giardino", "madonna pellegrina",
        "santa rita", "sant'osvaldo", "sant osvaldo", "forcellini", "stanga", "fiera", "stazione",
        "arcella", "san carlo", "borgomagno", "piazza dei signori", "piazza delle erbe",
        "piazza della frutta", "piazza garibaldi", "duomo", "ghetto", "eremitani", "ospedale",
        "giustinianeo", "belzoni", "ingegneria", "piovego", "tribunale", "porta portello",
        # as written in English posts
        "city centre", "city center", "old town", "historic centre", "historic center",
        "downtown", "train station", "railway station", "station", "hospital",
    ],
    "edge": ["bassanello", "terranegra", "san lazzaro"],
    "out": [
        "guizza", "paltana", "mortise", "san bellino", "chiesanuova", "brusegana", "voltabarozzo",
        "camin", "mandria", "salboro", "monta", "altichiero", "pontevigodarzere", "torre",
        "ponte di brenta", "crocifisso", "sant'ignazio", "brentelle", "cave", "agripolis",
        # towns around Padova
        "sarmeola", "rubano", "selvazzano", "tencarola", "albignasego", "ponte san nicolo",
        "roncaglia", "legnaro", "saonara", "vigonza", "noventa padovana", "noventa",
        "cadoneghe", "vigodarzere", "limena", "abano", "montegrotto", "mestrino", "maserà",
        "masera", "casalserugo", "villafranca padovana", "curtarolo", "campodarsego",
        "mestre", "venezia", "vicenza", "camposampiero", "piove di sacco",
    ],
}
STREET_PREFIX = r"(?:via|viale|v\.le|v\.|piazza|p\.zza|p\.za|piazzale|corso|c\.so|riviera|vicolo|largo|galleria|lungargine|contra|contrada|borgo)"
STOPWORDS = {"a", "di", "de", "del", "della", "dei", "degli", "delle", "da", "e"}


def norm(s):
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s.replace("’", "'")).strip()


class Area:
    def __init__(self, streets_path=ROOT / "area" / "streets_inout.json"):
        streets = json.load(open(streets_path))
        self.full, self.last = {}, {}
        for name, status in streets.items():
            n = norm(name)
            body = re.sub(rf"^{STREET_PREFIX}\s+", "", n)
            self.full.setdefault(body, set()).add(status)
            words = [w for w in body.split() if w not in STOPWORDS]
            if words and len(words[-1]) >= 4:
                self.last.setdefault(words[-1], set()).add(status)
        self.zone_re = [(status, z, re.compile(rf"(?<![a-z]){re.escape(z)}(?![a-z])"))
                        for status, zs in ZONES.items() for z in sorted(zs, key=len, reverse=True)]
        self.street_re = re.compile(rf"(?<![a-z]){STREET_PREFIX}\s+((?:[a-z']+\.?\s?){{1,5}})")

    def _street(self, phrase):
        words = [w.strip(".") for w in phrase.split()]
        # try the longest prefix of the words first: "via san francesco 12 zona..." -> "san francesco"
        for k in range(len(words), 0, -1):
            key = " ".join(words[:k])
            if key in self.full:
                return self.full[key], key
        for w in words[:3]:
            if w in self.last:
                return self.last[w], w
        return None, None

    def locate(self, *texts):
        hits = []
        for text in texts:
            t = norm(text or "")
            for m in self.street_re.finditer(t):
                st, key = self._street(m.group(1))
                if st:
                    hits.append(("edge" if len(st) > 1 else next(iter(st)), f"via {key}"))
            for status, z, rx in self.zone_re:
                if rx.search(t):
                    hits.append((status, z))
        if not hits:
            return "unknown", []
        statuses = {s for s, _ in hits}
        # a post naming an inside place wins over a passing mention of somewhere outside
        # ("10 min from Guizza, in via Belzoni"); only all-outside mentions mean out
        verdict = "in" if "in" in statuses else "edge" if "edge" in statuses else "out"
        return verdict, sorted({h for _, h in hits})
