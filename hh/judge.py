"""One post in, one decision per person out: dedup -> LLM facts -> area -> rules."""
from .area import Area
from .dedup import Dedup
from .extract import build_messages, parse
from .rules import decide


class Judge:
    def __init__(self, llm, profiles, today):
        self.llm, self.profiles, self.today = llm, profiles, today
        self.area, self.dedup = Area(), Dedup()

    def __call__(self, pid, text):
        dup = self.dedup.match(text)
        if dup is not None:
            return {"id": pid, "duplicate_of": dup}
        self.dedup.add(pid, text)
        raw = self.llm(build_messages(text, self.today))
        facts = parse(raw)
        # where the room IS decides the area: "in Albignasego, 10 min from Prato" is Albignasego.
        # Only when the post names no place for the room do "near X" places count ("near the station").
        loc = (facts or {}).get("room_location")
        status, hits = self.area.locate(loc) if loc else ("unknown", [])
        if status == "unknown":
            status, hits = self.area.locate(*(facts or {}).get("nearby", []))
        if status == "unknown":
            status, hits = self.area.locate(text)
        out = {"id": pid, "facts": facts, "raw": None if facts else raw, "area": status, "area_hits": hits}
        out["decisions"] = {p["name"]: decide(facts, status, hits, p) for p in self.profiles}
        return out
