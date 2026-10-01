"""Decide per person from the extracted facts: match / maybe / reject, with reasons.

Profiles live in profiles/profiles.json (not in git). Example:
  {"name": "...", "sex": "m", "occupation": "worker", "max_rent": 400,
   "move_in_from": "2026-11-01", "move_in_preferred": "2026-12-01", "move_in_latest": "2026-12-31"}

Hard rejects come only from things the post actually states. Anything missing
or unclear becomes a "maybe" with the reason, so nothing is lost silently.
"""
from datetime import date

ROOM_OK = {"single_room"}
ROOM_MAYBE = {"studio", "unknown"}
ALL_INCLUSIVE_SLACK = 70  # "450 tutto incluso" is roughly 380 + bills


def _date(s):
    try:
        return date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def _unit_verdict(u, max_rent):
    """(ok, maybe_reason or None, reject_reason or None) for one offered unit."""
    t = u.get("type") or "unknown"
    rent = u.get("rent_eur")
    basis = u.get("rent_basis") or "unknown"
    if t not in ROOM_OK | ROOM_MAYBE:
        return None, f"{t.replace('_', ' ')}, not a single room"
    if isinstance(rent, (int, float)):
        limit = max_rent + (ALL_INCLUSIVE_SLACK if basis == "all_inclusive" else 0)
        if rent > limit:
            return None, f"€{rent:g}{' all-inclusive' if basis == 'all_inclusive' else ''} is over budget"
        if basis == "all_inclusive" and rent > max_rent:
            return f"€{rent:g} all-inclusive, base rent probably under €{max_rent}", None
    else:
        return "price not stated", None
    if t == "studio":
        return "a studio, not a room in a shared flat", None
    if t == "unknown":
        return "room type not stated", None
    return None, None


def decide(facts, area_status, area_hits, profile):
    if facts is None:
        return "maybe", ["could not read the post automatically"]
    if facts.get("kind") != "offer":
        return "reject", [f"not an offer ({facts.get('kind')})"]

    maybes, rejects = [], []

    # room type + price: the post qualifies if at least one unit does
    units = [_unit_verdict(u, profile["max_rent"]) for u in (facts.get("units") or [{"type": "unknown"}])]
    if not any(maybe is None and reject is None for maybe, reject in units):
        unit_maybes = [maybe for maybe, reject in units if reject is None]
        if unit_maybes:
            maybes.append(unit_maybes[0])
        else:
            rejects.append(units[0][1])

    g = facts.get("gender")
    if (g == "female_only" and profile["sex"] == "m") or (g == "male_only" and profile["sex"] == "f"):
        rejects.append("women only" if g == "female_only" else "men only")

    t = facts.get("tenant")
    if t == "students_only" and profile["occupation"] == "worker":
        rejects.append("students only")

    start = _date(facts.get("available_from"))
    if start is None:
        maybes.append(f"start date not stated{': ' + facts['available_note'] if facts.get('available_note') else ''}")
    elif start > _date(profile["move_in_latest"]):
        rejects.append(f"available only from {start:%d %b %Y}")
    elif start > _date(profile["move_in_preferred"]):
        maybes.append(f"available from {start:%d %b}, later than preferred")
    elif start < _date(profile["move_in_from"]):
        maybes.append(f"available from {start:%d %b}, earlier than you need")

    if area_status == "out":
        rejects.append(f"outside your area ({', '.join(area_hits)})")
    elif area_status == "edge":
        maybes.append(f"on the edge of your area ({', '.join(area_hits)})")
    elif area_status == "unknown":
        maybes.append("location not stated")

    if rejects:
        return "reject", rejects
    return ("maybe", maybes) if maybes else ("match", [])
