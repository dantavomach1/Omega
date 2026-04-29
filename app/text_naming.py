# omega/app/text_naming.py
from __future__ import annotations

import re
import unicodedata
from typing import Optional, Tuple


_MOJIBAKE_MARKERS = (
    "Ã",
    "Â",
    "â",
    "€",
    "™",
    "œ",
    "ž",
    "�",
)


def _mojibake_score(text: str) -> int:
    score = 0
    for marker in _MOJIBAKE_MARKERS:
        score += text.count(marker)
    return score


def _repair_mojibake_once(text: str) -> str:
    if not text or _mojibake_score(text) == 0:
        return text

    for src_encoding in ("latin-1", "cp1252"):
        try:
            repaired = text.encode(src_encoding, errors="ignore").decode("utf-8", errors="ignore")
        except Exception:
            continue
        if repaired and _mojibake_score(repaired) < _mojibake_score(text):
            return repaired
    return text


def sanitize_display_text(raw: str) -> str:
    """
    Normalize user-facing text coming from filenames, local metadata, or
    previously mojibaked state so widgets do not render garbage glyph soup.
    """
    text = unicodedata.normalize("NFKC", str(raw or "")).replace("\xa0", " ")
    for _ in range(3):
        repaired = unicodedata.normalize("NFKC", _repair_mojibake_once(text)).replace("\xa0", " ")
        if repaired == text:
            break
        text = repaired

    text = re.sub(r"[\u0000-\u001F\u007F]+", " ", text)
    text = text.replace("\u2022", " - ").replace("\u2014", " - ").replace("\u2013", " - ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


class NameCleaner:
    """
    Local-only title cleanup.

    This is NOT internet metadata.
    It is intentionally conservative:
      - It cleans common junk
      - It avoids “creative guesses”
      - It aims to look good and be stable
    """

    STRIP_TOKENS = {
        "1080p", "720p", "2160p", "4k", "8k",
        "webrip", "web-rip", "webdl", "web-dl",
        "bluray", "brrip", "hdrip", "dvdrip",
        "x264", "x265", "h264", "h265", "hevc", "avc",
        "hdr", "sdr", "dv", "dovi",
        "aac", "ac3", "eac3", "ddp", "ddp5", "ddp5.1", "dts", "truehd", "atmos",
        "amzn", "nf", "dsnp", "hulu", "hmax", "appletv",
        "proper", "repack", "internal", "remux",
        "subs", "subbed", "dubbed",
    }

    SMALL_WORDS = {"a", "an", "the", "and", "or", "of", "to", "in", "on", "for", "at", "by"}

    @staticmethod
    def _strip_bracket_groups(s: str) -> str:
        s = re.sub(r"\([^)]*\)", " ", s)
        s = re.sub(r"\[[^\]]*\]", " ", s)
        s = re.sub(r"\{[^}]*\}", " ", s)
        return s

    @staticmethod
    def _collapse_ws(s: str) -> str:
        return re.sub(r"\s+", " ", s).strip()

    @classmethod
    def clean(cls, raw: str) -> str:
        s = sanitize_display_text(raw)
        if not s:
            return ""

        # unify separators to spaces
        s = s.replace("_", " ").replace(".", " ").replace("-", " ")

        # remove bracket groups (years, tags, etc.)
        s = cls._strip_bracket_groups(s)

        # remove common season/episode patterns
        s = re.sub(r"\bS\d{1,2}\b", " ", s, flags=re.IGNORECASE)
        s = re.sub(r"\bS\d{1,2}E\d{1,3}\b", " ", s, flags=re.IGNORECASE)
        s = re.sub(r"\b\d{1,2}x\d{1,3}\b", " ", s, flags=re.IGNORECASE)

        # remove standalone years
        s = re.sub(r"\b(19\d{2}|20\d{2})\b", " ", s)

        parts = []
        for tok in re.split(r"\s+", s):
            t = tok.strip()
            if not t:
                continue

            # strip leading/trailing non-alnum
            t = re.sub(r"^[^A-Za-z0-9]+|[^A-Za-z0-9]+$", "", t)
            if not t:
                continue

            if t.casefold() in cls.STRIP_TOKENS:
                continue

            # conservative “release-tag-like” trimming
            if len(t) >= 10 and re.search(r"[A-Za-z].*\d", t):
                if not re.fullmatch(r"[IVXLCDM]+", t, flags=re.IGNORECASE):
                    continue

            parts.append(t)

        s = " ".join(parts)
        s = cls._collapse_ws(s)

        if not s:
            return ""

        # title case with small words rule
        words = s.split(" ")
        out = []
        for i, w in enumerate(words):
            wl = w.casefold()
            if i != 0 and wl in cls.SMALL_WORDS:
                out.append(wl)
            else:
                out.append(w[:1].upper() + w[1:].lower())
        return " ".join(out).strip()


def parse_season_episode(stem: str) -> Tuple[Optional[int], Optional[int]]:
    """
    Supports:
      - S01E02
      - 1x02
      - "Episode 02" (episode only)
    """
    s = sanitize_display_text(stem)

    m = re.search(r"\bS(\d{1,2})E(\d{1,3})\b", s, flags=re.IGNORECASE)
    if m:
        return int(m.group(1)), int(m.group(2))

    m = re.search(r"\b(\d{1,2})x(\d{1,3})\b", s, flags=re.IGNORECASE)
    if m:
        return int(m.group(1)), int(m.group(2))

    m = re.search(r"\b(?:ep|episode)\s*0*(\d{1,3})\b", s, flags=re.IGNORECASE)
    if m:
        return None, int(m.group(1))

    return None, None


def extract_show_title_from_episode_filename(filename_stem: str) -> str:
    """
    Best-effort show-title extraction for loose episode files.

    It only trusts the title text before a recognizable episode marker, so
    "Show.Name.S01E02.Title" becomes "Show Name" while "Episode 02" falls
    back to the containing folder elsewhere.
    """
    s = sanitize_display_text(filename_stem)
    s = s.replace("_", " ").replace(".", " ").replace("-", " ")
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return ""

    patterns = (
        r"\bS\d{1,2}E\d{1,3}\b",
        r"\b\d{1,2}x\d{1,3}\b",
        r"\b(?:ep|episode)\s*0*\d{1,3}\b",
    )
    first_start: Optional[int] = None
    for pattern in patterns:
        match = re.search(pattern, s, flags=re.IGNORECASE)
        if match is None:
            continue
        if first_start is None or match.start() < first_start:
            first_start = int(match.start())

    if first_start is None or first_start <= 0:
        return ""

    return NameCleaner.clean(s[:first_start]).strip()


def episode_fallback_label(index_1_based: int, season_num: Optional[int], episode_num: Optional[int]) -> str:
    """
    Fallback naming rule:
    - If we know episode number: "Episode N"
    - Else: "Episode {index}"
    """
    if episode_num is not None:
        return f"Episode {episode_num}"
    return f"Episode {index_1_based}"


def extract_episode_title_from_filename(show_display_title: str, filename_stem: str) -> str:
    """
    Example:
      Show.Name.S01E02.The.Escape.1080p.WEB-DL -> The Escape
    If no obvious title, returns "".
    """
    s = sanitize_display_text(filename_stem)
    s = s.replace("_", " ").replace(".", " ").replace("-", " ")
    s = re.sub(r"\s+", " ", s).strip()

    show_norm = NameCleaner.clean(sanitize_display_text(show_display_title)).casefold()
    if show_norm:
        words = [re.escape(w) for w in show_norm.split() if w]
        if words:
            pat = r"^\s*" + r"\s*".join(words) + r"\s*"
            s2 = re.sub(pat, "", s, flags=re.IGNORECASE).strip()
            if len(s2) < len(s):
                s = s2

    s = re.sub(r"\bS\d{1,2}E\d{1,3}\b", " ", s, flags=re.IGNORECASE)
    s = re.sub(r"\b\d{1,2}x\d{1,3}\b", " ", s, flags=re.IGNORECASE)
    s = re.sub(r"\b(?:ep|episode)\s*\d{1,3}\b", " ", s, flags=re.IGNORECASE)

    s = NameCleaner.clean(s)
    return s.strip()
