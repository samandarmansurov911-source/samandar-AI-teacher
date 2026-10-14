"""Tekshiruv natijasidan umumiy ballni (75 dan) ajratib olish."""

import re


def extract_score(text, labels=("overall", "umumiy ball")):
    """'Overall: 54/75' kabi yozuvdan 54 ni qaytaradi; topilmasa None."""
    if not text:
        return None
    for label in labels:
        m = re.search(re.escape(label) + r"[^0-9\n]{0,20}(\d{1,3})\s*/\s*75", text, re.IGNORECASE)
        if m:
            return int(m.group(1))
    # Yorliq bo'lmasa, matndagi oxirgi "X/75"
    found = re.findall(r"(\d{1,3})\s*/\s*75", text)
    return int(found[-1]) if found else None


def short_report(name, score):
    return f"{name} — {score}"
