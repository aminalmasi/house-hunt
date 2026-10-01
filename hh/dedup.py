"""Spot the same ad posted in several groups (or reposted a few days later).

Two posts are the same ad when their text is nearly identical (word 4-gram
overlap), or when they share a phone number AND a price. Light edits such as
an added emoji, a changed first line or "UP" bumps still match.
"""
import re

from .area import norm


def phones(text):
    digits = re.findall(r"(?:\+?39[\s.-]?)?3\d{2}[\s.-]?\d{3}[\s.-]?\d{3,4}", text)
    return {re.sub(r"\D", "", p)[-10:] for p in digits}


def shingles(text, n=4):
    words = re.findall(r"[a-z0-9€]+", norm(text))
    return {" ".join(words[i:i + n]) for i in range(max(1, len(words) - n + 1))}


PRICE_RE = re.compile(r"(?<!\d)([1-9]\d{2})(?:[.,]00)?\s?(?:€|euro\b|eur\b)|€\s?([1-9]\d{2})(?!\d)")


def prices(text):
    return {a or b for a, b in PRICE_RE.findall(text.lower())}


class Dedup:
    def __init__(self, threshold=0.6):
        self.seen = []  # (id, shingles, phones, prices)
        self.threshold = threshold

    def match(self, text):
        """Id of an earlier post that is the same ad, else None."""
        sh, ph, pr = shingles(text), phones(text), prices(text)
        for pid, sh2, ph2, pr2 in self.seen:
            jac = len(sh & sh2) / max(1, len(sh | sh2))
            if jac >= self.threshold or (ph & ph2 and pr & pr2):
                return pid
        return None

    def add(self, pid, text):
        self.seen.append((pid, shingles(text), phones(text), prices(text)))
