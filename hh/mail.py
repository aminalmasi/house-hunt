"""Read Facebook notification emails from the bot's Gmail inbox over IMAP.

Every Facebook email is saved as-is to data/mail/<uid>.eml (not in git) so the
parser can be checked against real messages. Only emails that link to a group
post become posts; welcome/security emails are skipped.
"""
import email
import imaplib
import json
import re
from email.header import decode_header, make_header
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
POST_LINK = re.compile(r"groups/(\d+|[\w.]+)/(?:posts|permalink)/(\d+)")
FOOTER = re.compile(r"(={10,}|This message was sent to|Questo messaggio è stato inviato|To unsubscribe|Per annullare l'iscrizione"
                    r"|View on Facebook|Visualizza su Facebook|Reply to this email|Rispondi a questa e-mail)", re.I)


def _text(msg):
    plain, html = "", ""
    for part in msg.walk():
        ctype = part.get_content_type()
        if ctype in ("text/plain", "text/html") and not part.get_filename():
            body = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
            if ctype == "text/plain":
                plain += body
            else:
                html += body
    return plain, html


def parse_email(raw):
    msg = email.message_from_bytes(raw)
    subject = str(make_header(decode_header(msg.get("Subject", ""))))
    plain, html = _text(msg)
    links = POST_LINK.findall(unquote(unquote(plain + html)))
    if not links:
        return None
    gid, pid = links[0]
    # post text = the plain body with Facebook's redirect links and footer removed
    body = re.sub(r"\[?https?://\S+\]?", " ", plain)
    body = FOOTER.split(body)[0]
    body = re.sub(r"[ \t]+", " ", body)
    body = re.sub(r"\n\s*\n+", "\n", body).strip()
    group = re.search(r"(?:in|nel gruppo|su)\s+(.+?)$", subject)
    return {"id": f"fb:{gid}:{pid}", "group": group.group(1).strip() if group else subject,
            "subject": subject, "text": body, "url": f"https://www.facebook.com/groups/{gid}/posts/{pid}/",
            "date": msg.get("Date", "")}


class Inbox:
    def __init__(self, address, app_password):
        self.address, self.password = address, app_password
        self.state_path = DATA / "mail_state.json"
        (DATA / "mail").mkdir(parents=True, exist_ok=True)

    def _last_uid(self):
        try:
            return json.load(open(self.state_path))["last_uid"]
        except (FileNotFoundError, KeyError, ValueError):
            return 0

    def fetch_new(self):
        """New Facebook posts since the last call. Advances the saved position only after reading."""
        last = self._last_uid()
        posts = []
        M = imaplib.IMAP4_SSL("imap.gmail.com", 993)
        try:
            M.login(self.address, self.password)
            M.select('"[Gmail]/All Mail"', readonly=True)
            typ, data = M.uid("search", None, f"UID {last + 1}:*", 'FROM "facebookmail.com"')
            uids = [int(u) for u in data[0].split() if int(u) > last]
            for uid in uids:
                typ, msg = M.uid("fetch", str(uid), "(BODY.PEEK[])")
                raw = msg[0][1]
                (DATA / "mail" / f"{uid}.eml").write_bytes(raw)
                post = parse_email(raw)
                if post:
                    post["uid"] = uid
                    posts.append(post)
            if uids:
                json.dump({"last_uid": max(uids)}, open(self.state_path, "w"))
        finally:
            try:
                M.logout()
            except Exception:
                pass
        return posts
