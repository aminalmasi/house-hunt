"""Send an alert for one judged post to the person's Telegram channel."""
import html
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

ROME = ZoneInfo("Europe/Rome")
QUIET = range(0, 9)  # 00:00-08:59: deliver without sound


def find_chat_id(token, title):
    """A private channel has no @name; the bot learns its id from any post made after it became admin."""
    ups = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=20).json().get("result", [])
    for u in reversed(ups):
        for k in ("channel_post", "my_chat_member", "message"):
            chat = u.get(k, {}).get("chat")
            if chat and (chat.get("title") or "").lower() == title.lower():
                return chat["id"]
    return None


def format_alert(verdict, reasons, post, facts, area_hits):
    head = "🟢 <b>Match</b>" if verdict == "match" else "🟡 <b>Maybe</b>"
    lines = [head]
    if facts and facts.get("summary_en"):
        lines.append(html.escape(facts["summary_en"]))
    unit = next((u for u in (facts or {}).get("units") or [] if u.get("type") == "single_room"), None)
    bits = []
    if unit and unit.get("rent_eur"):
        basis = {"all_inclusive": " all-in", "base": " + bills"}.get(unit.get("rent_basis"), "")
        bits.append(f"€{unit['rent_eur']:g}{basis}")
    if facts and facts.get("available_from"):
        bits.append(f"from {facts['available_from']}")
    if area_hits:
        bits.append("📍 " + ", ".join(area_hits[:3]))
    if bits:
        lines.append(" · ".join(html.escape(b) for b in bits))
    if reasons:
        lines.append("<i>Check: " + html.escape("; ".join(reasons)) + "</i>")
    if post.get("group"):
        lines.append(f"Group: {html.escape(post['group'])}")
    lines.append("")
    lines.append(html.escape(post["text"][:2500]))
    if post.get("url"):
        lines.append(f'\n<a href="{html.escape(post["url"])}">Open post</a>')
    return "\n".join(lines)


def send(token, chat_id, text):
    quiet = datetime.now(ROME).hour in QUIET
    r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", timeout=30, data={
        "chat_id": chat_id, "text": text[:4096], "parse_mode": "HTML",
        "disable_web_page_preview": "true", "disable_notification": str(quiet).lower()})
    r.raise_for_status()
    return r.json()["result"]["message_id"]
