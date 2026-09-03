"""Phone number extraction and normalization utility for schedule text."""

from __future__ import annotations

import re

# Finds candidate Russian phone number strings starting with +7, 7, 8, or 9
PHONE_CANDIDATE_REGEX = re.compile(
    r"(?:\+?[78]|9)[\d\s\-\(\)\.]{8,20}\d"
)


def extract_and_format_phones(texts: list[str]) -> list[str]:
    """Extract, normalize (+7XXXXXXXXXX), and deduplicate Russian phone numbers."""
    phones: list[str] = []
    seen: set[str] = set()

    for text in texts:
        if not text:
            continue
        for match in PHONE_CANDIDATE_REGEX.finditer(text):
            digits = re.sub(r"\D", "", match.group(0))
            if len(digits) == 11 and digits[0] in ("7", "8"):
                normalized = f"+7{digits[1:]}"
                if normalized not in seen:
                    seen.add(normalized)
                    phones.append(normalized)
            elif len(digits) == 10 and digits[0] == "9":
                normalized = f"+7{digits}"
                if normalized not in seen:
                    seen.add(normalized)
                    phones.append(normalized)

    return phones
