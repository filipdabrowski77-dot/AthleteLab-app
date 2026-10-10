"""
Wczytywanie i parsowanie eksportów CSV z Vald ForceDecks (Trial Summary).

Specyfika formatu Vald:
- Kolumny asymetrii mają wartości typu "13 L" / "0.5 R" — liczba + strona dominująca.
- Daty są zazwyczaj w formacie DD/MM/YYYY (europejski).
- Nazwy kolumn często mają trailing spaces i jednostki w nawiasach kwadratowych.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd


TestType = str  # "CMJ" | "SJ" | "IMTP" | "HOP" | "UNKNOWN"

SIDE_SUFFIX = "__side"

TEST_PATTERNS: dict[TestType, list[str]] = {
    "CMJ": [r"\bCMJ\b", r"counter[\s\-]?movement"],
    "SJ": [r"\bSJ\b", r"squat[\s\-]?jump"],
    "IMTP": [r"\bIMTP\b", r"iso(metric)?[\s\-]?(mid[\s\-]?thigh|squat)"],
    "HOP": [r"\bhop\b", r"\b10[\s/\-]?5\b", r"\bHJ\b", r"reactive[\s\-]?strength"],
    "DJ": [r"\bDJ\b", r"drop[\s\-]?jump"],
    "RSAIP": [r"\bRSAIP\b", r"run[\s\-]?specific[\s\-]?ankle"],
    "RSKIP": [r"\bRSKIP\b", r"run[\s\-]?specific[\s\-]?knee"],
}

ATHLETE_CANDIDATES = ["Athlete", "Name", "Profile", "Player", "Subject"]
DATE_CANDIDATES = ["Date", "Test Date", "Timestamp", "DateTime", "Date/Time"]
TEST_TYPE_CANDIDATES = ["Test Type", "TestType", "Test", "Protocol", "Type"]


# Patterny kolumn METRYK PERFORMANCE — w merge MAX+AVG bierzemy je z pliku MAX
# (peak ability), pozostałe metryki z pliku AVERAGE (typowa wykonalność).
PERFORMANCE_FROM_MAX_PATTERNS: list[str] = [
    "jump height",
    "rsi-modified",
    "peak power / bm",
    "concentric mean force / bw",
    "force at zero velocity",
]


@dataclass
class LoadedData:
    df: pd.DataFrame
    source_name: str


# ─────────────────────────────────────────────────────────────────────────────
# Asymetria: "13 L" → (13.0, "L")
# ─────────────────────────────────────────────────────────────────────────────

_ASYM_VALUE_RE = re.compile(r"^\s*(-?\d+(?:[.,]\d+)?)\s*([LR])?\s*$", re.IGNORECASE)


# ─────────────────────────────────────────────────────────────────────────────
# Daty
# ─────────────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────────────
# Detekcja typu testu
# ─────────────────────────────────────────────────────────────────────────────

def find_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    norm = {_norm(c): c for c in df.columns}
    for cand in candidates:
        if _norm(cand) in norm:
            return norm[_norm(cand)]
    for cand in candidates:
        for col in df.columns:
            if _norm(cand) in _norm(col):
                return col
    return None


def _norm(s: str) -> str:
    return re.sub(r"[\s_\-/()\[\]]+", "", str(s)).lower()


def detect_test_type_df(df: pd.DataFrame) -> dict[TestType, pd.DataFrame]:
    test_type_col = find_column(df, TEST_TYPE_CANDIDATES)
    out: dict[TestType, pd.DataFrame] = {}

    if test_type_col:
        df = df.copy()
        df["__test_type__"] = df[test_type_col].apply(_match_test_type)
        for ttype, sub in df.groupby("__test_type__"):
            out[str(ttype)] = sub.reset_index(drop=True)
        return out

    # Brak kolumny Test Type — zgaduj po nazwach kolumn
    cols_blob = " ".join(df.columns)
    matched: TestType = "UNKNOWN"
    for ttype, patterns in TEST_PATTERNS.items():
        if any(re.search(pat, cols_blob, re.IGNORECASE) for pat in patterns):
            matched = ttype
            break
    if matched == "UNKNOWN":
        col_norm = [_norm(c) for c in df.columns]
        if any("rfd" in c and ("100ms" in c or "200ms" in c) for c in col_norm):
            matched = "IMTP"
        elif any("rsi" in c for c in col_norm) and any("contact" in c for c in col_norm):
            matched = "HOP"
        elif any("jumpheight" in c for c in col_norm) or any("countermovementdepth" in c for c in col_norm):
            matched = "CMJ"
    out[matched] = df.reset_index(drop=True)
    return out


def _match_test_type(value) -> TestType:
    if pd.isna(value):
        return "UNKNOWN"
    s = str(value)
    for ttype, patterns in TEST_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, s, re.IGNORECASE):
                return ttype
    return "UNKNOWN"
