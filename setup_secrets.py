"""Store the bot's keys in ~/.config/house-hunt.env (readable only by you).

Run on labsrv7:  python3 /extra/malmasik/house-hunt/setup_secrets.py
Secret values are typed hidden. Press Enter to keep what is already saved,
so you can run it again later just to add the Telegram bots.
"""
import getpass
import os

PATH = os.path.expanduser("~/.config/house-hunt.env")
FIELDS = [  # (key, prompt, hidden)
    ("GMAIL_ADDRESS", "Gmail address that receives the Facebook emails", False),
    ("GMAIL_APP_PASSWORD", "Gmail app password (16 letters)", True),
    ("APIFY_TOKEN", "Apify API token", True),
    ("BOT_TOKEN_1", "Telegram bot token for YOUR channel", True),
    ("CHANNEL_1", "YOUR channel link or @name", False),
    ("BOT_TOKEN_2", "Telegram bot token for ASMA's channel", True),
    ("CHANNEL_2", "ASMA's channel link or @name", False),
]

saved = {}
if os.path.exists(PATH):
    for line in open(PATH):
        if "=" in line:
            k, v = line.rstrip("\n").split("=", 1)
            saved[k] = v

for key, prompt, hidden in FIELDS:
    have = " [saved, Enter to keep]" if saved.get(key) else " [Enter to skip]"
    val = (getpass.getpass if hidden else input)(f"{prompt}{have}: ").strip()
    if key == "GMAIL_APP_PASSWORD":
        val = val.replace(" ", "")  # Google shows it in groups of four
    if val:
        saved[key] = val

os.makedirs(os.path.dirname(PATH), exist_ok=True)
fd = os.open(PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w") as f:
    f.writelines(f"{k}={v}\n" for k, v in saved.items())
print("saved:", ", ".join(k for k, _, _ in FIELDS if saved.get(k)) or "nothing")
print("missing:", ", ".join(k for k, _, _ in FIELDS if not saved.get(k)) or "nothing")
