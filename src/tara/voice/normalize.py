"""
Text normalizer for ElevenLabs TTS.

ElevenLabs multilingual_v2 does NOT reliably handle Indian-format numbers,
currency (Rs.), or dates. This module preprocesses text to convert them
into spoken words before sending to TTS.

Examples:
    "Rs.1,25,000"     → "one lakh twenty five thousand rupees"
    "2026-04-15"      → "15 April 2026"
    "Rs.20,833.33"    → "twenty thousand eight hundred thirty three rupees"
    "45 din"          → "forty five din"
"""
from __future__ import annotations

import re

from num_to_words import num_to_word


MONTH_NAMES = {
    1: "January", 2: "February", 3: "March", 4: "April",
    5: "May", 6: "June", 7: "July", 8: "August",
    9: "September", 10: "October", 11: "November", 12: "December",
}


def _num_to_spoken(n: int) -> str:
    """Convert integer to spoken English with Indian grouping (lakh, crore)."""
    words = num_to_word(n, lang="en")
    # Clean up: remove hyphens and extra commas from indic-num2words output
    words = words.replace("-", " ").replace(",", "")
    # Collapse multiple spaces
    return re.sub(r"\s+", " ", words).strip()


def normalize_currency(text: str) -> str:
    """
    Convert Rs.X,XX,XXX patterns to spoken words.

    Rs.1,25,000      → one lakh twenty five thousand rupees
    Rs.1,25,000.50   → one lakh twenty five thousand rupees fifty paise
    Rs. 20,833.33    → twenty thousand eight hundred thirty three rupees
    """
    pattern = r"Rs\.?\s*([\d,]+(?:\.\d{1,2})?)"

    def _replace(match: re.Match) -> str:
        raw = match.group(1).replace(",", "")
        parts = raw.split(".")
        main = int(parts[0])
        words = _num_to_spoken(main)

        if len(parts) > 1 and int(parts[1]) > 0:
            paise = int(parts[1].ljust(2, "0"))
            paise_words = _num_to_spoken(paise)
            return f"{words} rupees {paise_words} paise"

        return f"{words} rupees"

    return re.sub(pattern, _replace, text, flags=re.IGNORECASE)


def normalize_dates(text: str) -> str:
    """
    Convert date formats to TTS-friendly spoken form.

    2026-04-15  → 15 April 2026
    15/03/1985  → 15 March 1985

    We keep the numbers as digits here — normalize_numbers() will
    handle converting them to words if needed.
    """
    # YYYY-MM-DD
    def _replace_ymd(match: re.Match) -> str:
        y, m, d = int(match.group(1)), int(match.group(2)), int(match.group(3))
        month = MONTH_NAMES.get(m, str(m))
        return f"{d} {month} {y}"

    text = re.sub(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", _replace_ymd, text)

    # DD/MM/YYYY
    def _replace_dmy(match: re.Match) -> str:
        d, m, y = int(match.group(1)), int(match.group(2)), int(match.group(3))
        month = MONTH_NAMES.get(m, str(m))
        return f"{d} {month} {y}"

    text = re.sub(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", _replace_dmy, text)

    return text


def normalize_numbers(text: str) -> str:
    """
    Convert standalone numbers to spoken words.

    - Indian comma format: 1,25,000 → one lakh twenty five thousand
    - Large plain numbers (>999): 125000 → one lakh twenty five thousand
    - Small numbers (≤999) are left as-is — TTS handles these fine
    """
    # Indian comma format: 1,25,000 or 35,43,57,730
    def _replace_indian(match: re.Match) -> str:
        num_str = match.group(0).replace(",", "")
        n = int(num_str)
        if n > 999:
            return _num_to_spoken(n)
        return match.group(0)  # Leave small numbers

    text = re.sub(r"\b\d{1,2}(?:,\d{2})*,\d{3}\b", _replace_indian, text)

    # Plain large numbers without commas (4+ digits, not part of a word)
    def _replace_plain(match: re.Match) -> str:
        n = int(match.group(0))
        if n > 999:
            return _num_to_spoken(n)
        return match.group(0)

    text = re.sub(r"(?<![,\d])\b(\d{4,})\b(?![,\d])", _replace_plain, text)

    return text


def normalize_for_tts(text: str) -> str:
    """
    Full normalization pipeline for ElevenLabs TTS.

    Order matters:
    1. Currency (before general numbers — Rs.1,25,000 must not be split)
    2. Dates (before general numbers — 2026-04-15 must not be split)
    3. Remaining numbers
    """
    text = normalize_currency(text)
    text = normalize_dates(text)
    text = normalize_numbers(text)
    return text
