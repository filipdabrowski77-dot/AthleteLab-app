"""
Athlete Testing Dashboard — Vald ForceDecks.

Uruchomienie:
    source .venv/bin/activate
    streamlit run app.py
"""
from __future__ import annotations

import os
import re
import subprocess
import threading
import time
from pathlib import Path

import pandas as pd
import streamlit as st

from vald.metrics import (
    ASYM_GREEN,
    ASYM_YELLOW,
    METRICS_BY_TEST,
    MetricDef,
    asymmetry_flag,
    match_column,
    resolve_metrics,
)
from vald.library import (
    LIBRARY_DIR,
    LIBRARY_PATH,
    delete_athlete,
    delete_athlete_test_day,
    delete_athlete_test_series,
    delete_athlete_test_type,
    delete_athlete_trial,
    get_athlete_data,
    get_athlete_test_days,
    get_athlete_test_type_counts,
    get_athletes_summary,
    rename_athlete,
    save_to_library,
)
from vald.profiles import (
    coach_of,
    delete_profile,
    get_profile,
    get_test_note,
    list_profile_names,
    rename_profile,
    save_profile,
    save_test_note,
)
from vald.parser import (
    ATHLETE_CANDIDATES,
    DATE_CANDIDATES,
    PERFORMANCE_FROM_MAX_PATTERNS,
    SIDE_SUFFIX,
    detect_test_type_df,
    find_column,
)
from vald.report import build_report_pdf
from vald.viz import (
    FLAG_COLORS,
    asymmetry_bipolar_trend,
    asymmetry_overview_bar,
    asymmetry_vertical_column,
    key_metrics_timeline_chart,
    metric_sparkline,
    metric_trend_chart,
)

# Aktywne typy testów na dashboardzie — inne (SJ, IMTP, DJ, SLHJ, SQT, RSAIP,
# ABCMJ, SLSEICR itp.) są w bazie ale ukrywane w UI. Dodaj "SJ" tu jak będziesz
# gotowy żeby też pokazywać Squat Jump.
ENABLED_TEST_TYPES: tuple[str, ...] = ("CMJ", "SJ", "HOP", "DJ", "IMTP", "RSAIP", "RSKIP")


TEST_LABELS = {
    "CMJ": "CMJ — Counter Movement Jump",
    "SJ": "SJ — Squat Jump",
    "IMTP": "IMTP / ISO Squat",
    "HOP": "10/5 Hop Test",
    "DJ": "DJ — Drop Jump",
    "RSAIP": "RSAIP — Run Specific Ankle Iso Push",
    "RSKIP": "RSKIP — Run Specific Knee Iso Push",
    "UNKNOWN": "Nierozpoznany typ",
}

SECTION_LABELS = {
    "performance": "PERFORMANCE",
    "strategy": "STRATEGY",
    "asymmetry": "ASYMMETRY",
}

TABLE_TAB_LABEL = "COMPARISON TABLE"

FLAG_EMOJI = {"green": "🟢", "orange": "🟡", "red": "🔴", "gray": "⚪"}

# Kluczowe metryki — zestaw najważniejszych przy pierwszym rzucie oka, per test_type.
KEY_TILES: dict[str, list[str]] = {
    "CMJ": [
        "Jump Height",
        "RSI-mod",
        "Ecc. Peak Velocity",
        "CM Depth",
        "Ecc. Duration",
        "Contraction Time",
    ],
    "SJ": [
        "Jump Height",
        "Concentric Peak Power / BM",
        "Concentric Peak Force",
        "Concentric RFD 100",
    ],
    "HOP": [
        "Best RSI",
        "Mean RSI",
        "Best Jump Height",
        "Best Contact Time",
        "Mean Contact Time",
    ],
    "DJ": [],   # rendering custom przez _render_dj_special_key_tiles (analog HOP)
    "IMTP": [
        "Peak Force",
        "Peak Force / BM",
        "Force @ 100ms / BM",
        "Force @ 200ms / BM",
    ],
    "RSAIP": [],  # rendering custom przez _render_rsaip_key_tiles (L|R obok siebie)
    "RSKIP": [],  # ten sam rendering co RSAIP (analog test, knee zamiast ankle)
}

# Strategy/Asymmetry agregacja per dzień testowy:
# - asymmetry → mean ze wszystkich rep'ów dnia
# - strategy → mean z TOP N rep'ów po primary metric (CMJ:JH N=3, HOP:RSI N=5)
#   Eliminuje warmup; standard zgodny z naukową metodologią S&C.
STRATEGY_TOP_N_BY_TEST: dict[str, int] = {
    "CMJ": 3,
    "SJ":  3,
    "HOP": 5,
    "DJ":  3,   # 3 drop jumpy z najwyższym RSI (Flight/Contact) per test
    "IMTP": 3,
    "RSAIP": 3,
    "RSKIP": 3,
}


# Główna metryka per test_type — używana jako kryterium "najlepszy skok"
# (all-time best, ranking testów w pickerze itp.).
# Kolor akcentu per typ testu — szybka identyfikacja wzrokowa w Overview
# (pasek na karcie, nagłówek). Stonowane, spójne z paletą Slate.
TEST_ACCENT: dict[str, str] = {
    "CMJ":   "oklch(0.56 0.15 248)",   # blue (główny akcent)
    "SJ":    "#7c6ff0",                # violet
    "HOP":   "oklch(0.64 0.15 162)",   # green
    "DJ":    "#e58c3a",                # orange
    "IMTP":  "#5b7ba6",                # steel blue
    "RSAIP": "#14b8a6",                # teal
    "RSKIP": "#d97706",                # amber
}

PRIMARY_METRIC_LABEL: dict[str, str] = {
    "CMJ": "Jump Height",
    "SJ": "Jump Height",
    "HOP": "Best RSI",              # w HOP główny wskaźnik to RSI, nie wysokość
    "DJ":  "Best RSI",              # DJ analogicznie — RSI = reaktywność
    "IMTP": "Peak Force",
    "RSAIP": "Peak Force",          # analog IMTP, per noga
    "RSKIP": "Peak Force",          # analog RSAIP, kolano zamiast kostka
}

# Dodatkowe metryki pokazywane obok głównej w bannerze "All-time best".
ALL_TIME_BEST_SIDE_LABELS: dict[str, list[str]] = {
    "CMJ": ["RSI-mod"],
    "SJ": ["Concentric Peak Power / BM"],   # SJ nie ma RSI-mod w eksporcie
    "HOP": ["Mean RSI"],
    "DJ":  [],   # DJ overview card ma własną logikę (Best RSI + Mean RSI)
    # IMTP: relative force + early/mid F-T cross-sections, wszystkie z TEJ
    # SAMEJ próby z najwyższym Peak Force (best execution wg Comfort 2019).
    "IMTP": ["Peak Force / BM", "Force @ 100ms / BM", "Force @ 200ms / BM"],
    "RSAIP": [],  # RSAIP overview card ma własną logikę (L|R per metryka)
    "RSKIP": [],  # RSKIP analog RSAIP
}

# Strefy referencyjne RSI (Flight Time method) — wg Flanagan, E. (2025) @eamonn.flanagan
# Używane do klasyfikacji "Reactive Strength Profile" w karcie Athlete Profile.
# Source ma drobną nakładkę między "High" (3.3–3.7) a "World class" (>3.6) —
# zaokrąglam na rozłączne kubełki przez próg 3.7.
RSI_ZONES_MALE = [
    {
        "name": "Low",
        "label": "< 2.4",
        "lo": None, "hi": 2.4,
        "summary": "Low reactive strength ability",
        "desc": "Athlete unprepared for moderate intensity plyometrics. "
                "Strength development & low-level plyometric techniques "
                "should be targeted.",
        "color": "#ef4444",   # red
    },
    {
        "name": "Moderate",
        "label": "2.4 – 2.9",
        "lo": 2.4, "hi": 2.9,
        "summary": "Moderate reactive strength ability",
        "desc": "Athlete prepared for moderate intensity plyometrics. "
                "Reactive strength is an area for performance enhancement.",
        "color": "#f59e0b",   # orange
    },
    {
        "name": "Well established",
        "label": "2.9 – 3.3",
        "lo": 2.9, "hi": 3.3,
        "summary": "Well established reactive strength ability",
        "desc": "Intensive plyometrics are appropriate.",
        "color": "#22c55e",   # green
    },
    {
        "name": "High",
        "label": "3.3 – 3.7",
        "lo": 3.3, "hi": 3.7,
        "summary": "High level of reactive strength",
        "desc": "Diminishing training returns for some athletes in this range. "
                "Critical analysis: will greater reactive strength levels "
                "improve performance?",
        "color": "#06b6d4",   # cyan
    },
    {
        "name": "World class",
        "label": "> 3.7",
        "lo": 3.7, "hi": None,
        "summary": "World class reactive strength levels",
        "desc": "Limited capacity for further improvements in reactive strength.",
        "color": "#a855f7",   # purple
    },
]

# Strefy referencyjne RSI dla kobiet (Flight Time method)
#
# UWAGA — TE PROGI NIE MAJĄ PUBLIKACJI. Powstały przez przesunięcie tabeli
# Flanagana w dół (faktycznie o 0,2 / 0,3 / 0,4 / 0,5 — nie „~0,2", jak
# mówił poprzedni komentarz). Dopóki nie ma źródła dla kobiet, tabela jest
# oznaczona w interfejsie jako orientacyjna i NIE wolno jej podpisywać
# nazwiskiem Flanagana (Filip 2026-09-04).
RSI_ZONES_FEMALE = [
    {
        "name": "Low",
        "label": "< 2.2",
        "lo": None, "hi": 2.2,
        "summary": "Low reactive strength ability",
        "desc": "Athlete unprepared for moderate intensity plyometrics. "
                "Strength development & low-level plyometric techniques "
                "should be targeted.",
        "color": "#ef4444",
    },
    {
        "name": "Moderate",
        "label": "2.2 – 2.6",
        "lo": 2.2, "hi": 2.6,
        "summary": "Moderate reactive strength ability",
        "desc": "Athlete prepared for moderate intensity plyometrics. "
                "Reactive strength is an area for performance enhancement.",
        "color": "#f59e0b",
    },
    {
        "name": "Well established",
        "label": "2.6 – 2.9",
        "lo": 2.6, "hi": 2.9,
        "summary": "Well established reactive strength ability",
        "desc": "Intensive plyometrics are appropriate.",
        "color": "#22c55e",
    },
    {
        "name": "High",
        "label": "2.9 – 3.2",
        "lo": 2.9, "hi": 3.2,
        "summary": "High level of reactive strength",
        "desc": "Diminishing training returns for some athletes in this range. "
                "Critical analysis: will greater reactive strength levels "
                "improve performance?",
        "color": "#06b6d4",
    },
    {
        "name": "World class",
        "label": "> 3.2",
        "lo": 3.2, "hi": None,
        "summary": "World class reactive strength levels",
        "desc": "Limited capacity for further improvements in reactive strength.",
        "color": "#a855f7",
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# Profile neuromięśniowe atletek (CMJ) — McLean Performance
# Źródło: 192 zawodniczek uniwersyteckich, 5 sportów, force plates + CMJ.
# 3 klastry: STRONG & FAST (target), WEAK & FAST, WEAK & SLOW.
# Wartości = centroidy profili. Klasyfikacja: nearest-centroid po normalizacji
# (range across profiles), metryki z NAJLEPSZEJ CMJ w historii zawodniczki
# (max JH Imp-Mom — spójna kinematyka jednego skoku).
# ─────────────────────────────────────────────────────────────────────────────
FEMALE_CMJ_PROFILES: list[dict] = [
    {
        "key": "strong_fast",
        "name": "STRONG & FAST",
        "emoji": "💪",
        "color": "#22c55e",
        "target": True,
        "desc": "Profil docelowy — wysoka siła względna i szybka strategia skoku. "
                "Utrzymanie: mixed-methods (siła + plyo wysokiej intensywności).",
        "values": {
            "jh": 29.8, "pp": 47.6, "bp": 17.5,
            "ct": 0.82, "stiff": 111.9, "conc": 22.3, "ecc": 25.9,
        },
    },
    {
        "key": "weak_fast",
        "name": "WEAK & FAST",
        "emoji": "⚡",
        "color": "#f59e0b",
        "target": False,
        "desc": "Szybka strategia (krótki CT, wysoka sztywność), ale deficyt siły "
                "względnej. Priorytet: maksymalna siła (squat/IMTP progres), "
                "plyo podtrzymująco.",
        "values": {
            "jh": 23.8, "pp": 41.9, "bp": 12.1,
            "ct": 0.81, "stiff": 111.8, "conc": 20.1, "ecc": 24.0,
        },
    },
    {
        "key": "weak_slow",
        "name": "WEAK & SLOW",
        "emoji": "🔻",
        "color": "#ef4444",
        "target": False,
        "desc": "Deficyt siły i wolna strategia (długi CT, niska sztywność). "
                "Priorytet: budowa siły bazowej + technika skoku, plyo niskiej "
                "intensywności na start.",
        "values": {
            "jh": 23.3, "pp": 39.5, "bp": 12.8,
            "ct": 0.94, "stiff": 73.5, "conc": 20.3, "ecc": 24.7,
        },
    },
]

# Metryki profilu: (key, label, unit, decimals, higher_better)
# CT: niżej = szybciej (higher_better=False) — tylko do strzałek/kolorów w UI.
FEMALE_PROFILE_METRICS: list[tuple[str, str, str, int, bool]] = [
    ("jh",    "CMJ Height",            "cm",     1, True),
    ("pp",    "Peak Power / BM",       "W/kg",   1, True),
    ("bp",    "Braking Power / BM",    "W/kg",   1, True),
    ("ct",    "Contraction Time",      "s",      2, False),
    ("stiff", "Lower-Limb Stiffness",  "N/m/kg", 1, True),
    ("conc",  "Max Concentric Force",  "N/kg",   1, True),
    ("ecc",   "Max Eccentric Force",   "N/kg",   1, True),
]


def _female_profile_metrics_from_best_cmj(cmj_df: pd.DataFrame) -> dict | None:
    """Wyciągnij metryki profilu z NAJLEPSZEJ CMJ w historii (max JH Imp-Mom).
    Wszystkie wartości z TEGO SAMEGO repa — spójna kinematyka jednego skoku.
    Zwraca dict {key: value} + '_date' (timestamp skoku) lub None gdy brak danych."""
    JH_COL = "Jump Height (Imp-Mom) [cm] "
    if JH_COL not in cmj_df.columns:
        # Fallback na flight time JH gdy Imp-Mom nieobecne
        JH_COL = "Jump Height (Flight Time)"
        if JH_COL not in cmj_df.columns:
            return None
    jh_vals = pd.to_numeric(cmj_df[JH_COL], errors="coerce")
    if jh_vals.isna().all():
        return None
    best_idx = jh_vals.idxmax()
    row = cmj_df.loc[best_idx]

    def _num(col: str) -> float:
        v = pd.to_numeric(pd.Series([row.get(col)]), errors="coerce").iloc[0]
        return float(v) if pd.notna(v) else float("nan")

    out: dict = {
        "jh":   _num(JH_COL),
        "pp":   _num("Peak Power / BM [W/kg] "),
        "bp":   _num("Eccentric Deceleration Mean Power / BM"),
        "conc": _num("Concentric Peak Force / BM"),
        "ecc":  _num("Eccentric Peak Force / BM"),
    }
    # Contraction Time: VALD eksportuje ms → s (profile w sekundach)
    ct_ms = _num("Contraction Time [ms] ")
    out["ct"] = ct_ms / 1000.0 if pd.notna(ct_ms) else float("nan")
    # Stiffness: VALD absolutna (N/m) → względna (N/m/kg) przez bodyweight
    stiff_abs = _num("Lower-Limb Stiffness")
    bw_kg = _num("Bodyweight in Kilograms")
    out["stiff"] = (
        stiff_abs / bw_kg
        if pd.notna(stiff_abs) and pd.notna(bw_kg) and bw_kg > 0
        else float("nan")
    )
    # Metadane skoku
    ts = pd.to_datetime(row.get("Date"), errors="coerce")
    out["_date"] = ts if pd.notna(ts) else None
    return out


def _classify_female_cmj_profile(athlete_vals: dict) -> list[dict]:
    """Nearest-centroid: dystans znormalizowany range'm metryki across 3 profile.
    Zwraca listę [{profile, distance, similarity_pct}] sortowaną od najbliższego.
    Metryki z NaN u zawodniczki są pomijane (dystans liczony na dostępnych)."""
    results = []
    for prof in FEMALE_CMJ_PROFILES:
        sq_sum, n_used = 0.0, 0
        for key, *_ in FEMALE_PROFILE_METRICS:
            av = athlete_vals.get(key)
            if av is None or pd.isna(av):
                continue
            prof_vals = [p["values"][key] for p in FEMALE_CMJ_PROFILES]
            rng = max(prof_vals) - min(prof_vals)
            if rng <= 0:
                rng = abs(max(prof_vals)) or 1.0
            z = (av - prof["values"][key]) / rng
            sq_sum += z * z
            n_used += 1
        if n_used == 0:
            continue
        dist = (sq_sum / n_used) ** 0.5
        results.append({"profile": prof, "distance": dist, "n_used": n_used})
    if not results:
        return []
    results.sort(key=lambda r: r["distance"])
    # Similarity % — softmax-like z inverse distance (czytelna proporcja w UI)
    inv = [1.0 / (r["distance"] + 0.05) for r in results]
    total = sum(inv)
    for r, w in zip(results, inv):
        r["similarity_pct"] = round(w / total * 100)
    return results


def _get_rsi_zones(sex: str = "") -> list[dict]:
    """Zwróć tabelę RSI zgodną z płcią. Default: male (gdy płeć nieustawiona)."""
    return RSI_ZONES_FEMALE if (sex or "").lower() == "female" else RSI_ZONES_MALE


def _rsi_zone(rsi: float, sex: str = "") -> dict | None:
    if pd.isna(rsi):
        return None
    for z in _get_rsi_zones(sex):
        lo, hi = z["lo"], z["hi"]
        if lo is None and rsi < hi:
            return z
        if hi is None and rsi >= lo:
            return z
        if lo is not None and hi is not None and lo <= rsi < hi:
            return z
    return None


def _current_athlete_sex() -> str:
    """Płeć aktywnego zawodnika z profilu (do doboru norm). Pusta gdy brak."""
    name = st.session_state.get("loaded_from_library")
    if not name:
        return ""
    return (get_profile(name) or {}).get("sex", "") or ""


# ─────────────────────────────────────────────────────────────────────────────
# EUR — Eccentric Utilization Ratio (McGuigan et al., 2006)
# EUR = best CMJ Jump Height / best SJ Jump Height
# Normy: VALD Data Lakehouse — NFL i NCAA Football (2024/25)
# ─────────────────────────────────────────────────────────────────────────────

# Tabela decyzyjna EUR — progi, klasyfikacja, focus treningowy i test uzupełniający.
# Strefy dostosowane do praktyki S&C: < 1.00 inwersja, 1.00–1.09 poniżej normy,
# 1.10–1.25 norma (McGuigan 2006), > 1.25 weryfikacja jakości SJ.
EUR_ZONES = [
    {
        "name": "Inwersja / brak SSC",
        "label": "< 1.00",
        "sub_label": "SJ ≥ CMJ",
        "lo": None, "hi": 1.00,
        "desc": "Brak korzyści z odruchu rozciągowego.",
        "focus": "Plyometria ekstensywna, nauka mechaniki SSC, fundament "
                 "reaktywności. Bez ciężkiej siły maksymalnej.",
        "next_test": "DJ → RSI",
        "color": "#E24B4A",
    },
    {
        "name": "Poniżej normy",
        "label": "1.00 – 1.09",
        "sub_label": "CMJ 0–9% > SJ",
        "lo": 1.00, "hi": 1.10,
        "desc": "Sub-optymalna utylizacja CM.",
        "focus": "Plyometria (fast i slow SSC), speed-strength. Siła jako "
                 "tło, nie priorytet.",
        "next_test": "DJ → RSI (dobór intensywności plyo)",
        "color": "#BA7517",
    },
    {
        "name": "Norma",
        "label": "1.10 – 1.25",
        "sub_label": "CMJ 10–25% > SJ",
        "lo": 1.10, "hi": 1.25,
        "desc": "Efektywne wykorzystanie slow SSC. McGuigan 2006.",
        "focus": "Siła maksymalna, ballistic, strength-speed. Plyometria "
                 "jako utrzymanie.",
        "next_test": "FVP lub IMTP",
        "color": "#639922",
    },
    {
        "name": "Wysoki – weryfikacja",
        "label": "> 1.25",
        "sub_label": "CMJ > 25% > SJ",
        "lo": 1.25, "hi": None,
        "desc": "Możliwy artefakt słabego SJ (RFD, muscle slack).",
        "focus": "Najpierw weryfikacja jakości SJ (force-time). Jeśli SJ "
                 "czysty → siła maksymalna + RFD koncentryczne.",
        "next_test": "IMTP + re-test SJ",
        "color": "#378ADD",
    },
]

# Normy z VALD Data Lakehouse — pomocne tylko przy populacjach football-pokrewnych.
# Dla innych dyscyplin traktuj z dystansem.
EUR_NORMS = {
    "NFL": {"10th": 0.92, "25th": 1.00, "50th": 1.07, "75th": 1.16, "99th": 1.26},
    "NCAA": {"10th": 0.99, "25th": 1.03, "50th": 1.13, "75th": 1.19, "99th": 1.24},
}


def _eur_zone(eur: float) -> dict | None:
    if pd.isna(eur):
        return None
    for z in EUR_ZONES:
        lo, hi = z["lo"], z["hi"]
        if lo is None and eur < hi:
            return z
        if hi is None and eur >= lo:
            return z
        if lo is not None and hi is not None and lo <= eur < hi:
            return z
    return None


# ─────────────────────────────────────────────────────────────────────────────
# DSI — Dynamic Strength Index
# DSI = best CMJ Concentric Peak Force [N] / best IMTP Peak Force [N]
# Wartości ABSOLUTNE (N, bez normalizacji do BM).
# Sheppard 2011, Comfort 2018, Suchomel 2020.
# ─────────────────────────────────────────────────────────────────────────────

DSI_ZONES = [
    {
        "name": "Ballistic deficit",
        "label": "< 0.60",
        "sub_label": "CMJ < 60% IMTP",
        "lo": None, "hi": 0.60,
        "desc": "Wykorzystanie <60% siły max w CMJ. Sheppard 2011.",
        "focus": "Plyometria reaktywna, jump squats 30–40% 1RM, OL derivatives "
                 "(high pull, hang clean). Niskie obciążenie, max intencja prędkości.",
        "next_test": "DJ → RSI",
        "color": "#BA7517",  # amber — deficit po stronie balistycznej, nie patologia
    },
    {
        "name": "Zbalansowany",
        "label": "0.60 – 0.80",
        "sub_label": "CMJ 60–80% IMTP",
        "lo": 0.60, "hi": 0.80,
        "desc": "Optymalna utylizacja 60–80%. Strefa celu dla sportów drużynowych. Comfort 2018.",
        "focus": "Concurrent: heavy resistance 5–8RM (squat, deadlift, RDL) + "
                 "ballistic (jump squats, throws) + trening kontrastowy.",
        "next_test": "FVP, IMTP F200",
        "color": "#639922",  # green
    },
    {
        "name": "Strength deficit",
        "label": "> 0.80",
        "sub_label": "CMJ > 80% IMTP",
        "lo": 0.80, "hi": 1.00,
        "desc": "Pełna ekspresja niskiego potencjału siłowego. Sufit power ograniczony siłą max. Suchomel 2020.",
        "focus": "Siła maksymalna: back squat, trap bar / conventional deadlift "
                 "80–95% 1RM, 3–6 powt. Bilateralne compound.",
        "next_test": "IMTP relative PF, 1RM squat",
        "color": "#378ADD",  # blue
    },
    {
        "name": "Invalid",
        "label": "> 1.00",
        "sub_label": "CMJ PF > IMTP PF",
        "lo": 1.00, "hi": None,
        "desc": "CMJ PF > IMTP PF — fizjologicznie niemożliwe. Błąd protokołu IMTP lub sztywne CMJ.",
        "focus": "Brak rekomendacji — powtórz test po familiaryzacji IMTP "
                 "(kąt 145°, „fast and hard”).",
        "next_test": "Re-test IMTP",
        "color": "#E24B4A",  # red — error
    },
]


def _dsi_zone(dsi: float) -> dict | None:
    if pd.isna(dsi):
        return None
    for z in DSI_ZONES:
        lo, hi = z["lo"], z["hi"]
        if lo is None and dsi < hi:
            return z
        if hi is None and dsi >= lo:
            return z
        if lo is not None and hi is not None and lo <= dsi < hi:
            return z
    return None


# Metryki rysowane na dużym wykresie trendów (różne linie, jeden wykres).
# Bierzemy je z najlepszych skoków per dzień (gdzie "najlepszy" = max Jump Height).
KEY_TIMELINE_METRICS: dict[str, list[str]] = {
    "CMJ": [
        "Jump Height",
        "RSI-mod",
        "Ecc. Peak Velocity",
        "CM Depth",
        "Ecc. Duration",
        "Contraction Time",
    ],
    "SJ": [
        "Jump Height",
        "Concentric Peak Power / BM",
        "Concentric Peak Force",
        "Concentric RFD 100",
    ],
    "HOP": [
        "Best RSI",
        "Mean RSI",
        "Best Jump Height",
        "Best Contact Time",
        "Mean Contact Time",
    ],
    "IMTP": [
        "Peak Force",
        "Peak Force / BM",
        "Force @ 100ms / BM",
        "Force @ 200ms / BM",
    ],
}


st.set_page_config(
    page_title="Athletic Performance Hub",
    page_icon="🏋️",
    layout="wide",
)

st.markdown(
    """
    <style>
      @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
      @import url('https://fonts.googleapis.com/css2?family=Archivo:wght@400;500;700&family=Archivo+Black&display=swap');

      /* ── Globalna typografia (bez !important żeby nie zabić ikon) ─── */
      html, body, .stApp {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont,
                     'Segoe UI', sans-serif;
        font-feature-settings: 'cv11', 'ss01';
      }
      /* Material Icons / Symbols — chroń własną czcionkę ikon Streamlita */
      .material-icons,
      .material-symbols-outlined,
      .material-symbols-rounded,
      [class*="material-symbols"],
      span[data-testid*="icon"] {
        font-family: 'Material Symbols Outlined', 'Material Icons' !important;
      }

      /* AGRESYWNY upward shift — wszystkie wrapper'y Streamlit z 0 top padding */
      html, body, .stApp,
      [data-testid="stAppViewContainer"],
      [data-testid="stMain"],
      [data-testid="stMainBlockContainer"],
      [data-testid="block-container"],
      section.main,
      .main,
      .main .block-container {
        padding-top: 0 !important;
        margin-top: 0 !important;
      }
      .main .block-container,
      [data-testid="stMainBlockContainer"],
      [data-testid="block-container"] {
        /* 1.4→0.6 rem: ekran zaczynał się nisko, a nad paskiem „← Start"
           nie ma żadnej treści do oddzielenia (Filip 2026-09-04) */
        padding-top: 0.6rem !important;
        max-width: 1750px !important;
        padding-left: 2rem !important;
        padding-right: 2rem !important;
        margin-left: auto !important;
        margin-right: auto !important;
      }
      /* Ukryj wszystkie Streamlit chrome na górze + zeruj wysokość */
      [data-testid="stHeader"],
      [data-testid="stToolbar"],
      [data-testid="stDecoration"],
      [data-testid="stStatusWidget"],
      header[data-testid="stHeader"],
      .stApp > header {
        display: none !important;
        height: 0 !important;
        min-height: 0 !important;
        visibility: hidden !important;
      }
      /* Czasami Streamlit dorzuca empty spacer div jako pierwsze dziecko */
      .stApp > div:first-child:not([data-testid]):empty {
        display: none !important;
      }
      /* Kontenery z samym <style> (wstrzyknięcia CSS) zabierają slot w
         flex-gapie pionowego bloku (16px każdy) → ~110px pustej przestrzeni
         na górze nad logo/searchem. Wyrzucamy je z layoutu. */
      [data-testid="stElementContainer"]:has(style) {
        display: none !important;
      }
      /* Pierwszy element wewnątrz block-container ma czasem nadmiarowy margin */
      [data-testid="block-container"] > div:first-child,
      .main .block-container > div:first-child {
        margin-top: 0 !important;
        padding-top: 0 !important;
      }

      /* ── Bazowe tła z subtelnym gradientem ──────────────────────────── */
      .stApp {
        background: var(--aph-page);
      }
      [data-testid="stSidebar"] {
        background: var(--aph-panel);
        border-right: 1px solid var(--aph-line);
      }
      [data-testid="stSidebar"] [data-testid="stSidebarUserContent"] {
        padding-top: 1.5rem;
      }

      /* ── Logo — Athletic Performance Hub (stencil A-mark + wordmark) ──── */
      /* Tokens: ink=#0E0E10, bg=#161618, bone=#F2EFE8, accent=#B54A32 */
      .aph-logo-bar {
        background: transparent;
        padding: 0;
        margin: 0 0 24px 0;
        display: flex;
        align-items: center;
      }
      .aph-logo {
        display: inline-flex;
        align-items: center;
        gap: 16px;
        margin: 0;
      }
      .aph-mark-frame {
        background: #0E0E10;
        padding: 7px;
        border-radius: 10px;
        display: grid;
        place-items: center;
        flex-shrink: 0;
        box-shadow: 0 6px 14px -10px rgba(14, 14, 16, .3);
      }
      .aph-logo svg {
        width: 44px; height: 44px;
        display: block;
        flex-shrink: 0;
      }
      .aph-wordmark { line-height: 1; }
      .aph-word-1 {
        font-family: 'Archivo Black', 'Archivo', sans-serif;
        font-size: 1.5rem;
        letter-spacing: -0.02em;
        text-transform: uppercase;
        color: #0E0E10;
      }
      .aph-word-2 {
        font-family: 'Archivo', sans-serif;
        font-weight: 500;
        font-size: 0.62rem;
        letter-spacing: 0.34em;
        margin-top: 5px;
        text-transform: uppercase;
        color: #5E5E64;
      }
      /* Header Streamlita transparentny — żeby tytuł nie był odcięty */
      [data-testid="stHeader"] {
        background: transparent;
      }

      /* ── Banner z imieniem zawodnika ───────────────────────────────── */
      .athlete-name-banner {
        font-size: 2.1rem; font-weight: 700; color: #f1f5f9;
        margin: 0.4rem 0 0.2rem 0; line-height: 1.1;
        letter-spacing: -0.02em;
      }
      .athlete-name-banner .icon {
        margin-right: 0.5rem; opacity: 0.85;
      }
      .athlete-count-banner {
        font-size: 1.15rem; font-weight: 600; color: #cbd5e1;
        margin: 0.5rem 0;
      }

      /* ── Karta profilu pod imieniem — minimalistyczna, "ala metryka" ── */
      .profile-card {
        display: flex; flex-wrap: wrap; gap: 1.6rem;
        margin: 0.3rem 0 1rem 0;
      }
      .profile-field {
        display: flex; flex-direction: column; gap: 0.15rem;
        min-width: 0;
      }
      .profile-field .pf-label {
        font-size: 0.68rem;
        color: #64748b;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        font-weight: 600;
      }
      .profile-field .pf-value {
        font-size: 1rem;
        color: #f1f5f9;
        font-weight: 500;
        line-height: 1.35;
      }

      /* ── Stat pills u góry ─────────────────────────────────────────── */
      .stat-pills {
        display: flex; flex-wrap: wrap; gap: 0.6rem;
        margin: 0.4rem 0 1.25rem 0;
      }
      .stat-pill {
        background: linear-gradient(180deg, #0e131a 0%, #0b1015 100%);
        border: 1px solid rgba(255, 255, 255, 0.05);
        border-radius: 10px;
        padding: 0.55rem 0.95rem;
        display: flex; align-items: baseline; gap: 0.45rem;
        line-height: 1.1;
        transition: border-color 150ms ease;
      }
      .stat-pill:hover {
        border-color: rgba(255, 255, 255, 0.1);
      }
      .stat-pill .num {
        font-size: 1.05rem; font-weight: 700; color: #f1f5f9;
        font-variant-numeric: tabular-nums;
      }
      .stat-pill .lbl {
        font-size: 0.72rem; color: #64748b;
        text-transform: uppercase; letter-spacing: 0.06em;
        font-weight: 500;
      }

      /* ── All-time best — hero card ─────────────────────────────────── */
      .abest-card {
        position: relative;
        background:
          radial-gradient(circle at 0% 0%, rgba(234, 179, 8, 0.08), transparent 50%),
          linear-gradient(135deg, #131822 0%, #0a0f15 100%);
        border: 1px solid rgba(234, 179, 8, 0.25);
        border-left: 3px solid #eab308;
        border-radius: 14px;
        padding: 1.1rem 1.4rem;
        margin: 0.75rem 0 1.5rem 0;
        box-shadow:
          0 0 40px rgba(234, 179, 8, 0.04),
          0 1px 0 rgba(255, 255, 255, 0.04) inset;
      }
      .abest-header {
        display: flex; align-items: center; gap: 0.6rem;
        margin-bottom: 0.3rem;
      }
      .abest-trophy { font-size: 1.3rem; }
      .abest-title {
        font-size: 0.72rem; font-weight: 700;
        color: #eab308; letter-spacing: 0.18em;
      }
      .abest-date {
        margin-left: auto;
        color: #64748b; font-size: 0.8rem; font-weight: 500;
      }
      .abest-jump {
        font-size: 3rem; font-weight: 800;
        color: #f1f5f9; line-height: 1; margin: 0.2rem 0 0.7rem 0;
        letter-spacing: -0.03em; font-variant-numeric: tabular-nums;
      }
      .abest-jump-unit {
        font-size: 1.05rem; color: #64748b; font-weight: 500;
        margin-left: 0.2rem; letter-spacing: 0;
      }
      .abest-metrics {
        color: #cbd5e1; font-size: 0.88rem;
        display: flex; flex-wrap: wrap; gap: 0.85rem 1.3rem;
      }
      .abest-metric { white-space: nowrap; }
      .abest-metric-label { color: #64748b; font-weight: 500; }
      .abest-metric-value {
        color: #f1f5f9; font-weight: 700; margin-left: 0.3rem;
        font-variant-numeric: tabular-nums;
      }

      /* ── Kafelki metryk — wycentrowane dla spójnego wyglądu ───────── */
      .tile {
        padding: 0.6rem 0.5rem 0.5rem 0.5rem;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        text-align: center;
        min-height: 110px;
      }
      .tile.tile-asym {
        border-left: 3px solid var(--flag, #475569);
        padding-left: 0.8rem;
      }
      .tile-label {
        font-size: 0.68rem; text-transform: uppercase; color: #64748b;
        letter-spacing: 0.08em; margin-bottom: 0.6rem; font-weight: 600;
        line-height: 1.2;
      }
      .tile-value {
        font-size: 1.6rem; font-weight: 700; color: #f1f5f9; line-height: 1.1;
        letter-spacing: -0.02em; font-variant-numeric: tabular-nums;
        display: flex; flex-wrap: wrap; align-items: baseline;
        justify-content: center; gap: 0.15rem 0.35rem;
      }
      .tile-value .unit {
        font-size: 0.78rem; color: #64748b; font-weight: 500;
        letter-spacing: 0;
      }
      /* Side jako inline kolorowy suffix obok wartości (VALD style "13% P").
         L = ocean blue (lewa), R/P = amber (prawa). */
      .side-letter-inline {
        font-family: var(--aph-display);
        font-size: 1.0rem;
        font-weight: 700;
        letter-spacing: -0.01em;
        margin-left: 0.25rem;
        vertical-align: baseline;
      }
      .stApp .side-letter-inline.side-L {
        color: #3B6FB0 !important;
      }
      .stApp .side-letter-inline.side-R {
        color: #E08A2B !important;
      }
      .tile-delta {
        font-size: 0.74rem; margin-top: 0.5rem; font-weight: 600;
        font-variant-numeric: tabular-nums;
        text-align: center;
      }
      .delta-up { color: var(--aph-good); }
      .delta-down { color: var(--aph-bad); }
      .delta-neutral { color: #64748b; }

      /* ── Container border (st.container(border=True)) ─────────────── */
      [data-testid="stVerticalBlockBorderWrapper"] {
        border-color: rgba(255, 255, 255, 0.05) !important;
        background: linear-gradient(180deg, #0e131a 0%, #0a0f15 100%);
        border-radius: 12px !important;
      }

      /* ── Tabs — refined underline style ────────────────────────────── */
      .stTabs [data-baseweb="tab-list"] {
        gap: 0.25rem;
        border-bottom: 1px solid rgba(255, 255, 255, 0.05);
        background: transparent;
      }
      .stTabs [data-baseweb="tab"] {
        background: transparent !important;
        border: none !important;
        border-radius: 0 !important;
        padding: 0.55rem 1rem !important;
        color: #64748b !important;
        font-weight: 500 !important;
        transition: color 150ms ease;
      }
      .stTabs [data-baseweb="tab"]:hover {
        color: #cbd5e1 !important;
      }
      .stTabs [aria-selected="true"] {
        color: #f1f5f9 !important;
        font-weight: 600 !important;
      }
      .stTabs [data-baseweb="tab-highlight"] {
        background: #22c55e !important;
        height: 2px !important;
      }
      .stTabs [data-baseweb="tab-list"] button [data-testid="stMarkdownContainer"] p {
        font-size: 0.95rem;
        font-weight: inherit;
        letter-spacing: 0.01em;
      }

      /* ── Metric (st.metric) refinement ─────────────────────────────── */
      [data-testid="stMetric"] {
        background: linear-gradient(180deg, #0e131a 0%, #0a0f15 100%);
        border: 1px solid rgba(255, 255, 255, 0.05);
        border-radius: 10px;
        padding: 0.85rem 0.95rem;
      }
      [data-testid="stMetricLabel"] {
        color: #64748b !important;
        font-size: 0.72rem !important;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        font-weight: 600 !important;
      }
      [data-testid="stMetricValue"] {
        color: #f1f5f9 !important;
        font-variant-numeric: tabular-nums;
        font-weight: 700 !important;
        letter-spacing: -0.02em;
      }

      /* ── Expander odświeżony ──────────────────────────────────────── */
      .streamlit-expanderHeader,
      [data-testid="stExpander"] summary {
        background: transparent !important;
        border: 1px solid rgba(255, 255, 255, 0.05) !important;
        border-radius: 8px !important;
        color: #cbd5e1 !important;
        font-weight: 500 !important;
        transition: border-color 150ms ease, background 150ms ease;
      }
      [data-testid="stExpander"] summary:hover {
        border-color: rgba(255, 255, 255, 0.1) !important;
        background: rgba(255, 255, 255, 0.01) !important;
      }

      /* ── Buttons refinement ────────────────────────────────────────── */
      .stButton button {
        border: 1px solid rgba(255, 255, 255, 0.08);
        background: linear-gradient(180deg, #0e131a 0%, #0a0f15 100%);
        color: #cbd5e1;
        font-weight: 500;
        transition: all 150ms ease;
      }
      .stButton button:hover {
        border-color: rgba(34, 197, 94, 0.4);
        color: #f1f5f9;
      }
      .stButton button[kind="primary"] {
        background: var(--aph-ink) !important;
        border-color: var(--aph-ink) !important;
        color: var(--aph-bone) !important;
        font-weight: 600 !important;
        box-shadow: var(--aph-shadow) !important;
      }

      /* ── NORMS chip — slim height matching tabs ─────────────────────── */
      /* Target via has(): any stButton whose label contains "NORMS" */
      .stButton:has(p:is(*)) button[kind="secondary"]:where(:has([data-testid="stMarkdownContainer"])) {
        /* fallback dla browserów bez :has() — generic secondary buttons stay default */
      }
      .stButton button[aria-label*="NORMS"],
      .stButton button:has(p:where(*)):where([kind="secondary"]) {
        /* no-op selector — actual rule below targets via key wrapper */
      }
      /* Precyzyjny target: button w ostatniej kolumnie horizontal block,
         tylko gdy ma label "NORMS" — Streamlit zapisuje label w button textContent.
         Używamy :has() które jest dostępne we wszystkich nowych przeglądarkach. */
      [data-testid="stHorizontalBlock"]
        > [data-testid="column"]:last-child
        .stButton button[kind="secondary"]:has(p) {
        padding: 0.35rem 0.55rem !important;
        font-size: 0.85rem !important;
        min-height: unset !important;
        line-height: 1.2 !important;
        font-weight: 600 !important;
        border-color: var(--aph-line) !important;
        color: var(--aph-ink) !important;
        background: var(--aph-card) !important;
      }
      [data-testid="stHorizontalBlock"]
        > [data-testid="column"]:last-child
        .stButton button[kind="secondary"]:hover {
        border-color: var(--aph-ink) !important;
        background: var(--aph-tint) !important;
      }

      /* ── Selectbox + radio refinement ─────────────────────────────── */
      .stSelectbox [data-baseweb="select"] > div,
      .stRadio [role="radiogroup"] {
        background: #0e131a !important;
        border-color: rgba(255, 255, 255, 0.06) !important;
      }

      /* ── File uploader subtle ─────────────────────────────────────── */
      [data-testid="stFileUploader"] section {
        background: rgba(255, 255, 255, 0.01) !important;
        border: 1px dashed rgba(255, 255, 255, 0.1) !important;
        border-radius: 10px !important;
      }
      /* Ukryj "Drag and drop files here" + "Limit 50MB per file • CSV" */
      [data-testid="stFileUploaderDropzoneInstructions"] {
        display: none !important;
      }

      /* ── Tooltipy ── */
      [data-baseweb="tooltip"] {
        font-size: 0.8rem !important;
        background: #0e131a !important;
        border: 1px solid rgba(255, 255, 255, 0.08) !important;
      }

      /* ── Scrollbar refinement ──────────────────────────────────────── */
      ::-webkit-scrollbar { width: 8px; height: 8px; }
      ::-webkit-scrollbar-track { background: transparent; }
      ::-webkit-scrollbar-thumb {
        background: rgba(255, 255, 255, 0.08);
        border-radius: 4px;
      }
      ::-webkit-scrollbar-thumb:hover {
        background: rgba(255, 255, 255, 0.15);
      }
    </style>
    """,
    unsafe_allow_html=True,
)


# ─────────────────────────────────────────────────────────────────────────────
# APH v2 — Athletic Performance Hub redesign (bone/cream canvas, black ink,
# selective red accent). Wstawione jako oddzielny blok PO starym CSS żeby
# istniejące klasy działały podczas stopniowej migracji komponentów.
# Pełny spec: docs/design/redesign-spec.md
# Referencja React: docs/design/react-reference.md
# Mockup: docs/design/cmj-mockup.png
# ─────────────────────────────────────────────────────────────────────────────
st.markdown(
    """
    <style>
      @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600&family=Archivo:wght@400;500;600;700;900&display=swap');

      :root {
        /* surfaces — paleta wspólna z powłoką (views/app_shell/index.html),
           żeby Performance testing nie odstawał chłodnym błękitem od reszty
           aplikacji (Filip 2026-09-03). Nazwy zmiennych zostają, zmieniają
           się tylko wartości — reszta arkusza działa bez zmian. */
        --aph-page:    #fbfbf9;
        --aph-panel:   #FFFFFF;
        --aph-card:    #FFFFFF;
        --aph-ink:     #1c1b18;
        --aph-ink-2:   #3c3a33;
        --aph-line:    #e6e3db;
        --aph-line-2:  #f2f1ec;
        --aph-dim:     #6f6b61;
        --aph-mute:    #8a867c;
        --aph-bone:    #f8f7f4;
        --aph-tint:    #f2f1ec;
        --aph-line-h:  #d8d5cc;
        --aph-shadow:  0 1px 3px rgba(28,27,24,.06);

        /* brand + state */
        --aph-accent:        oklch(0.56 0.15 248);  /* blue — używaj oszczędnie */
        --aph-accent-deep:   oklch(0.48 0.15 248);
        --aph-good:          oklch(0.64 0.15 162);
        --aph-bad:           oklch(0.58 0.18 25);

        /* type */
        --aph-display: "Archivo Black", "Archivo", system-ui, sans-serif;
        --aph-text:    "Archivo", system-ui, sans-serif;
        --aph-mono:    "JetBrains Mono", ui-monospace, "SF Mono", monospace;

        /* radii */
        --aph-r-card:  13px;
        --aph-r-pill:  999px;
        --aph-r-md:    12px;
      }

      /* Globalne tło + tekst — bone canvas, ink text, Archivo font.
         !important żeby pobić stary dark gradient na .stApp. */
      html, body,
      .stApp,
      [data-testid="stAppViewContainer"],
      [data-testid="stMain"],
      .main {
        background: var(--aph-page) !important;
        color: var(--aph-ink) !important;
      }
      html, body, .stApp {
        font-family: var(--aph-text) !important;
      }
      /* mniej pustego pasa nad treścią — więcej widać na ekranie
         (Filip 2026-09-01) */
      .stApp .block-container { padding-top: 1.2rem !important; }
      .stApp::before { content: none !important; }   /* zabija ewentualne pseudo-bg */

      /* Sidebar (gdyby był używany) — panel cream */
      [data-testid="stSidebar"] {
        background: var(--aph-panel) !important;
        border-right: 1px solid var(--aph-line) !important;
      }

      /* Streamlit header transparent (pozostawiamy strukturę, ukryjemy chrome
         w fazie 2 gdy własny hero będzie gotowy) */
      [data-testid="stHeader"] { background: transparent !important; }

      /* ── Override starych klas które miały jasny tekst na ciemnym tle ──
         Po Fazie 1 te elementy są na bone bg, więc muszą mieć ink color. */
      .athlete-name-banner,
      .athlete-count-banner,
      .profile-field .pf-value,
      .stat-pill .num,
      .abest-jump,
      .abest-metric-value,
      .tile-value {
        color: var(--aph-ink) !important;
      }
      .profile-field .pf-label,
      .stat-pill .lbl,
      .abest-metric-label,
      .abest-date,
      .tile-label {
        color: var(--aph-dim) !important;
      }

      /* Stare kontenery (st.container border, stat-pill, metric, expander)
         muszą zmienić tła z ciemnego gradientu na białe karty żeby były czytelne */
      [data-testid="stVerticalBlockBorderWrapper"] {
        background: var(--aph-card) !important;
        border-color: var(--aph-line) !important;
        border-radius: var(--aph-r-card) !important;
      }
      .stat-pill {
        background: var(--aph-card) !important;
        border-color: var(--aph-line) !important;
      }
      [data-testid="stMetric"] {
        background: var(--aph-card) !important;
        border-color: var(--aph-line) !important;
      }
      [data-testid="stMetricLabel"] { color: var(--aph-dim) !important; }
      [data-testid="stMetricValue"] { color: var(--aph-ink) !important; }
      .streamlit-expanderHeader,
      [data-testid="stExpander"] summary {
        background: var(--aph-card) !important;
        border-color: var(--aph-line) !important;
        color: var(--aph-ink) !important;
      }

      /* Buttons — w fazie 5 zrobimy własne pill components.
         Na razie: białe tło + ink text żeby były czytelne. */
      .stButton button {
        background: var(--aph-card) !important;
        border-color: var(--aph-line) !important;
        color: var(--aph-ink) !important;
      }
      .stButton button:hover {
        border-color: var(--aph-ink) !important;
        color: var(--aph-ink) !important;
      }

      /* Selectbox + radio — białe tła */
      .stSelectbox [data-baseweb="select"] > div,
      .stRadio [role="radiogroup"] {
        background: var(--aph-card) !important;
        border-color: var(--aph-line) !important;
      }

      /* All-time best card — tymczasowo na białej karcie żeby było czytelne.
         Faza 5 przebuduje to na primary KPI card. */
      .abest-card {
        background: var(--aph-card) !important;
        border-color: var(--aph-line) !important;
        border-left-color: var(--aph-accent) !important;
      }
      .abest-title { color: var(--aph-accent) !important; }

      /* Tabs — w Fazie 3 przebudujemy na styl mockupu.
         Na razie: ink color + dim dla nieaktywnych, accent na underline. */
      .stTabs [data-baseweb="tab-list"] {
        border-bottom: 1px solid var(--aph-line) !important;
      }
      .stTabs [data-baseweb="tab"] {
        color: var(--aph-dim) !important;
      }
      .stTabs [data-baseweb="tab"]:hover {
        color: var(--aph-ink) !important;
      }
      .stTabs [aria-selected="true"] {
        color: var(--aph-ink) !important;
      }
      .stTabs [data-baseweb="tab-highlight"] {
        background: var(--aph-accent) !important;
        height: 3px !important;
      }

      /* Tooltipy */
      [data-baseweb="tooltip"] {
        background: var(--aph-ink) !important;
        border: 1px solid var(--aph-line) !important;
        color: var(--aph-bone) !important;
      }

      /* Scrollbar — ciemniejszy na bone bg */
      ::-webkit-scrollbar-thumb {
        background: rgba(14, 14, 16, 0.15) !important;
      }
      ::-webkit-scrollbar-thumb:hover {
        background: rgba(14, 14, 16, 0.28) !important;
      }

      /* ── Utility classes ── */
      .aph-mono {
        font-family: var(--aph-mono);
        letter-spacing: 0.18em;
        text-transform: uppercase;
      }
      .aph-display {
        font-family: var(--aph-display);
        letter-spacing: -0.02em;
      }
    </style>
    """,
    unsafe_allow_html=True,
)


# ─────────────────────────────────────────────────────────────────────────────
# Faza 2: CSS — Hero atlety (utility row + avatar + identity + actions)
# ─────────────────────────────────────────────────────────────────────────────
st.markdown(
    """
    <style>
      /* ── Hero container ─────────────────────────────────────────────── */
      /* Karta hero — realny kontener Streamlit (.st-key-aph_hero), nie
         auto-domykany div z markdownu. Ramka + oddech od tabów pod spodem. */
      .stApp .st-key-aph_hero {
        padding: 14px 20px;
        background: var(--aph-panel);
        border: 1px solid var(--aph-line);
        border-radius: var(--aph-r-card);
        box-shadow: var(--aph-shadow);
        margin: 0 0 18px 0;
      }
      .aph-v2-hero {
        padding: 12px 20px 14px;
        background: var(--aph-panel);
        border: 1px solid var(--aph-line);
        border-radius: var(--aph-r-card);
        margin: 0 0 10px 0;
      }

      /* Utility row (logo+breadcrumb LEFT / status+bell+coach RIGHT) */
      .aph-v2-util {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 22px;
      }
      .aph-v2-brand {
        display: flex;
        align-items: center;
        gap: 14px;
      }
      .aph-v2-brand-mark {
        width: 44px;
        height: 44px;
        border-radius: 12px;
        background: var(--aph-ink);
        display: grid;
        place-items: center;
        flex-shrink: 0;
      }
      .aph-v2-brand-text { line-height: 1; }
      .aph-v2-brand-title {
        font-family: var(--aph-display);
        font-size: 13px;
        letter-spacing: 0.02em;
        text-transform: uppercase;
        color: var(--aph-ink);
      }
      .aph-v2-breadcrumb {
        font-family: var(--aph-mono);
        font-size: 10px;
        letter-spacing: 0.24em;
        color: var(--aph-mute);
        margin-top: 5px;
        text-transform: uppercase;
      }
      .aph-v2-breadcrumb .crumb-active {
        color: var(--aph-ink);
      }
      .aph-v2-util-right {
        display: flex;
        align-items: center;
        gap: 10px;
      }
      .aph-v2-status-pill {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        padding: 8px 14px;
        background: var(--aph-card);
        border: 1px solid var(--aph-line);
        border-radius: var(--aph-r-pill);
        font-family: var(--aph-mono);
        font-size: 11px;
        letter-spacing: 0.06em;
        color: var(--aph-ink);
        text-transform: uppercase;
      }
      .aph-v2-status-dot {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        background: var(--aph-good);
      }
      .aph-v2-icon-btn {
        width: 38px;
        height: 38px;
        border-radius: var(--aph-r-pill);
        background: var(--aph-card);
        border: 1px solid var(--aph-line);
        display: grid;
        place-items: center;
        cursor: pointer;
      }
      .aph-v2-icon-btn svg { color: var(--aph-ink); }
      .aph-v2-coach-pill {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        padding: 5px 14px 5px 5px;
        background: var(--aph-card);
        border: 1px solid var(--aph-line);
        border-radius: var(--aph-r-pill);
        font-family: var(--aph-text);
        font-size: 13px;
        font-weight: 600;
        color: var(--aph-ink);
      }
      .aph-v2-coach-avatar {
        width: 28px;
        height: 28px;
        border-radius: 50%;
        background: var(--aph-accent);
        color: var(--aph-bone);
        display: grid;
        place-items: center;
        font-family: var(--aph-display);
        font-size: 11px;
        letter-spacing: 0;
      }

      /* Hero row (back + avatar + identity + actions) */
      .aph-v2-hero-row {
        display: flex;
        align-items: center;
        gap: 24px;
      }
      .aph-v2-back {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        font-family: var(--aph-text);
        font-size: 13px;
        font-weight: 500;
        color: var(--aph-dim);
        text-decoration: none;
        white-space: nowrap;
      }
      /* Wszystkie standard st.button → oval pill (mockup style spójny APH v2).
         Faza 1 base button styling dorzuca background + border, tu dodajemy
         border-radius i większy padding. */
      .stApp .stButton > button {
        border-radius: 999px !important;
      }
      .aph-v2-avatar {
        width: 46px;
        height: 46px;
        border-radius: 13px;
        background: var(--aph-ink);
        position: relative;
        display: grid;
        place-items: center;
        flex-shrink: 0;
        box-shadow: 0 8px 18px -10px rgba(15,23,40,.35),
                    0 0 0 2px color-mix(in oklab, var(--aph-accent) 30%, transparent);
        overflow: hidden;
      }
      .aph-v2-avatar-initials {
        font-family: var(--aph-display);
        font-size: 17px;
        color: var(--aph-bone);
        letter-spacing: -0.02em;
        position: relative;
        z-index: 2;
      }
      .aph-v2-avatar-mark {
        position: absolute;
        inset: 0;
        width: 100%;
        height: 100%;
        opacity: 0.12;
        z-index: 1;
        pointer-events: none;
      }
      .aph-v2-avatar-dot {
        position: absolute;
        top: 6px;
        right: 6px;
        width: 12px;
        height: 12px;
        border-radius: 50%;
        background: var(--aph-good);
        border: 2.5px solid var(--aph-ink);
        z-index: 3;
      }
      .aph-v2-avatar-dot.stale {
        background: oklch(0.78 0.16 80);    /* amber for 14-30d */
      }
      .aph-v2-avatar-dot.overdue {
        background: var(--aph-bad);
      }

      .aph-v2-identity {
        flex: 1;
        min-width: 0;
      }
      .aph-v2-badges {
        display: flex;
        align-items: center;
        gap: 10px;
        margin-bottom: 6px;
        flex-wrap: wrap;
      }
      .aph-v2-badge-active {
        font-family: var(--aph-text);
        font-size: 12px;
        font-weight: 600;
        letter-spacing: 0;
        text-transform: none;
        color: var(--aph-good);
        padding: 4px 10px 4px 9px;
        border-radius: 999px;
        background: color-mix(in oklab, var(--aph-good) 12%, transparent);
        border: 1px solid color-mix(in oklab, var(--aph-good) 28%, transparent);
        display: inline-flex;
        align-items: center;
        gap: 4px;
      }
      .aph-v2-badge-active.stale {
        color: oklch(0.55 0.12 80);
        background: color-mix(in oklab, oklch(0.78 0.16 80) 12%, transparent);
        border-color: color-mix(in oklab, oklch(0.78 0.16 80) 22%, transparent);
      }
      .aph-v2-badge-code {
        font-family: var(--aph-mono);
        font-size: 10px;
        color: var(--aph-mute);
        letter-spacing: 0.16em;
        text-transform: uppercase;
      }
      .aph-v2-name-row {
        display: flex;
        align-items: center;
        gap: 14px;
        flex-wrap: wrap;
      }
      .aph-v2-name {
        font-family: var(--aph-display);
        /* 32→24 px: nazwisko zajmowało pół karty, a jest tylko etykietą
           tego, czyje dane oglądam (Filip 2026-09-04) */
        font-size: 24px;
        margin: 0;
        letter-spacing: -0.025em;
        line-height: 1;
        color: var(--aph-ink);
      }
      .aph-v2-meta {
        margin: 8px 0 0 0;
        padding: 0;
        display: flex;
        gap: 18px;
        flex-wrap: wrap;
      }
      /* Hero meta: label inline LEFT + value RIGHT (mockup style "Sport Basketball") */
      .aph-v2-meta-item {
        display: inline-flex;
        align-items: baseline;
        gap: 6px;
        min-width: 0;
      }
      .aph-v2-meta-label {
        font-family: var(--aph-text);
        font-size: 13px;
        color: var(--aph-mute);
        letter-spacing: 0;
        text-transform: none;
        margin: 0;
        font-weight: 500;
      }
      .aph-v2-meta-value {
        margin: 0;
        font-family: var(--aph-text);
        font-weight: 600;
        font-size: 13px;
        color: var(--aph-ink);
      }

      /* Etykieta przycisku Streamlita to <p> w stMarkdownContainer, a nie
         tekst samego <button>. Globalna reguła koloru na tym kontenerze
         wygrywała z kolorem dziedziczonym z przycisku, więc napis „Edit"
         był czarny na czarnym tle (Filip 2026-09-03). Kolor i font trzeba
         ustawiać na <p>, inaczej Streamlit narzuca własne. */
      .stApp .st-key-aph_hero_actions [data-testid="stHorizontalBlock"]
        > [data-testid="stColumn"]:first-child .stButton button
        [data-testid="stMarkdownContainer"] p,
      .stApp .st-key-aph_hero_actions [data-testid="stHorizontalBlock"]
        > [data-testid="stColumn"]:first-child .stButton button p {
        color: var(--aph-bone) !important;
        font-family: var(--aph-text) !important;
        font-size: 13px !important;
        font-weight: 600 !important;
      }
      /* to samo dla każdego przycisku z ciemnym tłem na tym ekranie */
      .stApp [data-testid="stBaseButton-primary"] [data-testid="stMarkdownContainer"] p {
        color: #fff !important;
      }

      /* Actions w hero — realny kontener (.st-key-aph_hero_actions).
         Edit = solid ink pill (primary wg handoffu), "⋯" = ghost. */
      .stApp .st-key-aph_hero_actions [data-testid="stHorizontalBlock"]
        > [data-testid="stColumn"]:first-child .stButton button,
      .stApp .st-key-aph_hero_actions [data-testid="stHorizontalBlock"]
        > [data-testid="column"]:first-child .stButton button {
        background: var(--aph-ink) !important;
        color: var(--aph-bone) !important;
        border: none !important;
        border-radius: var(--aph-r-pill) !important;
        padding: 10px 18px !important;
        font-family: var(--aph-text) !important;
        font-weight: 600 !important;
        font-size: 13px !important;
        box-shadow: 0 1px 0 rgba(0,0,0,.06), 0 8px 24px -10px rgba(14,14,16,.45) !important;
      }
      .stApp .st-key-aph_hero_actions [data-testid="stHorizontalBlock"]
        > [data-testid="stColumn"]:first-child .stButton button:hover,
      .stApp .st-key-aph_hero_actions [data-testid="stHorizontalBlock"]
        > [data-testid="column"]:first-child .stButton button:hover {
        background: var(--aph-ink-2) !important;
        color: var(--aph-bone) !important;
      }
      /* Sekundarne pill (Norms/Edit/Delete) */
      .aph-v2-actions-row .stButton button {
        background: var(--aph-card) !important;
        border: 1px solid var(--aph-line) !important;
        color: var(--aph-ink) !important;
        border-radius: var(--aph-r-pill) !important;
        padding: 8px 14px !important;
        font-family: var(--aph-text) !important;
        font-weight: 600 !important;
        font-size: 12px !important;
      }
      .aph-v2-actions-row .stButton button:hover {
        border-color: var(--aph-ink) !important;
      }
    </style>
    """,
    unsafe_allow_html=True,
)


# ─────────────────────────────────────────────────────────────────────────────
# Globalne wymuszenie ink color na całym tekście (faza 1 hot-fix)
# Stary CSS miał kolory dla dark mode (#f1f5f9, #cbd5e1, #94a3b8) które przebijały
# się mimo override .stApp. Tutaj mocniejszy global — z wyjątkami dla aph-v2-*
# elementów które muszą zostać mute/accent.
# ─────────────────────────────────────────────────────────────────────────────
st.markdown(
    """
    <style>
      /* Wszystkie native tekstowe elementy Streamlit → ink (czarny) */
      .stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp h5, .stApp h6,
      .stApp p, .stApp label, .stApp li, .stApp dt, .stApp dd,
      .stApp [data-testid="stMarkdownContainer"],
      .stApp [data-testid="stMarkdownContainer"] *,
      .stApp [data-testid="stText"],
      .stApp [data-testid="stCaptionContainer"],
      .stApp .stMarkdown *,
      .stApp .stCaption,
      .stApp [data-baseweb="select"] *,
      .stApp [data-baseweb="input"] *,
      .stApp [data-baseweb="textarea"] *,
      .stApp [data-testid="stSelectbox"] *,
      .stApp [data-testid="stTextInput"] *,
      .stApp [data-testid="stTextArea"] *,
      .stApp [data-testid="stRadio"] *,
      .stApp [data-testid="stCheckbox"] * {
        color: var(--aph-ink) !important;
      }

      /* Wyjątki — elementy które MUSZĄ zostać mute/dim/accent */
      .stApp .aph-v2-breadcrumb,
      .stApp .aph-v2-breadcrumb *:not(.crumb-active),
      .stApp .aph-v2-meta-label,
      .stApp .aph-v2-badge-code,
      .stApp .aph-v2-back,
      .stApp .aph-mono.dim,
      .stApp .pf-label,
      .stApp .tile-label,
      .stApp .stat-pill .lbl,
      .stApp .abest-date,
      .stApp .abest-metric-label,
      .stApp [data-testid="stMetricLabel"] {
        color: var(--aph-mute) !important;
      }

      /* Active badge: zielony (good); stale: amber; overdue: red */
      .stApp .aph-v2-badge-active:not(.stale):not(.overdue) {
        color: var(--aph-good) !important;
      }
      .stApp .aph-v2-badge-active.stale {
        color: oklch(0.55 0.12 80) !important;
      }
      .stApp .aph-v2-badge-active.overdue {
        color: var(--aph-bad) !important;
      }
      .stApp .abest-title {
        color: var(--aph-accent) !important;
      }

      /* Crumb active — czarny (nie mute) */
      .stApp .aph-v2-breadcrumb .crumb-active {
        color: var(--aph-ink) !important;
      }

      /* Delta colors w starych tiles */
      .stApp .delta-up { color: var(--aph-good) !important; }
      .stApp .delta-down { color: var(--aph-bad) !important; }
      .stApp .delta-neutral { color: var(--aph-mute) !important; }

      /* Nazwisko: reguła .aph-v2-name (0,1,0) przegrywała z regułą emotion
         Streamlita na h1 (0,1,1) i nazwisko wychodziło 44 px zamiast
         zadeklarowanych. Prefiks .stApp podbija specyficzność. */
      .stApp h1.aph-v2-name {
        font-size: 24px !important;
        line-height: 1.1 !important;
        margin: 0 !important;
      }

      /* Hero white text — avatar initials i status pill text MUSZĄ zostać jasne */
      .stApp .aph-v2-avatar-initials {
        color: var(--aph-bone) !important;
      }
      .stApp .aph-v2-coach-avatar {
        color: var(--aph-bone) !important;
      }
      /* Mini avatar na empty state cards (inicjały zawodnika) — białe na czarnym */
      .stApp .aph-v2-athlete-mini-avatar,
      .stApp .aph-v2-athlete-mini-avatar * {
        color: var(--aph-bone) !important;
      }
      /* Primary button text (czarny pill) — bone */
      .stApp .aph-v2-actions [data-testid="stHorizontalBlock"]
        > [data-testid="column"]:first-child .stButton button,
      .stApp .aph-v2-actions [data-testid="stHorizontalBlock"]
        > [data-testid="column"]:first-child .stButton button * {
        color: var(--aph-bone) !important;
      }
      /* Wszystkie primary buttons (solid ink pill) → bone text/label.
         Wyższa specyficzność + ostatni blok = bije globalny ink force powyżej. */
      .stApp .stButton button[kind="primary"],
      .stApp .stButton button[kind="primary"] *,
      .stApp .stButton button[kind="primary"] [data-testid="stMarkdownContainer"] p {
        color: var(--aph-bone) !important;
      }
      /* Logo button (target przez st-key — stabilny; marker :has() nie łapał
         przez wrapper stMarkdown w tej wersji Streamlita). A-mark + wordmark. */
      .stApp .st-key-btn_logo_home button {
        border: none !important;
        background: transparent !important;
        box-shadow: none !important;
        padding: 6px 8px !important;
        justify-content: flex-start !important;
        min-height: 44px !important;
        border-radius: 10px !important;
      }
      .stApp .st-key-btn_logo_home button:hover {
        background: var(--aph-tint) !important;
      }
      .stApp .st-key-btn_logo_home button p {
        display: inline-flex !important;
        align-items: center !important;
        gap: 12px !important;
        font-family: var(--aph-display) !important;
        font-size: 12.5px !important;
        font-weight: 800 !important;
        letter-spacing: 0.06em !important;   /* 0.10em ucinało "HUB" w kolumnie */
        text-transform: uppercase !important;
        color: var(--aph-ink) !important;
        margin: 0 !important;
        white-space: nowrap !important;
      }
      .stApp .st-key-btn_logo_home button p::before {
        content: "";
        display: inline-block;
        width: 36px; height: 36px;
        flex-shrink: 0;
        background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Crect width='100' height='100' rx='24' fill='%230F1722'/%3E%3Cpolygon points='50,12 86,90 71,90 50,44 29,90 14,90' fill='%23EEF3F8'/%3E%3Crect x='32' y='74' width='36' height='6' fill='%230F1722'/%3E%3Crect x='32' y='74' width='36' height='2.4' fill='%232F6BD8'/%3E%3C/svg%3E");
        background-size: contain;
        background-repeat: no-repeat;
      }

      /* Karta zawodnika klikalna w całości (tryb przeglądania): niewidzialny
         "open" button rozciągnięty na całą kartę. Marker .aph-card-open-mode
         jest tylko w trybie przeglądania → w trybie Manage brak overlaya,
         Edit/Delete klikalne normalnie. (st.container(border=True) renderuje się
         jako stVerticalBlock w tej wersji Streamlita.) */
      /* Przyciski Testy|Plany na kafelku — przygaszone, pełna widoczność
         na hover karty (etap 1 wg Filipa: wybór panelu per osoba). */
      [data-testid="stVerticalBlock"]:has(> [data-testid="stElementContainer"] .aph-v2-athlete-card-head)
        .stButton button {
        opacity: 0.35;
        transition: opacity .15s ease;
        padding: 6px 10px !important;
        min-height: 0 !important;
        font-size: 12.5px !important;
      }
      [data-testid="stVerticalBlock"]:has(> [data-testid="stElementContainer"] .aph-v2-athlete-card-head):hover
        .stButton button {
        opacity: 1;
      }
      [data-testid="stVerticalBlock"]:has(> [data-testid="stElementContainer"] .aph-card-open-mode) {
        position: relative;
        cursor: pointer;
      }
      /* Kontener "open" buttona = absolutny overlay na całą kartę */
      [data-testid="stVerticalBlock"]:has(> [data-testid="stElementContainer"] .aph-card-open-mode)
        > [data-testid="stElementContainer"]:has(.stButton) {
        position: absolute !important;
        inset: 0 !important;
        margin: 0 !important;
        padding: 0 !important;
        z-index: 4 !important;
      }
      /* Pośredni div .stButton + sam button wypełniają overlay */
      [data-testid="stVerticalBlock"]:has(> [data-testid="stElementContainer"] .aph-card-open-mode)
        > [data-testid="stElementContainer"]:has(.stButton) .stButton {
        height: 100% !important;
        width: 100% !important;
      }
      [data-testid="stVerticalBlock"]:has(> [data-testid="stElementContainer"] .aph-card-open-mode)
        .stButton button {
        width: 100% !important;
        height: 100% !important;
        min-height: 0 !important;
        opacity: 0 !important;
        padding: 0 !important;
        margin: 0 !important;
        border: none !important;
        background: transparent !important;
        box-shadow: none !important;
        cursor: pointer !important;
      }

      /* ── Session picker — panel (dni + wiersze skoków) ────────────────── */
      .aph-sp-day {
        display: flex; align-items: center; gap: 8px;
        padding: 8px 12px; border-radius: 8px;
        border-left: 3px solid transparent;
      }
      .aph-sp-day.sel {
        background: var(--aph-card);
        border-left: 3px solid var(--aph-accent);
        box-shadow: var(--aph-shadow);
      }
      .aph-sp-day-main { flex: 1; min-width: 0; }
      .aph-sp-day-date { font-family: var(--aph-display); font-size: 14px;
        color: var(--aph-ink); letter-spacing: -0.01em; }
      .aph-sp-day-sub { font-family: var(--aph-text); font-size: 12px;
        color: var(--aph-mute); margin-top: 1px; }

      /* Klikalne wiersze pickera: markdown + niewidzialny button-overlay */
      [data-testid="stVerticalBlock"]:has(> [data-testid="stElementContainer"] .aph-sp-rowmark) {
        position: relative;
      }
      [data-testid="stVerticalBlock"]:has(> [data-testid="stElementContainer"] .aph-sp-rowmark)
        > [data-testid="stElementContainer"]:has(.stButton) {
        position: absolute !important; inset: 0 !important;
        margin: 0 !important; padding: 0 !important; z-index: 4 !important;
      }
      [data-testid="stVerticalBlock"]:has(> [data-testid="stElementContainer"] .aph-sp-rowmark)
        > [data-testid="stElementContainer"]:has(.stButton) .stButton {
        height: 100% !important; width: 100% !important;
      }
      [data-testid="stVerticalBlock"]:has(> [data-testid="stElementContainer"] .aph-sp-rowmark)
        .stButton button {
        width: 100% !important; height: 100% !important; min-height: 0 !important;
        opacity: 0 !important; padding: 0 !important; margin: 0 !important;
        border: none !important; background: transparent !important;
        box-shadow: none !important; cursor: pointer !important;
      }
      /* Ciasne odstępy między wierszami w kolumnach pickera */
      [data-testid="stVerticalBlock"]:has(.aph-sp-rowmark) { gap: 4px !important; }

      /* Otwarty picker → popover: JEDNA reguła, niżej w pliku (blok
         "SESSION PICKER jako POPOVER", scope przez pill-marker). Wcześniej
         były DWIE konkurujące (:has(.aph-sp-head) 600px vs min-width:720px)
         — 720 wygrywało z max-width:88vw i popover wystawał poza viewport. */

      /* Back link "← Athletes" — ghost (bez ramki/tła), jak w mockupie */
      .stApp .st-key-btn_back_to_grid button {
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
        color: var(--aph-dim) !important;
        padding: 4px 2px !important;
        font-weight: 600 !important;
      }
      .stApp .st-key-btn_back_to_grid button:hover {
        color: var(--aph-ink) !important;
        background: transparent !important;
      }
    </style>
    """,
    unsafe_allow_html=True,
)


# ─────────────────────────────────────────────────────────────────────────────
# Faza 3: tabs (Overview / CMJ / HOP) — mono uppercase z czerwonym underline
# ─────────────────────────────────────────────────────────────────────────────
st.markdown(
    """
    <style>
      /* Tabs container — odstęp i border-bottom */
      .stTabs [data-baseweb="tab-list"] {
        gap: 2rem !important;
        border-bottom: 1px solid var(--aph-line) !important;
        padding: 0 4px;
        background: transparent !important;
      }
      /* Każdy tab button */
      .stTabs [data-baseweb="tab"] {
        background: transparent !important;
        border: none !important;
        border-radius: 0 !important;
        padding: 14px 4px 16px !important;
        color: var(--aph-dim) !important;
        font-family: var(--aph-display) !important;
        font-weight: 700 !important;
      }
      .stTabs [data-baseweb="tab"] p {
        font-family: var(--aph-text) !important;
        font-weight: 600 !important;
        font-size: 15px !important;
        letter-spacing: -0.01em !important;
        text-transform: none !important;
        margin: 0 !important;
      }
      .stTabs [aria-selected="true"] p {
        font-weight: 700 !important;
      }
      .stTabs [data-baseweb="tab"]:hover,
      .stTabs [data-baseweb="tab"]:hover p {
        color: var(--aph-ink) !important;
      }
      /* Aktywna tab */
      .stTabs [aria-selected="true"],
      .stTabs [aria-selected="true"] p {
        color: var(--aph-ink) !important;
      }
      /* Underline pod aktywną — niebieski accent 3px (Slate) */
      .stTabs [data-baseweb="tab-highlight"] {
        background: var(--aph-accent) !important;
        height: 3px !important;
        border-radius: 2px !important;
      }
      /* Border-bottom paskiem tab-list zostaje, highlight nad nim */
      .stTabs [data-baseweb="tab-border"] {
        background: transparent !important;
      }
    </style>
    """,
    unsafe_allow_html=True,
)


# ─────────────────────────────────────────────────────────────────────────────
# Faza 4: session pill (expander) + stats row + note pill
# ─────────────────────────────────────────────────────────────────────────────
st.markdown(
    """
    <style>
      /* ── Stats row → mockup-style: label MIXED CASE nad bigger Archivo Black value.
         Bez tła (transparent), gęsty layout z gap. */
      .stApp .stat-pills {
        display: flex !important;
        gap: 24px !important;
        background: transparent !important;
        padding: 4px 0 !important;
        border: none !important;
        margin: 0 0 10px !important;
        align-items: flex-start !important;
        flex-wrap: wrap !important;
        justify-content: flex-start !important;
      }
      .stApp .stat-pill {
        background: transparent !important;
        border: none !important;
        padding: 0 !important;
        flex-direction: column !important;
        align-items: flex-start !important;
        gap: 3px !important;
        line-height: 1 !important;
        min-width: 0 !important;
      }
      .stApp .stat-pill:hover {
        border: none !important;
      }
      .stApp .stat-pill .lbl {
        font-family: var(--aph-text) !important;
        font-size: 11px !important;
        font-weight: 500 !important;
        letter-spacing: 0 !important;
        color: var(--aph-mute) !important;
        text-transform: none !important;
        line-height: 1.2 !important;
      }
      .stApp .stat-pill .num {
        font-family: var(--aph-display) !important;
        font-size: 20px !important;
        font-weight: 700 !important;
        letter-spacing: -0.02em !important;
        color: var(--aph-ink) !important;
        line-height: 1 !important;
      }

      /* ── Session picker pill → mockup-style oval (mockup-aligned) ────── */
      /* Marker `.aph-v2-session-pill-marker` jest tuż przed expanderem session
         pickera. Cross-stElementContainer :has() jest niezawodne w nowszych
         wersjach Streamlit — używamy bardziej brute-force approach: każdy
         expander summary ma `width: fit-content` (dopasowuje się do treści,
         nie rozciąga na pełną szerokość). Session pill ma długi label
         "18 May 2026 · 7 jumps · 12:40" → ~360px. Performance/Strategy ma
         krótkie ("PERFORMANCE") → ~180px. Każdy auto-fit. */
      .stApp [data-testid="stExpander"] summary {
        width: fit-content !important;
        max-width: 100% !important;
      }
      /* Marker invisible */
      .aph-v2-session-pill-marker {
        display: none;
      }
      /* Pozostałe expander summary (Performance/Strategy/Asymmetry/Comparison
         Table) — full width, ale w stylu APH (białe BG, ink text) */
      .stApp [data-testid="stExpander"] summary {
        background: var(--aph-card) !important;
        border: 1px solid var(--aph-line) !important;
        border-radius: 12px !important;
        padding: 12px 16px !important;
      }
      .stApp [data-testid="stExpander"] summary p {
        font-family: var(--aph-text) !important;
        font-size: 14px !important;
        font-weight: 600 !important;
        letter-spacing: -0.005em !important;
        text-transform: none !important;
        color: var(--aph-ink) !important;
      }
      .stApp [data-testid="stExpander"] summary:hover {
        border-color: var(--aph-ink) !important;
        background: var(--aph-card) !important;
      }
      /* Expander content (selectboxes) */
      .stApp [data-testid="stExpander"] [data-testid="stExpanderDetails"] {
        background: var(--aph-card) !important;
        border: 1px solid var(--aph-line) !important;
        border-top: none !important;
        border-radius: 0 0 var(--aph-r-md) var(--aph-r-md) !important;
        padding: 14px 16px !important;
      }

      /* ── SESSION PICKER — kontrolowany popover (sp_wrap/sp_toggle/sp_panel).
         st.expander nie dawał się zamknąć programowo → po wyborze skoku panel
         wisiał nad kartami Key metrics ("rozjeżdżanie" — Filip). Teraz stan
         open/close w session_state; wybór skoku/Apply zamyka panel. */
      .stApp [class*="st-key-sp_wrap_"] {
        position: relative !important;
      }
      /* Toggle-pill — wygląd dawnego summary (karta + chevron w labelu) */
      .stApp [class*="st-key-sp_toggle_"] button {
        width: 100% !important;
        justify-content: flex-start !important;
        background: var(--aph-card) !important;
        border: 1px solid var(--aph-line) !important;
        border-radius: 12px !important;
        padding: 11px 14px !important;
        box-shadow: var(--aph-shadow) !important;
        font-family: var(--aph-text) !important;
        font-weight: 600 !important;
        font-size: 13.5px !important;
        color: var(--aph-ink) !important;
      }
      /* Taby-przyciski (własne, zamiast st.tabs) — ghost z podkreśleniem */
      .stApp [class*="st-key-tabbtn_"] button {
        background: transparent !important;
        border: none !important;
        box-shadow: inset 0 -3px 0 transparent !important;
        border-radius: 0 !important;
        padding: 10px 2px 12px !important;
        min-height: 0 !important;
        width: 100% !important;
        font-family: var(--aph-text) !important;
        font-size: 14px !important;
        font-weight: 600 !important;
        color: var(--aph-dim) !important;
        white-space: nowrap !important;
      }
      .stApp [class*="st-key-tabbtn_"] button:hover {
        color: var(--aph-ink) !important;
        background: transparent !important;
      }
      /* Tabbar: kontener key JEST vertical-blockiem — przestawiamy na RZĄD */
      .stApp .st-key-aph_tabbar {
        flex-direction: row !important;
        gap: 1.6rem !important;
        align-items: flex-end !important;
        border-bottom: 1px solid var(--aph-line);
        flex-wrap: nowrap !important;
        overflow-x: auto;
      }
      .stApp .st-key-aph_tabbar [data-testid="stElementContainer"] {
        width: auto !important;
      }
      .stApp [class*="st-key-tabbtn_"] button {
        width: auto !important;
      }
      /* Kafelki trybu Key metrics (Selected jump | Mean of top N) */
      .stApp [class*="st-key-km_tile_"] button {
        width: 100% !important;
        background: var(--aph-card) !important;
        border: 1px solid var(--aph-line) !important;
        border-radius: 10px !important;
        padding: 8px 10px !important;
        box-shadow: none !important;
        font-family: var(--aph-text) !important;
        font-size: 12px !important;
        font-weight: 600 !important;
        color: var(--aph-mute) !important;
        min-height: 0 !important;
        white-space: nowrap !important;
      }
      .stApp [class*="st-key-km_tile_"] button:hover {
        border-color: var(--aph-accent) !important;
        color: var(--aph-ink) !important;
        background: var(--aph-card) !important;
      }
      /* Wiersze skoków/triali — natywne przyciski, lewe wyrównanie, mono */
      .stApp [class*="st-key-sp_jump_"] button,
      .stApp [class*="st-key-sp_trial_"] button {
        width: 100% !important;
        justify-content: flex-start !important;
        background: var(--aph-card) !important;
        border: 1px solid var(--aph-line) !important;
        border-radius: 10px !important;
        padding: 9px 12px !important;
        box-shadow: none !important;
        font-family: var(--aph-mono) !important;
        font-size: 12.5px !important;
        color: var(--aph-ink) !important;
        min-height: 0 !important;
      }
      .stApp [class*="st-key-sp_jump_"] button:hover,
      .stApp [class*="st-key-sp_trial_"] button:hover {
        border-color: var(--aph-accent) !important;
        background: var(--aph-card) !important;
      }
      /* Best skoku dnia — po prawej w wierszu dnia */
      .aph-sp-day-best {
        font-family: var(--aph-mono);
        font-size: 13px;
        font-weight: 700;
        color: var(--aph-ink);
        white-space: nowrap;
        margin-left: auto;
        padding-left: 10px;
      }
      .aph-sp-day-best .u {
        font-size: 10px;
        font-weight: 400;
        color: var(--aph-mute);
      }
      .stApp [class*="st-key-sp_toggle_"] button:hover {
        border-color: var(--aph-line-h) !important;
        background: var(--aph-card) !important;
      }
      /* Single metric explorer jako karta — kontrolki + wykres w jednej ramie */
      .stApp [class*="st-key-explorer_"] {
        background: var(--aph-card) !important;
        border: 1px solid var(--aph-line) !important;
        border-radius: 14px !important;
        box-shadow: var(--aph-shadow) !important;
        padding: 14px 16px 6px !important;
        margin-top: 6px;
      }
      /* Panel pickera = karta FULL-WIDTH w flow (push-down) — spycha treść
         w dół zamiast ją zakrywać (Filip: overlay "najeżdżał" na karty). */
      .stApp [class*="st-key-sp_panelslot_"]:has(.aph-sp-day) {
        background: var(--aph-card) !important;
        border: 1px solid var(--aph-line) !important;
        border-radius: 14px !important;
        box-shadow: var(--aph-shadow) !important;
        padding: 14px 16px !important;
        margin: 8px 0 14px !important;
      }

      /* ── "Test session" label nad session pill (mockup style) ────────── */
      .aph-v2-session-label {
        font-family: var(--aph-text);
        font-size: 13px;
        color: var(--aph-mute);
        font-weight: 500;
        margin: 0 0 6px;
        letter-spacing: 0;
      }

      /* ── Note pill (z _render_test_day_notes) ────────────────────────── */
      /* Wrapper diva który ma "📝 Notatka:" / "Brak notatki" */
      .stApp [data-testid="stHorizontalBlock"]:has(button[aria-label*="Notatka"]) {
        margin: 0 0 14px !important;
      }
    </style>
    """,
    unsafe_allow_html=True,
)


# ─────────────────────────────────────────────────────────────────────────────
# Faza 5: KPI cards (Key Metrics section)
# ─────────────────────────────────────────────────────────────────────────────
st.markdown(
    """
    <style>
      /* Section heading "Key metrics" — large Archivo Black mixed case + subtitle caption */
      .aph-v2-kpi-section-head {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        margin: 18px 0 14px;
        flex-wrap: wrap;
        gap: 12px;
      }
      .aph-v2-kpi-section-title {
        font-family: var(--aph-display);
        font-size: 30px;
        letter-spacing: -0.025em;
        line-height: 1;
        color: var(--aph-ink);
      }
      .aph-v2-kpi-section-caption {
        font-family: var(--aph-text);
        font-size: 13px;
        color: var(--aph-mute);
        font-weight: 500;
      }

      /* KPI card — wspólne. Stała wysokość żeby wszystkie kafle w wierszu
         były równe (Streamlit columns nie wyrównuje automatycznie). */
      .aph-v2-kpi-card {
        background: var(--aph-card);
        border: 1px solid var(--aph-line);
        border-radius: var(--aph-r-card);
        padding: 12px 14px;
        display: flex;
        flex-direction: column;
        gap: 6px;
        position: relative;
        overflow: hidden;
        /* 200→132 px: przy sześciu kafelkach w rzędzie to była ściana
           pustego miejsca między wartością a stopką (Filip 2026-09-04) */
        min-height: 132px;
        height: 100%;
        box-sizing: border-box;
        box-shadow: 0 1px 2px rgba(14,14,16,0.03),
                    0 6px 16px -10px rgba(14,14,16,0.08);
        transition: box-shadow .18s ease, border-color .18s ease,
                    transform .18s ease;
      }
      .aph-v2-kpi-card:hover {
        box-shadow: 0 2px 4px rgba(14,14,16,0.04),
                    0 14px 28px -12px rgba(14,14,16,0.16);
        border-color: rgba(14,14,16,0.16);
        transform: translateY(-2px);
      }
      /* Każda kolumna w wierszu KPI ma stretch — żeby karty wewnątrz wyrównały
         się wysokością do najwyższej */
      .stApp [data-testid="stHorizontalBlock"]:has(.aph-v2-kpi-card)
        [data-testid="column"] {
        display: flex !important;
        flex-direction: column !important;
      }
      .stApp [data-testid="stHorizontalBlock"]:has(.aph-v2-kpi-card)
        [data-testid="column"] > div {
        flex: 1 !important;
        display: flex !important;
      }
      .stApp [data-testid="stHorizontalBlock"]:has(.aph-v2-kpi-card)
        [data-testid="column"] > div > div {
        flex: 1 !important;
        width: 100%;
      }
      /* Primary KPI card (Jump Height): solid czarne tło + cream text,
         większa wartość, sparkline w cream. Mockup-style. */
      /* Primary card — JASNE tło jak reszta kafelków (Filip: czarny tekst na
         czarnym tle był nieczytelny). Wyróżnienie przez mocniejszą ramkę (ink)
         + większy value + cień, nie przez ciemne tło. */
      /* Primary KPI card — BIAŁA jak pozostałe (Filip: czarne tło nieczytelne).
         Wyróżnienie tylko nieco większą wartością, nie ciemnym tłem. */
      .aph-v2-kpi-card.primary {
        background: var(--aph-card) !important;
        border: 1px solid var(--aph-line) !important;
        box-shadow: var(--aph-shadow) !important;
      }
      .aph-v2-kpi-card.primary .aph-v2-kpi-label {
        color: var(--aph-dim) !important;
      }
      .aph-v2-kpi-card.primary .aph-v2-kpi-value {
        color: var(--aph-ink) !important;
      }
      .aph-v2-kpi-card.primary .aph-v2-kpi-unit {
        color: var(--aph-mute) !important;
      }
      .aph-v2-kpi-card.primary .aph-v2-kpi-footer {
        border-top: 1px solid var(--aph-line) !important;
      }
      .aph-v2-kpi-card.primary .aph-v2-kpi-vs-label {
        color: var(--aph-mute) !important;
      }

      /* Header row — rezerwuje 2 linie wysokości żeby kafelki były równe
         niezależnie od długości label'a. Bez tego "Ecc. Peak Velocity"
         wraps i robi kafelek wyższym od reszty. */
      .aph-v2-kpi-header {
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
        min-height: 2.6em;
      }
      .aph-v2-kpi-label {
        font-family: var(--aph-text);
        font-size: 12px;
        line-height: 1.25;
        color: var(--aph-dim);
        letter-spacing: 0;
        text-transform: none;
        font-weight: 600;
        white-space: normal;
        overflow-wrap: anywhere;
      }
      .aph-v2-kpi-card .aph-v2-kpi-label {
        color: var(--aph-dim);
      }
      /* Niebieska kropka akcentu przed każdą etykietą KPI (Slate) */
      .aph-v2-kpi-label::before {
        content: "";
        display: inline-block;
        width: 6px;
        height: 6px;
        border-radius: 50%;
        background: var(--aph-accent);
        margin-right: 7px;
        vertical-align: middle;
        position: relative;
        top: -1px;
      }
      .aph-v2-kpi-index {
        font-family: var(--aph-mono);
        font-size: 10px;
        color: var(--aph-mute);
        letter-spacing: 0.1em;
      }
      .aph-v2-kpi-primary-badge {
        font-family: var(--aph-mono);
        font-size: 9px;
        letter-spacing: 0.22em;
        text-transform: uppercase;
        padding: 3px 7px;
        border-radius: 4px;
        color: var(--aph-accent);
        background: color-mix(in oklab, var(--aph-accent) 22%, transparent);
        font-weight: 600;
      }

      /* Value row */
      .aph-v2-kpi-value-row {
        display: flex;
        align-items: baseline;
        gap: 6px;
        flex-wrap: nowrap;
        min-width: 0;
      }
      .aph-v2-kpi-value {
        font-family: var(--aph-display);
        font-size: 32px;
        letter-spacing: -0.03em;
        line-height: 1;
        color: var(--aph-ink);
        min-width: 0;
        white-space: nowrap;
        overflow: visible;
      }
      .aph-v2-kpi-card.primary .aph-v2-kpi-value {
        font-size: 38px;
      }
      .aph-v2-kpi-unit {
        font-family: var(--aph-mono);
        font-size: 13px;
        color: var(--aph-mute);
        letter-spacing: 0;
        flex-shrink: 0;
        white-space: nowrap;
        padding-right: 4px;
      }

      /* Sparkline container */
      .aph-v2-kpi-spark {
        margin: 2px 0 4px;
      }

      /* Sparkline hover tooltip — natychmiastowy (CSS hover), bez 700ms delay
         native browser tooltip. Każdy <g.aph-spark-hover-group> ma 4 elementy:
         hot-zone (transparent r=10), highlight kropka, value text, date text. */
      .aph-spark-hover-group .aph-spark-hot {
        cursor: crosshair;
      }
      .aph-spark-hover-group .aph-spark-hl,
      .aph-spark-hover-group .aph-spark-val,
      .aph-spark-hover-group .aph-spark-date {
        pointer-events: none;
        transition: opacity 80ms ease-out;
      }
      .aph-spark-hover-group:hover .aph-spark-hl {
        opacity: 1 !important;
      }
      .aph-spark-hover-group:hover .aph-spark-val {
        opacity: 1 !important;
      }
      .aph-spark-hover-group:hover .aph-spark-date {
        opacity: 0.7 !important;
      }
      .aph-spark-val {
        font-family: var(--aph-mono);
        font-size: 11px;
        font-weight: 600;
        fill: var(--aph-ink);
        paint-order: stroke;
        stroke: var(--aph-card);
        stroke-width: 3px;
        stroke-linejoin: round;
      }
      .aph-spark-date {
        font-family: var(--aph-mono);
        font-size: 8px;
        letter-spacing: 0.1em;
        fill: var(--aph-mute);
        paint-order: stroke;
        stroke: var(--aph-card);
        stroke-width: 2px;
        stroke-linejoin: round;
      }

      /* Footer row */
      .aph-v2-kpi-footer {
        display: flex;
        justify-content: space-between;
        align-items: center;
        border-top: 1px solid var(--aph-line-2);
        padding-top: 10px;
        margin-top: auto;
        gap: 8px;
      }
      .aph-v2-kpi-pb {
        font-family: var(--aph-mono);
        font-size: 10px;
        color: var(--aph-mute);
        letter-spacing: 0.06em;
        white-space: nowrap;
      }
      .aph-v2-kpi-vs-label {
        font-family: var(--aph-text);
        font-size: 11px;
        color: var(--aph-mute);
        font-weight: 500;
        margin-left: auto;
      }

      /* Delta pill */
      .aph-v2-delta-pill {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        font-family: var(--aph-mono);
        font-size: 11px;
        font-weight: 600;
        padding: 3px 8px;
        border-radius: var(--aph-r-pill);
        letter-spacing: 0.04em;
      }
      .aph-v2-delta-pill.up {
        color: var(--aph-good);
        background: color-mix(in oklab, var(--aph-good) 14%, transparent);
        border: 1px solid color-mix(in oklab, var(--aph-good) 30%, transparent);
      }
      .aph-v2-delta-pill.down {
        color: var(--aph-bad);
        background: color-mix(in oklab, var(--aph-bad) 14%, transparent);
        border: 1px solid color-mix(in oklab, var(--aph-bad) 30%, transparent);
      }
      .aph-v2-delta-pill.neutral {
        color: var(--aph-mute);
        background: transparent;
        border: 1px solid var(--aph-line);
      }
      /* More metrics heading nad expanders */
      .aph-v2-more-metrics-head {
        font-family: var(--aph-display);
        font-size: 18px;
        letter-spacing: -0.01em;
        text-transform: uppercase;
        color: var(--aph-ink);
        margin: 18px 0 10px;
      }
      .aph-v2-more-metrics-sub {
        font-family: var(--aph-mono);
        font-size: 11px;
        letter-spacing: 0.14em;
        color: var(--aph-mute);
        margin-left: 6px;
        text-transform: uppercase;
      }

      /* Overview chart header (nad timeline plotly) */
      .aph-v2-overview-head {
        display: flex;
        justify-content: space-between;
        align-items: baseline;
        gap: 12px;
        margin: 14px 0 8px;
        flex-wrap: wrap;
      }
      .aph-v2-overview-title {
        font-family: var(--aph-display);
        font-size: 16px;
        letter-spacing: -0.01em;
        text-transform: uppercase;
        color: var(--aph-ink);
      }
      .aph-v2-overview-subtitle {
        font-family: var(--aph-mono);
        font-size: 11px;
        letter-spacing: 0.14em;
        color: var(--aph-mute);
        margin-left: 6px;
        text-transform: uppercase;
      }
      .aph-v2-overview-actions {
        display: inline-flex;
        gap: 8px;
      }
      .aph-v2-pill-ghost {
        display: inline-flex;
        align-items: center;
        gap: 5px;
        padding: 6px 12px;
        background: var(--aph-card);
        border: 1px solid var(--aph-line);
        border-radius: var(--aph-r-pill);
        font-family: var(--aph-text);
        font-size: 12px;
        font-weight: 600;
        color: var(--aph-ink);
        cursor: default;
      }
      .aph-v2-pill-ghost:hover {
        border-color: var(--aph-ink);
      }

      /* Primary card delta pills — karta jest ciemna (navy), więc neutral pill
         w odcieniach bone żeby był czytelny. up/down (green/red) czytelne na navy. */
      .aph-v2-kpi-card.primary .aph-v2-delta-pill.neutral {
        color: var(--aph-mute);
        border-color: var(--aph-line);
      }

      /* Top bar search — selectbox stylized as oval pill search (mockup).
         Wide enough żeby cała placeholder się mieścił i nie był ucinany. */
      .stApp [data-baseweb="select"]:has(input[aria-label="Search"]),
      .stApp [data-baseweb="select"]:has(input[aria-label="Search"]) > div {
        min-height: 48px !important;
      }
      .stApp [data-baseweb="select"]:has(input[aria-label="Search"]) > div {
        background: var(--aph-card) !important;
        border-radius: 999px !important;
        border: 1px solid var(--aph-line) !important;
        padding: 6px 22px !important;
      }
      .stApp [data-baseweb="select"]:has(input[aria-label="Search"]) [data-baseweb="tag"],
      .stApp [data-baseweb="select"]:has(input[aria-label="Search"]) [data-baseweb="select"] > div > div {
        white-space: nowrap !important;
        overflow: visible !important;
        text-overflow: clip !important;
      }
      /* Fallback selector dla starszych Streamlit wersji */
      .stApp .stSelectbox [data-baseweb="select"] > div {
        min-height: 44px !important;
      }
      /* Coach profile pill (top right) */
      .aph-v2-coach-pill {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        padding: 4px 14px 4px 4px;
        background: var(--aph-card);
        border: 1px solid var(--aph-line);
        border-radius: 999px;
        font-family: var(--aph-text);
        font-size: 13px;
        font-weight: 600;
        color: var(--aph-ink);
        cursor: pointer;
      }
      .aph-v2-coach-avatar {
        width: 32px;
        height: 32px;
        border-radius: 50%;
        background: var(--aph-accent);
        color: var(--aph-bone);
        display: grid;
        place-items: center;
        font-family: var(--aph-display);
        font-size: 11px;
        flex-shrink: 0;
      }
      .stApp .aph-v2-coach-avatar,
      .stApp .aph-v2-coach-avatar * {
        color: var(--aph-bone) !important;
      }
      .aph-v2-coach-name {
        white-space: nowrap;
      }
      .aph-v2-coach-chevron {
        color: var(--aph-mute);
        font-size: 10px;
        margin-left: 2px;
      }
      /* Refresh icon button mały (40x40) — top bar */
      .stApp .stColumn:has(button[aria-label*="Refresh"]) .stButton button,
      .stApp button[data-testid="baseButton-secondary"][aria-label*="Refresh"] {
        padding: 8px !important;
        min-height: 40px !important;
        border-radius: 12px !important;
      }

      /* Last API sync card — mały kafelek obok przycisku refresh */
      .aph-v2-sync-card {
        background: var(--aph-card);
        border: 1px solid var(--aph-line);
        border-radius: var(--aph-r-md);
        padding: 10px 14px;
        display: flex;
        flex-direction: column;
        gap: 3px;
        min-width: 0;
      }
      .aph-v2-sync-card.empty {
        opacity: 0.7;
      }
      .aph-v2-sync-label {
        font-family: var(--aph-mono);
        font-size: 9px;
        letter-spacing: 0.22em;
        text-transform: uppercase;
        color: var(--aph-mute);
        line-height: 1;
      }
      .aph-v2-sync-stamp {
        font-family: var(--aph-mono);
        font-size: 12px;
        font-weight: 600;
        color: var(--aph-ink);
        letter-spacing: 0.06em;
        line-height: 1.2;
      }
      .aph-v2-sync-rel {
        font-family: var(--aph-text);
        font-size: 11px;
        color: var(--aph-dim);
        font-weight: 500;
        line-height: 1;
      }

      /* Phase summary cards (Eccentric / Concentric / Landing) — APH v2 */
      .aph-v2-phase-card {
        background: var(--aph-card);
        border: 1px solid var(--aph-line);
        border-radius: var(--aph-r-card);
        padding: 16px 18px;
        display: flex;
        flex-direction: column;
        gap: 12px;
        box-shadow: 0 1px 0 rgba(14, 14, 16, 0.02),
                    0 6px 18px -10px rgba(14, 14, 16, 0.10);
      }
      .aph-v2-phase-header {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        gap: 10px;
      }
      .aph-v2-phase-name {
        font-family: var(--aph-display);
        font-size: 18px;
        letter-spacing: -0.015em;
        color: var(--aph-ink);
      }
      .aph-v2-phase-total {
        font-family: var(--aph-mono);
        font-size: 10px;
        letter-spacing: 0.18em;
        text-transform: uppercase;
        color: var(--aph-mute);
      }
      .aph-v2-phase-chips {
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
      }
      .aph-v2-phase-chip {
        font-family: var(--aph-mono);
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 0.04em;
        padding: 4px 10px;
        border-radius: var(--aph-r-pill);
        line-height: 1.2;
        text-transform: lowercase;
      }
      .aph-v2-phase-chip.green {
        background: color-mix(in oklab, var(--aph-good) 18%, transparent);
        color: oklch(0.40 0.16 152);
        border: 1px solid color-mix(in oklab, var(--aph-good) 38%, transparent);
      }
      .aph-v2-phase-chip.amber {
        background: color-mix(in oklab, oklch(0.78 0.16 80) 18%, transparent);
        color: oklch(0.45 0.14 75);
        border: 1px solid color-mix(in oklab, oklch(0.78 0.16 80) 38%, transparent);
      }
      .aph-v2-phase-chip.red {
        background: color-mix(in oklab, var(--aph-bad) 14%, transparent);
        color: oklch(0.48 0.18 28);
        border: 1px solid color-mix(in oklab, var(--aph-bad) 34%, transparent);
      }
      .aph-v2-phase-chip.muted {
        background: transparent;
        color: var(--aph-mute);
        border: 1px solid var(--aph-line);
      }
      /* Override fazy 1 global ink color — phase chips zachowują kolor wg statusu */
      .stApp .aph-v2-phase-chip.green { color: oklch(0.40 0.16 152) !important; }
      .stApp .aph-v2-phase-chip.amber { color: oklch(0.45 0.14 75) !important; }
      .stApp .aph-v2-phase-chip.red { color: oklch(0.48 0.18 28) !important; }
      .stApp .aph-v2-phase-chip.muted { color: var(--aph-mute) !important; }

      /* Cienka linia separator — jak border-bottom tabs (1px line var, nie
         pełna szerokość okna). Używany w empty state pod top bar. */
      .aph-v2-thin-divider {
        border: none !important;
        border-top: 1px solid var(--aph-line) !important;
        margin: 14px 0 18px 0 !important;
        padding: 0 !important;
        background: none !important;
        height: 0 !important;
      }
      /* Default Streamlit HR + wszystkie inne hr — zerujemy "rounded" look */
      .stApp hr {
        border: none !important;
        border-top: 1px solid var(--aph-line) !important;
        background: none !important;
        height: 0 !important;
        margin: 14px 0 !important;
      }
      /* Add athlete button right-aligned (bez pustych column spacers) */
      .aph-v2-add-athlete-row {
        display: flex;
        justify-content: flex-end;
        margin: 6px 0 8px;
      }
      .aph-v2-add-athlete-row + div .stButton button,
      .aph-v2-add-athlete-row ~ div .stButton button[key="empty_add_athlete"] {
        max-width: 220px;
      }
      /* Top bar divider — taka sama cienka kreska jak pod tabs (CMJ/HOP),
         między top bar (logo + search + coach) a hero/content. */
      .aph-v2-topbar-divider {
        border: none !important;
        border-top: 1px solid var(--aph-line) !important;
        margin: 10px 0 12px 0 !important;
        padding: 0 !important;
        background: none !important;
        height: 0 !important;
      }
      /* Logo bar margin-bottom redukcja — divider daje wystarczający separator */
      .aph-logo-bar {
        margin-bottom: 0 !important;
      }

      /* Logo button — wygląda jak logo, klikalny → reset do home.
         Marker `.aph-logo-btn-marker` (invisible div) jest TUŻ przed buttonem
         logo. Scope CSS przez :has() na rodzeństwo aby nie psuć innych buttonów. */
      .aph-logo-btn-marker { display: none; }
      [data-testid="stElementContainer"]:has(> .aph-logo-btn-marker)
        + [data-testid="stElementContainer"] [data-testid="stButton"] button {
        border: none !important;
        background: transparent !important;
        padding: 8px 12px !important;
        text-align: left !important;
        justify-content: flex-start !important;
        font-family: var(--aph-display) !important;
        font-size: 17px !important;
        font-weight: 800 !important;
        letter-spacing: -0.02em !important;
        color: var(--aph-ink) !important;
        border-radius: 10px !important;
        box-shadow: none !important;
        white-space: nowrap !important;
        min-height: 40px !important;
        height: auto !important;
        line-height: 1.1 !important;
      }
      [data-testid="stElementContainer"]:has(> .aph-logo-btn-marker)
        + [data-testid="stElementContainer"] [data-testid="stButton"] button:hover {
        background: rgba(14, 14, 16, 0.05) !important;
        color: var(--aph-ink) !important;
      }
      [data-testid="stElementContainer"]:has(> .aph-logo-btn-marker)
        + [data-testid="stElementContainer"] [data-testid="stButton"] button p {
        font-family: var(--aph-display) !important;
        font-size: 17px !important;
        font-weight: 800 !important;
        color: var(--aph-ink) !important;
        margin: 0 !important;
      }

      /* ── Roster title bar (Athletes + count + subtitle) ─────────────── */
      .aph-roster-title {
        font-family: var(--aph-display);
        font-size: 30px;
        color: var(--aph-ink);
        letter-spacing: -0.02em;
        line-height: 1;
      }
      .aph-roster-count {
        font-family: var(--aph-mono);
        font-size: 15px;
        color: var(--aph-mute);
        margin-left: 8px;
      }
      .aph-roster-sub {
        font-family: var(--aph-text);
        font-size: 13px;
        color: var(--aph-dim);
        margin-top: 4px;
      }

      /* Kafelki zawodników w jednym rzędzie mają mieć równą wysokość —
         bez tego karta bez sportu jest o 28 px niższa i rząd się rozjeżdża
         (Filip 2026-09-03). Streamlit opakowuje kartę w kilka divów, więc
         flex musi przejść przez cały łańcuch, inaczej height:100% nie ma
         się do czego odnieść. Przyciski dosunięte do dołu karty. */
      [data-testid="stHorizontalBlock"]:has(.aph-v2-athlete-card-head)
        > [data-testid="stColumn"],
      [data-testid="stHorizontalBlock"]:has(.aph-v2-athlete-card-head)
        > [data-testid="stColumn"] > div,
      [data-testid="stHorizontalBlock"]:has(.aph-v2-athlete-card-head)
        [data-testid="stVerticalBlockBorderWrapper"],
      [data-testid="stHorizontalBlock"]:has(.aph-v2-athlete-card-head)
        [data-testid="stVerticalBlockBorderWrapper"] > div {
        display: flex !important;
        flex-direction: column !important;
      }
      [data-testid="stHorizontalBlock"]:has(.aph-v2-athlete-card-head)
        > [data-testid="stColumn"] > div,
      [data-testid="stHorizontalBlock"]:has(.aph-v2-athlete-card-head)
        [data-testid="stVerticalBlockBorderWrapper"],
      [data-testid="stHorizontalBlock"]:has(.aph-v2-athlete-card-head)
        [data-testid="stVerticalBlockBorderWrapper"] > div,
      [data-testid="stHorizontalBlock"]:has(.aph-v2-athlete-card-head)
        [data-testid="stLayoutWrapper"]:has(.aph-v2-athlete-card-head),
      [data-testid="stHorizontalBlock"]:has(.aph-v2-athlete-card-head)
        [data-testid="stVerticalBlock"]:has(.aph-v2-athlete-card-head) {
        flex: 1 1 auto !important;
      }
      [data-testid="stVerticalBlock"]:has(> [data-testid="stElementContainer"] .aph-v2-athlete-card-head)
        > [data-testid="stElementContainer"]:has(.stButton),
      [data-testid="stVerticalBlock"]:has(> [data-testid="stElementContainer"] .aph-v2-athlete-card-head)
        > [data-testid="stHorizontalBlock"] {
        margin-top: auto !important;
      }

      /* Edit / Delete w trybie Manage — drobne akcje porządkowe, nie mają
         ważyć tyle co „Testy" (Filip 2026-09-03) */
      .stApp [class*="st-key-edit_"] button,
      .stApp [class*="st-key-del_"] button,
      .stApp [class*="st-key-del_yes_"] button {
        min-height: 28px !important;
        height: 28px !important;
        padding: 0 10px !important;
        font-size: 11.5px !important;
        font-weight: 600 !important;
        border-radius: 8px !important;
      }

      /* ── Empty state — karty atletów w stylu APH v2 ─────────────────── */
      .aph-v2-athlete-card-head {
        display: flex;
        align-items: center;
        gap: 14px;
        margin-bottom: 8px;
      }
      .aph-v2-athlete-chevron {
        margin-left: auto;
        color: var(--aph-mute);
        font-size: 22px;
        line-height: 1;
      }
      .aph-v2-athlete-mini-avatar {
        width: 52px;
        height: 52px;
        border-radius: 12px;
        background: var(--aph-ink);
        color: var(--aph-bone);
        display: grid;
        place-items: center;
        font-family: var(--aph-display);
        font-size: 18px;
        letter-spacing: -0.02em;
        flex-shrink: 0;
        box-shadow: 0 0 0 3px color-mix(in oklab, var(--aph-accent) 22%, transparent);
      }
      .aph-v2-athlete-name {
        font-family: var(--aph-display);
        font-size: 17px;
        color: var(--aph-ink);
        letter-spacing: -0.02em;
        line-height: 1.1;
        min-width: 0;
        white-space: pre-line;
      }
      .aph-v2-athlete-meta {
        display: flex;
        flex-direction: column;
        gap: 1px;
        margin-bottom: 8px;
      }
      .aph-v2-athlete-meta .aph-v2-meta-label {
        font-family: var(--aph-mono);
        font-size: 9px;
        letter-spacing: 0.22em;
        text-transform: uppercase;
        color: var(--aph-mute);
      }
      .aph-v2-athlete-meta .aph-v2-meta-value {
        font-family: var(--aph-text);
        font-weight: 600;
        font-size: 13px;
        color: var(--aph-ink);
      }
      .aph-v2-athlete-sport {
        display: flex;
        align-items: center;
        gap: 7px;
        font-family: var(--aph-text);
        font-size: 13px;
        color: var(--aph-dim);
        margin-bottom: 8px;
      }
      .aph-v2-sport-dot {
        width: 7px;
        height: 7px;
        border-radius: 50%;
        background: var(--aph-accent);
        flex-shrink: 0;
      }
      .aph-v2-athlete-tests {
        display: inline-flex;
        align-items: baseline;
        gap: 6px;
        padding: 6px 12px;
        background: color-mix(in oklab, var(--aph-ink) 6%, transparent);
        border: 1px solid var(--aph-line);
        border-radius: var(--aph-r-pill);
        margin-bottom: 12px;
      }
      .aph-v2-athlete-tests .num {
        font-family: var(--aph-display);
        font-size: 14px;
        color: var(--aph-ink);
        letter-spacing: -0.02em;
      }
      .aph-v2-athlete-tests .lbl {
        font-family: var(--aph-mono);
        font-size: 9px;
        color: var(--aph-mute);
        letter-spacing: 0.22em;
        text-transform: uppercase;
      }
      .aph-v2-athlete-tag.pending {
        display: inline-block;
        font-family: var(--aph-mono);
        font-size: 10px;
        letter-spacing: 0.18em;
        text-transform: uppercase;
        padding: 4px 10px;
        border-radius: 4px;
        color: oklch(0.55 0.14 70);
        background: color-mix(in oklab, oklch(0.78 0.16 70) 14%, transparent);
        border: 1px solid color-mix(in oklab, oklch(0.78 0.16 70) 28%, transparent);
        margin-bottom: 12px;
      }
      /* ── Faza 8: kompleksowy audit — wszystkie baseweb popovery,
         dialogi, dropdowns, tooltipy, alerty na light theme APH ───────── */

      /* Selectbox dropdown / autocomplete menu (BaseWeb popover) — POPOVER JEST
         RENDEROWANY W PORTALU (body root), więc selector BEZ .stApp prefix!
         Plus mocny override na wszystkich descendants. */
      body [data-baseweb="popover"],
      body [data-baseweb="popover"] *,
      body [data-baseweb="menu"],
      body [data-baseweb="menu"] *,
      body [data-baseweb="list"],
      body [data-baseweb="list"] * {
        color: #0E0E10 !important;
      }
      body [data-baseweb="popover"],
      body [data-baseweb="popover"] [role="listbox"],
      body [data-baseweb="popover"] > div,
      body [data-baseweb="popover"] > div > div,
      body [data-baseweb="menu"],
      body [data-baseweb="list"] {
        background: #FFFFFF !important;
        border: 1px solid rgba(14, 14, 16, 0.08) !important;
        border-radius: 12px !important;
        box-shadow: 0 12px 32px -16px rgba(14, 14, 16, 0.28) !important;
      }
      /* Dropdown popover ma prawo rozrosnąć się horyzontalnie żeby zmieścić
         pełne opcje. Na każdym poziomie kontenera popovera force min-width:
         max-content. Bez :has() — działa we wszystkich przypadkach. */
      body [data-baseweb="popover"],
      body [data-baseweb="popover"] > div,
      body [data-baseweb="popover"] > div > div,
      body [data-baseweb="popover"] [role="listbox"],
      body [data-baseweb="popover"] [role="listbox"] > ul,
      body [data-baseweb="menu"],
      body [data-baseweb="menu"] > ul {
        min-width: max-content !important;
        max-width: min(560px, 92vw) !important;
      }
      body [data-baseweb="popover"] [role="option"],
      body [data-baseweb="menu"] [role="option"],
      body [data-baseweb="menu"] li,
      body [data-baseweb="list"] li {
        background: #FFFFFF !important;
        background-color: #FFFFFF !important;
        color: #0E0E10 !important;
        font-family: "Archivo", sans-serif !important;
        /* Cały tekst widoczny — bez ellipsis '...' */
        white-space: nowrap !important;
        overflow: visible !important;
        text-overflow: clip !important;
        width: auto !important;
      }
      body [data-baseweb="popover"] [role="option"] *,
      body [data-baseweb="menu"] [role="option"] *,
      body [data-baseweb="menu"] li *,
      body [data-baseweb="list"] li * {
        white-space: nowrap !important;
        overflow: visible !important;
        text-overflow: clip !important;
        color: #0E0E10 !important;
        background: transparent !important;
        background-color: transparent !important;
      }
      /* Hover state — light grey tinted, NIE czarny (default BaseWeb dark theme) */
      body [data-baseweb="popover"] [role="option"]:hover,
      body [data-baseweb="popover"] [role="option"][aria-selected="true"],
      body [data-baseweb="popover"] [role="option"]:focus,
      body [data-baseweb="popover"] [role="option"][data-focusvisible="true"],
      body [data-baseweb="menu"] [role="option"]:hover,
      body [data-baseweb="menu"] [role="option"][aria-selected="true"],
      body [data-baseweb="menu"] [role="option"]:focus,
      body [data-baseweb="menu"] li:hover {
        background: rgba(14, 14, 16, 0.08) !important;
        background-color: rgba(14, 14, 16, 0.08) !important;
        color: #0E0E10 !important;
      }
      /* Hover children — żeby nie nadpisali parenta */
      body [data-baseweb="popover"] [role="option"]:hover *,
      body [data-baseweb="popover"] [role="option"][aria-selected="true"] *,
      body [data-baseweb="menu"] [role="option"]:hover *,
      body [data-baseweb="menu"] [role="option"][aria-selected="true"] * {
        background: transparent !important;
        background-color: transparent !important;
        color: #0E0E10 !important;
      }
      /* Fallback: any role=listbox renderowany w body root */
      body div[role="listbox"],
      body ul[role="listbox"],
      body div[role="listbox"] *,
      body ul[role="listbox"] * {
        background: #FFFFFF !important;
        color: #0E0E10 !important;
      }
      body div[role="listbox"] [role="option"]:hover,
      body ul[role="listbox"] [role="option"]:hover,
      body [role="listbox"] [aria-selected="true"] {
        background: rgba(14, 14, 16, 0.08) !important;
        background-color: rgba(14, 14, 16, 0.08) !important;
      }
      /* ─── DEFENSIVE SWEEP: BaseWeb dropdown options ───────────────────
         BaseWeb steruje hover/keyboard-focus przez ATTRIBUTES (data-highlighted,
         data-focusvisible, aria-selected) — nie tylko :hover. Jeśli któryś
         z nich zostawi dark bg, label imienia atlety znika na czarnym tle.
         Pokrywam wszystkie + force light bg + ink text na każdym descendant. */
      body [role="listbox"] [role="option"],
      body [role="listbox"] [role="option"] *,
      body [data-baseweb="select-dropdown"] [role="option"],
      body [data-baseweb="select-dropdown"] [role="option"] * {
        color: #0E0E10 !important;
      }
      body [role="listbox"] [role="option"]:hover,
      body [role="listbox"] [role="option"][aria-selected="true"],
      body [role="listbox"] [role="option"][data-highlighted="true"],
      body [role="listbox"] [role="option"][data-focusvisible="true"],
      body [data-baseweb="select-dropdown"] [role="option"]:hover,
      body [data-baseweb="select-dropdown"] [role="option"][aria-selected="true"],
      body [data-baseweb="select-dropdown"] [role="option"][data-highlighted="true"] {
        background: rgba(14, 14, 16, 0.08) !important;
        background-color: rgba(14, 14, 16, 0.08) !important;
        color: #0E0E10 !important;
      }
      /* Children — żeby nie pomalowały się na dark przez własne BaseWeb style */
      body [role="listbox"] [role="option"]:hover *,
      body [role="listbox"] [role="option"][aria-selected="true"] *,
      body [role="listbox"] [role="option"][data-highlighted="true"] *,
      body [role="listbox"] [role="option"][data-focusvisible="true"] *,
      body [data-baseweb="select-dropdown"] [role="option"]:hover *,
      body [data-baseweb="select-dropdown"] [role="option"][aria-selected="true"] *,
      body [data-baseweb="select-dropdown"] [role="option"][data-highlighted="true"] * {
        background: transparent !important;
        background-color: transparent !important;
        color: #0E0E10 !important;
      }
      /* Popover (st.popover "More" menu w hero) — tło białe, ink text */
      body [data-testid="stPopover"],
      body [data-testid="stPopover"] *,
      body div[role="dialog"][aria-modal="false"],
      body div[role="dialog"][aria-modal="false"] * {
        color: #0E0E10 !important;
      }
      body [data-testid="stPopover"] > div,
      body div[role="dialog"][aria-modal="false"] > div {
        background: #FFFFFF !important;
        border: 1px solid rgba(14, 14, 16, 0.10) !important;
        border-radius: 12px !important;
        box-shadow: 0 12px 32px -12px rgba(14, 14, 16, 0.28) !important;
      }

      /* Selectbox input field + value */
      .stSelectbox [data-baseweb="select"],
      .stSelectbox [data-baseweb="select"] > div,
      [data-baseweb="select"] [data-baseweb="select-control"] {
        background: var(--aph-card) !important;
        border-color: var(--aph-line) !important;
        color: var(--aph-ink) !important;
      }
      [data-baseweb="select"] input,
      [data-baseweb="select"] [data-baseweb="tag"] {
        color: var(--aph-ink) !important;
      }
      [data-baseweb="select"] svg { color: var(--aph-dim) !important; }

      /* Text input / textarea */
      .stTextInput input,
      .stTextArea textarea,
      [data-baseweb="input"] input,
      [data-baseweb="textarea"] textarea {
        background: var(--aph-card) !important;
        border-color: var(--aph-line) !important;
        color: var(--aph-ink) !important;
      }
      [data-baseweb="input"]:focus-within,
      [data-baseweb="textarea"]:focus-within {
        border-color: var(--aph-ink) !important;
      }

      /* Radio / checkbox */
      [data-baseweb="radio"] *,
      [data-baseweb="checkbox"] * {
        color: var(--aph-ink) !important;
      }

      /* Dialog / Modal (st.dialog NORMS, profile, test note) */
      [data-testid="stDialog"],
      [data-testid="stModal"],
      [data-baseweb="modal"],
      [data-baseweb="dialog"],
      [role="dialog"] {
        background: var(--aph-page) !important;
        color: var(--aph-ink) !important;
      }
      [data-baseweb="modal"] > div,
      [role="dialog"] > div {
        background: var(--aph-page) !important;
      }
      [data-testid="stDialog"] *,
      [data-baseweb="modal"] *,
      [role="dialog"] *:not([data-baseweb="popover"]):not([data-baseweb="menu"]):not(.material-symbols-outlined):not([class*="material-symbols"]) {
        color: var(--aph-ink);
      }
      /* Wyjątek: markdown-label w primary button (np. "💾 Zapisz") ma
         ciemne tło — tekst musi być bone, nie ink-na-ink. */
      [role="dialog"] button[data-testid="stBaseButton-primary"] *,
      [data-testid="stDialog"] button[data-testid="stBaseButton-primary"] *,
      .stApp button[data-testid="stBaseButton-primary"] p {
        color: var(--aph-bone) !important;
      }
      /* Wewnątrz dialogu zachowaj mute dla labels */
      [role="dialog"] .pf-label,
      [role="dialog"] [data-testid="stMetricLabel"],
      [role="dialog"] .stCaption,
      [role="dialog"] [data-testid="stCaptionContainer"] {
        color: var(--aph-mute) !important;
      }
      /* Dialog tytuł — Archivo Black */
      [role="dialog"] h1,
      [role="dialog"] h2,
      [role="dialog"] h3 {
        font-family: var(--aph-display) !important;
        color: var(--aph-ink) !important;
      }
      /* Dialog backdrop (overlay) */
      [data-baseweb="modal"] [aria-label="modal-overlay"] {
        background: rgba(15, 23, 40, 0.40) !important;
      }

      /* NORMS dialog — personal-best mini-karty (spójne z KPI na stronie) */
      [role="dialog"] .aph-pb-tile {
        background: var(--aph-card) !important;
        border: 1px solid var(--aph-line);
        border-radius: var(--aph-r-md);
        padding: 12px 14px;
        box-shadow: var(--aph-shadow);
      }
      [role="dialog"] .aph-pb-label {
        font-family: var(--aph-mono) !important;
        font-size: 10px;
        letter-spacing: 0.16em;
        text-transform: uppercase;
        color: var(--aph-dim) !important;
        margin-bottom: 6px;
        display: block;
      }
      [role="dialog"] .aph-pb-label::before {
        content: "";
        display: inline-block;
        width: 5px; height: 5px;
        border-radius: 50%;
        background: var(--aph-accent);
        margin-right: 6px;
        vertical-align: middle;
        position: relative; top: -1px;
      }
      [role="dialog"] .aph-pb-value {
        font-family: var(--aph-display) !important;
        font-size: 28px;
        color: var(--aph-ink) !important;
        line-height: 1;
        letter-spacing: -0.02em;
      }
      [role="dialog"] .aph-pb-unit {
        font-family: var(--aph-text) !important;
        font-size: 13px;
        font-weight: 500;
        color: var(--aph-dim) !important;
        margin-left: 3px;
      }

      /* Tooltipy (BaseWeb) — light theme */
      [data-baseweb="tooltip"] {
        background: var(--aph-ink) !important;
        color: var(--aph-bone) !important;
        border: 1px solid var(--aph-line) !important;
        border-radius: 8px !important;
      }
      [data-baseweb="tooltip"] * {
        color: var(--aph-bone) !important;
      }

      /* Alerts (st.info / st.warning / st.success / st.error) — adapt kolory */
      [data-testid="stAlert"] {
        border-radius: var(--aph-r-md) !important;
        border: 1px solid var(--aph-line) !important;
      }
      [data-testid="stAlert"][data-baseweb*="notification"] {
        background: var(--aph-card) !important;
      }
      /* Info alert (niebieski) → bone bg + ink text */
      [data-testid="stAlert"]:has(svg[fill*="#3b82f6"]),
      [data-testid="stAlert"]:has([class*="info"]) {
        background: color-mix(in oklab, var(--aph-ink) 4%, transparent) !important;
        border-color: var(--aph-line) !important;
      }
      [data-testid="stAlert"] * {
        color: var(--aph-ink) !important;
      }

      /* Toast (st.success) — adapt */
      [data-testid="stToast"] {
        background: var(--aph-ink) !important;
        color: var(--aph-bone) !important;
        border-radius: var(--aph-r-md) !important;
      }
      [data-testid="stToast"] * {
        color: var(--aph-bone) !important;
      }

      /* Caption / help text */
      .stCaption,
      [data-testid="stCaptionContainer"],
      [data-testid="stCaption"],
      small {
        color: var(--aph-mute) !important;
        font-family: var(--aph-text) !important;
      }

      /* Slider — clean light */
      [data-baseweb="slider"] [role="slider"] {
        background: var(--aph-ink) !important;
      }
      [data-baseweb="slider"] div[data-testid] {
        background: var(--aph-line) !important;
      }

      /* File uploader dropzone */
      [data-testid="stFileUploader"] section,
      [data-testid="stFileUploaderDropzone"] {
        background: var(--aph-card) !important;
        border: 1px dashed var(--aph-line) !important;
        color: var(--aph-ink) !important;
      }

      /* Dataframe — light theme */
      [data-testid="stDataFrame"],
      [data-testid="stDataFrame"] * {
        color: var(--aph-ink) !important;
      }
      [data-testid="stDataFrame"] [role="row"]:hover {
        background: color-mix(in oklab, var(--aph-ink) 4%, transparent) !important;
      }

      /* Expander hover state — subtle */
      [data-testid="stExpander"] summary:hover {
        background: color-mix(in oklab, var(--aph-ink) 3%, transparent) !important;
      }

      /* Spinner */
      .stSpinner > div {
        color: var(--aph-ink) !important;
      }

      /* Progress bar */
      [data-testid="stProgress"] > div > div > div > div {
        background: var(--aph-ink) !important;
      }

      /* Container border wrapper — neutralizuj 'border' atrybut na containerach
         które NIE mają athlete-card-head (te mają już gradient border).
         Plus subtle box-shadow żeby karty wyróżniały się od bone bg strony. */
      [data-testid="stVerticalBlockBorderWrapper"]:not(:has(.aph-v2-athlete-card-head)) {
        background: var(--aph-card) !important;
        border: 1px solid var(--aph-line) !important;
        border-radius: var(--aph-r-card) !important;
        box-shadow: 0 1px 0 rgba(14, 14, 16, 0.02),
                    0 4px 16px -8px rgba(14, 14, 16, 0.08) !important;
      }

      /* Padding karty atlety większy + spójny z mockup KPI cards */
      /* Gradient border via double-background trick: solid card fill na padding-box,
         lekki diagonal gradient na border-box. Ink → accent → ink dla subtelnego
         akcentu bez przytłaczania.
         Stała min-height + flex column żeby wszystkie kafle miały TĘ SAMĄ wysokość
         (przyciski wyrównane na dole, niezależnie od długości meta). */
      /* JEDNA karta na kafel: styl tylko na NAJBLIŻSZYM bloku z headem.
         Wcześniej selektor łapał też zewnętrzny BorderWrapper → karta w karcie
         (podwójna ramka na rosterze, screenshot audytu 2026-07-03). */
      [data-testid="stVerticalBlock"]:has(> [data-testid="stElementContainer"] .aph-v2-athlete-card-head) {
        padding: 16px !important;
        background: var(--aph-card) !important;
        border: 1px solid var(--aph-line) !important;
        border-radius: var(--aph-r-card) !important;
        transition: transform 150ms ease, box-shadow 150ms ease, border-color 150ms ease;
        min-height: 92px !important;
        display: flex !important;
        flex-direction: column !important;
        box-shadow: var(--aph-shadow) !important;
      }
      /* Zewnętrzny wrapper kontenera = przezroczysty przekaźnik */
      [data-testid="stVerticalBlockBorderWrapper"]:has(.aph-v2-athlete-card-head) {
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
        padding: 0 !important;
      }
      [data-testid="stVerticalBlock"]:has(> [data-testid="stElementContainer"] .aph-v2-athlete-card-head):hover {
        transform: translateY(-2px);
        border-color: var(--aph-accent) !important;
        box-shadow: 0 1px 2px rgba(15,23,40,.05),
                    0 18px 40px -16px rgba(15,23,40,.30) !important;
      }
      /* Wewnętrzny vertical block w karcie atlety: column z space-between żeby
         buttons (Otwórz/Edit/Delete) wisiały na dole nawet gdy meta puste */
      [data-testid="stVerticalBlockBorderWrapper"]:has(.aph-v2-athlete-card-head)
        > [data-testid="stVerticalBlock"] {
        display: flex !important;
        flex-direction: column !important;
        flex: 1 !important;
        gap: 0 !important;
      }
      /* Spacer: ostatni element przed buttonami (zwykle st.markdown z meta lub
         pusty placeholder) — push buttons w dół */
      [data-testid="stVerticalBlockBorderWrapper"]:has(.aph-v2-athlete-card-head)
        > [data-testid="stVerticalBlock"]
        > [data-testid="stHorizontalBlock"]:last-child {
        margin-top: auto !important;
      }
    </style>
    """,
    unsafe_allow_html=True,
)


# ─────────────────────────────────────────────────────────────────────────────
# Główny entrypoint
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# Dialog: dodaj / edytuj zawodnika
# ─────────────────────────────────────────────────────────────────────────────

# Pull infra (R/valdr) — wykryj w obu znanych lokalizacjach. Bez tego przyciski
# refresh znikają gdy folder leży w ~/Desktop/Pulpit/vald-api zamiast ~/Desktop/vald-api
# (przycisk pokazuje się tylko gdy _VALD_API_ROOT.exists()).
_VALD_API_CANDIDATES = [
    # infra pull'a leży WEWNĄTRZ projektu (obok app.py) — preferowana ścieżka
    Path(__file__).resolve().parent / "vald-api",
    Path.home() / "Desktop" / "vald-forcedecks" / "vald-api",
    Path.home() / "Desktop" / "vald-api",
    Path.home() / "Desktop" / "Pulpit" / "vald-api",
    Path.home() / "Pulpit" / "vald-api",
]
_VALD_API_ROOT = next(
    (p for p in _VALD_API_CANDIDATES if p.exists()), _VALD_API_CANDIDATES[0]
)
_VALD_API_DATA_DIR = _VALD_API_ROOT / "data"


@st.dialog("VALD API pull log", width="large")
def _pull_log_dialog(log: str) -> None:
    """Modal z logiem ostatniego pull'a — używany po failure (zamiast inline
    expandera który rozsuwał layout strony)."""
    st.markdown(
        "<div style='color:var(--aph-bad); font-weight:600; margin-bottom:8px;'>"
        "❌ Pull nieudany — szczegóły poniżej</div>",
        unsafe_allow_html=True,
    )
    st.code(log or "(brak outputu)", language="text")


def _last_api_pull_at() -> "pd.Timestamp | None":
    """Najnowszy folder pull w ~/Desktop/vald-api/data/ — kiedy ostatnio strona
    pobrała dane z VALD API. Format folderu: YYYY-MM-DD lub YYYY-MM-DD_HHMM.
    Zwraca None gdy brak folderów."""
    if not _VALD_API_DATA_DIR.exists():
        return None
    candidates: list[tuple[pd.Timestamp, Path]] = []
    for p in _VALD_API_DATA_DIR.iterdir():
        if not p.is_dir() or not p.name[:1].isdigit():
            continue
        # Parsuj nazwę folderu na timestamp + fallback do mtime
        try:
            ts = pd.to_datetime(p.name.replace("_", " "), format="%Y-%m-%d %H%M", errors="coerce")
            if pd.isna(ts):
                ts = pd.to_datetime(p.name[:10], errors="coerce")
            if pd.isna(ts):
                continue
            # Jeśli folder ma tylko datę (bez HHMM), dodaj mtime aby porównanie było stabilne
            if len(p.name) == 10:
                ts = ts + pd.Timedelta(seconds=int(p.stat().st_mtime % 86400))
            candidates.append((ts, p))
        except Exception:
            continue
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][0]


def _humanize_since(ts: "pd.Timestamp") -> str:
    """Krótki opis 'ile czasu temu' (PL)."""
    try:
        delta = pd.Timestamp.now() - ts
    except Exception:
        return ""
    secs = int(delta.total_seconds())
    if secs < 60:
        return "przed chwilą"
    if secs < 3600:
        m = secs // 60
        return f"{m} min temu"
    if secs < 86400:
        h = secs // 3600
        return f"{h} h temu"
    d = secs // 86400
    if d == 1:
        return "wczoraj"
    if d < 30:
        return f"{d} dni temu"
    months = d // 30
    return f"{months} mies. temu"
_VALD_FORCEDECKS_ROOT = Path(__file__).resolve().parent


# Jeden pull naraz — chroni przed kolizją ręcznego przycisku z auto-refreshem
# w tle (dwa równoległe Rscripty piszące do tych samych CSV = korupcja delty).
_REFRESH_LOCK = threading.Lock()


def _rscript_path() -> str | None:
    """Pełna ścieżka Rscript. Streamlit odpalany przez AthleteLab.app
    (launchd) dostaje minimalny PATH bez /usr/local/bin — goły 'Rscript'
    kończył się '❌ nie znaleziony w PATH' mimo zainstalowanego R."""
    import shutil
    found = shutil.which("Rscript")
    if found:
        return found
    for cand in (
        "/usr/local/bin/Rscript",
        "/opt/homebrew/bin/Rscript",
        "/Library/Frameworks/R.framework/Resources/bin/Rscript",
    ):
        if Path(cand).exists():
            return cand
    return None


def _run_vald_api_refresh(*, full: bool = False) -> tuple[bool, str]:
    """Uruchom pipeline pull z VALD API:
    1. Rscript scripts/04_weekly_pull.R (default — incremental tests/trials
       + świeży snapshot profiles + result_definitions)
       lub scripts/03_initial_pull.R (full=True — pełen pull od początku roku)
    2. python tools/api_to_dashboard.py (CSV → format dashboardu)
    Zwraca (success, combined_log).

    Quick (weekly) wystarcza na codzienną pracę — pulluje też nowych atletów
    przez snapshot profiles. Full używaj tylko gdy podejrzewasz że stara baza
    ma braki / rebuild from scratch."""
    if not _REFRESH_LOCK.acquire(blocking=False):
        return False, (
            "⏳ Refresh już trwa (ręczny lub automatyczny w tle) — "
            "poczekaj aż się skończy i spróbuj ponownie."
        )
    try:
        return _run_vald_api_refresh_inner(full=full)
    finally:
        _REFRESH_LOCK.release()


def _run_vald_api_refresh_inner(*, full: bool = False) -> tuple[bool, str]:
    log_parts: list[str] = []

    if not _VALD_API_ROOT.exists():
        return False, f"❌ Brak {_VALD_API_ROOT} — działa tylko lokalnie."

    # Krok 1: R pull
    script_name = "03_initial_pull.R" if full else "04_weekly_pull.R"
    r_script = _VALD_API_ROOT / "scripts" / script_name
    if not r_script.exists():
        return False, f"❌ Brak {r_script}"
    rscript = _rscript_path()
    if not rscript:
        return False, (
            "❌ Rscript nie znaleziony (PATH ani standardowe lokalizacje). "
            "Zainstaluj R albo dodaj Rscript do PATH."
        )
    try:
        r = subprocess.run(
            [rscript, str(r_script)],
            cwd=_VALD_API_ROOT,
            capture_output=True, text=True,
            timeout=600 if full else 300,
        )
        log_parts.append(f"=== Rscript {script_name} (rc={r.returncode}) ===")
        if r.stdout:
            log_parts.append(r.stdout.strip())
        if r.stderr:
            log_parts.append(f"[stderr]\n{r.stderr.strip()}")
        if r.returncode != 0:
            return False, "\n".join(log_parts)
    except FileNotFoundError:
        return False, "❌ `Rscript` nie znaleziony w PATH. Zainstaluj R."
    except subprocess.TimeoutExpired:
        return False, "❌ Rscript timeout (>5 min)."

    # Krok 2: Python pivot
    py_script = _VALD_FORCEDECKS_ROOT / "tools" / "api_to_dashboard.py"
    venv_py = _VALD_FORCEDECKS_ROOT / ".venv" / "bin" / "python"
    py_bin = str(venv_py) if venv_py.exists() else "python"
    try:
        p = subprocess.run(
            [py_bin, str(py_script)],
            cwd=_VALD_FORCEDECKS_ROOT,
            capture_output=True, text=True, timeout=180,
        )
        log_parts.append(f"\n=== api_to_dashboard.py (rc={p.returncode}) ===")
        if p.stdout:
            log_parts.append(p.stdout.strip())
        if p.stderr:
            log_parts.append(f"[stderr]\n{p.stderr.strip()}")
        if p.returncode != 0:
            return False, "\n".join(log_parts)
    except subprocess.TimeoutExpired:
        return False, "❌ api_to_dashboard.py timeout (>3 min)."

    # Krok 3: Auto-import wygenerowanych CSV do library.parquet
    _do_auto_import_csv(log_parts)

    return True, "\n".join(log_parts)


def _do_auto_import_csv(log_parts: list[str]) -> None:
    """Wczytaj wszystkie CSV z dashboard_csv/ i zapisz do library.parquet
    (z dedupe po Name+Date). Modyfikuje log_parts in-place."""
    dashboard_csv_dir = _VALD_API_DATA_DIR / "dashboard_csv"
    if not dashboard_csv_dir.exists():
        return
    csvs = sorted(dashboard_csv_dir.glob("*.csv"))
    log_parts.append(f"\n=== Auto-import do library.parquet ({len(csvs)} CSV) ===")
    try:
        frames = []
        for csv_path in csvs:
            try:
                frames.append(pd.read_csv(csv_path, low_memory=False))
            except Exception as e:
                log_parts.append(f"⚠️  {csv_path.name}: {e}")
        if frames:
            merged = pd.concat(frames, ignore_index=True, sort=False)
            if "Date" in merged.columns:
                merged["Date"] = pd.to_datetime(merged["Date"], errors="coerce")
            stats = save_to_library(merged)
            log_parts.append(
                f"✅ Library: +{stats.get('added', 0)} nowych, "
                f"{stats.get('replaced', 0)} nadpisało duplikaty, "
                f"total {stats.get('total', 0)} wierszy."
            )
        else:
            log_parts.append("⚠️  Brak CSV do importu.")
    except Exception as e:
        log_parts.append(f"❌ Auto-import error: {e}")


def _run_pivot_and_import() -> tuple[bool, str]:
    """Szybki pipeline — tylko Python pivot + auto-import (bez R API pulla).
    Używane po dodaniu nowego zawodnika żeby pobrać jego HISTORYCZNE testy
    z istniejących plików ~/Desktop/vald-api/data/. ~10s zamiast 2 min."""
    log_parts: list[str] = []
    if not _VALD_API_ROOT.exists():
        return False, f"❌ Brak {_VALD_API_ROOT} — działa tylko lokalnie."

    py_script = _VALD_FORCEDECKS_ROOT / "tools" / "api_to_dashboard.py"
    venv_py = _VALD_FORCEDECKS_ROOT / ".venv" / "bin" / "python"
    py_bin = str(venv_py) if venv_py.exists() else "python"
    try:
        p = subprocess.run(
            [py_bin, str(py_script)],
            cwd=_VALD_FORCEDECKS_ROOT,
            capture_output=True, text=True, timeout=180,
        )
        log_parts.append(f"=== api_to_dashboard.py (rc={p.returncode}) ===")
        if p.stdout:
            log_parts.append(p.stdout.strip())
        if p.stderr:
            log_parts.append(f"[stderr]\n{p.stderr.strip()}")
        if p.returncode != 0:
            return False, "\n".join(log_parts)
    except subprocess.TimeoutExpired:
        return False, "❌ api_to_dashboard.py timeout (>3 min)."

    _do_auto_import_csv(log_parts)
    return True, "\n".join(log_parts)


def _get_vald_profile_options() -> list[tuple[str, str]]:
    """Zwróć listę zawodników z VALD API (najnowszy folder z profiles.csv):
    [(display_label, normalized_name), ...]. Wyklucza tych już w dashboardzie
    (library.parquet + athletes_meta.json).
    Pusta lista gdy brak pullu (np. Streamlit Cloud bez lokalnego folderu vald-api)."""
    if not _VALD_API_DATA_DIR.exists():
        return []
    # Najnowszy folder ZAWIERAJĄCY profiles.csv — incremental pulle
    # (04_weekly_pull.R) tworzą foldery tylko z tests/trials, bez profiles.
    pulls_with_profiles = sorted(
        (p for p in _VALD_API_DATA_DIR.iterdir()
         if p.is_dir() and p.name[:1].isdigit()
         and (p / "profiles.csv").exists()),
        reverse=True,
    )
    if not pulls_with_profiles:
        return []
    profiles_csv = pulls_with_profiles[0] / "profiles.csv"
    try:
        prof = pd.read_csv(profiles_csv)
    except Exception:
        return []
    # prof.get("col", "") zwraca SKALAR "" gdy kolumny brak → "".fillna() rzuca
    # AttributeError POZA try/except i wywala dialog dodawania. Bierzemy kolumnę
    # tylko gdy istnieje, inaczej pustą Series (graceful → []).
    def _name_col(col: str) -> pd.Series:
        return prof[col] if col in prof.columns else pd.Series("", index=prof.index)
    prof["full_name"] = (
        _name_col("givenName").fillna("").astype(str).str.strip() + " "
        + _name_col("familyName").fillna("").astype(str).str.strip()
    ).str.strip()
    prof["full_name"] = prof["full_name"].map(lambda s: " ".join(s.split()))
    prof = prof[prof["full_name"] != ""].copy()

    # Wyklucz tych już w dashboardzie
    already_in = set(list_profile_names())
    already_in.update(a["name"] for a in get_athletes_summary())
    prof = prof[~prof["full_name"].isin(already_in)]
    prof = prof.sort_values("full_name").reset_index(drop=True)

    return [(name, name) for name in prof["full_name"].tolist()]


# ─────────────────────────────────────────────────────────────────────────────
# Tryb treningowy (Plany / Baza ćwiczeń / Siłownia / widok zawodnika)
# wydzielony do vald/ui_training.py — patrz tamtejszy docstring.
# ─────────────────────────────────────────────────────────────────────────────
from vald.ui_training import (  # noqa: E402
    _render_athlete_mode,
    _render_gym_mode,
)

# Hexy akcentów testów do PDF (matplotlib nie zna oklch z TEST_ACCENT)
_PDF_TEST_ACCENT: dict[str, str] = {
    "CMJ": "#2F6BD8", "SJ": "#7C6FF0", "HOP": "#3BA776",
    "DJ": "#E58C3A", "IMTP": "#5B7BA6", "RSAIP": "#14B8A6", "RSKIP": "#D97706",
}

# Metryki liniowe testów specjalnych (bez MetricDef) — (label, kolumna, unit)
_REPORT_DJ_METRICS = [
    ("RSI (FT/CT)", "RSI (Flight Time/Contact Time)", ""),
    ("Jump Height", "Jump Height (Flight Time)", "cm"),
    ("Contact Time", "Contact Time [ms] ", "ms"),
]


def _report_line_options(sub: pd.DataFrame, tt: str) -> list[str]:
    """Etykiety metryk trendu dostępnych w danych dla danego testu."""
    if tt == "DJ":
        return [lbl for lbl, col, _u in _REPORT_DJ_METRICS if col in sub.columns]
    if tt in ("RSAIP", "RSKIP"):
        return [lbl for _c, lbl, _u, _d in RSAIP_TILE_METRICS if _c in sub.columns]
    out = []
    for m in METRICS_BY_TEST.get(tt, []):
        if m.asymmetry:
            continue
        if match_column(sub, m):
            out.append(m.label)
    return out


def _report_asym_options(sub: pd.DataFrame, tt: str) -> list[str]:
    if tt in ("RSAIP", "RSKIP"):
        return ["Peak Force (L/R)"] if "Peak Vertical Force" in sub.columns else []
    if tt in ("DJ", "HOP"):
        return []
    return [m.label for m, _c in resolve_metrics(sub, tt, section="asymmetry")]


def _report_day_best_series(
    sub: pd.DataFrame, tt: str, col: str, date_col: str,
    by_col: str | None = None,
) -> "pd.Series":
    """Wartość `col` per dzień z repa o najwyższym `by_col` (domyślnie: col).
    Spójna kinematyka: wszystkie metryki dnia z TEGO SAMEGO najlepszego repa."""
    d = sub[[date_col, col] + ([by_col] if by_col and by_col != col else [])].copy()
    d["_day"] = pd.to_datetime(d[date_col], errors="coerce").dt.date
    d[col] = pd.to_numeric(d[col], errors="coerce")
    rank_col = by_col if by_col else col
    d[rank_col] = pd.to_numeric(d[rank_col], errors="coerce")
    d = d.dropna(subset=["_day", rank_col])
    if d.empty:
        return pd.Series(dtype=float)
    idx = d.groupby("_day")[rank_col].idxmax()
    out = d.loc[idx].set_index("_day")[col].dropna().sort_index()
    out.index = pd.to_datetime(out.index)
    return out


@st.dialog("📄 Raport PDF", width="large")
def _report_dialog(name: str) -> None:
    """Wybór testów + metryk → PDF 'Raport testów — Imię Nazwisko'."""
    df = st.session_state.get("data")
    if df is None or df.empty:
        st.info("Brak danych zawodnika.")
        return
    date_col = "Date" if "Date" in df.columns else None
    if not date_col:
        st.info("Brak dat w danych — raport trendów niedostępny.")
        return
    splits = {
        tt: df[df["Test Type"] == tt]
        for tt in ENABLED_TEST_TYPES
        if "Test Type" in df.columns and not df[df["Test Type"] == tt].empty
    }
    if not splits:
        st.info("Brak testów do raportu.")
        return

    st.caption(f"**{name}** · zaznacz co ma wejść do PDF")
    sel_tests = st.multiselect(
        "Testy",
        options=list(splits.keys()),
        default=[t for t in ("CMJ",) if t in splits] or list(splits.keys())[:1],
        key="rpt_tests",
    )

    selections: dict[str, dict] = {}
    for tt in sel_tests:
        sub = splits[tt]
        line_opts = _report_line_options(sub, tt)
        asym_opts = _report_asym_options(sub, tt)
        st.markdown(
            f"<div style='font-family:var(--aph-text); font-size:12px; "
            f"font-weight:700; color:{_PDF_TEST_ACCENT.get(tt, '#2F6BD8')}; "
            f"margin:10px 0 2px;'>{tt}</div>",
            unsafe_allow_html=True,
        )
        c1, c2 = st.columns([1.2, 1])
        with c1:
            sel_lines = st.multiselect(
                "Metryki — trend w czasie",
                options=line_opts,
                default=line_opts[:3],
                key=f"rpt_lines_{tt}",
            )
        with c2:
            sel_asym = st.multiselect(
                "Asymetrie — słupki L/R",
                options=asym_opts,
                default=[],
                key=f"rpt_asym_{tt}",
            ) if asym_opts else []
        selections[tt] = {"lines": sel_lines, "asym": sel_asym}

    if not any(v["lines"] or v["asym"] for v in selections.values()):
        st.caption("Wybierz przynajmniej jedną metrykę.")
        return

    if st.button("Generuj PDF", type="primary", key="rpt_generate",
                 use_container_width=True):
        with st.spinner("Buduję raport…"):
            sections: list[dict] = []
            for tt, sel in selections.items():
                sub = splits[tt]
                charts: list[dict] = []
                primary_col = None
                if tt in ("CMJ", "SJ"):
                    primary_col = "Jump Height (Imp-Mom) [cm] "
                elif tt == "HOP":
                    primary_col = "RSI (Flight/Contact Time)"
                elif tt == "IMTP":
                    primary_col = "Peak Vertical Force"

                for lbl in sel["lines"]:
                    if tt == "DJ":
                        col, unit = next(
                            (c, u) for l, c, u in _REPORT_DJ_METRICS if l == lbl
                        )
                        for hv, gsub in _dj_height_groups(sub):
                            s = _report_day_best_series(
                                gsub, tt, col, date_col,
                                by_col="RSI (Flight Time/Contact Time)",
                            )
                            if not s.empty:
                                # VALD eksportuje Contact Time dla DJ
                                # w SEKUNDACH, mimo nazwy kolumny „[ms]".
                                # Bez tego raport pokazywał 0,18 z osią „ms"
                                # zamiast 183 ms (Filip 2026-09-04).
                                # Ten sam auto-detect co w widoku DJ (max < 5).
                                if col.strip().startswith("Contact Time"):
                                    _mx = pd.to_numeric(s, errors="coerce").max()
                                    if pd.notna(_mx) and _mx < 5:
                                        s = s * 1000
                                charts.append({
                                    "kind": "line", "unit": unit,
                                    "title": f"{lbl} · drop {_dj_height_label(hv)}",
                                    "series": s,
                                })
                    elif tt in ("RSAIP", "RSKIP"):
                        col, unit, _dec = next(
                            (c, u, d) for c, l, u, d in RSAIP_TILE_METRICS
                            if l == lbl
                        )
                        sl = _report_day_best_series(
                            sub[sub.get("TrialLimb") == "Left"], tt, col,
                            date_col, by_col="Peak Vertical Force",
                        )
                        sr = _report_day_best_series(
                            sub[sub.get("TrialLimb") == "Right"], tt, col,
                            date_col, by_col="Peak Vertical Force",
                        )
                        charts.append({
                            "kind": "line2", "title": lbl, "unit": unit,
                            "series_l": sl, "series_r": sr,
                        })
                    else:
                        m = next(
                            (m for m in METRICS_BY_TEST.get(tt, [])
                             if m.label == lbl and not m.asymmetry), None,
                        )
                        mcol = match_column(sub, m) if m else None
                        if not mcol:
                            continue
                        s = _report_day_best_series(
                            sub, tt, mcol, date_col, by_col=primary_col
                            if primary_col in sub.columns else None,
                        )
                        if not s.empty:
                            charts.append({
                                "kind": "line", "title": lbl,
                                "unit": m.unit or "", "series": s,
                            })

                for lbl in sel["asym"]:
                    if tt in ("RSAIP", "RSKIP"):
                        sl = _report_day_best_series(
                            sub[sub.get("TrialLimb") == "Left"], tt,
                            "Peak Vertical Force", date_col,
                        )
                        sr = _report_day_best_series(
                            sub[sub.get("TrialLimb") == "Right"], tt,
                            "Peak Vertical Force", date_col,
                        )
                        both = pd.concat(
                            {"L": sl, "R": sr}, axis=1,
                        ).dropna()
                        if not both.empty:
                            signed = (
                                (both["R"] - both["L"])
                                / both.max(axis=1) * 100.0
                            )
                            charts.append({
                                "kind": "asym",
                                "title": "Peak Force — asymetria",
                                "series": signed,
                            })
                    else:
                        pair = next(
                            ((m, c) for m, c in resolve_metrics(
                                sub, tt, section="asymmetry")
                             if m.label == lbl), None,
                        )
                        if not pair:
                            continue
                        signed = _signed_asym_mean_per_day(
                            sub, pair[1], date_col,
                        )
                        if not signed.empty:
                            charts.append({
                                "kind": "asym", "title": lbl,
                                "series": signed,
                            })

                if charts:
                    sections.append({
                        "test": TEST_LABELS.get(tt, tt),
                        "accent": _PDF_TEST_ACCENT.get(tt, "#2F6BD8"),
                        "charts": charts,
                    })

            # Meta strony tytułowej
            dts = pd.to_datetime(df[date_col], errors="coerce").dropna()
            span = (
                f"{dts.min():%d.%m.%Y} – {dts.max():%d.%m.%Y}"
                if not dts.empty else ""
            )
            meta = {
                "sport": (get_profile(name) or {}).get("sport", ""),
                "span": span,
                "n_days": int(dts.dt.date.nunique()) if not dts.empty else None,
                "tests": " · ".join(selections.keys()),
            }
            pdf_bytes = build_report_pdf(name, meta, sections)
            st.session_state["_rpt_pdf"] = pdf_bytes
            st.session_state["_rpt_fname"] = (
                f"Raport_{name.replace(' ', '_')}_{pd.Timestamp.now():%Y%m%d}.pdf"
            )

    if st.session_state.get("_rpt_pdf"):
        st.download_button(
            "⬇ Pobierz PDF",
            data=st.session_state["_rpt_pdf"],
            file_name=st.session_state.get("_rpt_fname", "raport.pdf"),
            mime="application/pdf",
            use_container_width=True,
            key="rpt_download",
        )


@st.dialog("👤 Profil zawodnika")
def _athlete_profile_dialog(prefill_name: str = "") -> None:
    """Modal z formularzem profilu. Jeśli prefill_name istnieje — edycja
    (nawet gdy profil jeszcze pusty, tj. zawodnik ma tylko testy bez metadanych)."""
    existing = get_profile(prefill_name) if prefill_name else {}
    is_edit = bool(prefill_name)

    if is_edit:
        st.caption(f"Edycja profilu: **{prefill_name}**")
        name = st.text_input(
            "Imię i nazwisko *",
            value=prefill_name,
            help="Zmiana imienia przepnie wszystkie testy tego zawodnika w bazie.",
            key="dlg_name_input",
        )
    else:
        vald_options = _get_vald_profile_options()
        # Toggle: pick z VALD vs wpisz ręcznie (gdy zawodnik świeżo dodany w VALD
        # i nie jest jeszcze w lokalnym profiles.csv — incremental pull go pomija).
        manual_entry = st.toggle(
            "Wpisz nazwisko ręcznie (jeśli zawodnik świeżo dodany w VALD i nie ma go na liście)",
            value=not vald_options,
            key="dlg_manual_entry",
            help="Manual entry tworzy profil w lokalnej bazie. Gdy następny "
                 "pełen pull z VALD przyniesie testy zawodnika, zostaną do niego "
                 "podpięte automatycznie po nazwisku.",
        )

        if manual_entry:
            name = st.text_input(
                "Imię i nazwisko *",
                value="",
                placeholder="Jan Kowalski",
                key="dlg_manual_name_input",
                help="Wpisz dokładnie takie samo imię i nazwisko jak w VALD ForceDecks "
                     "(diakrytyki, spacje) żeby testy się podpięły przy następnym pull'u.",
            )
        elif not vald_options:
            st.warning(
                "Brak danych z VALD API w `~/Desktop/vald-api/data/`. "
                "Uruchom najpierw pull z API (przycisk **🔄** w prawym górnym rogu) "
                "lub zaznacz **Wpisz nazwisko ręcznie** powyżej."
            )
            name = ""
        else:
            displays = ["— wybierz —"] + [d for d, _ in vald_options]
            picked = st.selectbox(
                f"Zawodnik z VALD ({len(vald_options)} dostępnych)",
                options=displays,
                key="dlg_vald_picker",
            )
            if picked != "— wybierz —":
                name = next(n for d, n in vald_options if d == picked)
                st.caption(f"✅ Dodam: **{name}**")
            else:
                name = ""

    SEX_OPTIONS = [("", "— wybierz —"), ("male", "Mężczyzna"), ("female", "Kobieta")]
    existing_sex = (existing.get("sex") or "").lower()
    sex_idx = next(
        (i for i, (k, _) in enumerate(SEX_OPTIONS) if k == existing_sex), 0,
    )
    sex_label = st.selectbox(
        "Płeć *",
        options=[lbl for _, lbl in SEX_OPTIONS],
        index=sex_idx,
        key="dlg_sex_input",
    )
    sex = next((k for k, lbl in SEX_OPTIONS if lbl == sex_label), "")

    sport = st.text_input(
        "Sport / dyscyplina",
        value=existing.get("sport", ""),
        key="dlg_sport_input",
    )
    injury = st.text_area(
        "Urazy / kontuzje",
        value=existing.get("injury", ""),
        height=80,
        key="dlg_injury_input",
    )
    goals = st.text_area(
        "Cele treningowe",
        value=existing.get("goals", ""),
        height=80,
        key="dlg_goals_input",
    )
    notes = st.text_area(
        "Dodatkowe notatki",
        value=existing.get("notes", ""),
        height=70,
        key="dlg_notes_input",
    )

    # ── Usuwanie testów per typ + per dzień (tylko w edycji) ──
    if is_edit:
        type_counts = get_athlete_test_type_counts(prefill_name)
        if type_counts:
            st.markdown("---")
            st.caption("**Testy w bazie** — usuń całą historię typu albo pojedynczy dzień testowy:")
            for ttype in sorted(type_counts.keys()):
                n = type_counts[ttype]
                label = TEST_LABELS.get(ttype, ttype)
                confirm_key = f"confirm_del_tests_{prefill_name}_{ttype}"
                row = st.container()
                with row:
                    cols = st.columns([4, 2])
                    cols[0].markdown(f"**{label}** · {n} rep'ów łącznie")
                    if st.session_state.get(confirm_key):
                        if cols[1].button(
                            f"✅ Potwierdź usuń ({n})",
                            use_container_width=True,
                            type="primary",
                            key=f"btn_confirm_del_{ttype}",
                        ):
                            removed = delete_athlete_test_type(prefill_name, ttype)
                            st.session_state.pop(confirm_key, None)
                            for k in ("data", "data_max", "data_avg"):
                                st.session_state.pop(k, None)
                            st.success(f"Usunięto {removed} rep'ów {ttype}")
                            st.rerun()
                    else:
                        if cols[1].button(
                            "🗑️ Usuń wszystko",
                            use_container_width=True,
                            key=f"btn_del_{ttype}",
                            help=f"Usuń całą historię {ttype} ({n} rep'ów) z bazy",
                        ):
                            st.session_state[confirm_key] = True
                            st.rerun()

                # Per-day expander — wybierz konkretny dzień do usunięcia
                days = get_athlete_test_days(prefill_name, ttype)
                if days:
                    with st.expander(
                        f"📅 Usuń pojedynczy dzień ({len(days)} sesji)",
                        expanded=False,
                    ):
                        for day_str, day_n in days:
                            day_confirm_key = (
                                f"confirm_del_day_{prefill_name}_{ttype}_{day_str}"
                            )
                            day_cols = st.columns([4, 2])
                            day_cols[0].markdown(
                                f"📅 **{day_str}** · {day_n} rep"
                                f"{'a' if day_n in (2,3,4) else 'ów' if day_n != 1 else ''}"
                            )
                            if st.session_state.get(day_confirm_key):
                                if day_cols[1].button(
                                    f"✅ Potwierdź ({day_n})",
                                    use_container_width=True,
                                    type="primary",
                                    key=f"btn_confirm_del_day_{ttype}_{day_str}",
                                ):
                                    removed = delete_athlete_test_day(
                                        prefill_name, ttype, day_str,
                                    )
                                    st.session_state.pop(day_confirm_key, None)
                                    for k in ("data", "data_max", "data_avg"):
                                        st.session_state.pop(k, None)
                                    st.success(
                                        f"Usunięto sesję {ttype} z {day_str} "
                                        f"({removed} rep'ów)"
                                    )
                                    st.rerun()
                            else:
                                if day_cols[1].button(
                                    "🗑️",
                                    use_container_width=True,
                                    key=f"btn_del_day_{ttype}_{day_str}",
                                    help=f"Usuń sesję {ttype} z {day_str} ({day_n} rep'ów)",
                                ):
                                    st.session_state[day_confirm_key] = True
                                    st.rerun()
            st.markdown("---")

    col_save, col_cancel = st.columns([1, 1])
    if col_save.button("💾 Zapisz", type="primary", use_container_width=True,
                       key="dlg_save_btn"):
        new_name = " ".join(name.split())
        if not new_name:
            st.error("Imię i nazwisko jest wymagane")
            return

        if not sex:
            st.error("Wybór płci jest wymagany.")
            return

        old_name = " ".join(prefill_name.split()) if prefill_name else ""
        is_rename = is_edit and old_name and new_name != old_name

        if is_rename:
            # Kolizja z istniejącym zawodnikiem — nie scalamy automatycznie
            existing_athletes = {a["name"] for a in get_athletes_summary()}
            existing_athletes |= set(list_profile_names())
            if new_name in existing_athletes:
                st.error(
                    f"⚠️ Zawodnik **{new_name}** już istnieje w bazie. "
                    "Najpierw usuń tamten albo wybierz inne imię."
                )
                return
            # Przepnij testy + profil pod nową nazwę
            n_moved = rename_athlete(old_name, new_name)
            rename_profile(old_name, new_name)
            # KRYTYCZNE: usuń stary per-athlete CSV (Name=old wbity w każdy wiersz).
            # Bez tego przy następnym refreshu _do_auto_import_csv wczytuje WSZYSTKIE
            # *.csv — stary plik (old) + nowy (new) mają różny Name dla tych samych
            # TestId → dedupe ich nie scala → zawodnik "zmartwychwstaje" pod starą
            # nazwą i rename się cofa. (delete robi to samo przez _delete_athlete_csv.)
            _delete_athlete_csv(old_name)
            # Zsynchronizuj selektor sidebaru (żeby selectbox nie wrócił do
            # "— wybierz zawodnika —" po rerunie)
            if st.session_state.get("loaded_from_library") == old_name:
                st.session_state["loaded_from_library"] = new_name
                st.session_state["library_picker"] = new_name
                # Przeładuj świeże dane z biblioteki — bez tego banner i kafelki
                # pokazują DataFrame z poprzedniego renderu (stara nazwa w kol. Name).
                fresh = get_athlete_data(new_name)
                st.session_state["data"] = (
                    fresh if fresh is not None and not fresh.empty else None
                )
                # Surowe MAX/AVG z poprzedniego uploadu już nie pasują —
                # zawierają starą nazwę i sprawiłyby błąd w tabeli porównawczej.
                st.session_state["data_max"] = None
                st.session_state["data_avg"] = None

        save_profile(
            new_name,
            sport=sport, injury=injury, goals=goals, notes=notes, sex=sex,
        )
        st.session_state["profile_just_saved"] = new_name
        # Dla NOWEGO zawodnika (nie edycji) — flaga do auto-pivotu po rerunie,
        # żeby pobrać jego historyczne testy z VALD CSV bez klikania Quick refresh.
        if not is_edit and _VALD_API_ROOT.exists():
            st.session_state["_pending_pivot_for"] = new_name
        st.rerun()
    if col_cancel.button("Anuluj", use_container_width=True, key="dlg_cancel_btn"):
        st.rerun()


_APH_LOGO_HTML = """
<div class='aph-logo-bar'>
  <div class='aph-logo'>
    <div class='aph-mark-frame'>
      <svg viewBox='0 0 200 200' aria-label='Athletic Performance Hub'>
        <defs>
          <clipPath id='aph-aclip'>
            <polygon points='100,18 188,182 152,182 100,80 48,182 12,182' />
          </clipPath>
        </defs>
        <g clip-path='url(#aph-aclip)'>
          <rect x='0' y='0' width='200' height='200' fill='#F2EFE8' />
          <rect x='0' y='130' width='200' height='8' fill='#0E0E10' />
          <rect x='0' y='152' width='200' height='8' fill='#0E0E10' />
          <rect x='0' y='174' width='200' height='8' fill='#0E0E10' />
          <rect x='0' y='141' width='200' height='5' fill='#B54A32' />
        </g>
      </svg>
    </div>
    <div class='aph-wordmark'>
      <div class='aph-word-1'>Athletic</div>
      <div class='aph-word-2'>Performance Hub</div>
    </div>
  </div>
</div>
"""


# ─────────────────────────────────────────────────────────────────────────────
# Auto-refresh VALD API — raz w tygodniu, w tle (bez klikania)
# ─────────────────────────────────────────────────────────────────────────────

_AUTO_REFRESH_MAX_AGE_DAYS = 7
_AUTO_REFRESH_CHECK_EVERY_S = 6 * 3600   # sprawdzaj wiek pulla co 6 h
_AUTO_REFRESH_LOG = Path.home() / "Library" / "Logs" / "athletelab-autorefresh.log"


def _auto_refresh_loop() -> None:
    """Pętla daemona: gdy ostatni pull starszy niż tydzień → Quick refresh.
    Pierwszy check od razu po starcie serwera (świeże dane po reboocie),
    potem co 6 h. Lock w _run_vald_api_refresh chroni przed kolizją
    z ręcznym przyciskiem."""
    while True:
        try:
            if _VALD_API_ROOT.exists():
                last = _last_api_pull_at()
                stale = (
                    last is None
                    or (pd.Timestamp.now() - last)
                    > pd.Timedelta(days=_AUTO_REFRESH_MAX_AGE_DAYS)
                )
                if stale:
                    ok, log = _run_vald_api_refresh(full=False)
                    try:
                        with open(_AUTO_REFRESH_LOG, "a", encoding="utf-8") as f:
                            f.write(
                                f"\n===== auto-refresh {pd.Timestamp.now():%Y-%m-%d %H:%M:%S} "
                                f"ok={ok} =====\n{log}\n"
                            )
                    except OSError:
                        pass
        except Exception:
            # Daemon nie może położyć appki — każdy błąd tylko logujemy pętlą dalej
            pass
        time.sleep(_AUTO_REFRESH_CHECK_EVERY_S)


@st.cache_resource
def _start_auto_refresh_daemon() -> bool:
    """Jeden wątek per proces serwera (cache_resource = singleton).
    APH_DISABLE_AUTOREFRESH=1 wyłącza (testy, deployed bez R/API)."""
    if os.environ.get("APH_DISABLE_AUTOREFRESH"):
        return False
    t = threading.Thread(
        target=_auto_refresh_loop, daemon=True, name="aph-auto-refresh",
    )
    t.start()
    return True


def main() -> None:
    # Publiczny adres instancji gościa — bez hasła wszedłby każdy, kto zna
    # link (Streamlit Cloud: jedna zamknięta apka na konto). Bez sekretu
    # `haslo` ta funkcja zwraca True od razu, więc u Filipa nic się nie zmienia.
    from vald.brama import sprawdz_haslo
    if not sprawdz_haslo():
        return
    _start_auto_refresh_daemon()

    # Deep-link: ?athlete=Imię+Nazwisko otwiera profil od razu (np. link
    # wysłany treneowi / zakładka). Konsumowany raz — potem nawigacja normalna.
    qp_athlete = st.query_params.get("athlete")
    if qp_athlete and not st.session_state.get("_qp_athlete_consumed"):
        st.session_state["_qp_athlete_consumed"] = True
        st.session_state["_pending_athlete_open"] = " ".join(str(qp_athlete).split())
        try:
            del st.query_params["athlete"]
        except Exception:
            pass
    qp_mode = st.query_params.get("mode")
    if (qp_mode in ("training", "gym")
            and not st.session_state.get("_qp_mode_consumed")):
        st.session_state["_qp_mode_consumed"] = True
        st.session_state["app_mode"] = qp_mode
        try:
            del st.query_params["mode"]
        except Exception:
            pass

    # Sekretny link zawodnika: ?plan=<token> — TYLKO ten jeden plan
    qp_tok = st.query_params.get("plan")
    if qp_tok:
        st.session_state["_athlete_token"] = str(qp_tok)
        qp_ws = str(st.query_params.get("ws") or "").strip()
        if qp_ws:
            from vald import store as _vs
            _vs.set_workspace(qp_ws)
    if st.session_state.get("_athlete_token"):
        _render_athlete_mode(st.session_state["_athlete_token"])
        return

    # Tryb SIŁOWNIA (telefon): pełny ekran bez top baru i sidebara
    if st.session_state.get("app_mode") == "gym":
        _render_gym_mode()
        return
    qp_tab_main = str(st.query_params.get("tab") or "").upper()
    if qp_tab_main and not st.session_state.get("_qp_tab_consumed"):
        st.session_state["_qp_tab_consumed"] = True
        st.session_state["_pending_tab"] = qp_tab_main
        try:
            del st.query_params["tab"]
        except Exception:
            pass
    # Top bar: samo „⋯" — wyszukiwarka zawodników zdjęta (Filip
    # 2026-08-30: nieużywana, zajmowała pas na każdej stronie)
    # Pasek ⋯ (sync VALD) tylko w Performance testing — Training Plans
    # zaczyna się od razu tytułem (Filip 2026-09-01)
    _mode_top = st.session_state.get("app_mode", "home")
    # Start / Training Plans / Baza ćwiczeń: powłoka z paczki Claude Design
    # (views/app_shell) — jeden komponent rysuje sidebar i strony,
    # Python podaje dane i obsługuje akcje. Performance testing zostaje
    # w dotychczasowym widoku (Filip 2026-09-02).
    if _mode_top in ("home", "training", "exlib", "athletes"):
        from vald.shell import render_shell
        try:
            render_shell()
        except RuntimeError as e:
            # magazyn niedostępny (sieć/TLS/Supabase) — komunikat zamiast
            # ściany traceballa na ekranie trenera (Filip 2026-09-20)
            st.error(f"Nie mogę połączyć się z magazynem planów. {e}")
            st.caption("Sprawdź internet i kliknij Spróbuj ponownie. "
                       "Twoje dane są bezpieczne, nic nie zostało zapisane.")
            if st.button("Spróbuj ponownie", type="primary"):
                from vald import store as _s
                _s.invalidate()
                st.rerun()
        return
    # Performance testing: „← Start" po lewej paska (Filip 2026-09-02 —
    # powrót do menu bez sidebaru), „⋯" po prawej jak dotąd
    _back_col, _, util_col = (st.columns([0.9, 8.3, 0.7],
                                         vertical_alignment="center")
                              if _mode_top == "tests" else (None, None, None))
    if _back_col is not None:
        st.markdown(
            """<style>.stApp .st-key-pt_back_home button{
            min-height:34px!important;height:34px!important;padding:0 12px!important;
            border-radius:9px!important;border:1px solid var(--aph-line)!important;
            background:#fff!important;font-size:13px!important;font-weight:600!important;
            color:var(--aph-ink)!important}
            .stApp .st-key-pt_back_home button:hover{border-color:#a09c92!important;
            background:#f4f2ee!important}</style>""",
            unsafe_allow_html=True)
        if _back_col.button("← Start", key="pt_back_home",
                            help="Wróć do panelu głównego"):
            st.session_state["app_mode"] = "home"
            st.rerun()

    if util_col is not None:
        # Minimalizm (decyzja Filipa 2026-08-23): w pasku tylko „⋯" —
        # sync (z datą ostatniej synchronizacji), Full re-pull i log
        # siedzą w środku. Atrapa profilu „FK Filip K. ▾" usunięta
        # (nic nie robiła, zaśmiecała pasek).
        if _VALD_API_ROOT.exists():
            last_sync_dt = _last_api_pull_at()
            relative = (
                _humanize_since(last_sync_dt)
                if last_sync_dt is not None else "brak pulla"
            )
            with util_col.popover("⋯", use_container_width=False):
                st.caption(f"Ostatnia synchronizacja VALD: {relative}. "
                           f"Auto-sync działa co tydzień.")
                if st.button(
                    "⟳ Sync teraz",
                    key="btn_refresh_vald_api",
                    use_container_width=True,
                ):
                    with st.spinner("Sync z VALD API…"):
                        success, log = _run_vald_api_refresh(full=False)
                    st.session_state["_last_pull_log"] = log
                    if success:
                        st.toast("Sync OK — odśwież stronę (Cmd+R)", icon="✅")
                    else:
                        st.toast("Sync nieudany — zobacz log (⋯)", icon="❌")
                        st.session_state["_last_pull_failed"] = True
                if st.button(
                    "Full re-pull (historia, ~1–5 min)",
                    key="btn_full_sync_vald_api",
                    use_container_width=True,
                ):
                    with st.spinner("Full re-pull VALD… ~1–5 min."):
                        success, log = _run_vald_api_refresh(full=True)
                    st.session_state["_last_pull_log"] = log
                    if success:
                        st.toast("Full re-pull OK — odśwież (Cmd+R)", icon="✅")
                    else:
                        st.toast("Full re-pull nieudany", icon="❌")
                        st.session_state["_last_pull_failed"] = True
                if st.session_state.get("_last_pull_log"):
                    if st.button("Pokaż log ostatniego pulla",
                                 key="btn_show_pull_log",
                                 use_container_width=True):
                        _pull_log_dialog(st.session_state["_last_pull_log"])

    # Cienka szara linia separator między top bar a content — taka sama jak
    # border-bottom pod tabs CMJ/HOP. Daje wizualne oddzielenie strefy brand
    # od strefy content (hero + reszta).
    if _mode_top == "tests":
        st.markdown(
            '<hr class="aph-v2-topbar-divider"/>',
            unsafe_allow_html=True,
        )

    # ── Sidebar w stylu konsoli trenera: sekcje, pozycje z podtytułem,
    #    aktywna podświetlona obwódką (wzór: screeny AthleteHub, 2026-08-30;
    #    bez emotek — decyzja Filipa) ──────────────────────────────────────
    import vald.store as _store
    mode = st.session_state.setdefault("app_mode", "home")
    if mode == "tests" and _store.tylko_plany():
        mode = st.session_state["app_mode"] = "home"
    # Menu musi mieć te same pozycje co powłoka — inaczej po wejściu
    # w Performance testing znikają „Baza ćwiczeń" i „Podopieczni"
    # i nie da się do nich wrócić inaczej niż przez Start (Filip 2026-09-03).
    _trening = [("training", "Training Plans", "Plany, PDF, linki dla zawodników"),
                ("exlib", "Baza ćwiczeń", "Filmy i kategorie ćwiczeń")]
    if not _store.tylko_plany():
        _trening.append(("tests", "Performance testing", "Profile i wyniki testów"))
    _NAV = [("WORKSPACE", [("home", "Start", "Do rozpisania i szybki dostęp")]),
            ("TRENING", _trening),
            ("ZAWODNICY", [("athletes", "Podopieczni",
                            "Profile, plany i testy siły")])]
    with st.sidebar:
        st.markdown(
            "<div style='display:flex; align-items:center; gap:10px; "
            "margin:2px 0 10px;'>"
            "<div style='width:36px; height:36px; border-radius:10px; "
            "background:var(--aph-ink); color:#ffffff; "
            "font-family:var(--aph-display); font-size:19px; "
            "line-height:36px; text-align:center; "
            "flex:0 0 36px;'>A</div>"
            "<div style='font-family:var(--aph-display); font-size:13.5px; "
            "letter-spacing:0.01em; color:var(--aph-ink); "
            "line-height:1.25;'>Athletic<br/>Performance Hub</div>"
            "</div>",
            unsafe_allow_html=True,
        )
        st.markdown(
            """<style>
            [data-testid="stSidebar"] [class*="st-key-nav_"] button {
                justify-content: flex-start !important;
                align-items: flex-start !important;
                border: 1px solid transparent !important;
                background: transparent !important;
                box-shadow: none !important;
                padding: 10px 12px !important;
                border-radius: 12px !important;
                min-height: 56px;
            }
            [data-testid="stSidebar"] [class*="st-key-nav_"] button
                [data-testid="stMarkdownContainer"] { text-align: left; }
            [data-testid="stSidebar"] [class*="st-key-nav_"] button p {
                font-size: 12px !important; line-height: 1.35 !important;
                color: var(--aph-mute) !important; margin: 0 !important;
            }
            [data-testid="stSidebar"] [class*="st-key-nav_"] button strong {
                font-size: 14px; color: var(--aph-ink);
            }
            [data-testid="stSidebar"] [class*="st-key-nav_"] button:hover {
                border-color: var(--aph-line) !important;
                background: var(--aph-card) !important;
            }
            /* dwa glowne moduly (Filip 2026-09-01): pelne karty */
            [data-testid="stSidebar"] .st-key-nav_training button,
            [data-testid="stSidebar"] .st-key-nav_tests button {
                background: #fff !important;
                border: 1px solid #d8d5cc !important;
                box-shadow: 0 1px 2px rgba(28,27,24,.05) !important;
                min-height: 72px; padding: 14px 14px !important;
            }
            [data-testid="stSidebar"] .st-key-nav_training button strong,
            [data-testid="stSidebar"] .st-key-nav_tests button strong {
                font-size: 15.5px; font-weight: 800;
                letter-spacing: -0.01em;
            }
            [data-testid="stSidebar"] .st-key-nav_training button:hover,
            [data-testid="stSidebar"] .st-key-nav_tests button:hover {
                border-color: #a09c92 !important;
                transform: translateY(-1px);
            }
            /* Start = ta sama karta, tylko nizsza — bez niej wyglada jak
               martwy tekst i nie widac, ze wraca do panelu glownego
               (Filip 2026-09-02: „nie moge wejsc z powrotem do panelu") */
            [data-testid="stSidebar"] .st-key-nav_home button {
                background: #fff !important;
                border: 1px solid #d8d5cc !important;
                box-shadow: 0 1px 2px rgba(28,27,24,.05) !important;
                min-height: 60px; padding: 11px 14px !important;
            }
            [data-testid="stSidebar"] .st-key-nav_home button strong {
                font-size: 14.5px; font-weight: 800;
                letter-spacing: -0.01em;
            }
            [data-testid="stSidebar"] .st-key-nav_home button:hover {
                border-color: #a09c92 !important;
                transform: translateY(-1px);
            }
            </style>""",
            unsafe_allow_html=True,
        )
        _mode_nav = "training" if mode == "exlib" else mode
        st.markdown(
            f"<style>[data-testid='stSidebar'] .st-key-nav_{_mode_nav} button{{"
            f"border-color:var(--aph-accent)!important;"
            f"background:#EDF3FC!important;}}</style>",
            unsafe_allow_html=True,
        )
        for _sekcja, _pozycje in _NAV:
            st.markdown(
                f"<div style='font-family:var(--aph-text); font-size:10.5px;"
                f"font-weight:700; letter-spacing:0.08em; "
                f"text-transform:uppercase; color:var(--aph-mute); "
                f"margin:10px 0 2px;'>{_sekcja}</div>",
                unsafe_allow_html=True,
            )
            for _m, _tytul, _pod in _pozycje:
                if st.button(f"**{_tytul}**\n\n{_pod}", key=f"nav_{_m}",
                             use_container_width=True):
                    # klik w moduł wraca tam, gdzie w nim byłem (Filip
                    # 2026-09-05: „zostajesz w tym samym momencie") — otwarty
                    # plan zamyka dopiero „← Plany" na jego ekranie
                    st.session_state["app_mode"] = _m
                    st.rerun()

    # Jeśli ostatni pull się nie powiódł — pokaż dialog z logiem (zamiast
    # rozszerzonego st.expander który rozsuwał layout)
    if st.session_state.pop("_last_pull_failed", False):
        log = st.session_state.get("_last_pull_log", "(brak outputu)")
        _pull_log_dialog(log)

    # Otwarcie zawodnika z gridu empty_state — ustawiamy session_state przed renderem.
    if "_pending_athlete_open" in st.session_state:
        pending = st.session_state.pop("_pending_athlete_open")
        st.session_state["loaded_from_library"] = pending
        data = get_athlete_data(pending)
        st.session_state["data"] = (
            data if data is not None and not data.empty else None
        )

    # Toast po zapisie profilu (z dialogu dodawania/edycji)
    if "profile_just_saved" in st.session_state:
        saved_name = st.session_state.pop("profile_just_saved")
        st.success(f"✅ Profil **{saved_name}** zapisany")

    # Auto-pivot dla nowo dodanego zawodnika — pobiera jego historyczne testy
    # z VALD CSV bez ręcznego klikania Quick refresh.
    if "_pending_pivot_for" in st.session_state:
        pivot_name = st.session_state.pop("_pending_pivot_for")
        with st.spinner(
            f"Pobieram historyczne testy {pivot_name} z VALD ({pivot_name})…"
        ):
            success, log = _run_pivot_and_import()
        if success:
            # Po imporcie — od razu otwórz dashboard zawodnika
            st.session_state["_pending_athlete_open"] = pivot_name
            st.success(f"✅ Pobrałem testy {pivot_name}. Otwieram dashboard…")
            st.rerun()
        else:
            st.error(f"❌ Auto-import testów {pivot_name} nieudany.")
            with st.expander("Log", expanded=True):
                st.code(log or "(brak outputu)", language="text")

    df: pd.DataFrame | None = st.session_state.get("data")
    if df is None or df.empty:
        selected_name = st.session_state.get("loaded_from_library")
        if selected_name:
            _render_profile_only_state(selected_name)
        else:
            _show_empty_state()
        return

    _render(df)


def _render_profile_only_state(name: str) -> None:
    """Widok zawodnika który ma profil ale jeszcze nie ma testów.
    Spójny z głównym widokiem athlete — używa nowy hero (jak po dodaniu testów)."""
    # Hero z avatar/identity (taki sam jak dla zawodników z testami)
    _render_athlete_hero(name, df=None, athlete_col=None, splits=None)
    st.info(
        f"📤 **{name}** nie ma jeszcze wgranych testów. "
        "Kliknij **⟳ Sync** w górnym pasku (opcja Full re-pull pod ⋯), "
        "żeby pobrać profile + testy z VALD."
    )


_PER_ATHLETE_STATE_PREFIXES = (
    "selected_day_", "selected_series_", "selected_skok_",  # picker state per test type
    "asym_day_",  # stary asymmetry day picker (removed), prefix kept dla cleanup
    "asym_section_day_picker_",  # NEW: selectbox dnia w sekcji Asymmetry
    "confirm_del_top_", "confirm_delete_", "empty_confirm_del_",
    "confirm_del_hero_",  # 2-step delete w nowym hero (APH v2)
    "_profile_dialog_",  # NORMS dialog content cache
)

_PER_ATHLETE_STATE_KEYS = (
    "data", "loaded_from_library", "data_max", "data_avg",
    "uploaded_max", "uploaded_avg",
)


def _clear_per_athlete_state() -> None:
    """Usuń ze session_state wszystkie klucze powiązane z aktualnym zawodnikiem.
    Bez tego selectboxy w pickerze i confirmacje delete'a wyciekają między widokami."""
    prefixed = [
        k for k in list(st.session_state.keys())
        if k.startswith(_PER_ATHLETE_STATE_PREFIXES)
    ]
    for k in prefixed + list(_PER_ATHLETE_STATE_KEYS):
        st.session_state.pop(k, None)


def _delete_athlete_csv(name: str) -> None:
    """Usuń CSV zawodnika z ~/Desktop/vald-api/data/dashboard_csv/.
    Bez tego przy następnym auto-imporcie CSV wraca do library jako zombie.
    Nazwa pliku MUSI być sanitizowana TAK SAMO jak w api_to_dashboard.py
    (znaki spoza [alnum, spacja, -, _] → '_'), inaczej unlink mija plik dla
    imion z np. ':' lub '/'. Próbujemy też raw name (legacy pliki)."""
    csv_dir = _VALD_API_DATA_DIR / "dashboard_csv"
    if not csv_dir.exists():
        return
    safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in str(name))
    for fname in {f"{safe}.csv", f"{name}.csv"}:
        candidate = csv_dir / fname
        if candidate.exists():
            try:
                candidate.unlink()
            except OSError:
                pass


def _render_back_button() -> None:
    """← do gridu wszystkich zawodników. Kompaktowy, bez rozpychania banera."""
    if st.button("← Athletes", key="btn_back_to_grid",
                 help="Wróć do listy wszystkich zawodników"):
        _clear_per_athlete_state()
        st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# APH v2 — Hero atlety (Faza 2 redesign)
# ─────────────────────────────────────────────────────────────────────────────

_APH_AMARK_INLINE_SVG = """
<svg viewBox='0 0 200 200' width='28' height='28' aria-hidden='true'>
  <polygon points='100,18 188,182 152,182 100,80 48,182 12,182' fill='#F2EFE8'/>
  <rect x='56' y='128' width='88' height='14' fill='#0E0E10'/>
  <rect x='56' y='128' width='88' height='4' fill='#B54A32'/>
</svg>
"""


def _get_initials(name: str) -> str:
    """'Filip Dąbrowski' → 'FD'. Bezpieczne dla single-name i pustych."""
    parts = [p for p in (name or "").strip().split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def _athlete_activity_status(
    df: pd.DataFrame | None,
) -> tuple[str, int | None]:
    """Status atlety na podstawie dni od ostatniego testu.
    active: ≤14d, stale: 15-30d, overdue: >30d. Zwraca (status, days_since)."""
    if df is None or df.empty:
        return "unknown", None
    date_col = next((c for c in DATE_CANDIDATES if c in df.columns), None)
    if not date_col:
        return "unknown", None
    try:
        last = pd.to_datetime(df[date_col], errors="coerce").max()
        if pd.isna(last):
            return "unknown", None
        days = int((pd.Timestamp.now().normalize() - last.normalize()).days)
    except Exception:
        return "unknown", None
    if days <= 14:
        return "active", days
    if days <= 30:
        return "stale", days
    return "overdue", days


def _render_athlete_hero(
    name: str,
    df: pd.DataFrame | None,
    athlete_col: str | None = None,
    splits: dict | None = None,
) -> None:
    """Hero atlety w stylu mockupu (docs/design/cmj-mockup.png).
    Utility row (brand + breadcrumb + status) + hero row (back + avatar +
    identity + actions). Reużywa istniejących callbacków (back, edit, delete,
    norms). Brakujące pola profilu (age/height/weight/squad/code) pomija
    — pokażemy tylko to co mamy w danych."""
    profile = get_profile(name) or {}
    initials = _get_initials(name)
    sport = (profile.get("sport") or "").strip()
    status, days_since = _athlete_activity_status(df)
    status_label_map = {
        "active": "Active",
        "stale": f"Stale · {days_since}d" if days_since is not None else "Stale",
        "overdue": f"Overdue · {days_since}d" if days_since is not None else "Overdue",
        "unknown": "—",
    }
    status_label = status_label_map[status]
    status_class = "" if status == "active" else status

    # 🔴 Wrapper przez st.container(key=...) — NIE przez st.markdown('<div>').
    # Streamlit auto-domyka div z markdownu → karta hero miała zerową wysokość,
    # avatar/meta lewitowały bez ramy i stykały się z tabami (screenshot
    # 2026-07-03), a style .aph-v2-actions nigdy nie łapały przycisków.
    hero_box = st.container(key="aph_hero")
    with hero_box:
        # Hero row — Streamlit columns (back, avatar, identity, actions).
        # av_c celowo wąska (0.5) — avatar to 64px, większa waga zostawiała
        # zbyt dużą przerwę między ikonką z inicjałami a imieniem zawodnika.
        back_c, av_c, id_c, act_c = st.columns(
            [0.55, 0.5, 4.4, 1.7], vertical_alignment="center",
        )

    with back_c:
        _render_back_button()

    with av_c:
        dot_class = "" if status == "active" else status_class
        # Avatar z subtle A-mark watermark w tle (mockup style)
        st.markdown(
            f"""
            <div class="aph-v2-avatar">
              <svg class="aph-v2-avatar-mark" viewBox='0 0 200 200' aria-hidden='true'>
                <defs>
                  <clipPath id='av-a-{initials}'>
                    <polygon points='100,18 188,182 152,182 100,80 48,182 12,182' />
                  </clipPath>
                </defs>
                <g clip-path='url(#av-a-{initials})'>
                  <rect x='0' y='0' width='200' height='200' fill='#F2EFE8'/>
                  <rect x='0' y='130' width='200' height='8' fill='#0E0E10'/>
                  <rect x='0' y='152' width='200' height='8' fill='#0E0E10'/>
                  <rect x='0' y='174' width='200' height='8' fill='#0E0E10'/>
                  <rect x='0' y='141' width='200' height='5' fill='#B54A32'/>
                </g>
              </svg>
              <span class="aph-v2-avatar-initials">{initials}</span>
              <span class="aph-v2-avatar-dot {dot_class}"></span>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with id_c:
        meta_items: list[tuple[str, str]] = []
        if sport:
            meta_items.append(("Sport", sport))
        # Opcjonalne pola z profile — pokażemy gdy są
        age = profile.get("age")
        height_cm = profile.get("height_cm") or profile.get("height")
        weight_kg = profile.get("weight_kg") or profile.get("weight")
        if age:
            meta_items.append(("Age", str(age)))
        if height_cm:
            meta_items.append(("Height", f"{height_cm} cm"))
        if weight_kg:
            meta_items.append(("Weight", f"{weight_kg} kg"))
        meta_html = "".join(
            f"""
            <div class="aph-v2-meta-item">
              <span class="aph-v2-meta-label">{k}</span>
              <span class="aph-v2-meta-value">{v}</span>
            </div>
            """
            for k, v in meta_items
        )
        st.markdown(
            f"""
            <div class="aph-v2-identity">
              <div class="aph-v2-name-row">
                <h1 class="aph-v2-name">{name}</h1>
                <span class="aph-v2-badge-active {status_class}">● {status_label}</span>
              </div>
              <div class="aph-v2-meta">{meta_html}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with act_c:
        # Pojedyncza pill "Edit" widoczna, Norms/Delete schowane do popovera
        # "⋯" (More) żeby hero był czysty. Kontener z key → działający scope
        # dla CSS akcji (stary wrapper-div markdown był auto-domykany = pusty).
        with st.container(key="aph_hero_actions"):
            edit_col, report_col, more_col = st.columns(
                [1.7, 1.9, 0.9], vertical_alignment="center",
            )
            with report_col:
                if st.button(
                    "📄 Raport", key=f"btn_report_hero_{name}",
                    use_container_width=True,
                    help="Generuj raport PDF — wybierz testy i metryki",
                ):
                    _report_dialog(name)
        with edit_col:
            if st.button(
                "✏ Edit", key=f"btn_edit_hero_{name}",
                use_container_width=True,
                help="Edytuj profil zawodnika",
            ):
                _athlete_profile_dialog(name)
        with more_col:
            # NORMS przeniesiony do session strip (per test tab). W popoverze
            # tylko realne akcje — placeholder '+ New session (wkrótce)' OUT.
            with st.popover("⋯", use_container_width=True, help="Więcej akcji"):
                _render_hero_delete_button(name)


def _inline_sparkline_svg(
    y_vals: list[float],
    color: str = "var(--aph-ink)",
    fill_alpha: float = 0.14,
    h: int = 40,
    dates: list | None = None,
    unit: str = "",
) -> str:
    """Inline SVG sparkline z gradient fill + halo na ostatnim punkcie.
    Per punkt invisible <circle> z <title> — daje native browser tooltip
    z datą i wartością na hover.
    Format: viewBox 0 0 200 h, preserveAspectRatio='none' żeby rozciągał się
    na pełną szerokość kontenera."""
    if not y_vals or len(y_vals) < 2:
        msg = "—" if not y_vals else "1 sesja"
        return (
            f"<div style='height:{h}px; font-family:var(--aph-mono); "
            f"font-size:10px; color:var(--aph-mute); display:grid; "
            f"place-items:center; letter-spacing:.12em;'>{msg}</div>"
        )
    import secrets
    w = 200
    n = len(y_vals)
    step = w / (n - 1)
    y_min, y_max = min(y_vals), max(y_vals)
    rng = (y_max - y_min) or 1.0
    pts = [
        (i * step, h - ((y - y_min) / rng) * (h - 8) - 4)
        for i, y in enumerate(y_vals)
    ]
    d_line = " ".join(
        ("M" if i == 0 else "L") + f" {x:.1f} {y:.1f}"
        for i, (x, y) in enumerate(pts)
    )
    d_fill = (
        f"M 0 {h} "
        + " ".join(f"L {x:.1f} {y:.1f}" for x, y in pts)
        + f" L {w} {h} Z"
    )
    last_x, last_y = pts[-1]
    grad_id = f"sg{secrets.token_hex(4)}"

    # Per-point hover groups — każdy punkt to <g> z:
    #   - widoczna mała kropka (r=2, opacity 0.7)
    #   - hot-zone hit circle r=8 transparent (cursor:crosshair)
    #   - hover-highlight: większa kropka r=4 opacity=0 → 1 on hover
    #   - hover-value: <text> z wartością opacity=0 → 1 on hover
    #   - <title> fallback (native browser tooltip dla accessibility)
    # CSS hover handler w globalnym bloku APH v2 (.aph-spark-hover-group).
    hover_groups = []
    for i, (x, y) in enumerate(pts):
        raw_val = y_vals[i]
        v_str = _fmt_pl(raw_val, 2)
        date_str = ""
        if dates is not None and i < len(dates):
            try:
                date_str = dates[i].strftime("%d.%m")
            except Exception:
                date_str = ""
        full_unit_str = f"{v_str}{(' ' + unit) if unit else ''}".strip()
        title_str = (
            f"{dates[i].strftime('%Y-%m-%d')} · {full_unit_str}"
            if dates is not None and i < len(dates) and hasattr(dates[i], "strftime")
            else full_unit_str
        )

        # Pozycja tekstu: nad punktem gdy jest w dolnej połowie wykresu (więcej miejsca),
        # pod gdy w górnej. Edge cases dla x — anchor start/end żeby tekst nie wyciekał.
        text_y = y - 10 if y > h * 0.45 else y + 16
        if x < 28:
            anchor, text_x = "start", x
        elif x > w - 28:
            anchor, text_x = "end", x
        else:
            anchor, text_x = "middle", x

        # Stale-visible kropka (r=2 opacity 0.7) — zachowuje obecny look.
        # Ostatni punkt nie ma — ma halo niżej.
        static_dot = (
            f"<circle cx='{x:.1f}' cy='{y:.1f}' r='2' fill='{color}' opacity='0.7'/>"
            if i < len(pts) - 1 else ""
        )

        hover_groups.append(
            f"<g class='aph-spark-hover-group'>"
            f"{static_dot}"
            # Hot-zone (transparent, łapie hover)
            f"<circle cx='{x:.1f}' cy='{y:.1f}' r='10' "
            f"fill='transparent' class='aph-spark-hot'>"
            f"<title>{title_str}</title></circle>"
            # Hover highlight kropka (visible on parent hover)
            f"<circle cx='{x:.1f}' cy='{y:.1f}' r='4.5' fill='{color}' "
            f"class='aph-spark-hl' opacity='0'/>"
            # Hover value label (visible on parent hover)
            f"<text x='{text_x:.1f}' y='{text_y:.1f}' "
            f"text-anchor='{anchor}' class='aph-spark-val' opacity='0'>"
            f"{full_unit_str}</text>"
            # Date subtitle (drugi line pod value)
            f"<text x='{text_x:.1f}' y='{text_y + (12 if y < h * 0.45 else -12):.1f}' "
            f"text-anchor='{anchor}' class='aph-spark-date' opacity='0'>"
            f"{date_str}</text>"
            f"</g>"
        )
    hover_html = "".join(hover_groups)

    return (
        f"<svg viewBox='0 0 {w} {h}' width='100%' height='{h}' "
        f"preserveAspectRatio='none' style='overflow:visible; display:block;'>"
        f"<defs><linearGradient id='{grad_id}' x1='0' x2='0' y1='0' y2='1'>"
        f"<stop offset='0%' stop-color='{color}' stop-opacity='{fill_alpha}'/>"
        f"<stop offset='100%' stop-color='{color}' stop-opacity='0'/>"
        f"</linearGradient></defs>"
        f"<path d='{d_fill}' fill='url(#{grad_id})'/>"
        f"<path d='{d_line}' fill='none' stroke='{color}' stroke-width='1.5' "
        f"stroke-linecap='round' stroke-linejoin='round'/>"
        f"<circle cx='{last_x:.1f}' cy='{last_y:.1f}' r='3.5' fill='{color}'/>"
        f"<circle cx='{last_x:.1f}' cy='{last_y:.1f}' r='6' fill='none' "
        f"stroke='{color}' stroke-opacity='0.25'/>"
        f"{hover_html}"
        f"</svg>"
    )


def _fmt_pl(v: float, max_decimals: int = 1) -> str:
    """Format liczb dla wartości w kartach: stripped trailing zeros + PL przecinek.
    Default = 1 cyfra po przecinku (Filip: w CMJ key metrics 2 cyfry urywały
    'cm' i robiły layout glitch, plus mniej szumu wizualnego)."""
    if abs(v) >= 1000:
        return f"{v:.0f}"
    s = f"{v:.{max_decimals}f}".rstrip("0").rstrip(".")
    return s.replace(".", ",")


def _auto_decimals(v: float) -> int:
    """Liczba miejsc po przecinku dobrana do rzędu wielkości metryki.

    Chroni MAŁE metryki (RSI-mod ~0,5 m/s, ratio ×BW, prędkości) przed
    zawyżeniem z zaokrąglenia do 1 cyfry — np. RSI-mod 0,77 → "0,8" to +4%,
    a 0,073 → "0,1" to aż +37%. Duże metryki (Jump Height, moc, czasy w ms)
    zostają na 1 cyfrze, żeby nie psuć layoutu kafelków (skrót wartości
    + jednostka muszą zmieścić się w jednej linii)."""
    if pd.isna(v):
        return 1
    a = abs(v)
    if a >= 10:
        return 1
    return 2


def _render_hero_delete_button(name: str) -> None:
    """2-step delete dla atlety w hero. Wyodrębnione żeby logika nie duplikowała się."""
    confirm_key = f"confirm_del_hero_{name}"
    if st.session_state.get(confirm_key):
        if st.button(
            "✓ Tak", key=f"btn_del_confirm_hero_{name}",
            use_container_width=True, type="primary",
        ):
            delete_athlete(name)
            delete_profile(name)
            _delete_athlete_csv(name)
            _clear_per_athlete_state()
            st.rerun()
    else:
        if st.button(
            "🗑 Delete", key=f"btn_del_hero_{name}",
            use_container_width=True,
            help="Usuń zawodnika (kliknij 2× aby potwierdzić)",
        ):
            st.session_state[confirm_key] = True
            st.rerun()


def _two_line_name(name: str) -> str:
    """Imię w 1. linii, reszta (nazwisko) w 2. — by długie nazwiska nie psuły
    layoutu kafelka. Zwraca html-escaped string z '\\n' (CSS white-space:pre-line)."""
    import html as _html
    parts = str(name).split()
    if len(parts) <= 1:
        return _html.escape(str(name))
    return _html.escape(parts[0]) + "\n" + _html.escape(" ".join(parts[1:]))


def _show_empty_state() -> None:
    """Główny ekran startowy — grid kafelków zawodników z opcjami zarządzania."""
    # Performance testing to ekran WYNIKÓW: pokazuje wyłącznie osoby, które
    # mają choć jeden test na platformie (Filip 2026-09-02 — „nawet jak jeden
    # to jest ich profil i testy"). Profile bez testów żyją w Training Plans,
    # który jest główną kategorią strony.
    # Każdy trener widzi tylko swoich zawodników — tak jak w bazie planów
    # (Filip 2026-09-06). Profil bez znacznika trenera należy do Filipa:
    # to dane sprzed rozdzielenia paneli.
    from vald import coaches as _coaches_pt
    _akt_trener = _coaches_pt.current()
    all_athletes = [a for a in get_athletes_summary()
                    if int(a.get("n_tests") or 0) > 0
                    and (coach_of(a["name"]) or "filip") == _akt_trener]

    # Wyszukiwarka jest już w top bar (global search) — zostawiamy tylko
    # "Dodaj zawodnika" button po prawej + cienka linia separator (jak tabs).
    if not all_athletes:
        # rozróżniamy pustą bazę od „baza pełna, ale nie moi zawodnicy" —
        # inaczej drugi trener dostawał radę, żeby zsynchronizować VALD
        _sa_inni = any(int(a.get("n_tests") or 0) > 0
                       for a in get_athletes_summary())
        if _sa_inni:
            st.info(
                f"**{_coaches_pt.name(_akt_trener)}** nie ma jeszcze zawodników "
                "z testami. Przypisz ich do siebie w **Podopieczni** "
                "(Edycja → ✎ → panel trenera) albo dodaj nowego poniżej."
            )
        else:
            st.info(
                "Brak zawodników w bazie. Kliknij **⟳ Sync** w prawym "
                "górnym rogu, żeby pobrać dane z VALD (~30s), albo **➕ Dodaj zawodnika** "
                "poniżej żeby utworzyć profil ręcznie."
            )
        if st.button("Dodaj zawodnika", type="primary", key="empty_add_athlete_only"):
            _athlete_profile_dialog()
        return

    # Header row rostera. Sync API mieszka WYŁĄCZNIE w top barze ([⟳ Sync ·
    # X temu] + ⋯) — wcześniej roster miał trzeci przycisk 'Refresh API'
    # i osobny blok 'LAST API SYNC' (ta sama info w 3 miejscach).
    n_ath = len(all_athletes)
    manage_mode = st.session_state.get("roster_manage_mode", False)
    title_col, sp_col, manage_col, add_col = st.columns(
        [2.1, 3.7, 1.3, 1.6], vertical_alignment="center",
    )
    with title_col:
        # Podtytuł tylko w trybie Manage (instrukcja); normalnie sam tytuł —
        # 'tap a card to open' było oczywistym szumem.
        sub_html = ""      # bez instrukcji — przyciski mówią same za siebie
        st.markdown(
            f"<div class='aph-roster-title'>Athletes "
            f"<span class='aph-roster-count'>{n_ath}</span></div>{sub_html}",
            unsafe_allow_html=True,
        )
    with sp_col:
        pass
    with manage_col:
        if st.button(
            "✓ Gotowe" if manage_mode else "⚙ Manage",
            key="roster_manage_toggle", use_container_width=True,
            type="primary" if manage_mode else "secondary",
            help="Włącz/wyłącz tryb edycji i usuwania zawodników",
        ):
            st.session_state["roster_manage_mode"] = not manage_mode
            # Wyczyść ewentualne wiszące potwierdzenia usunięcia
            for k in [kk for kk in st.session_state
                      if kk.startswith("empty_confirm_del_")]:
                st.session_state.pop(k, None)
            st.rerun()
    with add_col:
        if st.button("+ Dodaj zawodnika", type="primary",
                     key="empty_add_athlete", use_container_width=True):
            _athlete_profile_dialog()

    st.markdown('<hr class="aph-v2-thin-divider"/>', unsafe_allow_html=True)

    # Grid 4 kolumny — bardziej zwarty layout (Filip preferuje mniejsze kafle)
    n_cols = 4
    for row_idx in range(-(-len(all_athletes) // n_cols)):
        cols = st.columns(n_cols)
        for c in range(n_cols):
            idx = row_idx * n_cols + c
            if idx >= len(all_athletes):
                continue
            a = all_athletes[idx]
            name = a["name"]
            with cols[c]:
                with st.container(border=True):
                    profile = get_profile(name)
                    sport = (profile or {}).get("sport", "")
                    initials = _get_initials(name)
                    if a.get("profile_only") and not sport:
                        sport_html = (
                            "<div class='aph-v2-athlete-tag pending'>"
                            "Profil bez testów</div>"
                        )
                    elif sport:
                        sport_html = (
                            f"<div class='aph-v2-athlete-sport'>"
                            f"<span class='aph-v2-sport-dot'></span>"
                            f"<span class='aph-v2-sport-text'>{sport}</span>"
                            f"</div>"
                        )
                    else:
                        sport_html = ""

                    st.markdown(
                        f"""
                        <div class='aph-v2-athlete-card-head'>
                          <div class='aph-v2-athlete-mini-avatar'>{initials}</div>
                          <div class='aph-v2-athlete-name'>{_two_line_name(name)}</div>
                        </div>
                        {sport_html}
                        """,
                        unsafe_allow_html=True,
                    )

                    # Jedno wejście per osoba: Testy. Rozpiski otwiera się
                    # z Training Plans, a nie stąd (Filip 2026-09-02).
                    # W trybie Manage: Edit + Delete jak dotąd.
                    if not manage_mode:
                        if st.button("Testy", key=f"open_{name}",
                                     use_container_width=True):
                            st.session_state["app_mode"] = "tests"
                            st.session_state["_pending_athlete_open"] = name
                            st.rerun()
                    else:
                        btn_edit, btn_del = st.columns(2)
                        if btn_edit.button("Edit", key=f"edit_{name}",
                                           use_container_width=True,
                                           help="Edytuj profil"):
                            _athlete_profile_dialog(name)

                        confirm_key = f"empty_confirm_del_{name}"
                        if st.session_state.get(confirm_key):
                            if btn_del.button("Confirm", key=f"del_yes_{name}",
                                              use_container_width=True,
                                              help="Potwierdź usunięcie",
                                              type="primary"):
                                delete_athlete(name)
                                delete_profile(name)
                                _delete_athlete_csv(name)
                                st.session_state.pop(confirm_key, None)
                                st.rerun()
                        else:
                            if btn_del.button("Delete", key=f"del_{name}",
                                              use_container_width=True,
                                              help="Usuń zawodnika (kliknij 2× żeby potwierdzić)"):
                                st.session_state[confirm_key] = True
                                st.rerun()


def _render(df: pd.DataFrame) -> None:
    athlete_col = find_column(df, ATHLETE_CANDIDATES)
    date_col = find_column(df, DATE_CANDIDATES)

    # Pojedynczy zawodnik na widok — bez sklejania/porównywania osób.
    # Jeśli wybrany jest profil z biblioteki, filtruj do niego;
    # w przeciwnym razie (np. świeży upload z >1 osobami) pokaż selectbox.
    if athlete_col and athlete_col in df.columns:
        all_names = sorted({
            " ".join(str(n).split())
            for n in df[athlete_col].dropna().astype(str).unique()
            if str(n).strip()
        })
        loaded_name = st.session_state.get("loaded_from_library")
        if loaded_name and loaded_name in all_names:
            chosen_athlete = loaded_name
        elif len(all_names) == 1:
            chosen_athlete = all_names[0]
        elif len(all_names) > 1:
            chosen_athlete = st.selectbox(
                "Zawodnik do podglądu",
                options=all_names,
                key="athlete_focus",
                help="Każdą osobę oglądamy osobno — wybierz kogo pokazać.",
            )
        else:
            chosen_athlete = None
        if chosen_athlete:
            mask = (
                df[athlete_col].astype(str).map(lambda s: " ".join(s.split()))
                == chosen_athlete
            )
            df = df[mask].reset_index(drop=True)

    splits = {k: v for k, v in detect_test_type_df(df).items() if not v.empty}
    if not splits:
        st.warning("Nie udało się rozpoznać typu testu.")
        st.dataframe(df.head(20), use_container_width=True)
        return

    loaded_name = st.session_state.get("loaded_from_library") or (
        " ".join(df[athlete_col].iloc[0].split())
        if athlete_col and athlete_col in df.columns and not df.empty
        else ""
    )
    _render_athlete_hero(
        loaded_name, df=df, athlete_col=athlete_col, splits=splits,
    )
    _render_data_status_banner()

    # Zakładki na pełną szerokość — NORMS już w górnym pasku (po prawej od banera).
    # Zawsze pokazujemy Overview + każdy typ testu jako tab — nawet gdy 1 typ.
    # Wcześniej dla 1 typu był surowy `st.markdown("#### CMJ — Counter Movement Jump")`
    # heading bez tabs — Filip raportował niespójność wizualną z widokiem 2+ typów.
    tab_keys = [k for k in ENABLED_TEST_TYPES if k in splits]

    # Mixed case labels (mockup style)
    _MIXED_TAB_LABEL = {"CMJ": "CMJ", "HOP": "10/5 Hop Test", "SJ": "SJ", "DJ": "Drop Jump", "IMTP": "IMTP", "RSAIP": "RSAIP", "RSKIP": "RSKIP"}

    if tab_keys:
        # 🚀 WŁASNE taby (przyciski) zamiast st.tabs — st.tabs renderuje
        # WSZYSTKIE panele przy każdym rerunie (Overview+7 testów naraz =
        # dziesiątki wykresów w tle → "apka zamula"). Teraz renderuje się
        # WYŁĄCZNIE aktywny widok. Bonus: deep-link ?tab= to zwykłe
        # ustawienie stanu, a stan taba przeżywa rerun po kliku w picker.
        entries: list[tuple[str, str]] = (
            [("Overview", "__overview__")]
            + [(_MIXED_TAB_LABEL.get(k, k), k) for k in tab_keys]
        )
        valid_keys = {k for _, k in entries}

        # Deep-link ?tab= skonsumowany w main() → _pending_tab (bez wyścigu
        # z rerunem otwierania atlety)
        pend = st.session_state.pop("_pending_tab", None)
        if pend in valid_keys or pend in tab_keys:
            st.session_state["active_test_tab"] = pend
        if st.session_state.get("active_test_tab") not in valid_keys:
            st.session_state["active_test_tab"] = "__overview__"
        active = st.session_state["active_test_tab"]

        # Pasek tabów + NORMS po prawej. Tabbar = kontener flex-row
        # (st.columns rozstrzelało taby na całą szerokość i łamało wiersz).
        tabs_col, norms_col = st.columns([6, 1], vertical_alignment="top")
        with norms_col:
            _render_norms_chip(splits, key_suffix="_global")
        with tabs_col:
            active_safe = "ov" if active == "__overview__" else active
            st.markdown(
                f"<style>.stApp .st-key-tabbtn_{active_safe} button{{"
                f"color:var(--aph-ink)!important; "
                f"box-shadow:inset 0 -3px 0 var(--aph-accent)!important;}}</style>",
                unsafe_allow_html=True,
            )
            with st.container(key="aph_tabbar"):
                for lbl, key in entries:
                    safe_key = "ov" if key == "__overview__" else key
                    if st.button(lbl, key=f"tabbtn_{safe_key}"):
                        st.session_state["active_test_tab"] = key
                        st.rerun()

        # Render TYLKO aktywnego widoku
        if active == "__overview__":
            _render_overview_tab(splits, date_col)
        else:
            _render_test_view(
                splits[active], active, athlete_col, date_col, splits=splits,
            )

        # Deep-link ?norms=1 — otwórz dialog NORMS od razu (audyt/screeny,
        # linki). Konsumowane raz.
        if (st.query_params.get("norms")
                and not st.session_state.get("_qp_norms_consumed")):
            st.session_state["_qp_norms_consumed"] = True
            try:
                del st.query_params["norms"]
            except Exception:
                pass
            test_keys_n = [
                t for t in ENABLED_TEST_TYPES
                if t in splits and not splits[t].empty
            ]
            if test_keys_n:
                has_eur = (
                    "CMJ" in splits and not splits["CMJ"].empty
                    and "SJ" in splits and not splits["SJ"].empty
                )
                sections = test_keys_n + (["EUR"] if has_eur else []) + ["DSI"]
                st.session_state["_profile_dialog_splits"] = splits
                _athlete_profile_view_dialog(sections)


# ─────────────────────────────────────────────────────────────────────────────
# Overview — skrót cross-test: personal bests + EUR
# ─────────────────────────────────────────────────────────────────────────────

def _render_overview_tab(
    splits: dict[str, pd.DataFrame], date_col: str | None = None,
) -> None:
    """Zakładka Overview — ogólny obraz zawodnika cross-test.
    Personal bests POGRUPOWANE per typ testu, każda metryka w bordered kafelku.
    Wartości brane z TEGO SAMEGO NAJLEPSZEGO SKOKU (max Jump Height / Best RSI),
    nie peak per metryka osobno — dzięki czemu liczby są spójne (z jednego skoku).

    Pod sekcjami: wskaźnik EUR (gdy zawodnik ma i CMJ i SJ)."""

    # ── Gęsty kokpit zamiast sekwencji wielkich trophy-kart ─────────────
    # 1 wiersz statystyk cross-test + grid kompaktowych kart per test
    # (primary liczba + 2-3 sekundarne z TEGO SAMEGO najlepszego repa).

    def _num_at(row: pd.Series, col: str) -> float:
        v = pd.to_numeric(pd.Series([row.get(col)]), errors="coerce").iloc[0]
        return float(v) if pd.notna(v) else float("nan")

    def _fmt(v: float, dec: int) -> str:
        return "—" if pd.isna(v) else f"{v:.{dec}f}".replace(".", ",")

    # ── Statystyki cross-test ────────────────────────────────────────────
    frames = [
        splits[tt] for tt in ENABLED_TEST_TYPES
        if tt in splits and not splits[tt].empty
    ]
    if not frames:
        st.info("Brak danych do podsumowania.")
        return
    all_rows = pd.concat(frames, ignore_index=True, sort=False)
    dts = pd.to_datetime(all_rows.get("Date"), errors="coerce").dropna()
    n_tests = (
        all_rows["TestId"].nunique() if "TestId" in all_rows.columns
        else len(all_rows)
    )
    n_days = dts.dt.date.nunique() if not dts.empty else 0
    if not dts.empty:
        span_d = max((dts.max() - dts.min()).days, 0)
        span_txt = f"{span_d} dni" if span_d < 62 else f"{span_d // 30} mies."
        last_dt = dts.max()
        ago = (pd.Timestamp.now() - last_dt).days
        last_txt = "dziś" if ago <= 0 else ("wczoraj" if ago == 1 else f"{ago} dni temu")
        last_sub = last_dt.strftime("%d %b %Y")
    else:
        span_txt, last_txt, last_sub = "—", "—", ""

    # Kolor świeżości ostatniego testu: zielony ≤7d, bursztyn ≤30d, czerwony dalej
    if not dts.empty:
        _ago_d = (pd.Timestamp.now() - dts.max()).days
        last_color = (
            "var(--aph-good)" if _ago_d <= 7
            else "#d97706" if _ago_d <= 30 else "var(--aph-bad)"
        )
    else:
        last_color = "var(--aph-mute)"

    stat_items = [
        ("Tests", f"{n_tests}", "", "var(--aph-ink)"),
        ("Test days", f"{n_days}", "", "var(--aph-ink)"),
        ("Span", span_txt, "", "var(--aph-ink)"),
        ("Last test", last_txt, last_sub, last_color),
    ]
    stats_html = "".join(
        f"<div style='flex:1; min-width:120px; background:var(--aph-tint); "
        f"border-radius:12px; padding:10px 14px;'>"
        f"<div style='font-family:var(--aph-text); font-size:10px; "
        f"font-weight:600; letter-spacing:0.06em; text-transform:uppercase; "
        f"color:var(--aph-mute);'>{lbl}</div>"
        f"<div style='font-family:var(--aph-display); font-size:21px; "
        f"color:{vcol}; margin-top:2px; letter-spacing:-0.01em;'>{val}</div>"
        + (f"<div style='font-family:var(--aph-text); font-size:10.5px; "
           f"color:var(--aph-mute);'>{sub}</div>" if sub else "")
        + "</div>"
        for lbl, val, sub, vcol in stat_items
    )
    st.markdown(
        f"<div style='display:flex; gap:10px; flex-wrap:wrap; "
        f"margin:2px 0 16px;'>{stats_html}</div>",
        unsafe_allow_html=True,
    )

    # ── Karta per test — build data ──────────────────────────────────────
    def _card_for(tt: str, sub: pd.DataFrame) -> dict | None:
        """primary (val, unit, label) + rows [(label, val)] + meta stopki.
        Wszystkie sekundarne z TEGO SAMEGO repa co primary (spójna kinematyka)."""
        d = sub.copy()
        d["_dt"] = pd.to_datetime(d.get("Date"), errors="coerce")
        n_days_t = d["_dt"].dt.date.nunique()

        def _best(col: str):
            vals = pd.to_numeric(d.get(col, pd.Series(dtype=float)), errors="coerce")
            if vals.isna().all():
                return None
            bi = vals.idxmax()
            return d.loc[bi], float(vals.loc[bi])

        card = {"tt": tt, "rows": [], "n_days": n_days_t, "date": ""}

        if tt in ("CMJ", "SJ"):
            hit = _best("Jump Height (Imp-Mom) [cm] ")
            if not hit:
                return None
            row, jh = hit
            card.update(pv=_fmt(jh, 1), pu="cm", pl="Jump Height")
            if tt == "CMJ":
                card["rows"] = [
                    ("RSI-mod", _fmt(_num_at(row, "RSI-modified (Imp-Mom)"), 2)),
                    ("Peak Power / BM", _fmt(_num_at(row, "Peak Power / BM [W/kg] "), 1) + " W/kg"),
                    ("Contraction Time", _fmt(_num_at(row, "Contraction Time [ms] "), 0) + " ms"),
                ]
            else:
                # SJ nie eksportuje 'Concentric Peak Power / BM' — moc względna
                # siedzi w 'Peak Power / BM [W/kg] ' (jak w CMJ).
                card["rows"] = [
                    ("Peak Power / BW", _fmt(_num_at(row, "Peak Power / BM [W/kg] "), 1) + " W/kg"),
                    ("Conc. Peak Force / BM", _fmt(_num_at(row, "Concentric Peak Force / BM"), 1) + " N/kg"),
                ]
        elif tt == "HOP":
            hit = _best("RSI (Flight/Contact Time)")
            if not hit:
                return None
            row, rsi = hit
            card.update(pv=_fmt(rsi, 2), pu="", pl="Best RSI")
            card["rows"] = [
                ("Jump Height @ best", _fmt(_num_at(row, "Jump Height (Flight Time)"), 1) + " cm"),
                ("Contact Time @ best", _fmt(_num_at(row, "Contact Time [ms] "), 0) + " ms"),
            ]
        elif tt == "DJ":
            groups = _dj_height_groups(d)
            best_overall = None
            for hv, gsub in groups:
                vals = pd.to_numeric(
                    gsub.get("RSI (Flight Time/Contact Time)", pd.Series(dtype=float)),
                    errors="coerce",
                )
                if vals.isna().all():
                    continue
                bi = vals.idxmax()
                item = (float(vals.loc[bi]), hv, gsub.loc[bi])
                if best_overall is None or item[0] > best_overall[0]:
                    best_overall = item
                card["rows"].append(
                    (f"Best RSI · drop {_dj_height_label(hv)}", _fmt(float(vals.loc[bi]), 2)),
                )
            if best_overall is None:
                return None
            rsi, hv, row = best_overall
            card.update(
                pv=_fmt(rsi, 2), pu="",
                pl=f"Best RSI · {_dj_height_label(hv)}",
            )
            # primary już pokazany — nie dubluj w rows gdy tylko 1 wysokość
            if len(card["rows"]) == 1:
                card["rows"] = [
                    ("Jump Height @ best", _fmt(_num_at(row, "Jump Height (Flight Time)"), 1) + " cm"),
                ]
        elif tt == "IMTP":
            hit = _best("Peak Vertical Force")
            if not hit:
                return None
            row, pf = hit
            card.update(pv=_fmt(pf, 0), pu="N", pl="Peak Force")
            card["rows"] = [
                ("Peak Force / BW", _fmt(_num_at(row, "Peak Vertical Force / BW"), 2) + " × BW"),
                ("Force @ 200ms / BM", _fmt(_num_at(row, "Force at 200ms / BM"), 1) + " N/kg"),
            ]
        elif tt in ("RSAIP", "RSKIP"):
            if "TrialLimb" not in d.columns:
                return None
            # Peak Force / BW (względna) zamiast absolutnych N — porównywalna
            # między zawodnikami i w czasie (Filip). Fallback na N gdy /BW brak.
            REL_COL, ABS_COL = "Peak Vertical Force / BW", "Peak Vertical Force"
            use_rel = REL_COL in d.columns and pd.to_numeric(
                d[REL_COL], errors="coerce",
            ).notna().any()
            col = REL_COL if use_rel else ABS_COL
            unit = "× BW" if use_rel else "N"
            dec = 2 if use_rel else 0
            side_best: dict[str, float] = {}
            for side in ("Left", "Right"):
                s = d[d["TrialLimb"] == side]
                vals = pd.to_numeric(s.get(col, pd.Series(dtype=float)), errors="coerce")
                if not vals.isna().all():
                    side_best[side] = float(vals.max())
            if not side_best:
                return None
            top_side = max(side_best, key=side_best.get)
            card.update(
                pv=_fmt(side_best[top_side], dec), pu=unit,
                pl=f"Peak Force / BW · {'L' if top_side == 'Left' else 'R'}"
                   if use_rel else
                   f"Peak Force · {'L' if top_side == 'Left' else 'R'}",
            )
            for side in ("Left", "Right"):
                if side in side_best:
                    card["rows"].append(
                        (f"Peak Force {'L' if side == 'Left' else 'R'}",
                         _fmt(side_best[side], dec) + f" {unit}"),
                    )
            if len(side_best) == 2:
                l, r = side_best["Left"], side_best["Right"]
                asym = (r - l) / max(l, r) * 100.0
                dom = "R" if asym > 0 else "L"
                card["rows"].append(("Asymmetry", f"{abs(asym):.1f}%".replace(".", ",") + f" {dom}"))
        else:
            return None

        # Data PB do stopki (z primary repa gdy dostępna)
        try:
            ts = pd.to_datetime(row.get("Date"), errors="coerce")
            if pd.notna(ts):
                card["date"] = ts.strftime("%d %b %Y")
        except Exception:
            pass
        return card

    cards: list[dict] = []
    for tt in ENABLED_TEST_TYPES:
        if tt in splits and not splits[tt].empty:
            c = _card_for(tt, splits[tt])
            if c:
                cards.append(c)

    if not cards:
        st.info("Brak danych do podsumowania.")
        return

    st.markdown(
        "<div style='font-family:var(--aph-display); font-size:20px; "
        "letter-spacing:-0.02em; color:var(--aph-ink); margin:0 0 10px;'>"
        "Personal bests</div>",
        unsafe_allow_html=True,
    )

    cards_html = []
    for c in cards:
        acc = TEST_ACCENT.get(c["tt"], "var(--aph-accent)")
        rows_html = "".join(
            f"<div style='display:flex; justify-content:space-between; "
            f"align-items:baseline; gap:8px; padding:4.5px 0; "
            f"border-top:1px solid var(--aph-line-2);'>"
            f"<span style='font-family:var(--aph-text); font-size:11.5px; "
            f"color:var(--aph-dim);'>{lbl}</span>"
            f"<span style='font-family:var(--aph-text); font-size:12.5px; "
            f"font-weight:700; color:var(--aph-ink); white-space:nowrap; "
            f"font-variant-numeric:tabular-nums;'>{val}</span>"
            f"</div>"
            # Wiersz bez danych ("— W/kg") = szum — pomijamy w całości
            for lbl, val in c["rows"] if not str(val).startswith("—")
        )
        foot_bits = []
        if c["date"]:
            foot_bits.append(c["date"])
        foot_bits.append(f"{c['n_days']} dni test.")
        cards_html.append(
            f"<div style='background:var(--aph-card); border:1px solid var(--aph-line); "
            f"border-top:3px solid {acc}; "
            f"border-radius:14px; padding:12px 14px; box-shadow:var(--aph-shadow); "
            f"display:flex; flex-direction:column;'>"
            f"<div style='display:flex; align-items:center; gap:7px;'>"
            f"<span style='width:8px; height:8px; border-radius:99px; "
            f"background:{acc}; display:inline-block; flex-shrink:0;'></span>"
            f"<span style='font-family:var(--aph-text); font-size:11px; "
            f"letter-spacing:0.08em; text-transform:uppercase; font-weight:700; "
            f"color:{acc};'>{c['tt']}</span></div>"
            f"<div style='margin:8px 0 2px;'>"
            f"<span style='font-family:var(--aph-display); font-size:32px; "
            f"color:var(--aph-ink); letter-spacing:-0.02em; line-height:1;'>{c['pv']}</span>"
            f"<span style='font-family:var(--aph-text); font-size:13px; font-weight:600; "
            f"color:{acc}; margin-left:5px;'>{c['pu']}</span></div>"
            f"<div style='font-family:var(--aph-text); font-size:11px; "
            f"color:var(--aph-dim); margin-bottom:8px;'>{c['pl']}</div>"
            f"<div>{rows_html}</div>"
            f"<div style='font-family:var(--aph-text); font-size:10.5px; "
            f"color:var(--aph-mute); margin-top:auto; padding-top:8px;'>"
            f"{' · '.join(foot_bits)}</div>"
            f"</div>"
        )
    st.markdown(
        f"<div style='display:grid; "
        f"grid-template-columns:repeat(auto-fill, minmax(235px, 1fr)); "
        f"gap:12px;'>{''.join(cards_html)}</div>",
        unsafe_allow_html=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Widok dla jednego typu testu — 4 zakładki (Perf/Strat/Asym/Tabela)
# ─────────────────────────────────────────────────────────────────────────────

def _render_test_view(
    sub: pd.DataFrame,
    test_type: str,
    athlete_col: str | None,
    date_col: str | None,
    *,
    splits: dict[str, pd.DataFrame] | None = None,
) -> None:
    if test_type == "UNKNOWN":
        st.warning("Nierozpoznany typ testu — surowe dane:")
        st.dataframe(sub, use_container_width=True)
        return

    # Wybór zawodnika obsłużony w _render — tu zawsze jedna osoba.
    if sub.empty:
        st.info("Brak danych po filtrze.")
        return

    # Parse dates (gdy są)
    has_dates = bool(date_col and date_col in sub.columns and sub[date_col].notna().any())
    if has_dates:
        sub = sub.copy()
        sub[date_col] = pd.to_datetime(sub[date_col], errors="coerce")
        sub = sub.dropna(subset=[date_col]).sort_values(date_col)

    # Lista sekcji — pokażemy WSZYSTKIE 3 (performance/strategy/asymmetry)
    # nawet gdy puste (placeholder "Nie dotyczy tego testu") żeby zachować
    # spójny layout strony między różnymi typami testów (CMJ/SJ/HOP).
    available: list[tuple[str, list[tuple[MetricDef, str]]]] = []
    for sec in ("performance", "strategy", "asymmetry"):
        resolved = resolve_metrics(sub, test_type, section=sec)
        available.append((sec, resolved))

    # Jeśli ŻADNA sekcja nie ma metryk — nie ma sensu pokazywać widoku.
    # Wyjątek: DJ, RSAIP, RSKIP mają puste METRICS z premedytacją (custom
    # rendering bez standardowych MetricDef'ów), więc pokazujemy widok tak czy inaczej.
    if test_type not in ("DJ", "RSAIP", "RSKIP") and not any(resolved for _, resolved in available):
        st.warning("Brak dopasowanych metryk dla tego testu.")
        return

    athletes_in_data = (
        sorted(sub[athlete_col].dropna().astype(str).unique().tolist())
        if athlete_col and athlete_col in sub.columns else []
    )
    single_athlete = len(athletes_in_data) == 1

    # Session pill (lewa) + stats row (prawa). NORMS button przeniesiony
    # WYŻEJ — na poziomie tabs row (jeden globalny, po prawej tabs).
    selected_row: pd.Series | None = None
    selected_day = None
    if has_dates and single_athlete:
        pick_col, stats_col = st.columns([1.4, 2.6], vertical_alignment="top")
        with stats_col:
            _render_summary_line(sub, athlete_col, date_col)
        # Slot na rozwinięty panel pickera — FULL WIDTH, W FLOW (push-down).
        # Wcześniej panel był absolute-overlayem w wąskiej kolumnie pilla
        # i ZAKRYWAŁ karty Key metrics (Filip: "jedno najeżdża na drugie").
        panel_slot = st.container(key=f"sp_panelslot_{test_type}")
        with pick_col:
            selected_row, selected_day = _render_trial_picker(
                sub, test_type, athlete_col, date_col, panel_slot=panel_slot,
            )
    else:
        # Brak dat / wielu zawodników → tylko summary line (bez session pickera)
        if has_dates:
            _render_summary_line(sub, athlete_col, date_col)
        if len(sub) > 0:
            selected_row = sub.iloc[-1]
            if has_dates:
                selected_day = sub[date_col].iloc[-1].date()

    # Notatka coacha do testu z danego dnia (klikalna ⚙️ ikonka)
    loaded_name = st.session_state.get("loaded_from_library") or (
        athletes_in_data[0] if athletes_in_data else None
    )
    _render_test_day_notes(loaded_name, selected_day, test_type)

    # Kluczowe kafelki — pokazują wartości z WYBRANEJ próby + delta vs poprzednia sesja
    if has_dates and selected_row is not None:
        _render_key_tiles_from_row(
            selected_row, sub, test_type, athlete_col, date_col, selected_day,
        )
        st.markdown("")

    # Single metric explorer (CMJ/SJ) — fullwidth chart z dowolną metryką z testu.
    # Toggle Best jump / Mean of top 3. Picker na stronie nadpisuje best dla
    # selected_day (w trybie Best jump).
    if has_dates and test_type in ("CMJ", "SJ"):
        _render_metric_explorer_tile(
            sub, test_type, date_col,
            selected_row=selected_row, selected_day=selected_day,
        )
        st.markdown("")

    # Sekcje "dalsze" pokazujemy TYLKO gdy test ma zdefiniowane metryki
    # w danej kategorii — puste expandery / "Nie dotyczy" to szum (Filip).
    has_perf_strat = any(
        resolved for sec, resolved in available if sec in ("performance", "strategy")
    )
    asym_resolved = next(
        (resolved for sec, resolved in available if sec == "asymmetry"), [],
    )

    # ── DEEP DIVE — jedna zgrupowana sekcja zamiast luźnych szarych pasków.
    # Kolejność wg wagi dla S&C: Asymmetry → All metrics → Comparison table.
    show_asym = test_type not in ("RSAIP", "RSKIP") and bool(asym_resolved)
    if show_asym or has_perf_strat:
        st.markdown(
            "<div style='display:flex; align-items:baseline; gap:10px; "
            "margin:22px 0 8px;'>"
            "<div style='font-family:var(--aph-display); font-size:20px; "
            "letter-spacing:-0.02em; color:var(--aph-ink);'>Deep dive</div>"
            "<div style='font-family:var(--aph-text); font-size:12px; "
            "color:var(--aph-mute);'>asymetrie · wszystkie metryki · tabela</div>"
            "</div>",
            unsafe_allow_html=True,
        )

    if show_asym:
        with st.expander("Asymmetry · left / right per faza", expanded=False):
            _render_section_grid(
                sub, "asymmetry", asym_resolved, athlete_col, date_col,
                has_dates=has_dates, test_type=test_type,
                selected_row=selected_row, selected_day=selected_day,
            )

    if has_dates and has_perf_strat:
        with st.expander("All metrics · trend overview", expanded=False):
            _render_key_metrics_timeline(sub, test_type, athlete_col, date_col)

    if has_perf_strat or show_asym:
        with st.expander("Comparison table · sesje obok siebie", expanded=False):
            _render_comparison_table(sub, test_type, athlete_col, date_col)


# ─────────────────────────────────────────────────────────────────────────────
# Notatki coacha do testu z konkretnego dnia (per athlete + day)
# ─────────────────────────────────────────────────────────────────────────────

@st.dialog("📝 Notatka do testu", width="medium")
def _test_note_dialog(athlete: str, day, test_type: str) -> None:
    """Modal do edycji notatki coacha dla testu z danego dnia.
    Pusta notatka po zapisie = usunięcie wpisu."""
    if not athlete or day is None:
        st.info("Najpierw wybierz zawodnika i dzień testowy.")
        return
    day_label = day.strftime("%Y-%m-%d") if hasattr(day, "strftime") else str(day)[:10]
    st.caption(
        f"**{athlete}** · {day_label}\n\n"
        "Notatka jest wspólna dla wszystkich typów testów z tego dnia."
    )
    existing = get_test_note(athlete, day)
    note = st.text_area(
        "Treść notatki",
        value=existing,
        height=180,
        key=f"dlg_test_note_{test_type}_{day_label}",
    )
    col_save, col_del, col_cancel = st.columns([2, 1, 1])
    if col_save.button("💾 Zapisz", type="primary", use_container_width=True,
                       key="dlg_test_note_save"):
        save_test_note(athlete, day, note)
        st.rerun()
    if existing and col_del.button("🗑️ Usuń",
                                    use_container_width=True,
                                    key="dlg_test_note_delete"):
        save_test_note(athlete, day, "")
        st.rerun()
    if col_cancel.button("Anuluj", use_container_width=True,
                         key="dlg_test_note_cancel"):
        st.rerun()


def _render_test_day_notes(athlete: str | None, day, test_type: str) -> None:
    """Pod pickerem dnia testowego — notatka coacha jako JEDEN klikalny
    przycisk (cały wiersz otwiera edycję). Wcześniej: tekst + samotna ikonka
    ⚙️ w osobnej kolumnie po prawej wyglądały jak dwa niepowiązane elementy."""
    if not athlete or day is None:
        return
    note = get_test_note(athlete, day)
    day_label = day.strftime("%Y-%m-%d") if hasattr(day, "strftime") else str(day)[:10]
    if note:
        snippet = note if len(note) <= 90 else note[:87] + "…"
        label = f"📝 {snippet}"
        help_txt = f"Kliknij, aby edytować notatkę do testu {day_label}"
    else:
        label = "📝 Dodaj notatkę do tego testu"
        help_txt = f"Notatka coacha do dnia {day_label}"
    if st.button(
        label,
        key=f"btn_test_note_{test_type}_{day_label}",
        help=help_txt,
    ):
        _test_note_dialog(athlete, day, test_type)


# ─────────────────────────────────────────────────────────────────────────────
# Day + Trial picker — pozwala wybrać sesję testową i konkretną próbę
# ─────────────────────────────────────────────────────────────────────────────

def _sp_click_row(inner_html: str, key: str) -> bool:
    """Klikalny wiersz session-pickera: bogaty (wyrównany) HTML + niewidzialny
    button-overlay rozciągnięty na cały wiersz. Zwraca True gdy kliknięto.
    CSS (.aph-sp-rowmark) robi z buttona przezroczysty overlay na kontenerze."""
    with st.container():
        st.markdown(
            f"<div class='aph-sp-rowwrap'>{inner_html}"
            f"<span class='aph-sp-rowmark'></span></div>",
            unsafe_allow_html=True,
        )
        return st.button(".", key=key, use_container_width=True)


def _render_trial_picker(
    sub: pd.DataFrame, test_type: str,
    athlete_col: str | None, date_col: str,
    panel_slot=None,
) -> tuple[pd.Series | None, object]:
    """Wybór dnia + serii + skoku. Domyślnie: ostatni dzień + najlepsza seria + peak skok.
    Pickery schowane w expanderze; label expandera = aktualna selekcja (minimalistyczne).
    Zwraca (selected_row, selected_day)."""
    s = sub.copy()
    s["_day"] = s[date_col].dt.date
    days_sorted = sorted(s["_day"].unique().tolist(), reverse=True)
    if not days_sorted:
        return None, None

    # ── Krok 1: rozwiąż wybrany DZIEŃ z session_state (lub default) ─────
    day_key = f"selected_day_{test_type}"
    if day_key not in st.session_state or st.session_state[day_key] not in days_sorted:
        st.session_state[day_key] = days_sorted[0]
    selected_day = st.session_state[day_key]

    def _day_label(d) -> str:
        # Czytelny format daty: "18 May 2026" + (opcjonalnie) skoki
        try:
            date_str = d.strftime("%-d %b %Y")
        except Exception:
            date_str = str(d)
        day_rows = s[s["_day"] == d]
        n_contacts = len(day_rows)
        contact_w = (
            "skok" if n_contacts == 1
            else "skoki" if 2 <= n_contacts <= 4
            else "skoków"
        )
        return f"{date_str}  ·  {n_contacts} {contact_w}"

    # ── Krok 2: dla tego dnia — rozwiąż wybraną SERIĘ ───────────────────
    day_trials = (
        s[s["_day"] == selected_day].sort_values(date_col).reset_index(drop=True)
    )
    if day_trials.empty:
        return None, selected_day

    cmj_metrics = METRICS_BY_TEST.get(test_type, [])
    # PRIMARY metric per test_type (CMJ:JH, SJ:JH, HOP:Best RSI, IMTP:Peak Force)
    # Test izometryczny IMTP NIE ma JH/RSI — bez PRIMARY_METRIC_LABEL default
    # spadłby na "pierwszy chronologicznie" (warm-up rep). Generic via primary label.
    primary_label = PRIMARY_METRIC_LABEL.get(test_type, "Jump Height")
    primary_def = next(
        (m for m in cmj_metrics if m.label == primary_label and not m.asymmetry),
        None,
    )
    primary_col = match_column(day_trials, primary_def) if primary_def else None
    # Fallback: dla testów bez PRIMARY w MetricDef — spróbuj JH/RSI
    if primary_col is None:
        jh_def = next((m for m in cmj_metrics if "jump height" in " ".join(m.keywords).lower()), None)
        mrsi_def = next((m for m in cmj_metrics if "rsi" in " ".join(m.keywords).lower()), None)
        jh_col = match_column(day_trials, jh_def) if jh_def else None
        mrsi_col = match_column(day_trials, mrsi_def) if mrsi_def else None
    else:
        jh_col = primary_col
        mrsi_col = None

    # Fallback 2: bezpośrednie szukanie kolumn gdy MetricDef lookup zwrócił None
    # (DJ_METRICS/RSAIP_METRICS/RSKIP_METRICS = [] → brak match przez MetricDef)
    # WAŻNE: pomijamy preagregowane kolumny "Best RSI..."/"Mean RSI..." (puste w
    # per-rep tabeli) — chcemy per-rep RSI, np. "RSI (Flight Time/Contact Time)".
    if jh_col is None and mrsi_col is None:
        for _c in day_trials.columns:
            _cl = _c.lower().strip()
            if ("rsi" in _cl and ":" not in _c and "asym" not in _cl
                    and " (l)" not in _cl and " (r)" not in _cl
                    and not _cl.startswith("best") and not _cl.startswith("mean")
                    and pd.to_numeric(day_trials[_c], errors="coerce").notna().any()):
                mrsi_col = _c
                break
        if mrsi_col is None:
            for _c in day_trials.columns:
                _cl = _c.lower().strip()
                if ("jump height" in _cl and "flight time" in _cl
                        and ":" not in _c and "asym" not in _cl
                        and "inches" not in _cl and " (l)" not in _cl and " (r)" not in _cl
                        and pd.to_numeric(day_trials[_c], errors="coerce").notna().any()):
                    jh_col = _c
                    break
        if jh_col is None and mrsi_col is None:
            # Peak force fallback (IMTP/RSAIP/RSKIP bez MetricDef)
            for _c in day_trials.columns:
                _cl = _c.lower().strip()
                if ("peak" in _cl and "force" in _cl and ":" not in _c
                        and "asym" not in _cl and "/ bw" not in _cl
                        and " (l)" not in _cl and " (r)" not in _cl
                        and not _cl.startswith("best")
                        and pd.to_numeric(day_trials[_c], errors="coerce").notna().any()):
                    jh_col = _c
                    break

    # RSI-mod do WYŚWIETLENIA w tabeli skoków pickera (kolumna obok Jump Height),
    # nawet gdy primary metric = Jump Height (CMJ). Nie zmienia logiki wyboru.
    if mrsi_col is None:
        rsi_def = next(
            (m for m in cmj_metrics
             if m.label == "RSI-mod" and not m.asymmetry), None,
        )
        if rsi_def is None:
            rsi_def = next(
                (m for m in cmj_metrics
                 if "rsi" in m.label.lower() and "mod" in m.label.lower()
                 and not m.asymmetry), None,
            )
        if rsi_def is not None:
            _rc = match_column(day_trials, rsi_def)
            if _rc and pd.to_numeric(day_trials[_rc], errors="coerce").notna().any():
                mrsi_col = _rc

    # ── HOP: test 10/5 — wybieramy SERIĘ (trial), nie pojedynczego hopa.
    # Best hop = max PER-HOP RSI (Flight Time), nie agregat "Best RSI" serii
    # (ten jest identyczny dla wszystkich hopów → picker pokazywał duplikaty).
    hop_series_pick = (test_type == "HOP")
    if hop_series_pick:
        def _per_hop_col(needles, exclude):
            for _c in day_trials.columns:
                _cl = _c.lower().strip()
                if (all(n in _cl for n in needles)
                        and not any(e in _cl for e in exclude)
                        and not _cl.startswith("best") and not _cl.startswith("mean")
                        and ":" not in _c
                        and pd.to_numeric(day_trials[_c], errors="coerce").notna().any()):
                    return _c
            return None
        _hop_rsi = _per_hop_col(
            ["rsi", "flight", "contact"], ["asym", "fatigue", " (l)", " (r)"],
        )
        _hop_jh = _per_hop_col(
            ["jump height", "flight time"],
            ["asym", "fatigue", "inches", "relative", "rfd", "force", "push",
             " (l)", " (r)"],
        )
        if _hop_rsi is not None:
            mrsi_col = _hop_rsi   # per-hop RSI (Flight Time) — kryterium best hopa
        if _hop_jh is not None:
            jh_col = _hop_jh      # per-hop Jump Height (Flight Time) — display

    series_col = "TestId" if "TestId" in day_trials.columns else None
    if series_col is None:
        day_trials["_series"] = day_trials.index.astype(str)
        series_col = "_series"

    series_starts = (
        day_trials.groupby(series_col)[date_col].min()
        .sort_values().to_dict()
    )
    series_ids = list(series_starts.keys())

    best_metric_col = jh_col if jh_col else mrsi_col
    if hop_series_pick and mrsi_col is not None:
        # HOP: best hop i best trial wg per-hop RSI (Flight Time), nie JH.
        best_metric_col = mrsi_col
    if best_metric_col is not None:
        peaks = (
            day_trials.groupby(series_col)[best_metric_col]
            .apply(lambda g: pd.to_numeric(g, errors="coerce").max())
        )
        default_series_id = (
            peaks.idxmax() if peaks.notna().any() else series_ids[0]
        )
    else:
        default_series_id = series_ids[0]

    series_key = f"selected_series_{test_type}_{selected_day.isoformat()}"
    if (series_key not in st.session_state
            or st.session_state[series_key] not in series_ids):
        st.session_state[series_key] = default_series_id
    chosen_series = st.session_state[series_key]

    def format_series(sid: str) -> str:
        grp = day_trials[day_trials[series_col] == sid]
        n = len(grp)
        skok_w = "skok" if n == 1 else "skoki" if 2 <= n <= 4 else "skoków"
        idx = series_ids.index(sid) + 1
        return f"seria {idx} ({n} {skok_w})"

    # ── Krok 3: dla tej serii — rozwiąż wybraną PRÓBĘ ───────────────────
    series_rows = day_trials[day_trials[series_col] == chosen_series].copy()
    series_rows = series_rows.sort_values(date_col).reset_index(drop=True)

    # Guard na SKOERCOWANEJ serii: raw .notna() przepuszcza object-dtype z
    # sentinelami ('-', 'x') → to_numeric je zeruje (NaN) → idxmax()=NaN →
    # int(NaN) rzuca ValueError. Coerce najpierw, potem sprawdź notna (jak w
    # series-level default i pozostałych fallbackach).
    prim_num = (
        pd.to_numeric(series_rows[best_metric_col], errors="coerce")
        if best_metric_col is not None else None
    )
    if prim_num is not None and prim_num.notna().any():
        default_skok_idx = int(prim_num.idxmax())
    else:
        default_skok_idx = 0

    skok_key = (
        f"selected_skok_{test_type}_{selected_day.isoformat()}_{chosen_series}"
    )
    if (skok_key not in st.session_state
            or st.session_state[skok_key] not in series_rows.index):
        st.session_state[skok_key] = default_skok_idx
    sel_skok_idx = st.session_state[skok_key]

    def format_skok(i: int) -> str:
        """Format: '#2 — 48,1 cm  🏆' (lub bez RSI dla SJ). Krótki, czytelny,
        cyfra próby zawsze widoczna na początku."""
        row = series_rows.loc[i]
        # Pozycja w serii (1-based) — używamy positional integer index w
        # `series_rows.index.get_loc` żeby zawsze pokazywać 1, 2, 3 ...
        try:
            pos = series_rows.index.get_loc(i) + 1
        except KeyError:
            pos = i + 1
        is_best = (i == default_skok_idx and len(series_rows) > 1)
        best_mark = "  🏆" if is_best else ""

        parts: list[str] = []
        if jh_col is not None:
            v = pd.to_numeric(row.get(jh_col), errors="coerce")
            if pd.notna(v):
                parts.append(f"{_fmt_metric(v, 1).replace('.', ',')} cm")
        if mrsi_col is not None:
            v = pd.to_numeric(row.get(mrsi_col), errors="coerce")
            if pd.notna(v):
                parts.append(f"RSI {_fmt_metric(v, 2).replace('.', ',')}")
        # DJ: wysokość spadania (Drop Height z VALD) — kluczowy kontekst,
        # RSI z 30 cm i 40 cm nieporównywalne.
        if test_type == "DJ":
            hv = pd.to_numeric(row.get(DJ_DROP_HEIGHT_COL), errors="coerce")
            if pd.notna(hv) and hv >= 5:
                parts.append(f"⬇{int(round(hv))} cm")
            elif pd.notna(hv):
                parts.append("⬇? cm")
        info = "  ·  ".join(parts)
        if info:
            return f"#{pos}  —  {info}{best_mark}"
        return f"#{pos}{best_mark}"

    # ── Krok 4: mockup-style label "11 May 2026 · 5 jumps · 14:02" ──
    day_rows = s[s["_day"] == selected_day]
    n_jumps_day = len(day_rows)
    if pd.api.types.is_datetime64_any_dtype(day_rows[date_col]) and not day_rows.empty:
        t_min = day_rows[date_col].min().strftime("%H:%M")
        time_str = t_min if t_min != "00:00" else ""
    else:
        time_str = ""
    _rep_word = "hop" if test_type == "HOP" else "jump"
    jump_word = _rep_word if n_jumps_day == 1 else _rep_word + "s"
    # English mixed case format zgodny z mockupem
    date_str = selected_day.strftime("%-d %b %Y") if hasattr(selected_day, "strftime") else str(selected_day)
    expander_label = f"{date_str}  ·  {n_jumps_day} {jump_word}"
    if time_str:
        expander_label += f"  ·  {time_str}"
    # DJ: wysokości spadania użyte w tym dniu (np. "⬇ 30/40 cm")
    if test_type == "DJ" and not day_rows.empty:
        hs = _dj_height_series(day_rows).dropna().unique()
        if len(hs):
            hs_txt = "/".join(str(int(x)) for x in sorted(hs))
            expander_label += f"  ·  ⬇ {hs_txt} cm"

    # jump #N (CMJ/SJ) lub trial #N (HOP — wybieramy serię 10/5, nie pojedynczy hop)
    if hop_series_pick:
        try:
            expander_label += f"  ·  trial #{series_ids.index(chosen_series) + 1}"
        except Exception:
            pass
    else:
        try:
            expander_label += f"  ·  jump #{series_rows.index.get_loc(sel_skok_idx) + 1}"
        except Exception:
            pass

    # ── Kontrolowany popover zamiast st.expander ─────────────────────────
    # st.expander nie da się zamknąć programowo → po kliknięciu skoku popover
    # WISIAŁ nad kartami Key metrics ("wszystko się rozjeżdża" — Filip).
    # Teraz: własny stan open/close; wybór skoku/Apply ZAMYKA panel.
    sel_day_iso = (
        selected_day.isoformat() if hasattr(selected_day, "isoformat")
        else str(selected_day)
    )
    open_key = f"sp_open_{test_type}"
    if (st.query_params.get("picker")
            and not st.session_state.get("_qp_picker_consumed")):
        st.session_state["_qp_picker_consumed"] = True
        st.session_state[open_key] = True
        try:
            del st.query_params["picker"]
        except Exception:
            pass
    is_open = bool(st.session_state.get(open_key, False))
    if st.button(
        ("▾" if is_open else "▸") + "  " + expander_label,
        key=f"sp_toggle_{test_type}",
        use_container_width=True,
        help="Wybór dnia testowego i głównego skoku",
    ):
        st.session_state[open_key] = not is_open
        st.rerun()
    if not is_open:
        selected_row = series_rows.loc[sel_skok_idx]
        return selected_row, selected_day
    # Panel w przekazanym slocie (full-width, w flow — spycha treść w dół,
    # niczego nie zakrywa). Fallback: inline, gdy caller nie dał slotu.
    _panel_box = panel_slot if panel_slot is not None else st.container()
    with _panel_box:
        # Dynamiczny highlight wybranego dnia + skoku (CSS w ukrytym kontenerze)
        st.markdown(
            f"<style>"
            f".st-key-sp_day_{test_type}_{sel_day_iso} button{{"
            f"background:var(--aph-card)!important;"
            f"border-left:3px solid var(--aph-accent)!important;}}"
            f".st-key-sp_jump_{test_type}_{sel_day_iso}_{sel_skok_idx} button{{"
            f"background:color-mix(in oklab,var(--aph-good) 10%,transparent)"
            f"!important; border-color:color-mix(in oklab,var(--aph-good) 45%,transparent)!important;}}"
            f".st-key-sp_trial_{test_type}_{sel_day_iso}_{chosen_series} button{{"
            f"background:color-mix(in oklab,var(--aph-good) 10%,transparent)"
            f"!important; border-color:color-mix(in oklab,var(--aph-good) 45%,transparent)!important;}}"
            f"</style>",
            unsafe_allow_html=True,
        )
        day_ui, jumps_ui = st.columns([1.05, 1.95], gap="medium")

        # ── LEWA kolumna: dni testowe (data + n·czas + BEST skoku dnia) ──
        # Wartość best per dzień: primary metrykę dnia (JH lub RSI) liczymy
        # z tych samych kolumn co picker — czysto informacyjnie w wierszu.
        best_val_col = jh_col if jh_col is not None else mrsi_col
        best_val_unit = "cm" if jh_col is not None else ""
        with day_ui:
            for d in days_sorted:
                drows = s[s["_day"] == d]
                nd = len(drows)
                try:
                    tmin = drows[date_col].min().strftime("%H:%M")
                    tmin = "" if tmin == "00:00" else tmin
                except Exception:
                    tmin = ""
                d_iso = d.isoformat() if hasattr(d, "isoformat") else str(d)
                d_date = (
                    d.strftime("%-d %b %Y") if hasattr(d, "strftime") else str(d)
                )
                is_sel = (d == selected_day)
                sub_txt = (
                    f"{nd} {_rep_word}s · {tmin}" if tmin else f"{nd} {_rep_word}s"
                )
                best_html = ""
                if best_val_col is not None:
                    bv = pd.to_numeric(drows.get(best_val_col), errors="coerce").max()
                    if pd.notna(bv):
                        bv_txt = _fmt_metric(bv, 1 if best_val_unit else 2).replace(".", ",")
                        best_html = (
                            f"<span class='aph-sp-day-best'>{bv_txt}"
                            + (f"<span class='u'> {best_val_unit}</span>"
                               if best_val_unit else "")
                            + "</span>"
                        )
                html = (
                    f"<div class='aph-sp-day{' sel' if is_sel else ''}'>"
                    f"<div class='aph-sp-day-main'>"
                    f"<div class='aph-sp-day-date'>{d_date}</div>"
                    f"<div class='aph-sp-day-sub'>{sub_txt}</div></div>{best_html}</div>"
                )
                if _sp_click_row(html, key=f"sp_day_{test_type}_{d_iso}"):
                    st.session_state[day_key] = d
                    st.rerun()

        # ── PRAWA kolumna: skoki/triale jako NATYWNE przyciski ──────────
        # Zero overlay-hacków (nakładały się na siebie), zero nagłówków
        # tabeli / stopki 'Main jump' / Apply — klik wybiera i zamyka.
        with jumps_ui:
            if hop_series_pick:
                for ti, sid in enumerate(series_ids, start=1):
                    srows = day_trials[day_trials[series_col] == sid]
                    nh = len(srows)
                    try:
                        st_t = srows[date_col].min().strftime("%H:%M")
                    except Exception:
                        st_t = ""
                    brsi_txt = "—"
                    if mrsi_col is not None:
                        brsi = pd.to_numeric(srows[mrsi_col], errors="coerce").max()
                        if pd.notna(brsi):
                            brsi_txt = _fmt_metric(brsi, 2).replace(".", ",")
                    is_sel_t = (sid == chosen_series)
                    star = "★" if is_sel_t else "☆"
                    lbl = f"{star}  Trial {ti} · {nh} hops · {st_t} · RSI {brsi_txt}"
                    if st.button(
                        lbl, key=f"sp_trial_{test_type}_{sel_day_iso}_{sid}",
                        use_container_width=True,
                    ):
                        st.session_state[series_key] = sid
                        st.session_state[open_key] = False   # wybór = zamknij
                        st.rerun()
            else:
                # Seria selector tylko gdy dzień ma >1 serię
                if len(series_ids) > 1:
                    sc = st.columns(len(series_ids))
                    for si, sid in enumerate(series_ids):
                        with sc[si]:
                            if st.button(
                                f"Seria {si + 1}",
                                key=f"sp_series_{test_type}_{sel_day_iso}_{sid}",
                                use_container_width=True,
                                type="primary" if sid == chosen_series else "secondary",
                            ):
                                st.session_state[series_key] = sid
                                st.rerun()
                def _row_num(row, col: str) -> float:
                    v = pd.to_numeric(pd.Series([row.get(col)]), errors="coerce").iloc[0]
                    return float(v) if pd.notna(v) else float("nan")

                def _trial_label(row, jpos: int, is_sel: bool) -> str:
                    """Wiersz próby per TYP TESTU — właściwa metryka i jednostka
                    (wcześniej wszystko szło szablonem CMJ: RSAIP pokazywał
                    Peak Force w N podpisany '… cm', RSI '—')."""
                    star = "★" if is_sel else "☆"
                    try:
                        t_txt = pd.to_datetime(row.get(date_col)).strftime("%H:%M")
                    except Exception:
                        t_txt = ""
                    parts: list[str] = []
                    if test_type in ("RSAIP", "RSKIP"):
                        side_raw = str(row.get("TrialLimb") or "")
                        side = "L" if side_raw.startswith("L") else (
                            "R" if side_raw.startswith("R") else "·")
                        pf = _row_num(row, "Peak Vertical Force")
                        parts = [side, f"PF {_fmt_metric(pf, 0)} N" if pd.notna(pf) else "PF —"]
                    elif test_type == "IMTP":
                        pf = _row_num(row, "Peak Vertical Force")
                        parts = [f"PF {_fmt_metric(pf, 0)} N" if pd.notna(pf) else "PF —"]
                    elif test_type == "DJ":
                        rsi_v = _row_num(row, mrsi_col) if mrsi_col else float("nan")
                        jh_v = _row_num(row, "Jump Height (Flight Time)")
                        hv = _row_num(row, DJ_DROP_HEIGHT_COL)
                        if pd.notna(rsi_v):
                            parts.append("RSI " + _fmt_metric(rsi_v, 2).replace(".", ","))
                        if pd.notna(hv) and hv >= 5:
                            parts.append(f"⬇{int(round(hv))} cm")
                        if pd.notna(jh_v):
                            parts.append(f"JH {_fmt_metric(jh_v, 1).replace('.', ',')} cm")
                    elif test_type == "SJ":
                        jh_v = _row_num(row, jh_col) if jh_col else float("nan")
                        pp_v = _row_num(row, "Peak Power / BM [W/kg] ")
                        if pd.notna(jh_v):
                            parts.append(_fmt_metric(jh_v, 1).replace(".", ",") + " cm")
                        if pd.notna(pp_v):
                            parts.append(f"PP {_fmt_metric(pp_v, 1).replace('.', ',')} W/kg")
                    else:  # CMJ — zostaje jak było (Filip: 'tam już mamy ładnie')
                        if jh_col is not None:
                            v = _row_num(row, jh_col)
                            if pd.notna(v):
                                parts.append(_fmt_metric(v, 2).replace(".", ",") + " cm")
                        if mrsi_col is not None:
                            rv = _row_num(row, mrsi_col)
                            if pd.notna(rv):
                                parts.append("RSI " + _fmt_metric(rv, 2).replace(".", ","))
                    if not parts:
                        parts = ["—"]
                    core = " · ".join(parts)
                    word = "Próba" if test_type in ("RSAIP", "RSKIP", "IMTP") else "Skok"
                    tail = f" · {t_txt}" if t_txt and test_type in ("RSAIP", "RSKIP", "IMTP") else ""
                    return f"{star}  {word} {jpos} · {core}{tail}"

                for jpos, jidx in enumerate(series_rows.index.tolist(), start=1):
                    row = series_rows.loc[jidx]
                    is_sel = (jidx == sel_skok_idx)
                    if st.button(
                        _trial_label(row, jpos, is_sel),
                        key=f"sp_jump_{test_type}_{sel_day_iso}_{jidx}",
                        use_container_width=True,
                    ):
                        st.session_state[skok_key] = jidx
                        st.session_state[open_key] = False   # wybór = zamknij
                        st.rerun()

        # ── Akcje usuwania: pojedyncza próba / cała seria / cały dzień ──
        # Resolve athlete name z sub (zawsze 1 osoba w widoku)
        athlete_name = None
        if athlete_col and athlete_col in sub.columns:
            names = sub[athlete_col].dropna().astype(str).unique()
            if len(names) >= 1:
                athlete_name = " ".join(str(names[0]).split())

        if athlete_name and selected_day is not None:
            day_iso = selected_day.strftime("%Y-%m-%d") if hasattr(selected_day, "strftime") else str(selected_day)
            day_rows_count = len(s[s["_day"] == selected_day])
            series_rows_count = len(series_rows)
            selected_row_for_del = series_rows.loc[sel_skok_idx]

            st.markdown(
                "<div style='border-top:1px solid var(--aph-line); "
                "margin-top:14px; padding-top:10px;'></div>",
                unsafe_allow_html=True,
            )
            st.markdown(
                "<div style='font-family:var(--aph-mono); font-size:10px; "
                "letter-spacing:0.14em; text-transform:uppercase; "
                "color:var(--aph-mute); margin-bottom:6px;'>"
                "🗑️ Usuwanie z bazy</div>",
                unsafe_allow_html=True,
            )

            # 3 przyciski obok siebie: próba | seria | dzień
            btn_cols = st.columns(3, gap="small")

            # ── 1. POJEDYNCZA PRÓBA ──────────────────────────────────────
            try:
                trial_ts = pd.to_datetime(
                    selected_row_for_del.get(date_col), errors="coerce",
                )
            except Exception:
                trial_ts = None
            if trial_ts is not None and not pd.isna(trial_ts):
                trial_iso = trial_ts.isoformat()
                trial_short = trial_ts.strftime("%H:%M:%S")
                trial_confirm_key = f"confirm_del_trial_{athlete_name}_{test_type}_{trial_iso}"
                with btn_cols[0]:
                    if st.session_state.get(trial_confirm_key):
                        if st.button(
                            f"✅ Usuń próbę {trial_short}",
                            use_container_width=True, type="primary",
                            key=f"btn_confirm_trial_del_{test_type}_{trial_iso}",
                        ):
                            # Identyfikacja repa po (TestId/TrialId/Rep/TrialLimb)
                            # — deterministyczne usunięcie JEDNEGO repa (kluczowe
                            # dla DJ, gdzie repy dzielą identyczny Date timestamp).
                            removed = delete_athlete_trial(
                                athlete_name, trial_iso,
                                test_id=selected_row_for_del.get("TestId"),
                                trial_id=selected_row_for_del.get("TrialId"),
                                rep=selected_row_for_del.get("Rep"),
                                trial_limb=selected_row_for_del.get("TrialLimb"),
                            )
                            st.session_state.pop(trial_confirm_key, None)
                            for k in ("data", "data_max", "data_avg"):
                                st.session_state.pop(k, None)
                            st.session_state.pop(skok_key, None)
                            st.toast(
                                f"Usunięto próbę {trial_short} ({removed})",
                                icon="🗑️",
                            )
                            st.rerun()
                    else:
                        if st.button(
                            f"🦵 Próba {trial_short}",
                            use_container_width=True,
                            key=f"btn_trial_del_{test_type}_{trial_iso}",
                            help=f"Usuń wybraną próbę {trial_short} z bazy",
                        ):
                            st.session_state[trial_confirm_key] = True
                            st.rerun()

            # ── 2. SERIA (TestId) ────────────────────────────────────────
            test_id_str = str(chosen_series) if chosen_series else None
            if test_id_str:
                series_confirm_key = f"confirm_del_series_{athlete_name}_{test_type}_{test_id_str}"
                series_idx_label = series_ids.index(chosen_series) + 1
                with btn_cols[1]:
                    if st.session_state.get(series_confirm_key):
                        if st.button(
                            f"✅ Usuń serię {series_idx_label} ({series_rows_count})",
                            use_container_width=True, type="primary",
                            key=f"btn_confirm_series_del_{test_type}_{test_id_str}",
                        ):
                            removed = delete_athlete_test_series(
                                athlete_name, test_id_str,
                            )
                            st.session_state.pop(series_confirm_key, None)
                            for k in ("data", "data_max", "data_avg"):
                                st.session_state.pop(k, None)
                            st.session_state.pop(series_key, None)
                            st.session_state.pop(skok_key, None)
                            st.toast(
                                f"Usunięto serię {series_idx_label} "
                                f"({removed} rep'ów)",
                                icon="🗑️",
                            )
                            st.rerun()
                    else:
                        if st.button(
                            f"🎯 Seria {series_idx_label} ({series_rows_count})",
                            use_container_width=True,
                            key=f"btn_series_del_{test_type}_{test_id_str}",
                            help=(
                                f"Usuń całą serię {series_idx_label} "
                                f"({series_rows_count} rep'ów) z bazy"
                            ),
                        ):
                            st.session_state[series_confirm_key] = True
                            st.rerun()

            # ── 3. CAŁY DZIEŃ ────────────────────────────────────────────
            day_confirm_key = f"confirm_del_session_{athlete_name}_{test_type}_{day_iso}"
            with btn_cols[2]:
                if st.session_state.get(day_confirm_key):
                    if st.button(
                        f"✅ Usuń dzień ({day_rows_count})",
                        use_container_width=True, type="primary",
                        key=f"btn_confirm_session_del_{test_type}_{day_iso}",
                    ):
                        removed = delete_athlete_test_day(
                            athlete_name, test_type, day_iso,
                        )
                        st.session_state.pop(day_confirm_key, None)
                        for k in ("data", "data_max", "data_avg"):
                            st.session_state.pop(k, None)
                        st.session_state.pop(day_key, None)
                        st.session_state.pop(series_key, None)
                        st.session_state.pop(skok_key, None)
                        st.toast(
                            f"Usunięto dzień {day_iso} ({removed} rep'ów)",
                            icon="🗑️",
                        )
                        st.rerun()
                else:
                    if st.button(
                        f"📅 Dzień ({day_rows_count})",
                        use_container_width=True,
                        key=f"btn_session_del_{test_type}_{day_iso}",
                        help=(
                            f"Usuń całą sesję {test_type} z {day_iso} "
                            f"({day_rows_count} rep'ów)"
                        ),
                    ):
                        st.session_state[day_confirm_key] = True
                        st.rerun()

            # Anuluj wszystkie pending confirms (jeden klik na "Anuluj")
            any_confirm = any(
                st.session_state.get(k) for k in (
                    f"confirm_del_trial_{athlete_name}_{test_type}_{trial_iso}"
                        if trial_ts is not None and not pd.isna(trial_ts) else None,
                    f"confirm_del_series_{athlete_name}_{test_type}_{test_id_str}"
                        if test_id_str else None,
                    f"confirm_del_session_{athlete_name}_{test_type}_{day_iso}",
                ) if k
            )
            if any_confirm:
                if st.button(
                    "✖ Anuluj usuwanie",
                    key=f"btn_cancel_all_del_{test_type}_{day_iso}",
                ):
                    for k in list(st.session_state.keys()):
                        if k.startswith(f"confirm_del_") and athlete_name in k:
                            st.session_state.pop(k, None)
                    st.rerun()

    selected_row = series_rows.loc[sel_skok_idx]
    return selected_row, selected_day


def _best_row_for_day(
    sub: pd.DataFrame, test_type: str, day, date_col: str | None,
) -> "pd.Series | None":
    """Najlepszy skok DANEGO DNIA (= max primary metric: CMJ JH, HOP RSI, SJ JH).
    Zwraca pojedynczy row z którego można wziąć WSZYSTKIE metryki — spójne
    wartości z jednego skoku, nie agregaty per metryka."""
    if day is None or not date_col or date_col not in sub.columns:
        return None
    if pd.api.types.is_datetime64_any_dtype(sub[date_col]):
        days = sub[date_col].dt.date
    else:
        days = pd.to_datetime(sub[date_col], errors="coerce").dt.date
    day_rows = sub[days == day]
    if day_rows.empty:
        return None
    primary_label = PRIMARY_METRIC_LABEL.get(test_type, "Jump Height")
    all_metrics = METRICS_BY_TEST.get(test_type, [])
    m_primary = next(
        (x for x in all_metrics
         if x.label == primary_label and not x.asymmetry),
        None,
    )
    if m_primary is None:
        return None
    col = match_column(day_rows, m_primary)
    if not col:
        return None
    vals = pd.to_numeric(day_rows[col], errors="coerce")
    if vals.isna().all():
        return None
    idx = vals.idxmax() if m_primary.higher_better else vals.idxmin()
    return day_rows.loc[idx]


def _top_n_rows_by_primary(
    sub: pd.DataFrame, test_type: str, day, date_col: str | None, n: int,
) -> "pd.DataFrame":
    """Top N skoków DANEGO DNIA wg primary metric (Jump Height dla CMJ/SJ,
    Best RSI dla HOP). Zwraca DataFrame z N rows (lub mniej jeśli day ma <N skoków).
    Te N rows dostarcza wartości dla mean top N — każda metryka brana
    z TYCH SAMYCH rows (top 3 najwyższych jumps), nie top 3 per metryka osobno."""
    if day is None or not date_col or date_col not in sub.columns:
        return pd.DataFrame()
    if pd.api.types.is_datetime64_any_dtype(sub[date_col]):
        days = sub[date_col].dt.date
    else:
        days = pd.to_datetime(sub[date_col], errors="coerce").dt.date
    day_rows = sub[days == day]
    if day_rows.empty:
        return pd.DataFrame()
    primary_label = PRIMARY_METRIC_LABEL.get(test_type, "Jump Height")
    all_metrics = METRICS_BY_TEST.get(test_type, [])
    m_primary = next(
        (x for x in all_metrics
         if x.label == primary_label and not x.asymmetry),
        None,
    )
    if m_primary is None:
        return pd.DataFrame()
    col = match_column(day_rows, m_primary)
    if not col:
        return pd.DataFrame()
    vals = pd.to_numeric(day_rows[col], errors="coerce")
    valid = day_rows.loc[vals.notna()].copy()
    if valid.empty:
        return pd.DataFrame()
    if m_primary.higher_better:
        top_idx = pd.to_numeric(valid[col], errors="coerce").nlargest(n).index
    else:
        top_idx = pd.to_numeric(valid[col], errors="coerce").nsmallest(n).index
    return valid.loc[top_idx]


def _signed_asym_mean_per_day(
    sub: pd.DataFrame, mcol: str, date_col: str | None,
) -> pd.Series:
    """Mean SIGNED asymetrii per dzień (bez abs() — żeby widać L/P direction).
    Używane dla asymmetry_bipolar_trend chart w expander trendów."""
    if not date_col or date_col not in sub.columns or mcol not in sub.columns:
        return pd.Series(dtype=float)
    d = sub[[date_col, mcol]].copy()
    d[mcol] = pd.to_numeric(d[mcol], errors="coerce")
    if pd.api.types.is_datetime64_any_dtype(d[date_col]):
        d["_day"] = d[date_col].dt.date
    else:
        d["_day"] = pd.to_datetime(d[date_col], errors="coerce").dt.date
    d = d.dropna(subset=["_day", mcol])
    if d.empty:
        return pd.Series(dtype=float)
    per_day = d.groupby("_day")[mcol].mean().sort_index()
    per_day.index = pd.to_datetime(per_day.index)
    return per_day


def _mean_value_in_rows(
    rows: pd.DataFrame, m: MetricDef, mcol: str,
) -> float:
    """Mean wartość metryki z given rows (abs() dla asymmetry magnitude)."""
    if rows.empty or mcol not in rows.columns:
        return float("nan")
    vals = pd.to_numeric(rows[mcol], errors="coerce")
    if m.asymmetry:
        vals = vals.abs()
    vals = vals.dropna()
    if vals.empty:
        return float("nan")
    return float(vals.mean())


def _series_best_jump_per_day(
    sub: pd.DataFrame, test_type: str, m: MetricDef, mcol: str,
    date_col: str | None,
) -> pd.Series:
    """Wartość metryki z BEST JUMP (max primary) per dzień testowy.
    Używane dla sparkline w Sekcji 1 (Selected jump) — pokazuje trend best skoku."""
    if not date_col or date_col not in sub.columns:
        return pd.Series(dtype=float)
    if pd.api.types.is_datetime64_any_dtype(sub[date_col]):
        days = sub[date_col].dt.date
    else:
        days = pd.to_datetime(sub[date_col], errors="coerce").dt.date
    unique_days = sorted(set(d for d in days.dropna()))
    result = {}
    for day in unique_days:
        best = _best_row_for_day(sub, test_type, day, date_col)
        if best is None:
            continue
        v = pd.to_numeric(best.get(mcol), errors="coerce")
        if pd.notna(v):
            result[day] = abs(float(v)) if m.asymmetry else float(v)
    if not result:
        return pd.Series(dtype=float)
    s = pd.Series(result)
    s.index = pd.to_datetime(s.index)
    return s


def _series_top_n_mean_per_day(
    sub: pd.DataFrame, test_type: str, m: MetricDef, mcol: str,
    date_col: str | None, n: int,
) -> pd.Series:
    """Mean wartość metryki z top N rows (by primary) per dzień.
    Używane dla sparkline w Sekcji 2 (Mean of top N) — trend mean top N day-over-day."""
    if not date_col or date_col not in sub.columns:
        return pd.Series(dtype=float)
    if pd.api.types.is_datetime64_any_dtype(sub[date_col]):
        days = sub[date_col].dt.date
    else:
        days = pd.to_datetime(sub[date_col], errors="coerce").dt.date
    unique_days = sorted(set(d for d in days.dropna()))
    result = {}
    for day in unique_days:
        top_rows = _top_n_rows_by_primary(sub, test_type, day, date_col, n)
        v = _mean_value_in_rows(top_rows, m, mcol)
        if pd.notna(v):
            result[day] = float(v)
    if not result:
        return pd.Series(dtype=float)
    s = pd.Series(result)
    s.index = pd.to_datetime(s.index)
    return s


def _prev_day_best_row(
    sub: pd.DataFrame, test_type: str, selected_day, date_col: str | None,
) -> "pd.Series | None":
    """Best row z dnia bezpośrednio poprzedzającego selected_day."""
    if selected_day is None or not date_col or date_col not in sub.columns:
        return None
    if pd.api.types.is_datetime64_any_dtype(sub[date_col]):
        days = sub[date_col].dt.date
    else:
        days = pd.to_datetime(sub[date_col], errors="coerce").dt.date
    prev_days = sorted(set(d for d in days.dropna() if d < selected_day))
    if not prev_days:
        return None
    return _best_row_for_day(sub, test_type, prev_days[-1], date_col)


def _day_aggregate(
    sub: pd.DataFrame, m: MetricDef, mcol: str, date_col: str | None, day,
) -> float:
    """Wartość metryki zaagregowana dla DANEGO DNIA — używana w kafelkach sekcji
    Performance/Strategy/Asymmetry (jak Vald Summary CSV):
      - performance → peak (max/min) ze wszystkich rep'ów dnia
      - strategy + asymmetry → mean ze wszystkich rep'ów dnia
    Bez doboru top N — surowa średnia wszystkich powtórzeń tego dnia."""
    if day is None or not date_col or date_col not in sub.columns or mcol not in sub.columns:
        return float("nan")
    d = sub[[date_col, mcol]].copy()
    d[mcol] = pd.to_numeric(d[mcol], errors="coerce")
    if m.asymmetry:
        d[mcol] = d[mcol].abs()
    days = (
        d[date_col].dt.date
        if pd.api.types.is_datetime64_any_dtype(d[date_col])
        else pd.to_datetime(d[date_col], errors="coerce").dt.date
    )
    vals = d.loc[days == day, mcol].dropna()
    if vals.empty:
        return float("nan")
    if m.section == "performance":
        return float(vals.max()) if m.higher_better else float(vals.min())
    return float(vals.mean())


def _prev_day_aggregate(
    sub: pd.DataFrame, m: MetricDef, mcol: str, date_col: str | None, selected_day,
) -> float:
    """Wartość metryki z dnia BEZPOŚREDNIO POPRZEDZAJĄCEGO wybrany — analogicznie
    do _day_aggregate (peak dla performance, mean dla strategy/asym)."""
    if selected_day is None or not date_col or date_col not in sub.columns or mcol not in sub.columns:
        return float("nan")
    d = sub[[date_col, mcol]].copy()
    d[mcol] = pd.to_numeric(d[mcol], errors="coerce")
    if m.asymmetry:
        d[mcol] = d[mcol].abs()
    d["_day"] = (
        d[date_col].dt.date
        if pd.api.types.is_datetime64_any_dtype(d[date_col])
        else pd.to_datetime(d[date_col], errors="coerce").dt.date
    )
    d = d.dropna(subset=["_day", mcol])
    d = d[d["_day"] < selected_day]
    if d.empty:
        return float("nan")
    if m.section == "performance":
        agg_fn = "max" if m.higher_better else "min"
    else:
        agg_fn = "mean"
    per_day = d.groupby("_day")[mcol].agg(agg_fn).sort_index()
    return float(per_day.iloc[-1]) if not per_day.empty else float("nan")


def _fmt_metric(v: float, decimals: int = 2) -> str:
    """Wspólny format liczb metryk — używany w pickerach i kafelkach żeby
    NIE było rozjazdu typu '31.6 cm' w pickerze vs '31.58 cm' w kafelku.
    Spójny `.2f` z stripped trail-zeros: 31.5842 → '31.58', 30.0 → '30',
    0.5778 → '0.58'. Dla wartości ≥1000 zaokrąglamy do całości."""
    if pd.isna(v):
        return "—"
    if abs(v) >= 1000:
        return f"{v:.0f}"
    return f"{v:.{decimals}f}".rstrip("0").rstrip(".")


def _row_value(row: pd.Series, m: MetricDef, mcol: str) -> float:
    """Wyciągnij liczbową wartość z wybranego wiersza."""
    if mcol not in row.index:
        return float("nan")
    try:
        v = float(pd.to_numeric(row.get(mcol), errors="coerce"))
    except (TypeError, ValueError):
        return float("nan")
    return v


# ─────────────────────────────────────────────────────────────────────────────
# Linia podsumowania + Kluczowe kafelki (na samej górze, nad zakładkami sekcji)
# ─────────────────────────────────────────────────────────────────────────────

def _render_summary_line(
    sub: pd.DataFrame, athlete_col: str | None, date_col: str,
) -> None:
    n_tests = len(sub)
    total_reps = None
    if "Reps" in sub.columns:
        reps_num = pd.to_numeric(sub["Reps"], errors="coerce").dropna()
        if not reps_num.empty:
            total_reps = int(reps_num.sum())
    days_count = (
        sub[date_col].dt.date.nunique()
        if pd.api.types.is_datetime64_any_dtype(sub[date_col]) else None
    )
    span_days = int((sub[date_col].max() - sub[date_col].min()).days) if pd.notna(sub[date_col].min()) else 0
    last_test_dt = sub[date_col].max()
    last_test_str = last_test_dt.strftime("%Y-%m-%d")
    last_time = last_test_dt.strftime("%H:%M")
    if last_time != "00:00":
        last_test_str += f" {last_time}"

    # Mockup-style: "Last test 2 days ago" relative time (English) + mixed case labels
    def _humanize_en(ts) -> str:
        if pd.isna(ts):
            return "—"
        delta = pd.Timestamp.now() - ts
        secs = int(delta.total_seconds())
        if secs < 60:
            return "just now"
        if secs < 3600:
            m = secs // 60
            return f"{m} min ago"
        if secs < 86400:
            h = secs // 3600
            return f"{h}h ago"
        d = secs // 86400
        if d == 1:
            return "yesterday"
        if d < 30:
            return f"{d} days ago"
        months = d // 30
        return f"{months} mo ago"

    last_test_relative = _humanize_en(last_test_dt)

    pills: list[tuple[str, str]] = [("Tests", str(n_tests))]
    if days_count is not None:
        pills.append(("Test days", str(days_count)))
    pills.append(("Span", f"{span_days} days"))
    pills.append(("Last test", last_test_relative))

    html_pills = "".join(
        f"<div class='stat-pill'>"
        f"<span class='lbl'>{lbl}</span>"
        f"<span class='num'>{num}</span>"
        f"</div>"
        for lbl, num in pills
    )
    st.markdown(
        f"<div class='stat-pills'>{html_pills}</div>",
        unsafe_allow_html=True,
    )


DJ_DROP_HEIGHT_COL = "Drop Height"


def _dj_height_series(df: pd.DataFrame) -> pd.Series:
    """Wysokość spadania DJ w cm — kolumna 'Drop Height' wpisywana w VALD
    przy teście. Wartości <5 to błędne wpisy (metry zamiast cm / brak) → NaN.
    RSI z różnych wysokości NIE jest porównywalne — stąd grupowanie."""
    if DJ_DROP_HEIGHT_COL not in df.columns:
        return pd.Series(index=df.index, dtype=float)
    s = pd.to_numeric(df[DJ_DROP_HEIGHT_COL], errors="coerce")
    return s.where(s >= 5).round()


def _dj_height_label(h) -> str:
    """'30 cm' / '? cm' (gdy wysokość nie była wpisana w VALD)."""
    return f"{int(h)} cm" if pd.notna(h) else "? cm"


def _dj_height_groups(df: pd.DataFrame) -> list[tuple[object, pd.DataFrame]]:
    """Grupy (wysokość, sub_df) sortowane rosnąco po wysokości; NaN (niewpisana)
    na końcu jako osobna grupa."""
    h = _dj_height_series(df)
    groups: list[tuple[object, pd.DataFrame]] = []
    for hv in sorted(h.dropna().unique()):
        groups.append((hv, df[h == hv]))
    if h.isna().any():
        groups.append((float("nan"), df[h.isna()]))
    return groups


# Meta-kolumny które IGNORUJEMY w metric explorerze (nie są metrykami).
_METRIC_EXPLORER_EXCLUDE = {
    "Name", "Date", "Test Type", "TestId", "Time", "Tags", "Reps",
    "BW [KG]", "__saved_at__", "TrialLimb", "_day", "_pf",
}


def _format_metric_label(col: str) -> str:
    """Krótka czysta nazwa metryki do selectbox: strip końcowe spacje,
    nawiasy jednostek '[ms]' / '[cm]' / '[N/kg]' / '[m/s]' / '[W/kg]'.
    'Jump Height (Imp-Mom) [cm] ' → 'Jump Height (Imp-Mom)'"""
    s = col.strip()
    # Usuń jednostkę w nawiasach kwadratowych na końcu
    s = re.sub(r"\s*\[[^\]]+\]\s*$", "", s).strip()
    return s


def _render_metric_explorer_tile(
    sub: pd.DataFrame, test_type: str, date_col: str,
    selected_row: "pd.Series | None" = None,
    selected_day=None,
) -> None:
    """Fullwidth kafelek: wybierz DOWOLNĄ metrykę z CMJ/SJ data → trend w czasie.
    Toggle 2 trybów agregacji per dzień:
      - 'Best jump' — wartość z REP O MAX JH tego dnia (spójna kinematyka).
        Dla `selected_day` honor'ujemy `selected_row` (picker na stronie nadpisuje).
      - 'Mean of top 3' — mean wartości selected metryki z 3 REPÓW O NAJW. JH dnia.
    """
    if not date_col or date_col not in sub.columns:
        return

    # Primary col (max po nim wybiera best jump per dzień)
    primary_label = PRIMARY_METRIC_LABEL.get(test_type, "Jump Height")
    label_to_def = {m.label: m for m in METRICS_BY_TEST.get(test_type, [])
                    if not m.asymmetry}
    primary_def = label_to_def.get(primary_label)
    if not primary_def:
        return
    primary_col = match_column(sub, primary_def)
    if not primary_col or primary_col not in sub.columns:
        return

    # Wszystkie kolumny numeryczne z sub — filtruj:
    # - meta (Name, Date, TestId itd.)
    # - asymetria '% (Asym)' (osobna sekcja)
    # - side variants '(L)', '(R)' (mają main col)
    # - ratio columns z ':' (rzadko sensowne jako standalone)
    # - imperial 'in Inches' (duplikat cm)
    candidate_cols: list[str] = []
    for c in sub.columns:
        if c in _METRIC_EXPLORER_EXCLUDE:
            continue
        cl = c.lower()
        if "asym" in cl or "(l)" in cl or "(r)" in cl:
            continue
        if ":" in c or "in inches" in cl:
            continue
        # Musi być numeryczna i mieć przynajmniej 1 wartość
        v = pd.to_numeric(sub[c], errors="coerce")
        if v.notna().sum() == 0:
            continue
        candidate_cols.append(c)
    if not candidate_cols:
        return

    # Sort alfabetycznie po czystej nazwie (bez jednostek), ale primary zawsze pierwsza
    candidate_cols.sort(key=lambda c: _format_metric_label(c).lower())
    if primary_col in candidate_cols:
        candidate_cols.remove(primary_col)
        candidate_cols.insert(0, primary_col)

    # Pre-compute top idxs per dzień raz (działa dla każdej wybranej metryki).
    d = sub.copy()
    if pd.api.types.is_datetime64_any_dtype(d[date_col]):
        d["_day"] = d[date_col].dt.date
    else:
        d["_day"] = pd.to_datetime(d[date_col], errors="coerce").dt.date
    d = d.dropna(subset=["_day"])
    d[primary_col] = pd.to_numeric(d[primary_col], errors="coerce")
    d = d.dropna(subset=[primary_col])
    if d.empty:
        return
    # Best idx per day + top 3 idxs per day
    best_idx_per_day = d.groupby("_day")[primary_col].idxmax()
    top3_idxs_per_day = (
        d.groupby("_day")[primary_col]
        .apply(lambda s: s.nlargest(3).index.tolist())
    )
    n_days = len(best_idx_per_day)
    if n_days < 2:
        return  # Trend bez sensu dla 1 dnia

    with st.container(key=f"explorer_{test_type}"):
        # Section heading
        st.markdown(
            "<div style='display:flex; align-items:center; gap:7px; margin:0 0 8px;'>"
            "<span style='width:8px; height:8px; border-radius:99px; "
            "background:var(--aph-accent); display:inline-block;'></span>"
            "<span style='font-family:var(--aph-text); font-size:11px; "
            "letter-spacing:0.08em; text-transform:uppercase; font-weight:700; "
            "color:var(--aph-ink);'>Single metric explorer</span></div>",
            unsafe_allow_html=True,
        )

        # ── Toggle agregacji + selectbox metryki ────────────────────────────
        AGG_BEST = "Best jump"
        AGG_TOP3 = "Mean of top 3 jumps"
        agg_col, metric_col_ui = st.columns([1.7, 2.3], gap="small")
        with agg_col:
            agg_mode = st.radio(
                "Tryb agregacji",
                options=[AGG_BEST, AGG_TOP3],
                horizontal=True,
                key=f"single_metric_agg_{test_type}",
                label_visibility="collapsed",
            )
        with metric_col_ui:
            chosen_col = st.selectbox(
                "Metric",
                options=candidate_cols,
                index=0,
                format_func=_format_metric_label,
                key=f"single_metric_explorer_{test_type}",
                label_visibility="collapsed",
            )


        # Buduj serię per dzień zgodnie z trybem
        if agg_mode == AGG_BEST:
            # Per dzień: wartość z best_idx (lub selected_row dla selected_day)
            per_day_values: dict = {}
            for day, bi in best_idx_per_day.items():
                # Honor picker dla selected_day
                if (selected_day is not None and selected_row is not None
                        and day == selected_day):
                    v = pd.to_numeric(selected_row.get(chosen_col), errors="coerce")
                else:
                    v = pd.to_numeric(d.loc[bi, chosen_col], errors="coerce")
                if not pd.isna(v):
                    per_day_values[day] = float(v)
            chosen_vals = pd.Series(per_day_values).sort_index()
        else:
            # Mean top 3 per day
            per_day_values = {}
            for day, idxs in top3_idxs_per_day.items():
                vals = pd.to_numeric(d.loc[idxs, chosen_col], errors="coerce").dropna()
                if not vals.empty:
                    per_day_values[day] = float(vals.mean())
            chosen_vals = pd.Series(per_day_values).sort_index()

        chosen_vals.index = pd.to_datetime(chosen_vals.index)
        if chosen_vals.empty:
            st.info("Brak wartości dla tej metryki.")
            return

        # Latest value + delta vs previous session
        latest_v = float(chosen_vals.iloc[-1])
        prev_v = float(chosen_vals.iloc[-2]) if len(chosen_vals) >= 2 else float("nan")
        if not pd.isna(prev_v) and prev_v != 0:
            delta_pct = (latest_v - prev_v) / abs(prev_v) * 100
            delta_str = f"{'+' if delta_pct >= 0 else ''}{delta_pct:.1f}".replace(".", ",") + "%"
            delta_color = "#16a34a" if delta_pct >= 0 else "#dc2626"
            delta_arrow = "↑" if delta_pct >= 0 else "↓"
            delta_html = (
                f"<span style='color:{delta_color}; font-weight:700; "
                f"font-family:var(--aph-mono); font-size:13px; margin-left:8px;'>"
                f"{delta_arrow} {delta_str}</span>"
            )
        else:
            delta_html = ""

        nice_label = _format_metric_label(chosen_col)
        # Jednostka — z nawiasu kwadratowego w col name jeśli jest
        m_unit = ""
        unit_match = re.search(r"\[([^\]]+)\]", chosen_col)
        if unit_match:
            m_unit = unit_match.group(1)

        # Header z bieżącą wartością + delta
        st.markdown(
            f"""
            <div style="display:flex; align-items:baseline; gap:10px;
                        margin:10px 0 2px 0; flex-wrap:wrap;">
              <span style="font-family:var(--aph-display); font-size:30px; font-weight:800;
                           color:var(--aph-ink); letter-spacing:-0.02em;
                           font-variant-numeric:tabular-nums; line-height:1;">
                {_fmt_pl(latest_v, 2)}</span>
              <span style="font-size:13px; color:var(--aph-dim); font-weight:600;
                           font-family:var(--aph-mono);">{m_unit}</span>
              {delta_html}
            </div>
            <div style="font-size:12.5px; color:var(--aph-mute); font-weight:600;
                        margin:0 0 12px 0;">{nice_label}
              <span style="color:var(--aph-faint, #b8b4aa);">
                &nbsp;·&nbsp;{len(chosen_vals)} {"sesja" if len(chosen_vals) == 1
                else ("sesje" if 2 <= len(chosen_vals) % 10 <= 4
                      and not 12 <= len(chosen_vals) % 100 <= 14 else "sesji")}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # Buduj fig — używam istniejącego metric_trend_chart pattern, ale custom
        # bo nie mamy MetricDef dla każdej kolumny. Inline Plotly:
        import plotly.graph_objects as go
        x_vals = list(chosen_vals.index)
        y_vals = chosen_vals.tolist()
        # Linia neutralna. Wcześniej barwiła się na zielono/czerwono wg tego,
        # czy ostatnia wartość jest wyższa od pierwszej — a explorer pozwala
        # wybrać DOWOLNĄ kolumnę, także taką, gdzie wyżej znaczy gorzej
        # (CM Depth, Contraction Time, Ecc. Duration). Zielona linia sugerowała
        # tam poprawę, której nie było (Filip 2026-09-04). Ocenę zostawiamy
        # delcie procentowej przy metrykach o znanym kierunku.
        line_color = "#3c3a33"
        fill_rgba = "rgba(60,58,51,0.07)"
        fig = go.Figure()
        # Baseline (niewidoczna) na dole zakresu → fill obszaru NIE ciągnie osi
        # do zera i nie zalewa wykresu przy metrykach typu 40-50 cm.
        y_lo_d, y_hi_d = min(y_vals), max(y_vals)
        _span = (y_hi_d - y_lo_d) or (abs(y_hi_d) or 1)
        base_y = y_lo_d - _span * 0.30
        fig.add_trace(go.Scatter(
            x=x_vals, y=[base_y] * len(x_vals),
            mode="lines", line=dict(width=0),
            hoverinfo="skip", showlegend=False,
        ))
        fig.add_trace(go.Scatter(
            x=x_vals, y=y_vals,
            mode="lines+markers",
            line=dict(width=2.5, color=line_color, shape="linear"),
            marker=dict(size=7, color="#FFFFFF", line=dict(width=2.5, color=line_color)),
            fill="tonexty",
            fillcolor=fill_rgba,
            hovertemplate=(
                f"<b>{nice_label}</b><br>"
                f"%{{x|%d %b %Y}} · <b>%{{y:.2f}}</b> {m_unit}<extra></extra>"
            ),
        ))
        # Halo + solid większy marker na ostatnim punkcie (mockup-style)
        AKCENT = "#1c1b18"          # ostatnia sesja — jedyny mocny punkt
        fig.add_trace(go.Scatter(
            x=[x_vals[-1]], y=[y_vals[-1]], mode="markers",
            marker=dict(size=20, color=AKCENT, opacity=0.10, line=dict(width=0)),
            hoverinfo="skip", showlegend=False,
        ))
        fig.add_trace(go.Scatter(
            x=[x_vals[-1]], y=[y_vals[-1]], mode="markers",
            marker=dict(size=10, color=AKCENT, line=dict(width=2, color="#fff")),
            hoverinfo="skip", showlegend=False,
        ))
        # Y-axis zoom do zakresu danych — trend czytelny (mockup nie zaczyna od 0)
        y_range = [base_y, y_hi_d + _span * 0.22]
        fig.update_layout(
            template="plotly_white",
            height=440,
            margin=dict(l=52, r=26, t=10, b=42),
            showlegend=False,
            xaxis=dict(title="", showgrid=True, gridcolor="rgba(28,27,24,0.045)",
                       showline=True, linecolor="rgba(28,27,24,0.12)",
                       zeroline=False, ticks="outside", ticklen=4,
                       tickcolor="rgba(28,27,24,0.12)",
                       tickformat="%d %b", tickfont=dict(size=11.5)),
            yaxis=dict(title=dict(text=m_unit, font=dict(size=11)),
                       showgrid=True, gridcolor="rgba(28,27,24,0.07)",
                       griddash="dot", showline=False, zeroline=False, range=y_range,
                       tickfont=dict(size=11.5)),
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            hovermode="x unified",
            font=dict(family="Archivo, system-ui, sans-serif", size=11.5, color="#6f6b61"),
            hoverlabel=dict(bgcolor="#FFFFFF", bordercolor="rgba(28,27,24,0.15)",
                            font=dict(size=12.5, family="Archivo, system-ui, sans-serif",
                                      color="#1c1b18")),
        )
        # Value callout bubble na ostatnim punkcie (mockup "49.5 cm")
        fig.add_annotation(
            x=x_vals[-1], y=y_vals[-1],
            text=f"<b>{_fmt_pl(y_vals[-1], 1)}</b> {m_unit}".strip(),
            showarrow=False, xanchor="right", yshift=20, xshift=-2,
            font=dict(family="JetBrains Mono, monospace", size=12, color="#FFFFFF"),
            bgcolor="#1c1b18", borderpad=5, opacity=0.95,
        )
        st.plotly_chart(
            fig, use_container_width=True,
            config={"displayModeBar": False},
            key=f"single_metric_chart_{test_type}_{chosen_col}",
        )


def _render_key_metrics_timeline(
    sub: pd.DataFrame, test_type: str,
    athlete_col: str | None, date_col: str,
) -> None:
    """Multi-line wykres metryk per DZIEŃ TESTOWY.
    Toggle Performance/Strategy + opcjonalnie 1 metryka z listy (single big chart).

    Agregacja per dzień zależy od sekcji metryki:
      - performance → MAX (peak ever w tym dniu)
      - strategy    → MEAN top N po primary metric
      - asymmetry   → MEAN (typowa asymetria)
    """
    all_metrics = METRICS_BY_TEST.get(test_type, [])
    # Filter asym żeby uniknąć pl_label clash (np. SJ "Concentric Peak Force" perf vs asym)
    label_to_def = {m.label: m for m in all_metrics if not m.asymmetry}

    # Przygotuj _day (tylko data, bez czasu) — będziemy grupować po niej
    d = sub.copy()
    if pd.api.types.is_datetime64_any_dtype(d[date_col]):
        d["_day"] = d[date_col].dt.date
    else:
        d["_day"] = pd.to_datetime(d[date_col], errors="coerce").dt.date
    d = d.dropna(subset=["_day"])
    if d.empty:
        return

    n_days = d["_day"].nunique()
    if n_days < 2:
        st.caption(
            "📈 Wykres trendów pojawi się gdy wgrasz testy z co najmniej 2 różnych dni."
        )
        return

    # ── Sekcje dostępne dla tego test_type (z metrykami non-null) ──
    def _section_has_data(sec: str) -> list[MetricDef]:
        out = []
        for m in all_metrics:
            if m.section != sec or m.asymmetry:
                continue
            col = match_column(sub, m)
            if not col:
                continue
            if pd.to_numeric(sub[col], errors="coerce").notna().any():
                out.append(m)
        return out

    perf_metrics = _section_has_data("performance")
    strat_metrics = _section_has_data("strategy")

    available_sections = []
    if perf_metrics:
        available_sections.append(("Performance", "performance", perf_metrics))
    if strat_metrics:
        available_sections.append(("Strategy", "strategy", strat_metrics))

    if not available_sections:
        return

    # ── Toggle Performance / Strategy (tylko gdy obie dostępne) ──
    if len(available_sections) > 1:
        section_labels = [s[0] for s in available_sections]
        chosen_label = st.radio(
            "Sekcja metryk",
            options=section_labels,
            horizontal=True,
            label_visibility="collapsed",
            key=f"overview_section_{test_type}",
        )
        chosen_section_tuple = next(
            s for s in available_sections if s[0] == chosen_label
        )
    else:
        chosen_section_tuple = available_sections[0]

    _label, chosen_section, chosen_metrics = chosen_section_tuple

    # ── Buduj serie dla wybranej sekcji ──
    series_per_metric: dict[str, pd.Series] = {}
    metric_defs: dict[str, MetricDef] = {}
    for m in chosen_metrics:
        col = match_column(sub, m)
        if not col:
            continue
        per_day = _series_per_day(sub, m, col, date_col, test_type=test_type)
        if per_day.empty:
            continue
        if m.section == "performance":
            agg_tag = "peak/day"
        elif m.section == "strategy":
            n = STRATEGY_TOP_N_BY_TEST.get(test_type, 3)
            agg_tag = f"mean top {n}/day"
        else:
            agg_tag = "avg/day"
        labeled = f"{m.label} ({agg_tag})"
        series_per_metric[labeled] = per_day
        metric_defs[labeled] = m

    if not series_per_metric:
        return

    # ── Selector: single metric z DOWOLNEJ sekcji (Performance + Strategy razem) ──
    # Default = multi-line cała wybrana sekcja (z toggle wyżej). Selectbox pozwala
    # przejść w tryb single big chart wybierając konkretną metrykę z całej listy.
    OVERVIEW_KEY = "__overview__"
    options = [OVERVIEW_KEY]
    option_labels: dict[str, str] = {
        OVERVIEW_KEY: f"📊 {_label} — overview (multi-line)"
    }
    # Wszystkie metryki performance + strategy (oba section'y) w 1 selectorze
    for m in all_metrics:
        if m.asymmetry:
            continue
        if m.section not in ("performance", "strategy"):
            continue
        col = match_column(sub, m)
        if not col:
            continue
        if pd.to_numeric(sub[col], errors="coerce").notna().any():
            options.append(m.label)
            agg_tag = "peak/day" if m.section == "performance" else "avg/day"
            section_tag = "⚡ PERF" if m.section == "performance" else "🧭 STRAT"
            option_labels[m.label] = f"{section_tag}  ·  {m.label} ({agg_tag})"

    chosen_key = st.selectbox(
        "Click to view single metric",
        options=options,
        format_func=lambda k: option_labels.get(k, k),
        key=f"main_chart_{test_type}",
        help="Wybierz konkretną metrykę żeby zobaczyć duży wykres trendu (Performance + Strategy razem).",
    )

    if chosen_key == OVERVIEW_KEY:
        fig = key_metrics_timeline_chart(series_per_metric, metric_defs)
    else:
        m = next((x for x in all_metrics if x.label == chosen_key), None)
        if m is None:
            return
        mcol = match_column(sub, m)
        if not mcol:
            return

        # Agreguj per dzień zgodnie z sekcją (performance MAX, strategy top N po JH, asym MEAN)
        per_day = _series_per_day(sub, m, mcol, date_col, test_type=test_type)
        if per_day.empty:
            return

        athlete_name = "—"
        if athlete_col and athlete_col in sub.columns:
            names = sub[athlete_col].dropna().astype(str)
            if not names.empty:
                athlete_name = names.iloc[0]

        agg_df = pd.DataFrame({
            date_col: per_day.index,
            mcol: per_day.values,
            (athlete_col or "__source__"): athlete_name,
        })

        fig = metric_trend_chart(
            agg_df, m, mcol, athlete_col or "__source__", date_col,
            side_col=None, all_athletes=[athlete_name], height=460,
        )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def _render_kpi_card_v2(
    m: MetricDef,
    mcol: str,
    latest: float,
    prev: float,
    sub: pd.DataFrame,
    date_col: str | None,
    *,
    primary: bool,
    test_type: str,
    series_mode: str = "best_jump",
    top_n: int = 3,
) -> None:
    """KPI card w stylu mockupu.
    `latest`/`prev` z callera. `series_mode` decyduje co pokazuje sparkline:
    - 'best_jump': wartość z best skoku per dzień (Sekcja 1)
    - 'top_n_mean': mean top N rows by primary per dzień (Sekcja 2)
    - 'default': fallback do _series_per_day (max/mean per section)"""
    if m.asymmetry and not pd.isna(latest):
        latest = abs(latest)
    if m.asymmetry and not pd.isna(prev):
        prev = abs(prev)

    # Per-day series dla sparkline — dopasowane do source value sekcji
    if series_mode == "best_jump":
        series = _series_best_jump_per_day(sub, test_type, m, mcol, date_col)
    elif series_mode == "top_n_mean":
        series = _series_top_n_mean_per_day(sub, test_type, m, mcol, date_col, top_n)
    else:
        series = _series_per_day(sub, m, mcol, date_col, test_type=test_type)
    series_clean = (
        series.dropna() if not series.empty else pd.Series(dtype=float)
    )
    y_vals: list[float] = series_clean.tolist()
    spark_dates = list(series_clean.index)

    # Wartość
    if pd.isna(latest):
        value_text = "—"
    else:
        display_val = abs(latest) if m.asymmetry else latest
        value_text = _fmt_pl(display_val, _auto_decimals(display_val))

    unit_text = m.unit or ""

    # Delta % vs poprzednia sesja (day-over-day)
    if pd.isna(latest) or pd.isna(prev) or prev == 0:
        delta_html = "<span class='aph-v2-delta-pill neutral'>—</span>"
        sparkline_color = "var(--aph-mute)"
    else:
        if m.asymmetry:
            latest_cmp, prev_cmp = abs(latest), abs(prev)
        else:
            latest_cmp, prev_cmp = latest, prev
        delta_pct = (latest_cmp - prev_cmp) / abs(prev_cmp) * 100.0
        if m.neutral_direction or abs(delta_pct) < 0.05:
            tone_class = "neutral"
            sparkline_color = "var(--aph-mute)"
            arrow = "→" if abs(delta_pct) < 0.05 else ("↑" if delta_pct > 0 else "↓")
        else:
            if m.asymmetry:
                improved = delta_pct < 0
            else:
                improved = (delta_pct > 0) == m.higher_better
            tone_class = "up" if improved else "down"
            sparkline_color = "var(--aph-good)" if improved else "var(--aph-bad)"
            arrow = "↑" if delta_pct > 0 else "↓"
        sign = "+" if delta_pct > 0 else ""
        delta_html = (
            f"<span class='aph-v2-delta-pill {tone_class}'>"
            f"{arrow} {sign}{delta_pct:.1f}".replace(".", ",") + "%</span>"
        )

    # Karta jasna (także primary) — sparkline w kolorze trendu (good/bad/mute),
    # widoczny na jasnym tle. Primary tylko większy (wyższy sparkline).
    if primary:
        fill_alpha = 0.16
        spark_h = 44
    else:
        fill_alpha = 0.14
        spark_h = 36

    sparkline_html = _inline_sparkline_svg(
        y_vals, color=sparkline_color, fill_alpha=fill_alpha, h=spark_h,
        dates=spark_dates, unit=unit_text,
    )

    card_class = "aph-v2-kpi-card primary" if primary else "aph-v2-kpi-card"

    st.markdown(
        f"""
        <article class="{card_class}">
          <div class="aph-v2-kpi-header">
            <span class="aph-v2-kpi-label">{m.label}</span>
          </div>
          <div class="aph-v2-kpi-value-row">
            <span class="aph-v2-kpi-value">{value_text}</span>
            <span class="aph-v2-kpi-unit">{unit_text}</span>
          </div>
          <div class="aph-v2-kpi-spark">{sparkline_html}</div>
          <div class="aph-v2-kpi-footer">
            {delta_html}
            <span class="aph-v2-kpi-vs-label">vs previous</span>
          </div>
        </article>
        """,
        unsafe_allow_html=True,
    )


def _render_dj_special_key_tiles(
    dj_df: pd.DataFrame, date_col: str | None,
    selected_day=None,
) -> None:
    """Mirror _render_hop_special_key_tiles dla DJ — TOP_N=3 + inna nazwa
    kolumny RSI ('RSI (Flight Time/Contact Time)'). Pozostałe metryki (JH, CT)
    mają te same nazwy co w HOP.
    `selected_day` — dzień wybrany w session pickerze. Gdy podany, dane
    są filtrowane do tego dnia (sekcja 'selected day'). Gdy None — all-time."""
    RSI_COL = "RSI (Flight Time/Contact Time)"
    JH_COL = "Jump Height (Flight Time)"
    CT_COL = "Contact Time [ms] "
    TOP_N = 3

    # VALD DJ export ma Contact Time w SEKUNDACH (0.18s) zamiast ms jak nazwa
    # kolumny sugeruje. HOP eksportuje w ms (207). Auto-detect na całym dj_df
    # — żeby wszystkie późniejsze odczyty (best CT, mean CT z top_idx) były
    # spójne w ms.
    if CT_COL in dj_df.columns:
        _ct_raw = pd.to_numeric(dj_df[CT_COL], errors="coerce")
        if _ct_raw.notna().any() and _ct_raw.dropna().max() < 5:
            dj_df = dj_df.copy()
            dj_df[CT_COL] = _ct_raw * 1000

    # Pełna historia (po CT fix) — do sparkline'ów trendu per wysokość,
    # nawet gdy kafelki pokazują tylko wybrany dzień.
    dj_all = dj_df

    # Filtr do wybranego dnia (session picker) — gdy brak danych fallback na all
    if selected_day is not None and date_col and date_col in dj_df.columns:
        day_dates = pd.to_datetime(dj_df[date_col], errors="coerce").dt.date
        day_mask = day_dates == selected_day
        if day_mask.any():
            dj_df = dj_df[day_mask].copy()
        # else: brak danych dla wybranego dnia → zostań z full DF (edge case)

    if pd.to_numeric(
        dj_df.get(RSI_COL, pd.Series(dtype=float)), errors="coerce",
    ).isna().all():
        st.info("Brak danych RSI dla Drop Jump.")
        return

    def _tile_html(
        *, primary: bool, label: str, value: float, date_str: str,
        sub_rows: list[tuple[str, str]], note: str,
        spark_y: list[float], spark_x: list,
    ) -> str:
        # Karta jasna (także primary) — ciemny tekst zawsze, żeby był czytelny.
        text_main = "#0E0E10"
        text_mute = "#5E5E64"
        text_label = "#5E5E64"
        border_col = "rgba(14,14,16,0.08)"
        spark_color = "#0E0E10"
        value_size = 52 if primary else 48
        card_class = "aph-v2-kpi-card primary" if primary else "aph-v2-kpi-card"
        date_html = (
            f"<span style='font-size:11px; color:{text_mute} !important; "
            f"font-family: var(--aph-mono); letter-spacing:0; "
            f"text-transform:none; margin-left:auto;'>📅 {date_str}</span>"
            if date_str else ""
        )
        note_html = (
            f"<div style='font-size:10px; color:{text_mute} !important; "
            f"font-family: var(--aph-mono); letter-spacing:0.08em; "
            f"margin:-2px 0 4px 0;'>{note}</div>"
            if note else ""
        )
        sub_html = "".join(
            f"<div style='display:flex; justify-content:space-between; "
            f"align-items:baseline; font-size:13px; "
            f"padding:6px 0; border-top:1px solid {border_col};'>"
            f"<span style='color:{text_label} !important; "
            f"font-family: var(--aph-text); font-size:11.5px;'>{lbl}</span>"
            f"<span style='font-weight:700; color:{text_main} !important; "
            f"font-variant-numeric:tabular-nums;'>{val}</span>"
            f"</div>"
            for lbl, val in sub_rows
        )
        sparkline_html = ""
        if spark_y and len(spark_y) >= 1:
            sparkline_html = _inline_sparkline_svg(
                spark_y, color=spark_color, fill_alpha=0.20 if primary else 0.14,
                h=42, dates=spark_x, unit="",
            )
            sparkline_html = (
                f"<div style='margin:8px 0 4px 0;'>{sparkline_html}</div>"
            )
        return (
            f'<article class="{card_class}" style="min-height: 260px;">'
            f'  <div class="aph-v2-kpi-header" style="display:flex; align-items:baseline; gap:6px;">'
            f'    <span class="aph-v2-kpi-label" style="color:{text_label} !important;">{label}</span>'
            f'    {date_html}'
            f'  </div>'
            f'  {note_html}'
            f'  <div class="aph-v2-kpi-value-row">'
            f'    <span class="aph-v2-kpi-value" style="font-size:{value_size}px; color:{text_main} !important;">{_fmt_pl(value, 2)}</span>'
            f'  </div>'
            f'  {sparkline_html}'
            f'  <div style="margin-top:4px;">{sub_html}</div>'
            f'</article>'
        )

    # ── Sekcja per WYSOKOŚĆ SPADANIA (Drop Height z VALD) ───────────────
    # RSI z 30 cm vs 40 cm = inne zadania motoryczne — liczone i pokazywane
    # osobno. Sparkline = trend TEJ wysokości w czasie (z pełnej historii).
    height_all = _dj_height_series(dj_all)
    for hv, sub in _dj_height_groups(dj_df):
        rsi_vals = pd.to_numeric(sub.get(RSI_COL, pd.Series(dtype=float)), errors="coerce")
        jh_vals = pd.to_numeric(sub.get(JH_COL, pd.Series(dtype=float)), errors="coerce")
        ct_vals = pd.to_numeric(sub.get(CT_COL, pd.Series(dtype=float)), errors="coerce")
        if rsi_vals.isna().all():
            continue
        h_lbl = _dj_height_label(hv)

        # Best rep tej wysokości (w wybranym dniu)
        best_idx = rsi_vals.idxmax()
        best_rsi = float(rsi_vals.loc[best_idx])
        best_jh = (
            float(jh_vals.loc[best_idx])
            if best_idx in jh_vals.index and pd.notna(jh_vals.loc[best_idx]) else None
        )
        best_ct = (
            float(ct_vals.loc[best_idx])
            if best_idx in ct_vals.index and pd.notna(ct_vals.loc[best_idx]) else None
        )
        best_date_str = ""
        if date_col and date_col in sub.columns:
            ts = pd.to_datetime(sub.loc[best_idx, date_col], errors="coerce")
            if not pd.isna(ts):
                best_date_str = ts.strftime("%-d %b · %H:%M")

        # Mean RSI top 3 tej wysokości (w wybranym dniu)
        mean_rsi = mean_jh = mean_ct = None
        n_top = n_total = 0
        rsi_clean = rsi_vals.dropna()
        if not rsi_clean.empty:
            top_idx = rsi_clean.sort_values(ascending=False).head(TOP_N).index
            jh_g = pd.to_numeric(sub.loc[top_idx].get(JH_COL), errors="coerce")
            ct_g = pd.to_numeric(sub.loc[top_idx].get(CT_COL), errors="coerce")
            mean_rsi = float(rsi_clean.loc[top_idx].mean())
            mean_jh = float(jh_g.mean()) if jh_g.notna().any() else None
            mean_ct = float(ct_g.mean()) if ct_g.notna().any() else None
            n_top, n_total = int(len(top_idx)), int(len(rsi_clean))

        # Sparkline'y: trend per dzień Z PEŁNEJ HISTORII tej wysokości
        best_spark_y: list[float] = []
        best_spark_x: list = []
        mean_spark_y: list[float] = []
        mean_spark_x: list = []
        if date_col and date_col in dj_all.columns:
            if pd.isna(hv):
                hist = dj_all[height_all.isna()]
            else:
                hist = dj_all[height_all == hv]
            d = hist[[date_col, RSI_COL]].copy() if RSI_COL in hist.columns else pd.DataFrame()
            if not d.empty:
                d[RSI_COL] = pd.to_numeric(d[RSI_COL], errors="coerce")
                d["_day"] = pd.to_datetime(d[date_col], errors="coerce").dt.date
                d = d.dropna(subset=["_day", RSI_COL])
                if not d.empty:
                    best_per_day = d.groupby("_day")[RSI_COL].max().sort_index()
                    best_spark_y = best_per_day.tolist()
                    best_spark_x = list(best_per_day.index)
                    mean_per_day = (
                        d.groupby("_day")[RSI_COL]
                        .apply(lambda s: s.nlargest(TOP_N).mean()).sort_index()
                    )
                    mean_spark_y = mean_per_day.tolist()
                    mean_spark_x = list(mean_per_day.index)

        # Nagłówek grupy wysokości
        st.markdown(
            f"<div style='display:inline-flex; align-items:center; gap:6px; "
            f"font-family:var(--aph-mono); font-size:11px; font-weight:700; "
            f"letter-spacing:0.12em; text-transform:uppercase; "
            f"color:var(--aph-ink); background:var(--aph-card); "
            f"border:1px solid var(--aph-line); border-radius:99px; "
            f"padding:4px 14px; margin:6px 0 8px;'>"
            f"⬇ drop z {h_lbl}"
            f"<span style='font-weight:400; color:var(--aph-mute); "
            f"text-transform:none; letter-spacing:0;'>· {n_total} "
            f"skok(ów) w dniu</span></div>",
            unsafe_allow_html=True,
        )

        best_sub: list[tuple[str, str]] = []
        if best_jh is not None:
            best_sub.append(("Jump Height", f"{best_jh:.1f} cm"))
        if best_ct is not None:
            best_sub.append(("Contact Time", f"{best_ct:.0f} ms"))
        best_html = _tile_html(
            primary=True, label=f"Best RSI · {h_lbl}", value=best_rsi,
            date_str=best_date_str, sub_rows=best_sub, note="",
            spark_y=best_spark_y, spark_x=best_spark_x,
        )

        if mean_rsi is not None and n_total > 1:
            mean_sub: list[tuple[str, str]] = []
            if mean_jh is not None:
                mean_sub.append(("Mean Jump Height", f"{mean_jh:.1f} cm"))
            if mean_ct is not None:
                mean_sub.append(("Mean Contact Time", f"{mean_ct:.0f} ms"))
            mean_html = _tile_html(
                primary=False, label=f"Mean RSI · {h_lbl}", value=mean_rsi,
                date_str="", sub_rows=mean_sub, note=f"top {n_top}/{n_total} rep",
                spark_y=mean_spark_y, spark_x=mean_spark_x,
            )
        else:
            mean_html = (
                '<article class="aph-v2-kpi-card" style="min-height:260px; '
                'display:flex; align-items:center; justify-content:center; '
                'color:var(--aph-mute); font-style:italic;">'
                '1 skok w dniu — brak Mean RSI</article>'
            )

        c1, c2 = st.columns([1, 1], gap="small")
        with c1:
            st.markdown(best_html, unsafe_allow_html=True)
        with c2:
            st.markdown(mean_html, unsafe_allow_html=True)


# Metryki RSAIP — te same co IMTP performance, ale każda pokazywana per noga
# (L|R obok siebie). Format: (col_name, label, unit, decimals)
RSAIP_TILE_METRICS: list[tuple[str, str, str, int]] = [
    ("Peak Vertical Force",       "Peak Force",          "N",     0),
    ("Peak Vertical Force / BW",  "Peak Force / BW",     "× BW",  2),
    ("Force at 100ms / BM",       "Force @ 100ms / BM",  "N/kg",  1),
    ("Force at 200ms / BM",       "Force @ 200ms / BM",  "N/kg",  1),
    ("RFD - 100ms",               "RFD @ 100ms",         "N/s",   0),
    ("RFD - 200ms",               "RFD @ 200ms",         "N/s",   0),
]


def _render_rsaip_key_tiles(
    rsaip_df: pd.DataFrame, date_col: str | None,
    test_type: str = "RSAIP",
    selected_day=None,
) -> None:
    """Kafelki testu unilateralnego (RSAIP/RSKIP) — best execution per noga.
    Peak section: rep o max Peak Force per noga → wszystkie metryki z TEGO REPA.
    Top 3 mean: 3 reps o najwyższym Peak Force per noga → mean wszystkich
    metryk z tych 3 rep'ów. Standard S&C (Comfort 2019, Beckham 2018) —
    spójna kinematyka jednego pull'u zamiast 'best peaks per metryka'.
    `test_type` używany TYLKO do unique selectbox keys (RSAIP vs RSKIP w
    osobnych tabach nie kolidują).
    `selected_day` — dzień wybrany w session pickerze (date object). Gdy None,
    fallback na najnowszy dzień w danych."""
    if "TrialLimb" not in rsaip_df.columns or rsaip_df["TrialLimb"].isna().all():
        st.warning("Brak informacji o nogowości (TrialLimb) — re-pivot wymagany.")
        return

    # Filtr do wybranego (lub najnowszego) dnia testowego
    has_dates = bool(date_col and date_col in rsaip_df.columns)
    if has_dates:
        d_dates = pd.to_datetime(rsaip_df[date_col], errors="coerce")
        if selected_day is not None:
            # Użyj dnia z session pickera
            day_mask = d_dates.dt.date == selected_day
            # Jeśli wybrany dzień nie ma danych (np. stary state) — fallback na latest
            if not day_mask.any():
                selected_day = d_dates.dt.date.dropna().max()
                day_mask = d_dates.dt.date == selected_day
        else:
            selected_day = d_dates.dt.date.dropna().max()
            day_mask = d_dates.dt.date == selected_day
        day_df = rsaip_df[day_mask]
        date_str = selected_day.strftime("%Y-%m-%d") if selected_day else ""
    else:
        day_df = rsaip_df
        date_str = ""

    # Pre-compute best rep + top 3 rows per noga (po Peak Force).
    # Wszystkie metryki potem pociągniemy Z TYCH SAMYCH WIERSZY (spójna kinematyka).
    PRIMARY = "Peak Vertical Force"
    sides: dict[str, dict | None] = {}
    for side in ("Left", "Right"):
        s = day_df[day_df["TrialLimb"] == side]
        if s.empty or PRIMARY not in s.columns:
            sides[side] = None
            continue
        pf = pd.to_numeric(s[PRIMARY], errors="coerce")
        if pf.isna().all():
            sides[side] = None
            continue
        s_sorted = s.assign(_pf=pf).dropna(subset=["_pf"]).sort_values(
            "_pf", ascending=False,
        ).reset_index(drop=True)
        sides[side] = {
            "all_rows":  s_sorted,           # wszystkie reps sortowane po PF desc
            "top3_rows": s_sorted.head(3),   # zawsze top 3 po Peak Force
            "n_total":   len(s_sorted),
            # best_row ustawimy poniżej po selectboxie (default = idx 0 = max PF)
        }

    st.markdown(
        f"""
        <div class="aph-v2-kpi-section-head">
          <div class="aph-v2-kpi-section-title">Key metrics — best execution ({date_str})</div>
        </div>
        <div style="font-family:var(--aph-text); font-size:12.5px;
                    color:var(--aph-mute); margin:-8px 0 14px 0;">
          Domyślnie: rep o najwyższym Peak Force per noga — zmień próbę L/R
          poniżej. Top 3 mean rozwiniesz w kafelku.
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ── Pickery rep'ów L i R (osobne selectboxy obok siebie) ────────────
    # Default = idx 0 (max Peak Force). User może wybrać inny rep — wtedy
    # WSZYSTKIE metryki w kafelkach dla tej nogi pociągnie z wybranego rep'a.
    SIDE_L_COLOR = "#4d8fd1"
    SIDE_R_COLOR = "#e58c3a"
    pick_cols = st.columns(2, gap="small")
    for pick_col, side, side_color in [
        (pick_cols[0], "Left",  SIDE_L_COLOR),
        (pick_cols[1], "Right", SIDE_R_COLOR),
    ]:
        with pick_col:
            s_info = sides.get(side)
            if s_info is None:
                st.markdown(
                    f"<div style='font-family:var(--aph-mono); font-size:11px; "
                    f"color:var(--aph-mute); padding:8px 0;'>"
                    f"{side[0]} · brak rep'ów</div>",
                    unsafe_allow_html=True,
                )
                sides[side] = None
                continue
            all_rows = s_info["all_rows"]

            # Lista opcji: indeksy (0..N-1), sortowane po PF desc (0 = best)
            options = list(range(len(all_rows)))

            def _fmt_rep(i, _rows=all_rows, _date_col=date_col) -> str:
                """np. '#1 — 3153 N · 10:53:15  🏆'"""
                r = _rows.iloc[i]
                pf_v = float(r["_pf"])
                t_str = ""
                if _date_col and _date_col in r.index:
                    ts = pd.to_datetime(r[_date_col], errors="coerce")
                    if not pd.isna(ts):
                        t_str = ts.strftime("%H:%M:%S")
                trophy = "  🏆" if i == 0 else ""
                return f"#{i+1} — {pf_v:.0f} N · {t_str}{trophy}"

            key = f"unilateral_pick_{test_type}_{side}_{date_str}"
            chosen_idx = st.selectbox(
                f"🦵 {side[0]} · wybierz próbę",
                options=options,
                format_func=_fmt_rep,
                key=key,
                disabled=len(options) == 1,
            )
            sides[side]["best_row"] = all_rows.iloc[chosen_idx]

    st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)

    # Render 2 kafelki w rzędzie
    n_cols = 2
    rows = -(-len(RSAIP_TILE_METRICS) // n_cols)
    for r in range(rows):
        cols = st.columns(n_cols, gap="small")
        for c in range(n_cols):
            idx = r * n_cols + c
            if idx >= len(RSAIP_TILE_METRICS):
                continue
            col_name, label, unit, decimals = RSAIP_TILE_METRICS[idx]
            with cols[c]:
                _render_rsaip_lr_tile(sides, col_name, label, unit, decimals)


def _render_rsaip_lr_tile(
    sides: dict[str, dict | None], col_name: str, label: str,
    unit: str, decimals: int,
) -> None:
    """Pojedynczy kafelek RSAIP: peak section (wartości Z REPA O MAX PEAK FORCE)
    + rozwijany <details> "Top 3 mean" (mean Z 3 REPÓW O NAJW. PEAK FORCE).
    Spójna kinematyka — wszystkie metryki pochodzą z tych samych wybranych
    wierszy (best execution standard S&C: Comfort 2019, Beckham 2018)."""
    # Pull values from pre-computed best_row/top3_rows per noga
    def _peak(side: str) -> tuple[float | None, int]:
        s = sides.get(side)
        if s is None:
            return None, 0
        v = pd.to_numeric(s["best_row"].get(col_name), errors="coerce")
        return (float(v) if not pd.isna(v) else None), s["n_total"]

    def _top3(side: str) -> tuple[float | None, int]:
        s = sides.get(side)
        if s is None:
            return None, 0
        vals = pd.to_numeric(s["top3_rows"][col_name], errors="coerce").dropna() \
            if col_name in s["top3_rows"].columns else pd.Series(dtype=float)
        return (float(vals.mean()) if not vals.empty else None), len(s["top3_rows"])

    l_peak, n_l = _peak("Left")
    r_peak, n_r = _peak("Right")
    l_top3, n_l_top = _top3("Left")
    r_top3, n_r_top = _top3("Right")

    # Jeśli metryka nie ma kolumny — placeholder
    if (l_peak is None and r_peak is None
            and not any(s and col_name in s["top3_rows"].columns for s in sides.values() if s)):
        st.markdown(
            f"<article class='aph-v2-kpi-card' style='min-height:170px;'>"
            f"<div class='aph-v2-kpi-header'><span class='aph-v2-kpi-label'>{label}</span></div>"
            f"<div style='color:var(--aph-mute); font-style:italic; font-size:13px; padding:12px 0;'>"
            f"Brak metryki w danych</div></article>",
            unsafe_allow_html=True,
        )
        return

    def _fmt(v: float | None) -> str:
        if v is None or pd.isna(v):
            return "—"
        return _fmt_pl(v, decimals)

    SIDE_L = "#3B6FB0"   # steel blue — spójnie z viz.py (Slate)
    SIDE_R = "#E08A2B"   # amber

    def _lr_bars_html(l: float | None, r: float | None, h: int = 64) -> str:
        """Kolumnowy mini-wykres L vs R MIĘDZY boxami wartości. Skala
        WZMACNIA różnicę procentową (surowa proporcja przy 16% asym dawała
        wizualnie niemal równe słupki): silniejsza strona = 100%, słabsza
        = 100% − min(|asym|,30)/30 · 70 (15% asym → ~65%, ≥30% → 30%).
        Nad słabszym słupkiem różnica w % — od razu widać ILE brakuje."""
        if l is None and r is None:
            return ""
        lv = max(float(l), 0.0) if l is not None and not pd.isna(l) else 0.0
        rv = max(float(r), 0.0) if r is not None and not pd.isna(r) else 0.0
        base = max(lv, rv)
        if base <= 0:
            return ""
        asym = (rv - lv) / base * 100.0          # + = R silniejsza
        weak_pct = 100.0 - min(abs(asym), 30.0) / 30.0 * 70.0
        hl = 100.0 if lv >= rv else weak_pct
        hr = 100.0 if rv > lv else weak_pct
        diff_txt = "−" + f"{abs(asym):.0f}%" if abs(asym) >= 0.5 else ""

        def _bar(pct: float, color: str, letter: str, show_diff: bool) -> str:
            diff_html = (
                f"<div style='font-family:var(--aph-mono); font-size:9px; "
                f"font-weight:700; color:{color}; line-height:1;'>{diff_txt}</div>"
                if show_diff and diff_txt else
                "<div style='height:9px;'></div>"
            )
            return (
                f"<div style='display:flex; flex-direction:column; "
                f"align-items:center; justify-content:flex-end; height:100%; "
                f"gap:2px; flex:1;'>"
                f"{diff_html}"
                f"<div style='width:24px; height:{pct:.1f}%; max-height:calc(100% - 24px); "
                f"background:{color}; border-radius:4px 4px 0 0;'></div>"
                f"<div style='font-family:var(--aph-mono); font-size:9px; "
                f"font-weight:700; color:{color}; line-height:1;'>{letter}</div>"
                f"</div>"
            )

        return (
            f"<div style='width:84px; flex-shrink:0; height:{h + 14}px; "
            f"display:flex; align-items:flex-end; gap:8px; padding:0 4px;'>"
            f"{_bar(hl, SIDE_L, 'L', lv < rv)}{_bar(hr, SIDE_R, 'R', rv < lv)}"
            f"</div>"
        )

    def _value_pair_html(l: float | None, r: float | None, n_l_txt: str, n_r_txt: str,
                         compact: bool = False) -> str:
        """L | R obok siebie. compact=True dla wersji w <details> (mniejsze fonty)."""
        v_size = 20 if compact else 28
        unit_size = 11 if compact else 13
        pad = "6px 4px" if compact else "8px 4px"
        bars_mid = _lr_bars_html(l, r, h=62 if compact else 88)
        return (
            f"<div style='display:grid; grid-template-columns: 1fr auto 1fr; "
            f"gap:8px; align-items:center;'>"
            f"  <div style='text-align:center; padding:{pad};"
            f"              background:rgba(59,111,176,0.08); border-radius:8px;"
            f"              border:1px solid rgba(59,111,176,0.18);'>"
            f"    <div style='font-family:var(--aph-mono); font-size:10px;"
            f"                letter-spacing:0.18em; color:{SIDE_L}; font-weight:700;"
            f"                margin-bottom:4px;'>L · {n_l_txt}</div>"
            f"    <div style='font-size:{v_size}px; font-weight:800; color:var(--aph-ink);"
            f"                line-height:1; font-variant-numeric:tabular-nums;'>"
            f"      {_fmt(l)}<span style='font-size:{unit_size}px; color:var(--aph-dim);"
            f"      font-weight:500; margin-left:3px;'>{unit}</span>"
            f"    </div>"
            f"  </div>"
            f"  {bars_mid if bars_mid else '<div></div>'}"
            f"  <div style='text-align:center; padding:{pad};"
            f"              background:rgba(224,138,43,0.08); border-radius:8px;"
            f"              border:1px solid rgba(224,138,43,0.18);'>"
            f"    <div style='font-family:var(--aph-mono); font-size:10px;"
            f"                letter-spacing:0.18em; color:{SIDE_R}; font-weight:700;"
            f"                margin-bottom:4px;'>R · {n_r_txt}</div>"
            f"    <div style='font-size:{v_size}px; font-weight:800; color:var(--aph-ink);"
            f"                line-height:1; font-variant-numeric:tabular-nums;'>"
            f"      {_fmt(r)}<span style='font-size:{unit_size}px; color:var(--aph-dim);"
            f"      font-weight:500; margin-left:3px;'>{unit}</span>"
            f"    </div>"
            f"  </div>"
            f"</div>"
        )

    peak_pair = _value_pair_html(l_peak, r_peak, f"n={n_l}", f"n={n_r}")

    # Sekcja Top 3 mean — w <details> żeby była rozwijana
    top3_pair = _value_pair_html(
        l_top3, r_top3, f"top {n_l_top}/{n_l}", f"top {n_r_top}/{n_r}",
        compact=True,
    )
    details_html = (
        f"<details style='margin-top:8px; border-top:1px solid var(--aph-line); "
        f"padding-top:8px;'>"
        f"  <summary style='cursor:pointer; font-family:var(--aph-mono); "
        f"           font-size:10px; letter-spacing:0.16em; text-transform:uppercase; "
        f"           color:var(--aph-mute); font-weight:600; user-select:none; "
        f"           list-style:none; padding:2px 0;'>"
        f"    ▾ Top 3 mean"
        f"  </summary>"
        f"  <div style='margin-top:8px;'>{top3_pair}</div>"
        f"</details>"
    )

    st.markdown(
        f"""
        <article class="aph-v2-kpi-card" style="min-height: 200px;">
          <div class="aph-v2-kpi-header">
            <span class="aph-v2-kpi-label">{label}</span>
          </div>
          <div style="margin-top:6px;">{peak_pair}</div>
          {details_html}
        </article>
        """,
        unsafe_allow_html=True,
    )


def _render_hop_two_cards(
    sub: pd.DataFrame, date_col: str | None,
    selected_row: "pd.Series | None", selected_day,
) -> None:
    """HOP Key metrics: DWIE karty zamiast 8 kafli (Filip: nieprzejrzyste).
    [MEAN 5 HOP] — właściwy wynik testu 10/5: mean RSI z top 5 hopów
                   wybranego trialu + mean JH/CT z TYCH SAMYCH 5 hopów.
    [BEST HOP]   — najlepszy hop trialu (max RSI) + jego JH/CT.
    Delta vs poprzedni dzień testowy; sparkline = trend per dzień (pełna
    historia). Stylistyka pokrewna kartom Overview (kropka+kolor testu),
    ale odróżniona: większa, ze sparkline i deltą."""
    RSI_COL = "RSI (Flight/Contact Time)"
    JH_COL = "Jump Height (Flight Time)"
    CT_COL = "Contact Time [ms] "
    TOP_N = 5
    acc = TEST_ACCENT.get("HOP", "var(--aph-accent)")

    # ── Trial (seria 10/5) z pickera — fallback: cały wybrany dzień ─────
    trial_rows = pd.DataFrame()
    if (selected_row is not None and "TestId" in sub.columns
            and pd.notna(selected_row.get("TestId"))):
        trial_rows = sub[sub["TestId"] == selected_row.get("TestId")]
    if trial_rows.empty and selected_day is not None and date_col:
        days = pd.to_datetime(sub[date_col], errors="coerce").dt.date
        trial_rows = sub[days == selected_day]
    if trial_rows.empty:
        trial_rows = sub

    rsi = pd.to_numeric(trial_rows.get(RSI_COL, pd.Series(dtype=float)), errors="coerce")
    if rsi.isna().all():
        st.info("Brak danych RSI dla 10/5 Hop Test.")
        return
    rsi_clean = rsi.dropna()
    n_total = int(len(rsi_clean))

    # MEAN 5: top 5 hopów po RSI — wszystkie metryki z TYCH SAMYCH hopów
    top_idx = rsi_clean.nlargest(min(TOP_N, n_total)).index
    m5_rsi = float(rsi_clean.loc[top_idx].mean())
    jh_all = pd.to_numeric(trial_rows.get(JH_COL, pd.Series(dtype=float)), errors="coerce")
    ct_all = pd.to_numeric(trial_rows.get(CT_COL, pd.Series(dtype=float)), errors="coerce")
    m5_jh = float(jh_all.loc[top_idx].mean()) if jh_all.loc[top_idx].notna().any() else None
    m5_ct = float(ct_all.loc[top_idx].mean()) if ct_all.loc[top_idx].notna().any() else None

    # BEST hop trialu
    b_idx = rsi_clean.idxmax()
    b_rsi = float(rsi_clean.loc[b_idx])
    b_jh = float(jh_all.loc[b_idx]) if b_idx in jh_all.index and pd.notna(jh_all.loc[b_idx]) else None
    b_ct = float(ct_all.loc[b_idx]) if b_idx in ct_all.index and pd.notna(ct_all.loc[b_idx]) else None
    b_pos_txt = ""
    if date_col and date_col in trial_rows.columns:
        ordered = trial_rows.sort_values(date_col)
        try:
            pos = list(ordered.index).index(b_idx) + 1
            b_pos_txt = f"hop #{pos}/{n_total}"
        except ValueError:
            pass

    # ── Serie per dzień (pełna historia) — sparkline + prev ─────────────
    m5_day = pd.Series(dtype=float)
    best_day = pd.Series(dtype=float)
    if date_col and date_col in sub.columns:
        d = sub[[date_col, RSI_COL] + (["TestId"] if "TestId" in sub.columns else [])].copy()
        d[RSI_COL] = pd.to_numeric(d[RSI_COL], errors="coerce")
        d["_day"] = pd.to_datetime(d[date_col], errors="coerce").dt.date
        d = d.dropna(subset=["_day", RSI_COL])
        if not d.empty:
            best_day = d.groupby("_day")[RSI_COL].max().sort_index()
            if "TestId" in d.columns:
                per_trial = d.groupby(["_day", "TestId"])[RSI_COL].apply(
                    lambda s: s.nlargest(min(TOP_N, len(s))).mean()
                )
                m5_day = per_trial.groupby(level=0).max().sort_index()
            else:
                m5_day = d.groupby("_day")[RSI_COL].apply(
                    lambda s: s.nlargest(min(TOP_N, len(s))).mean()
                ).sort_index()

    def _prev_val(series: pd.Series) -> float:
        if selected_day is None or series.empty:
            return float("nan")
        prior = series[series.index < selected_day]
        return float(prior.iloc[-1]) if len(prior) else float("nan")

    prev_m5 = _prev_val(m5_day)
    prev_best = _prev_val(best_day)

    def _delta_pill(cur: float, prev: float) -> str:
        if pd.isna(cur) or pd.isna(prev) or prev == 0:
            return "<span class='aph-v2-delta-pill neutral'>—</span>"
        pct = (cur - prev) / abs(prev) * 100.0
        tone = "up" if pct > 0 else ("down" if pct < 0 else "neutral")
        arrow = "↑" if pct > 0 else ("↓" if pct < 0 else "→")
        sign = "+" if pct > 0 else ""
        txt = f"{pct:.1f}".replace(".", ",")
        return (
            f"<span class='aph-v2-delta-pill {tone}'>{arrow} {sign}{txt}%</span>"
        )

    def _card(
        *, title: str, primary: bool, value: float, sub_label: str,
        rows: list[tuple[str, str]], spark: pd.Series, prev: float,
    ) -> str:
        rows_html = "".join(
            f"<div style='display:flex; justify-content:space-between; "
            f"align-items:baseline; gap:8px; padding:5px 0; "
            f"border-top:1px solid var(--aph-line-2);'>"
            f"<span style='font-family:var(--aph-text); font-size:11.5px; "
            f"color:var(--aph-dim);'>{lbl}</span>"
            f"<span style='font-family:var(--aph-text); font-size:13px; "
            f"font-weight:700; color:var(--aph-ink); white-space:nowrap; "
            f"font-variant-numeric:tabular-nums;'>{val}</span></div>"
            for lbl, val in rows if not str(val).startswith("—")
        )
        spark_html = _inline_sparkline_svg(
            spark.tolist(), color="#0E0E10",
            fill_alpha=0.14, h=40, dates=list(spark.index), unit="",
        )
        card_class = "aph-v2-kpi-card primary" if primary else "aph-v2-kpi-card"
        return (
            f"<article class='{card_class}' style='min-height:252px;'>"
            f"<div style='display:flex; align-items:center; gap:7px;'>"
            f"<span style='width:8px; height:8px; border-radius:99px; "
            f"background:{acc}; display:inline-block;'></span>"
            f"<span style='font-family:var(--aph-text); font-size:11px; "
            f"letter-spacing:0.08em; text-transform:uppercase; font-weight:700; "
            f"color:{acc};'>{title}</span></div>"
            f"<div style='margin:8px 0 1px;'>"
            f"<span style='font-family:var(--aph-display); font-size:40px; "
            f"line-height:1; color:var(--aph-ink); "
            f"letter-spacing:-0.02em;'>" + f"{value:.2f}".replace(".", ",") + "</span></div>"
            f"<div style='font-family:var(--aph-text); font-size:11px; "
            f"color:var(--aph-dim); margin-bottom:8px;'>{sub_label}</div>"
            f"<div>{rows_html}</div>"
            f"<div style='margin:8px 0 4px;'>{spark_html}</div>"
            f"<div class='aph-v2-kpi-footer'>{_delta_pill(value, prev)}"
            f"<span class='aph-v2-kpi-vs-label'>vs previous session</span></div>"
            f"</article>"
        )

    st.markdown(
        """
        <div class="aph-v2-kpi-section-head">
          <div class="aph-v2-kpi-section-title">Key metrics — selected trial</div>
          <div class="aph-v2-kpi-section-caption">10/5 Hop · trial z pickera powyżej</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    mean_rows = [
        ("Mean Jump Height", (f"{m5_jh:.1f}".replace(".", ",") + " cm") if m5_jh is not None else "—"),
        ("Mean Contact Time", (f"{m5_ct:.0f} ms") if m5_ct is not None else "—"),
    ]
    best_rows = [
        ("Jump Height", (f"{b_jh:.1f}".replace(".", ",") + " cm") if b_jh is not None else "—"),
        ("Contact Time", (f"{b_ct:.0f} ms") if b_ct is not None else "—"),
    ]
    c1, c2 = st.columns(2, gap="small")
    with c1:
        st.markdown(
            _card(
                title="Mean 5 hop", primary=True, value=m5_rsi,
                sub_label=f"RSI · mean z top {min(TOP_N, n_total)}/{n_total} hopów",
                rows=mean_rows, spark=m5_day, prev=prev_m5,
            ),
            unsafe_allow_html=True,
        )
    with c2:
        st.markdown(
            _card(
                title="Best hop", primary=False, value=b_rsi,
                sub_label=f"RSI · {b_pos_txt}" if b_pos_txt else "RSI · najlepszy hop trialu",
                rows=best_rows, spark=best_day, prev=prev_best,
            ),
            unsafe_allow_html=True,
        )


def _render_key_tiles_from_row(
    row: pd.Series, sub: pd.DataFrame, test_type: str,
    athlete_col: str | None, date_col: str, selected_day,
) -> None:
    """Kluczowe kafelki KPI w stylu mockupu — pierwsza karta primary (czarne BG),
    pozostałe białe. Wartości z wybranej próby + delta vs poprzednia sesja
    + sparkline + PB."""
    # RSAIP / RSKIP: kafle per metryka z L|R obok siebie (testy unilateralne).
    if test_type in ("RSAIP", "RSKIP"):
        _render_rsaip_key_tiles(sub, date_col, test_type=test_type, selected_day=selected_day)
        return
    # DJ: tylko special tiles (Best RSI + Mean RSI z top 3) — bez standardowych
    # KEY_TILES (DJ_METRICS pusta lista, brak label_to_def matches).
    if test_type == "DJ":
        st.markdown(
            """
            <div class="aph-v2-kpi-section-head">
              <div class="aph-v2-kpi-section-title">Key metrics — selected day</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        _render_dj_special_key_tiles(sub, date_col, selected_day=selected_day)
        return
    # HOP: 2 karty (Mean 5 hop = wynik testu 10/5 + Best hop) — zamiast
    # dawnych 8 kafli (Filip: nieprzejrzyste, za dużo metryk).
    if test_type == "HOP":
        _render_hop_two_cards(sub, date_col, row, selected_day)
        return

    labels = KEY_TILES.get(test_type, [])
    if not labels:
        return

    all_metrics = METRICS_BY_TEST.get(test_type, [])
    # 🔴 CRITICAL: filtruj asym MetricDefs — w SJ jest "Concentric Peak Force"
    # ZARÓWNO performance (unit=N) JAK asymmetry (unit=%) z tym samym pl_label
    # ("Concentric Peak Force"). Bez filter asym overrides performance w dict
    # → KPI Performance card pokazywała % asymetrii (3.41%) zamiast N (1944).
    # KEY_TILES zawsze referencjuje PERFORMANCE/STRATEGY (nie asymmetry).
    label_to_def = {m.label: m for m in all_metrics if not m.asymmetry}

    chosen: list[tuple[MetricDef, str]] = []
    for label in labels:
        m = label_to_def.get(label)
        if not m:
            continue
        col = match_column(sub, m)
        if col:
            chosen.append((m, col))
    if not chosen:
        return

    total = len(chosen)
    primary_label = PRIMARY_METRIC_LABEL.get(test_type, "Jump Height")
    top_n = STRATEGY_TOP_N_BY_TEST.get(test_type, 3)

    # ── KEY METRICS: jeden komplet kart + przełącznik trybu ─────────────
    # [Selected jump] wartości z wybranej próby (picker) — spójna kinematyka
    #   jednego skoku; prev = best rep poprzedniej sesji.
    # [Mean of top N] mean metryk z N skoków dnia o najw. primary (te same
    #   rows dla wszystkich metryk); prev = analogicznie dzień wcześniej.
    # Wcześniej tryb Mean żył w osobnym expanderze z DRUGIM kompletem kart
    # (Filip: ściana kafli, nieprzejrzyste). Logika liczenia BEZ ZMIAN.
    if row is None:
        sel_row = _best_row_for_day(sub, test_type, selected_day, date_col)
    else:
        sel_row = row
    prev_best_row = _prev_day_best_row(sub, test_type, selected_day, date_col)

    # IMTP: tylko best pull (gold standard — Comfort 2019); bez trybu Mean.
    has_mean_mode = test_type not in ("IMTP",)
    MODE_SEL = "Selected jump"
    MODE_MEAN = f"Mean of top {top_n}"
    # Dwa klikalne KAFELKI trybu obok nagłówka (Filip: zamiast radio) —
    # aktywny lekko podświetlony (accent+tint przez dynamiczny CSS niżej).
    # Default: Selected jump (= best skok dnia z pickera).
    mode_key = f"km_mode_{test_type}"
    if st.session_state.get(mode_key) not in ("sel", "mean"):
        st.session_state[mode_key] = "sel"
    mode = MODE_SEL if st.session_state[mode_key] == "sel" else MODE_MEAN
    head_l, head_r = st.columns([2.4, 1.6], vertical_alignment="bottom")
    with head_l:
        st.markdown(
            """
            <div class="aph-v2-kpi-section-head" style="margin-bottom:6px;">
              <div class="aph-v2-kpi-section-title">Key metrics</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with head_r:
        if has_mean_mode:
            active = st.session_state[mode_key]
            st.markdown(
                f"<style>"
                f".stApp .st-key-km_tile_{test_type}_{active} button{{"
                f"background:color-mix(in oklab,var(--aph-accent) 10%,var(--aph-card))!important;"
                f"border:1.5px solid var(--aph-accent)!important;"
                f"color:var(--aph-ink)!important; font-weight:700!important;}}"
                f"</style>",
                unsafe_allow_html=True,
            )
            t1, t2 = st.columns(2, gap="small")
            with t1:
                if st.button(MODE_SEL, key=f"km_tile_{test_type}_sel",
                             use_container_width=True,
                             help="Wartości z wybranej próby (picker)"):
                    st.session_state[mode_key] = "sel"
                    st.rerun()
            with t2:
                if st.button(MODE_MEAN, key=f"km_tile_{test_type}_mean",
                             use_container_width=True,
                             help=f"Średnia z top {top_n} skoków dnia"):
                    st.session_state[mode_key] = "mean"
                    st.rerun()

    if mode == MODE_MEAN:
        # Top N rows dnia po primary — mean KAŻDEJ metryki z TYCH SAMYCH rows
        top_rows_today = _top_n_rows_by_primary(
            sub, test_type, selected_day, date_col, top_n,
        )
        if pd.api.types.is_datetime64_any_dtype(sub[date_col]):
            all_days_series = sub[date_col].dt.date
        else:
            all_days_series = pd.to_datetime(sub[date_col], errors="coerce").dt.date
        prev_days_unique = sorted(
            set(d for d in all_days_series.dropna() if d < selected_day)
        ) if selected_day is not None else []
        prev_day = prev_days_unique[-1] if prev_days_unique else None
        top_rows_prev = (
            _top_n_rows_by_primary(sub, test_type, prev_day, date_col, top_n)
            if prev_day is not None else pd.DataFrame()
        )

    cols = st.columns(total, gap="small")
    for i, (col_ui, (m, mcol)) in enumerate(zip(cols, chosen)):
        with col_ui:
            if mode == MODE_MEAN:
                latest_v = _mean_value_in_rows(top_rows_today, m, mcol)
                prev_v = _mean_value_in_rows(top_rows_prev, m, mcol)
                series_mode = "top_n_mean"
            else:
                latest_v = (
                    _row_value(sel_row, m, mcol) if sel_row is not None
                    else float("nan")
                )
                prev_v = (
                    _row_value(prev_best_row, m, mcol)
                    if prev_best_row is not None else float("nan")
                )
                series_mode = "best_jump"
            _render_kpi_card_v2(
                m, mcol, latest_v, prev_v, sub, date_col,
                primary=(i == 0), test_type=test_type,
                series_mode=series_mode, top_n=top_n,
            )


# ─────────────────────────────────────────────────────────────────────────────
# Kafelki w sekcji (Performance / Strategy / Asymmetry)
# ─────────────────────────────────────────────────────────────────────────────

def _render_section_grid(
    sub: pd.DataFrame,
    section: str,
    resolved: list[tuple[MetricDef, str]],
    athlete_col: str | None,
    date_col: str | None,
    *, has_dates: bool, test_type: str,
    selected_row: pd.Series | None, selected_day,
) -> None:
    athletes = (
        sorted(sub[athlete_col].dropna().astype(str).unique().tolist())
        if athlete_col and athlete_col in sub.columns else []
    )

    # Asymmetry — agregacja mean per dzień. Plus selectbox dnia BEZPOŚREDNIO
    # w sekcji (Filip: szybciej niż cofać się do trial pickera na górze).
    # Selectbox sync'uje state z głównym pickerem (selected_day_{test_type}).
    if section == "asymmetry":
        asym_row = selected_row
        asym_day = selected_day

        if (has_dates and date_col and date_col in sub.columns
                and selected_day is not None):
            # Selectbox dnia w sekcji asymetrii — wszystkie dni testowe z sub
            days_dt = pd.to_datetime(sub[date_col], errors="coerce")
            all_test_days = sorted(
                set(d for d in days_dt.dt.date.dropna()), reverse=True,
            )
            asym_day_selector_key = f"asym_section_day_picker_{test_type}"
            try:
                default_idx = all_test_days.index(selected_day)
            except ValueError:
                default_idx = 0
            picked_asym_day = st.selectbox(
                "🗓️ Dzień testowy (asymetrie)",
                options=all_test_days,
                index=default_idx,
                format_func=lambda d: d.strftime("%-d %b %Y") if hasattr(d, "strftime") else str(d),
                key=asym_day_selector_key,
                help="Zmiana dnia tu zsynchronizuje też trial picker na górze widoku",
            )
            # Sync z głównym pickerem (selected_day_{test_type})
            if picked_asym_day != selected_day:
                st.session_state[f"selected_day_{test_type}"] = picked_asym_day
                st.rerun()
            day_mask = days_dt.dt.date == selected_day
            sub_day = sub[day_mask]
            if not sub_day.empty:
                n_trials = len(sub_day)
                st.caption(
                    f"📊 Mean asymetrii z {n_trials} test"
                    f"{'u' if n_trials == 1 else 'ów'} w dniu "
                    f"{selected_day.strftime('%Y-%m-%d')}"
                )
                # Pseudo-row z mean per kolumna asymetrii + dominującą stroną
                row_data: dict = {}
                if date_col in sub_day.columns and not sub_day[date_col].dropna().empty:
                    row_data[date_col] = sub_day[date_col].dropna().iloc[0]
                for m, col in resolved:
                    side_resolved: str | None = None
                    if col in sub_day.columns:
                        vals_signed = pd.to_numeric(sub_day[col], errors="coerce").dropna()
                        row_data[col] = (
                            float(vals_signed.abs().mean())
                            if not vals_signed.empty else float("nan")
                        )
                        # Strona dominująca — fallback ze znaku wartości.
                        # VALD convention dla % (Asym): positive = R (prawa
                        # dominuje), negative = L (lewa). Mode znaku ze wszystkich
                        # rep'ów dnia daje najczęstszą dominację.
                        if not vals_signed.empty:
                            n_L = int((vals_signed < 0).sum())
                            n_R = int((vals_signed > 0).sum())
                            if n_L > n_R:
                                side_resolved = "L"
                            elif n_R > n_L:
                                side_resolved = "R"
                    # __side kolumna (jeśli pipeline ją dodał) ma priorytet nad sign fallback
                    side_col = col + SIDE_SUFFIX
                    if side_col in sub_day.columns:
                        sides = sub_day[side_col].dropna().astype(str)
                        sides = sides[sides.isin(["L", "R"])]
                        if not sides.empty:
                            mode = sides.mode()
                            if not mode.empty:
                                side_resolved = mode.iloc[0]
                    row_data[side_col] = side_resolved
                asym_row = pd.Series(row_data)
                asym_day = selected_day

        if asym_row is not None:
            _render_asymmetry_summary_from_row(asym_row, resolved, test_type)
        _render_asymmetry_phase_grid(
            sub, resolved, athlete_col, date_col,
            has_dates=has_dates, athletes=athletes,
            selected_row=asym_row, selected_day=asym_day,
            test_type=test_type,
        )
        return

    n_cols = 3
    rows = -(-len(resolved) // n_cols)
    for r in range(rows):
        cols = st.columns(n_cols)
        for c in range(n_cols):
            idx = r * n_cols + c
            if idx >= len(resolved):
                continue
            m, mcol = resolved[idx]
            with cols[c]:
                _render_section_metric_tile(
                    sub, m, mcol, athlete_col, date_col,
                    has_dates=has_dates, athletes=athletes, section=section,
                    selected_row=selected_row, selected_day=selected_day,
                    test_type=test_type,
                )


def _asymmetry_phase(m: MetricDef, test_type: str | None = None) -> str:
    """Sklasyfikuj metrykę asymetrii do fazy: 'eccentric', 'concentric', 'landing'.
    test_type matters dla "Force at Zero Velocity":
      - w CMJ to moment zwrotu (koniec eccentric)
      - w SJ to start ruchu z kucu (początek concentric)
      - IMTP to test izometryczny — nie ma faz dynamic, zostaje 'imtp_force'
        (osobne grupowanie żeby header był sensowny)"""
    n = m.name.lower()
    if test_type == "IMTP":
        return "imtp_force"
    if "landing" in n:
        return "landing"
    if "eccentric" in n:
        return "eccentric"
    if "zero velocity" in n:
        return "concentric" if test_type == "SJ" else "eccentric"
    if "concentric" in n:
        return "concentric"
    return "other"


def _render_asymmetry_phase_grid(
    sub: pd.DataFrame,
    resolved: list[tuple[MetricDef, str]],
    athlete_col: str | None,
    date_col: str | None,
    *, has_dates: bool, athletes: list[str],
    selected_row: pd.Series | None, selected_day,
    test_type: str | None = None,
) -> None:
    """Asymetrie pogrupowane w fazy (jedna pod drugą), metryki jako siatka 3 w rzędzie."""
    groups: dict[str, list[tuple[MetricDef, str]]] = {
        "eccentric": [], "concentric": [], "landing": [], "imtp_force": [], "other": [],
    }
    for m, mcol in resolved:
        groups[_asymmetry_phase(m, test_type)].append((m, mcol))

    # Kolory faz: zejście/hamowanie = niebieski, odbicie = zielony,
    # lądowanie = pomarańcz, IMTP = stalowy. Jedna kreska + nazwa — zero
    # emoji i dopisków (Filip: zbędne zdania robiły szum).
    PHASE_STYLE = {
        "eccentric":  ("Ekscentryka",  "oklch(0.56 0.15 248)"),
        "concentric": ("Koncentryka",  "oklch(0.64 0.15 162)"),
        "landing":    ("Lądowanie",    "#e58c3a"),
        "imtp_force": ("Siła (pull)",  "#5b7ba6"),
        "other":      ("Pozostałe",    "var(--aph-mute)"),
    }

    def _render_phase(metrics: list[tuple[MetricDef, str]], heading: str, caption: str) -> None:
        if not metrics:
            return
        ph_name, ph_color = PHASE_STYLE.get(caption, (heading, "var(--aph-ink)"))
        st.markdown(
            f"<div style='display:flex; align-items:center; gap:10px; "
            f"margin:14px 0 10px;'>"
            f"<span style='width:4px; height:20px; border-radius:99px; "
            f"background:{ph_color}; display:inline-block;'></span>"
            f"<span style='font-family:var(--aph-display); font-size:17px; "
            f"letter-spacing:-0.01em; color:var(--aph-ink);'>{ph_name}</span>"
            f"<span style='font-family:var(--aph-text); font-size:11.5px; "
            f"color:var(--aph-mute);'>mean per dzień · L/R</span></div>",
            unsafe_allow_html=True,
        )
        if not has_dates:
            st.caption("Brak dat w danych — wykresy w czasie niedostępne.")
            st.markdown("")
            return
        phase_slug = caption
        key_prefix = f"asymtrend_{test_type}_{phase_slug}"
        n_cols_trend = 2 if len(metrics) >= 2 else 1
        for r in range(-(-len(metrics) // n_cols_trend)):
            cols = st.columns(n_cols_trend, gap="medium")
            for c in range(n_cols_trend):
                idx = r * n_cols_trend + c
                if idx >= len(metrics):
                    continue
                m, mcol = metrics[idx]
                signed_per_day = _signed_asym_mean_per_day(sub, mcol, date_col)
                with cols[c]:
                    st.markdown(
                        f"<div style='font-family: var(--aph-mono); "
                        f"font-size: 12px; letter-spacing: 0.18em; "
                        f"text-transform: uppercase; color: var(--aph-dim); "
                        f"margin-bottom: 6px;'>{m.label}</div>",
                        unsafe_allow_html=True,
                    )
                    fig = asymmetry_bipolar_trend(signed_per_day, height=320)
                    st.plotly_chart(
                        fig, use_container_width=True,
                        config={"displayModeBar": False},
                        key=f"{key_prefix}_{m.label}_{mcol}",
                    )
        st.markdown("")

    _render_phase(groups["eccentric"], "Ekscentryka", "eccentric")
    _render_phase(groups["concentric"], "Koncentryka", "concentric")
    _render_phase(groups["landing"], "Lądowanie", "landing")
    _render_phase(groups["imtp_force"], "Siła (pull)", "imtp_force")
    _render_phase(groups["other"], "Pozostałe", "other")


def _series_per_day(
    sub: pd.DataFrame, m: MetricDef, mcol: str, date_col: str | None,
    test_type: str | None = None,
) -> "pd.Series":
    """Wartość metryki zagregowana per dzień testowy:
      - performance → MAX/MIN (peak ever)
      - strategy    → MEAN z TOP N skoków dnia po primary metric (CMJ:JH N=3, HOP:RSI N=5)
                      — eliminuje warmup, zostawia "best execution"
      - asymmetry   → MEAN ze wszystkich rep'ów dnia (typowa asymetria)
    Zwraca pd.Series indeksowane datą (datetime na początku dnia)."""
    if not date_col or date_col not in sub.columns or mcol not in sub.columns:
        return pd.Series(dtype=float)

    # Day extractor
    def _day_series(s):
        return (s.dt.date if pd.api.types.is_datetime64_any_dtype(s)
                else pd.to_datetime(s, errors="coerce").dt.date)

    # Strategy → top N po primary metric (jeśli mamy primary col w sub)
    if (m.section == "strategy" and test_type
            and test_type in PRIMARY_METRIC_LABEL):
        primary_label = PRIMARY_METRIC_LABEL[test_type]
        primary_def = next(
            (x for x in METRICS_BY_TEST.get(test_type, [])
             if x.label == primary_label),
            None,
        )
        primary_col = match_column(sub, primary_def) if primary_def else None
        if primary_col and primary_col in sub.columns:
            top_n = STRATEGY_TOP_N_BY_TEST.get(test_type, 3)
            d = sub[[date_col, mcol, primary_col]].copy()
            d[mcol] = pd.to_numeric(d[mcol], errors="coerce")
            d[primary_col] = pd.to_numeric(d[primary_col], errors="coerce")
            d["_day"] = _day_series(d[date_col])
            d = d.dropna(subset=["_day", mcol, primary_col])
            if d.empty:
                return pd.Series(dtype=float)

            # Per dzień: weź TOP N po primary metric, policz mean metryki
            def _top_n_mean(grp):
                top = grp.nlargest(top_n, primary_col)
                return top[mcol].mean()

            per_day = (
                d.groupby("_day", group_keys=False)
                .apply(_top_n_mean)
                .sort_index()
            )
            per_day.index = pd.to_datetime(per_day.index)
            return per_day

    # Fallback: performance (max/min) lub asymmetry (mean wszystkich)
    d = sub[[date_col, mcol]].copy()
    d[mcol] = pd.to_numeric(d[mcol], errors="coerce")
    if m.asymmetry:
        d[mcol] = d[mcol].abs()
    d["_day"] = _day_series(d[date_col])
    d = d.dropna(subset=["_day", mcol])
    if d.empty:
        return pd.Series(dtype=float)

    if m.section == "performance":
        agg_func = "max" if m.higher_better else "min"
    else:
        agg_func = "mean"
    per_day = d.groupby("_day")[mcol].agg(agg_func).sort_index()
    per_day.index = pd.to_datetime(per_day.index)
    return per_day


def _render_section_metric_tile(
    sub: pd.DataFrame, m: MetricDef, mcol: str,
    athlete_col: str | None, date_col: str | None,
    *, has_dates: bool, athletes: list[str], section: str,
    selected_row: pd.Series | None, selected_day,
    test_type: str = "",
) -> None:
    """Kafelek metryki w sekcji Perf/Strat/Asym: wartość ZAAGREGOWANA dla DNIA
    (peak dla performance, mean dla strategy/asymmetry — jak Vald Summary CSV).
    Stabilne dla dnia — NIE reaguje na picker konkretnego skoku (to wpływa tylko
    na górne KEY_TILES). Sekcje pokazują trend ogólny atlety.
    Delta vs poprzednia sesja + sparkline trendu per dzień."""
    if has_dates and selected_day is not None:
        latest = _day_aggregate(sub, m, mcol, date_col, selected_day)
        prev = _prev_day_aggregate(sub, m, mcol, date_col, selected_day)
    elif selected_row is not None:
        # Fallback gdy brak dat
        latest = _row_value(selected_row, m, mcol)
        prev = float("nan")
    else:
        latest = _single_value(sub, m, mcol)
        prev = float("nan")

    # Strona dominująca dla asymetrii — mode L/R ze wszystkich rep'ów dnia
    # (nie z selected_row, bo sekcje mają być stabilne dla dnia).
    # Fallback ze znaku wartości gdy __side kolumna nie istnieje (VALD API pipeline
    # ich nie tworzy — tylko manual upload CSV przez parser.py).
    side = None
    if m.asymmetry and has_dates and selected_day is not None:
        days = (
            sub[date_col].dt.date
            if pd.api.types.is_datetime64_any_dtype(sub[date_col])
            else pd.to_datetime(sub[date_col], errors="coerce").dt.date
        )
        # Sign fallback: VALD % (Asym) convention — pos = R, neg = L
        if mcol in sub.columns:
            vals_signed = pd.to_numeric(
                sub.loc[days == selected_day, mcol], errors="coerce"
            ).dropna()
            if not vals_signed.empty:
                n_L = int((vals_signed < 0).sum())
                n_R = int((vals_signed > 0).sum())
                if n_L > n_R:
                    side = "L"
                elif n_R > n_L:
                    side = "R"
        # __side column (z parser.py manual upload) ma priorytet
        side_col = mcol + SIDE_SUFFIX
        if side_col in sub.columns:
            day_sides = (
                sub.loc[days == selected_day, side_col]
                .dropna().astype(str)
            )
            day_sides = day_sides[day_sides.isin(["L", "R"])]
            if not day_sides.empty:
                mode = day_sides.mode()
                if not mode.empty:
                    side = mode.iloc[0]

    with st.container(border=True):
        _render_value_tile(m, latest, prev, side=side, with_flag_border=m.asymmetry)
        # Asymetrie: mini vertical column (bipolar) z aktualną wartością + strefy
        # Performance/Strategy: standard linia trendu per dzień
        if m.asymmetry:
            fig = asymmetry_vertical_column(latest, side, height=110)
            st.plotly_chart(
                fig, use_container_width=True, config={"displayModeBar": False},
                key=f"asym_col_{test_type}_{section}_{m.label}_{mcol}",
            )
        elif has_dates:
            per_day = _series_per_day(sub, m, mcol, date_col, test_type=test_type)
            fig = metric_sparkline(per_day, m, height=70)
            st.plotly_chart(
                fig, use_container_width=True, config={"displayModeBar": False},
                key=f"spark_{test_type}_{section}_{m.label}_{mcol}",
            )


# ─────────────────────────────────────────────────────────────────────────────
# Renderowanie pojedynczego "kafelka" — wartość + delta (HTML)
# ─────────────────────────────────────────────────────────────────────────────

def _render_value_tile(
    m: MetricDef, latest: float, prev: float,
    *, side: str | None = None, with_flag_border: bool = False,
) -> None:
    if pd.isna(latest):
        value_html = "—"
    else:
        # Dla asymetrii wyświetlamy magnitude (już abs)
        display_val = abs(latest) if m.asymmetry else latest
        v_str = (
            f"{display_val:.2f}".rstrip("0").rstrip(".")
            if abs(display_val) < 1000 else f"{display_val:.0f}"
        )
        unit_html = f"<span class='unit'>{m.unit}</span>" if m.unit else ""
        # Side jako inline kolorowy suffix obok wartości (VALD convention:
        # "13% P" = P jest o 13% silniejsza). Bez osobnego badge'a — proste.
        if side in ("L", "R"):
            side_letter = "L" if side == "L" else "P"
            side_html = f"<span class='side-letter-inline side-{side}'>{side_letter}</span>"
        else:
            side_html = ""
        value_html = f"{v_str} {unit_html}{side_html}"

    if pd.isna(latest) or pd.isna(prev):
        delta_html = "<span class='delta-neutral'>pierwsza sesja</span>"
    elif prev == 0:
        delta_html = "<span class='delta-neutral'>—</span>"
    else:
        # Dla asymetrii porównujemy magnitude
        if m.asymmetry:
            latest_cmp = abs(latest)
            prev_cmp = abs(prev)
        else:
            latest_cmp, prev_cmp = latest, prev
        delta_pct = (latest_cmp - prev_cmp) / abs(prev_cmp) * 100.0
        if abs(delta_pct) < 0.05:
            arrow, cls, prefix = "→", "delta-neutral", ""
        elif m.neutral_direction:
            # Brak jednoznacznej interpretacji kierunku — neutralna szara plakietka
            arrow = "↑" if delta_pct > 0 else "↓"
            cls = "delta-neutral"
            prefix = "zmiana "
        else:
            if m.asymmetry:
                improved = delta_pct < 0
            else:
                improved = (delta_pct > 0) if m.higher_better else (delta_pct < 0)
            cls = "delta-up" if improved else "delta-down"
            arrow = "↑" if delta_pct > 0 else "↓"
            prefix = ""
        delta_html = (
            f"<span class='{cls}'>{arrow} {prefix}{abs(delta_pct):.1f}% vs poprz. sesja</span>"
        )

    tile_classes = "tile"
    flag_color_style = ""
    if with_flag_border and not pd.isna(latest):
        flag = asymmetry_flag(abs(latest) if m.asymmetry else latest)
        flag_color_style = f"--flag: {FLAG_COLORS[flag]};"
        tile_classes += " tile-asym"

    st.markdown(
        f"""
        <div class='{tile_classes}' style='{flag_color_style}' title='{m.desc}'>
          <div class='tile-label'>{m.label}</div>
          <div class='tile-value'>{value_html}</div>
          <div class='tile-delta'>{delta_html}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Asymmetry summary KPI (na górze zakładki Asymmetry)
# ─────────────────────────────────────────────────────────────────────────────

def _render_asymmetry_summary_from_row(
    row: pd.Series, resolved: list[tuple[MetricDef, str]],
    test_type: str | None = None,
) -> None:
    """Mini-podsumowanie asymetrii Z WYBRANEJ PRÓBY: split per faza (eccentric/concentric/landing).
    Dla IMTP: jedna karta 'Force output' (test izometryczny — bez faz dynamic)."""
    # Phase meta per test type (IMTP ma 1 fazę, pozostałe 3)
    if test_type == "IMTP":
        phase_meta = [("imtp_force", "Force output")]
    else:
        phase_meta = [
            ("eccentric", "Eccentric"),
            ("concentric", "Concentric"),
            ("landing", "Landing"),
        ]
    phases: dict[str, list[tuple[MetricDef, str]]] = {k: [] for k, _ in phase_meta}
    for m, mcol in resolved:
        ph = _asymmetry_phase(m, test_type)
        if ph in phases:
            phases[ph].append((m, mcol))

    phase_counts: dict[str, tuple[int, int, int, int]] = {}
    flagged_all: list[tuple[MetricDef, str, float, str | None]] = []
    for ph, metrics in phases.items():
        n_grn = n_yel = n_red = 0
        for m, mcol in metrics:
            raw = row.get(mcol)
            try:
                mag = abs(float(raw))
            except (TypeError, ValueError):
                mag = float("nan")
            side_val = row.get(mcol + SIDE_SUFFIX)
            side_val = side_val if isinstance(side_val, str) else None
            flagged_all.append((m, mcol, mag, side_val))
            if pd.isna(mag):
                continue
            flag = asymmetry_flag(mag)
            n_grn += int(flag == "green")
            n_yel += int(flag == "orange")
            n_red += int(flag == "red")
        phase_counts[ph] = (n_grn, n_yel, n_red, len(metrics))

    cols = st.columns(len(phase_meta))
    for col_ui, (ph, label) in zip(cols, phase_meta):
        n_grn, n_yel, n_red, total = phase_counts[ph]
        # Big number = total flagged metrics (zielone+pomarańczowe+czerwone)
        # Pod spodem mini chipy z kolorami
        chip_badges = []
        if n_grn > 0:
            chip_badges.append(
                f"<span class='aph-v2-phase-chip green'>{n_grn} OK</span>"
            )
        if n_yel > 0:
            chip_badges.append(
                f"<span class='aph-v2-phase-chip amber'>{n_yel} watch</span>"
            )
        if n_red > 0:
            chip_badges.append(
                f"<span class='aph-v2-phase-chip red'>{n_red} flag</span>"
            )
        if not chip_badges:
            chip_badges = ["<span class='aph-v2-phase-chip muted'>brak danych</span>"]
        chips_html = "".join(chip_badges)
        with col_ui:
            st.markdown(
                f"""
                <div class='aph-v2-phase-card'>
                  <div class='aph-v2-phase-header'>
                    <span class='aph-v2-phase-name'>{label}</span>
                    <span class='aph-v2-phase-total'>{total} metryk</span>
                  </div>
                  <div class='aph-v2-phase-chips'>{chips_html}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    with st.expander("📊 Pokaż zbiorczy wykres asymetrii", expanded=False):
        st.plotly_chart(
            asymmetry_overview_bar(flagged_all),
            use_container_width=True,
            config={"displayModeBar": False},
        )
    st.markdown("")


# ─────────────────────────────────────────────────────────────────────────────
# Logika "latest vs previous session" — agregacja per dzień testu
# ─────────────────────────────────────────────────────────────────────────────

def _single_value(sub: pd.DataFrame, m: MetricDef, mcol: str) -> float:
    """Pojedyncza wartość — używane gdy nie ma dat lub jest 1 wiersz."""
    s = pd.to_numeric(sub[mcol], errors="coerce").dropna()
    if s.empty:
        return float("nan")
    if m.asymmetry:
        s = s.abs()
    return float(s.max() if m.higher_better else s.min())


# ─────────────────────────────────────────────────────────────────────────────
# Tabela porównawcza (4. zakładka)
# ─────────────────────────────────────────────────────────────────────────────

def _render_comparison_table(
    sub: pd.DataFrame, test_type: str,
    athlete_col: str | None, date_col: str | None,
) -> None:
    raw_max = st.session_state.get("data_max")
    raw_avg = st.session_state.get("data_avg")

    # Gdy są oba surowe pliki → dwie zakładki MAX / AVG (przełączane jednym klikiem)
    if raw_max is not None and raw_avg is not None:
        st.caption(
            "MAX = peak per metryka w teście · AVG = średnia z repów w teście"
        )
        tab_max, tab_avg = st.tabs(["📈 MAX (peak)", "📊 AVG (mean)"])
        with tab_max:
            _render_one_table(
                _filter_raw_to_match(raw_max, sub, athlete_col),
                test_type, athlete_col, date_col,
            )
        with tab_avg:
            _render_one_table(
                _filter_raw_to_match(raw_avg, sub, athlete_col),
                test_type, athlete_col, date_col,
            )
        return

    # Gdy jeden surowy plik → pokaż go
    if raw_max is not None:
        st.caption("Widok: **MAX** (peak). AVG niedostępny — wgraj plik AVG po lewej.")
        _render_one_table(
            _filter_raw_to_match(raw_max, sub, athlete_col),
            test_type, athlete_col, date_col,
        )
        return
    if raw_avg is not None:
        st.caption("Widok: **AVG** (mean). MAX niedostępny — wgraj plik MAX po lewej.")
        _render_one_table(
            _filter_raw_to_match(raw_avg, sub, athlete_col),
            test_type, athlete_col, date_col,
        )
        return

    # Bez surowych plików (np. dane z biblioteki) → zmergowane (info caption usunięty
    # na życzenie Filipa — niepotrzebny mental noise w widoku metryki)
    _render_one_table(sub, test_type, athlete_col, date_col)


def _render_one_table(
    source_df: pd.DataFrame, test_type: str,
    athlete_col: str | None, date_col: str | None,
) -> None:
    """Trzy tabele pod sobą — osobno Performance / Strategy / Asymmetry.
    Każda sortowana od najnowszego testu, z metrykami tylko z danej sekcji."""
    if "Test Type" in source_df.columns:
        type_mask = source_df["Test Type"].astype(str).str.upper().str.contains(
            test_type.upper(), na=False
        )
        if type_mask.any():
            source_df = source_df[type_mask]

    if date_col and date_col in source_df.columns:
        source_df = source_df.sort_values(date_col, ascending=False)

    base_cols: list[str] = []
    if athlete_col:
        base_cols.append(athlete_col)
    if date_col and date_col in source_df.columns:
        base_cols.append(date_col)

    section_headings = {
        "performance": "🚀 Performance",
        "strategy": "📐 Strategy",
        "asymmetry": "⚖️ Asymmetry",
    }
    any_rendered = False
    for sec in ("performance", "strategy", "asymmetry"):
        resolved = resolve_metrics(source_df, test_type, section=sec)
        if not resolved:
            continue
        metric_cols = [c for _, c in resolved]
        display_cols = [c for c in base_cols + metric_cols if c in source_df.columns]
        if not display_cols:
            continue
        out = source_df[display_cols].copy()
        for _, c in resolved:
            if c in out.columns:
                out[c] = pd.to_numeric(out[c], errors="coerce").round(2)
        out = out.rename(columns={c: m.label for m, c in resolved})

        # Format kolumn metryk wg jednostki — żeby tabela była czytelna
        # (np. asymetrie z "%", strategy z "ms", performance z "cm" itd.)
        col_config = {}
        for m, _ in resolved:
            if m.unit == "%":
                col_config[m.label] = st.column_config.NumberColumn(
                    m.label, format="%.1f%%"
                )
            elif m.unit:
                col_config[m.label] = st.column_config.NumberColumn(
                    m.label, format=f"%.2f {m.unit}"
                )

        st.markdown(f"**{section_headings[sec]}**")
        st.dataframe(
            out, use_container_width=True, hide_index=True,
            column_config=col_config,
        )
        any_rendered = True

    if not any_rendered:
        st.info("Brak dopasowanych metryk dla tego typu testu.")


def _filter_raw_to_match(
    raw: pd.DataFrame, sub: pd.DataFrame, athlete_col: str | None,
) -> pd.DataFrame:
    """Filtruj surowy DataFrame (MAX lub AVG) do (Name, Date) kluczy obecnych w sub.
    Normalizuje whitespace w Name — np. 'John  Smith' i 'John Smith' to ta sama osoba."""
    if "Name" not in sub.columns or "Date" not in sub.columns:
        return raw
    if "Name" not in raw.columns or "Date" not in raw.columns:
        return raw

    def _norm_name(s) -> str:
        return " ".join(str(s).split())

    keys = set(zip(sub["Name"].map(_norm_name), sub["Date"]))
    mask = raw.apply(
        lambda r: (_norm_name(r["Name"]), r["Date"]) in keys, axis=1
    )
    return raw[mask].sort_values("Date").reset_index(drop=True)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _render_data_status_banner() -> None:
    """Mała informacja co zostało wczytane — MAX / AVG / oba (tylko świeży upload)."""
    has_max = bool(st.session_state.get("uploaded_max"))
    has_avg = bool(st.session_state.get("uploaded_avg"))

    if has_max and has_avg:
        st.success(
            "✅ Wczytane: **MAX** (Performance) **+** **AVG** (Strategy / Asymmetry). "
            "Metryki performance pokazują peak ability, reszta to typowe wartości sesji."
        )
    elif has_avg and not has_max:
        st.warning(
            "📌 Wczytany tylko **AVG** — wartości performance (Jump Height, RSI-mod, "
            "Peak Power…) są **uśrednione** i zaniżone vs peak. "
            "Dorzuć MAX żeby zobaczyć rzeczywiste piki."
        )
    elif has_max and not has_avg:
        st.warning(
            "📌 Wczytany tylko **MAX** — metryki strategy (Contraction Time, "
            "CM Depth…) i asymetrie pokazują skrajne wartości, mogą być "
            "**niereprezentatywne**. Dorzuć AVG."
        )


def _best_pb_for(
    splits: dict[str, pd.DataFrame], test_type: str, label: str,
) -> tuple[float, str] | None:
    """Najlepsza (peak) wartość metryki danego test_type ze wszystkich sesji."""
    sub = splits.get(test_type)
    if sub is None or sub.empty:
        return None
    all_metrics = METRICS_BY_TEST.get(test_type, [])
    m = next((x for x in all_metrics if x.label == label), None)
    if m is None:
        return None
    col = match_column(sub, m)
    if not col:
        return None
    vals = pd.to_numeric(sub[col], errors="coerce").dropna()
    if vals.empty:
        return None
    best = float(vals.max()) if m.higher_better else float(vals.min())
    return best, m.unit


def _render_pb_tiles(pbs: list[tuple[str, float, str, int]]) -> None:
    if not pbs:
        return
    cols = st.columns(len(pbs))
    for col_ui, (label, val, unit, decimals) in zip(cols, pbs):
        unit_str = f"{unit}" if unit else ""
        with col_ui:
            st.markdown(
                f"<div class='aph-pb-tile'>"
                f"<span class='aph-pb-label'>{label}</span>"
                f"<div class='aph-pb-value'>{val:.{decimals}f}"
                f"<span class='aph-pb-unit'>{unit_str}</span></div>"
                f"</div>",
                unsafe_allow_html=True,
            )


def _render_rsi_zone_table(
    best_rsi: float, mean_rsi: float,
    mean_label: str = "Best Mean RSI (top 5/test)",
) -> None:
    """Tabela referencyjna RSI z osadzonymi Best RSI i Mean RSI w odpowiednich strefach.
    Strefy dobierane wg płci aktywnego zawodnika (default: male).
    `mean_label` — etykieta dla Mean RSI w info-bar (HOP używa 'top 5/test',
    DJ używa 'top 3/dzień')."""
    sex = _current_athlete_sex()
    zones = _get_rsi_zones(sex)
    best_zone = _rsi_zone(best_rsi, sex) if not pd.isna(best_rsi) else None
    mean_zone = _rsi_zone(mean_rsi, sex) if not pd.isna(mean_rsi) else None

    info_bits = []
    if not pd.isna(best_rsi):
        info_bits.append(
            f"Best RSI (peak rep) = <b style='color:var(--aph-ink);'>{best_rsi:.2f}</b>"
        )
    if not pd.isna(mean_rsi):
        info_bits.append(
            f"{mean_label} = <b style='color:var(--aph-dim);'>{mean_rsi:.2f}</b>"
        )
    st.markdown(
        "<div style='font-size:0.8rem; color:var(--aph-dim); margin:0.4rem 0 0.6rem 0;'>"
        f"<b>Reactive Strength Profile</b> · {' · '.join(info_bits)} "
        "(Flight Time method)"
        "</div>",
        unsafe_allow_html=True,
    )

    rows_html: list[str] = []
    for z in zones:
        is_best = best_zone is not None and z["name"] == best_zone["name"]
        is_mean = mean_zone is not None and z["name"] == mean_zone["name"]
        is_active = is_best or is_mean

        bg = f"{z['color']}22" if is_active else "rgba(15,23,42,0.05)"
        border = (
            f"1px solid {z['color']}" if is_active
            else "1px solid rgba(15,23,42,0.10)"
        )

        badges = ""
        if is_best:
            badges += (
                f"<span style='background:{z['color']}; color:#0E0E10; "
                f"font-size:0.6rem; font-weight:700; padding:0.1rem 0.4rem; "
                f"border-radius:3px; margin-left:0.4rem; letter-spacing:0.05em; "
                f"text-transform:uppercase;'>Peak rep</span>"
            )
        if is_mean:
            badges += (
                f"<span style='background:transparent; color:{z['color']}; "
                f"border:1px solid {z['color']}; "
                f"font-size:0.6rem; font-weight:700; padding:0.05rem 0.35rem; "
                f"border-radius:3px; margin-left:0.4rem; letter-spacing:0.05em; "
                f"text-transform:uppercase;'>Best mean</span>"
            )

        rows_html.append(
            f"<div style='display:grid; grid-template-columns:160px 1fr 90px; "
            f"gap:0.8rem; padding:0.55rem 0.75rem; background:{bg}; "
            f"border:{border}; border-radius:6px; margin-bottom:0.3rem; "
            f"align-items:center;'>"
            f"<div><span style='color:{z['color']}; font-weight:700; "
            f"font-size:0.85rem;'>{z['name']}</span>{badges}</div>"
            f"<div style='font-size:0.78rem; color:var(--aph-ink-2);'>"
            f"<b>{z['summary']}</b><br>"
            f"<span style='color:var(--aph-dim);'>{z['desc']}</span></div>"
            f"<div style='font-family:ui-monospace,monospace; "
            f"font-size:0.85rem; color:var(--aph-ink); text-align:right; "
            f"font-weight:600;'>{z['label']}</div>"
            f"</div>"
        )
    st.markdown("".join(rows_html), unsafe_allow_html=True)
    if sex == "female":
        # Tabela kobieca to przesunięte progi męskie — nie ma dla niej
        # publikacji, więc nie podpisujemy jej cudzym źródłem.
        st.caption(
            "Progi orientacyjne — brak opublikowanych norm RSI dla kobiet. "
            "Powstały przez przesunięcie tabeli męskiej w dół; traktuj jako "
            "punkt odniesienia, nie jako normę."
        )
    else:
        st.caption("Źródło: Flanagan, E. (2025) via Instagram @eamonn.flanagan")


def _render_female_cmj_profile_match(cmj_df: pd.DataFrame) -> None:
    """Dopasowanie zawodniczki do 1 z 3 profili neuromięśniowych (McLean
    Performance, n=192 atletek uniwersyteckich). Metryki z najlepszej CMJ
    w historii (max JH). Pokazywane TYLKO dla kobiet (gate w caller)."""
    athlete_vals = _female_profile_metrics_from_best_cmj(cmj_df)
    if not athlete_vals:
        return
    ranking = _classify_female_cmj_profile(athlete_vals)
    if not ranking:
        return

    best = ranking[0]
    prof = best["profile"]
    sim_by_key = {r["profile"]["key"]: r["similarity_pct"] for r in ranking}
    date_str = (
        athlete_vals["_date"].strftime("%Y-%m-%d")
        if athlete_vals.get("_date") is not None else "—"
    )
    meta = {k: (lbl, unit, dec, hb) for k, lbl, unit, dec, hb in FEMALE_PROFILE_METRICS}
    # Grupowanie metryk w sekcje — jak na kartach McLean (Instagram)
    tile_sections = [
        ("PERFORMANCE", ["jh", "pp", "bp"]),
        ("TIMING & STRATEGY", ["ct", "stiff"]),
        ("LEG STRENGTH", ["conc", "ecc"]),
    ]
    target_prof = next(
        (p for p in FEMALE_CMJ_PROFILES if p.get("target")), FEMALE_CMJ_PROFILES[0],
    )

    st.markdown("---")
    st.markdown(
        "<div style='font-family:var(--aph-mono); font-size:11px; "
        "letter-spacing:0.16em; text-transform:uppercase; color:var(--aph-mute); "
        "margin-bottom:10px;'>🧬 Profil neuromięśniowy (atletki) — normy McLean</div>",
        unsafe_allow_html=True,
    )

    # ── 3 KAFELKI PROFILI obok siebie ───────────────────────────────────
    # Dopasowany: kolorowa ramka + badge "TWÓJ PROFIL". Pozostałe przygaszone.
    cards_html = []
    for p in FEMALE_CMJ_PROFILES:
        is_match = p["key"] == prof["key"]
        sim = sim_by_key.get(p["key"], 0)
        target_tag = (
            "<div style='font-family:var(--aph-mono); font-size:8.5px; "
            "letter-spacing:0.1em; color:#22c55e; margin-top:2px;'>"
            "TARGET PROFILE ✓</div>"
            if p["target"] else ""
        )
        if is_match:
            match_badge = (
                f"<div style='font-family:var(--aph-mono); font-size:10px; "
                f"letter-spacing:0.08em; background:{p['color']}; color:#fff; "
                f"padding:4px 10px; border-radius:99px; font-weight:700; "
                f"white-space:nowrap;'>TWÓJ PROFIL · {sim}%</div>"
            )
        else:
            match_badge = (
                f"<div style='font-family:var(--aph-mono); font-size:10px; "
                f"color:var(--aph-mute); white-space:nowrap;'>{sim}%</div>"
            )
        secs_html = []
        for sec_name, keys in tile_sections:
            rows = []
            for k in keys:
                lbl, unit, dec, _hb = meta[k]
                pv_txt = f"{p['values'][k]:.{dec}f}".replace(".", ",")
                rows.append(
                    f"<div style='display:flex; justify-content:space-between; "
                    f"align-items:baseline; gap:8px; padding:2.5px 0;'>"
                    f"<span style='font-family:var(--aph-text); font-size:11.5px; "
                    f"color:var(--aph-dim);'>{lbl}</span>"
                    f"<span style='font-family:var(--aph-mono); font-size:12.5px; "
                    f"font-weight:700; color:var(--aph-ink); white-space:nowrap;'>"
                    f"{pv_txt} <span style='font-size:9.5px; font-weight:400; "
                    f"color:var(--aph-mute);'>{unit}</span></span>"
                    f"</div>"
                )
            secs_html.append(
                f"<div style='border-top:1px solid var(--aph-line); "
                f"margin-top:8px; padding-top:7px;'>"
                f"<div style='font-family:var(--aph-mono); font-size:8.5px; "
                f"letter-spacing:0.14em; color:{p['color']}; "
                f"margin-bottom:3px;'>{sec_name}</div>"
                f"{''.join(rows)}</div>"
            )
        border = (
            f"2px solid {p['color']}" if is_match
            else "1px solid var(--aph-line)"
        )
        bg = (
            f"linear-gradient(160deg, {p['color']}0f, transparent 55%)"
            if is_match else "var(--aph-card)"
        )
        shadow = (
            f"0 10px 28px -14px {p['color']}66" if is_match
            else "0 1px 2px rgba(14,14,16,0.04)"
        )
        opacity = "1" if is_match else "0.72"
        cards_html.append(
            f"<div style='flex:1 1 0; min-width:215px; border:{border}; "
            f"border-radius:14px; padding:14px 16px; background:{bg}; "
            f"box-shadow:{shadow}; opacity:{opacity}; box-sizing:border-box;'>"
            f"<div style='display:flex; justify-content:space-between; "
            f"align-items:flex-start; gap:8px;'>"
            f"<div><div style='font-size:21px; line-height:1.2;'>{p['emoji']}</div>"
            f"<div style='font-family:var(--aph-display); font-size:16.5px; "
            f"letter-spacing:-0.01em; color:var(--aph-ink); margin-top:3px; "
            f"white-space:nowrap;'>{p['name']}</div>{target_tag}</div>"
            f"{match_badge}</div>"
            f"{''.join(secs_html)}</div>"
        )
    st.markdown(
        f"<div style='display:flex; gap:12px; flex-wrap:wrap; "
        f"align-items:stretch; margin-bottom:16px;'>{''.join(cards_html)}</div>",
        unsafe_allow_html=True,
    )

    # ── WYNIKI ZAWODNICZKI — osadzenie z najlepszej CMJ + przypisanie ───
    result_tiles = []
    for key, lbl, unit, dec, hb in FEMALE_PROFILE_METRICS:
        av = athlete_vals.get(key)
        has_val = av is not None and pd.notna(av)
        tv = target_prof["values"][key]
        tv_txt = f"{tv:.{dec}f}".replace(".", ",")
        goal_sign = "≥" if hb else "≤"
        if has_val:
            av_txt = f"{av:.{dec}f}".replace(".", ",")
            # Kierunkowo: dla CT (hb=False) niższy czas = lepszy → 0,60 ≤ 0,82 = ✓
            meets = (av >= tv) if hb else (av <= tv)
            v_color = "#22c55e" if meets else "#e58c3a"
            badge = (
                "<span style='font-size:12px; font-weight:700;'>✓</span>"
                if meets else
                f"<span style='font-size:12px; font-weight:700;'>{'↑' if hb else '↓'}</span>"
            )
        else:
            av_txt, v_color, badge = "—", "var(--aph-mute)", ""
        result_tiles.append(
            f"<div style='background:var(--aph-card); border:1px solid var(--aph-line); "
            f"border-radius:10px; padding:9px 11px;'>"
            f"<div style='font-family:var(--aph-mono); font-size:8.5px; "
            f"letter-spacing:0.1em; text-transform:uppercase; "
            f"color:var(--aph-mute); margin-bottom:3px; white-space:nowrap; "
            f"overflow:hidden; text-overflow:ellipsis;'>{lbl}</div>"
            f"<div style='display:flex; align-items:baseline; gap:5px; "
            f"color:{v_color};'>"
            f"<span style='font-family:var(--aph-mono); font-size:19px; "
            f"font-weight:800;'>{av_txt}</span>"
            f"<span style='font-size:9.5px; color:var(--aph-mute);'>{unit}</span>"
            f"{badge}</div>"
            f"<div style='font-family:var(--aph-mono); font-size:9px; "
            f"color:var(--aph-mute); margin-top:2px;'>cel {goal_sign} {tv_txt}</div>"
            f"</div>"
        )
    st.markdown(
        f"""
        <div style="border:1px solid var(--aph-line); border-radius:14px;
                    padding:14px 16px; background:var(--aph-card);">
          <div style="display:flex; justify-content:space-between; align-items:center;
                      gap:10px; flex-wrap:wrap; margin-bottom:10px;">
            <div style="font-family:var(--aph-mono); font-size:10px;
                        letter-spacing:0.14em; text-transform:uppercase;
                        color:var(--aph-mute);">
              Wyniki — najlepsza CMJ ({date_str})
            </div>
            <div style="font-family:var(--aph-mono); font-size:11px; font-weight:700;
                        color:{prof['color']}; white-space:nowrap;">
              → {prof['emoji']} {prof['name']} ({best['similarity_pct']}%)
            </div>
          </div>
          <div style="display:grid;
                      grid-template-columns:repeat(auto-fit, minmax(128px, 1fr));
                      gap:8px;">{''.join(result_tiles)}</div>
          <div style="font-family:var(--aph-text); font-size:12.5px;
                      color:var(--aph-dim); margin-top:12px; line-height:1.5;
                      border-top:1px solid var(--aph-line); padding-top:10px;">
            {prof['desc']}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.caption(
        "✓ zielone = osiąga profil docelowy STRONG & FAST · ↑/↓ pomarańczowe = "
        "kierunek poprawy do celu. Contraction Time: krótszy = lepszy "
        "(np. 0,60 s lepsze niż 0,82 s), stąd cel ≤. "
        "Wszystkie wartości z JEDNEGO skoku — najlepszej CMJ w historii (max JH). "
        "Klasyfikacja: nearest-centroid (dystans znormalizowany do 3 profili). "
        "Źródło norm: McLean Performance — 192 atletki uniwersyteckie, 5 sportów "
        "(via Instagram @mccleanperformance). Braking Power = Ecc. Deceleration "
        "Mean Power / BM; Stiffness = Lower-Limb Stiffness / masa ciała."
    )


def _render_profile_pb_section(
    splits: dict[str, pd.DataFrame], test_type: str,
) -> None:
    """Sekcja personal bests dla jednego typu testu — wewnątrz dialogu profilu."""
    if test_type == "CMJ":
        pbs: list[tuple[str, float, str, int]] = []
        jh = _best_pb_for(splits, "CMJ", "Jump Height")
        if jh:
            pbs.append(("Jump Height (peak)", jh[0], jh[1], 1))
        mrsi = _best_pb_for(splits, "CMJ", "RSI-mod")
        if mrsi:
            pbs.append(("RSI-mod (peak)", mrsi[0], mrsi[1], 2))
        if not pbs:
            st.info("Brak dopasowanych metryk dla tego typu testu.")
            return
        _render_pb_tiles(pbs)

        # 🧬 Profil neuromięśniowy atletki (McLean) — tylko dla kobiet.
        # Gdy płeć nieustawiona — pokaż hint jak aktywować.
        sex = _current_athlete_sex()
        if sex == "female":
            _render_female_cmj_profile_match(splits["CMJ"])
        elif not sex:
            st.caption(
                "💡 Ustaw płeć w profilu zawodnika (✏ Edit), aby zobaczyć "
                "dopasowanie do profili neuromięśniowych atletek "
                "(STRONG & FAST / WEAK & FAST / WEAK & SLOW)."
            )

    elif test_type == "HOP":
        # Per-rep dane: Best RSI = peak single rep, Best Mean RSI = top 5 z testu
        # (zgodnie ze standardową interpretacją 10/5 Hop Test).
        hop_df = splits["HOP"]
        RSI_COL = "RSI (Flight/Contact Time)"
        JH_COL  = "Jump Height (Flight Time)"
        CT_COL  = "Contact Time [ms] "
        TOP_N = 5

        rsi_vals = pd.to_numeric(hop_df.get(RSI_COL, pd.Series(dtype=float)),
                                  errors="coerce")
        jh_vals  = pd.to_numeric(hop_df.get(JH_COL, pd.Series(dtype=float)),
                                  errors="coerce")
        ct_vals  = pd.to_numeric(hop_df.get(CT_COL, pd.Series(dtype=float)),
                                  errors="coerce")

        pbs = []
        best_rsi_val = float("nan")
        mean_rsi_val = float("nan")

        # Best RSI (peak single rep)
        if rsi_vals.notna().any():
            bi = rsi_vals.idxmax()
            best_rsi_val = float(rsi_vals.loc[bi])
            pbs.append(("Best RSI (peak rep)", best_rsi_val, "", 2))
            if jh_vals.notna().any():
                pbs.append(("JH @ Best", float(jh_vals.loc[bi]), "cm", 1))
            if ct_vals.notna().any():
                pbs.append(("CT @ Best", float(ct_vals.loc[bi]), "ms", 0))

        # Best Mean RSI (top 5 per test) — najlepszy test po mean RSI
        if "TestId" in hop_df.columns and rsi_vals.notna().any():
            per_test = []
            for test_id, grp in hop_df.groupby("TestId"):
                rsi_g = pd.to_numeric(grp.get(RSI_COL), errors="coerce").dropna()
                if rsi_g.empty:
                    continue
                top_idx = rsi_g.sort_values(ascending=False).head(TOP_N).index
                jh_g = pd.to_numeric(grp.loc[top_idx].get(JH_COL), errors="coerce")
                ct_g = pd.to_numeric(grp.loc[top_idx].get(CT_COL), errors="coerce")
                per_test.append({
                    "mean_rsi": float(rsi_g.loc[top_idx].mean()),
                    "mean_jh":  float(jh_g.mean()) if jh_g.notna().any() else None,
                    "mean_ct":  float(ct_g.mean()) if ct_g.notna().any() else None,
                })
            if per_test:
                best_t = max(per_test, key=lambda r: r["mean_rsi"])
                mean_rsi_val = best_t["mean_rsi"]
                pbs.append(("Best Mean RSI (top 5/test)", mean_rsi_val, "", 2))
                if best_t["mean_jh"] is not None and not pd.isna(best_t["mean_jh"]):
                    pbs.append(("Mean JH (top 5)", best_t["mean_jh"], "cm", 1))
                if best_t["mean_ct"] is not None and not pd.isna(best_t["mean_ct"]):
                    pbs.append(("Mean CT (top 5)", best_t["mean_ct"], "ms", 0))

        if not pbs and pd.isna(best_rsi_val) and pd.isna(mean_rsi_val):
            st.info("Brak dopasowanych metryk dla tego typu testu.")
            return

        _render_pb_tiles(pbs)
        if not (pd.isna(best_rsi_val) and pd.isna(mean_rsi_val)):
            st.markdown("---")
            _render_rsi_zone_table(best_rsi_val, mean_rsi_val)

    elif test_type == "DJ":
        # Analogicznie do HOP, ale:
        # - TOP_N = 3 (3 drop jumpy)
        # - Grupowanie per DZIEŃ (VALD DJ = 1 rep/test, więc per-test top 3 = top 1)
        # - Inna nazwa kolumny RSI ('RSI (Flight Time/Contact Time)' z 'Time' w środku)
        # - CT scale fix (sek → ms) — VALD eksportuje DJ CT w sekundach
        dj_df = splits["DJ"].copy()
        RSI_COL = "RSI (Flight Time/Contact Time)"
        JH_COL  = "Jump Height (Flight Time)"
        CT_COL  = "Contact Time [ms] "
        TOP_N = 3

        # Auto-konwersja CT z sekund na ms gdy max < 5
        if CT_COL in dj_df.columns:
            ct_raw = pd.to_numeric(dj_df[CT_COL], errors="coerce")
            if ct_raw.notna().any() and ct_raw.dropna().max() < 5:
                dj_df[CT_COL] = ct_raw * 1000

        # PB liczone OSOBNO per wysokość spadania (Drop Height z VALD) —
        # RSI z 30 cm i 40 cm to inne zadania, wspólny ranking by kłamał.
        overall_best_rsi = float("nan")
        overall_mean_rsi = float("nan")
        any_rendered = False
        for hv, sub in _dj_height_groups(dj_df):
            rsi_vals = pd.to_numeric(sub.get(RSI_COL, pd.Series(dtype=float)),
                                      errors="coerce")
            jh_vals  = pd.to_numeric(sub.get(JH_COL, pd.Series(dtype=float)),
                                      errors="coerce")
            ct_vals  = pd.to_numeric(sub.get(CT_COL, pd.Series(dtype=float)),
                                      errors="coerce")
            if rsi_vals.isna().all():
                continue
            h_lbl = _dj_height_label(hv)
            pbs = []

            # Best RSI tej wysokości (peak single rep)
            bi = rsi_vals.idxmax()
            best_rsi_val = float(rsi_vals.loc[bi])
            pbs.append((f"Best RSI ⬇{h_lbl}", best_rsi_val, "", 2))
            if bi in jh_vals.index and pd.notna(jh_vals.loc[bi]):
                pbs.append(("JH @ Best", float(jh_vals.loc[bi]), "cm", 1))
            if bi in ct_vals.index and pd.notna(ct_vals.loc[bi]):
                pbs.append(("CT @ Best", float(ct_vals.loc[bi]), "ms", 0))

            # Best Mean RSI tej wysokości (top 3 per dzień; najlepszy dzień)
            mean_rsi_val = float("nan")
            if "Date" in sub.columns:
                days = pd.to_datetime(sub["Date"], errors="coerce").dt.date
                per_day = []
                for day, grp in sub.groupby(days):
                    rsi_g = pd.to_numeric(grp.get(RSI_COL), errors="coerce").dropna()
                    if rsi_g.empty:
                        continue
                    top_idx = rsi_g.sort_values(ascending=False).head(TOP_N).index
                    jh_g = pd.to_numeric(grp.loc[top_idx].get(JH_COL), errors="coerce")
                    ct_g = pd.to_numeric(grp.loc[top_idx].get(CT_COL), errors="coerce")
                    per_day.append({
                        "mean_rsi": float(rsi_g.loc[top_idx].mean()),
                        "mean_jh":  float(jh_g.mean()) if jh_g.notna().any() else None,
                        "mean_ct":  float(ct_g.mean()) if ct_g.notna().any() else None,
                    })
                if per_day:
                    best_d = max(per_day, key=lambda r: r["mean_rsi"])
                    mean_rsi_val = best_d["mean_rsi"]
                    pbs.append((f"Best Mean RSI (top 3/dzień)", mean_rsi_val, "", 2))
                    if best_d["mean_jh"] is not None and not pd.isna(best_d["mean_jh"]):
                        pbs.append(("Mean JH (top 3)", best_d["mean_jh"], "cm", 1))
                    if best_d["mean_ct"] is not None and not pd.isna(best_d["mean_ct"]):
                        pbs.append(("Mean CT (top 3)", best_d["mean_ct"], "ms", 0))

            st.markdown(
                f"<div style='display:inline-flex; align-items:center; gap:6px; "
                f"font-family:ui-monospace,monospace; font-size:0.72rem; "
                f"font-weight:700; letter-spacing:0.1em; text-transform:uppercase; "
                f"color:var(--aph-ink); background:rgba(14,14,16,0.06); "
                f"border-radius:99px; padding:3px 12px; margin:8px 0 4px;'>"
                f"⬇ drop z {h_lbl} <span style='font-weight:400; "
                f"color:var(--aph-mute); text-transform:none; letter-spacing:0;'>"
                f"· {int(rsi_vals.notna().sum())} skok(ów)</span></div>",
                unsafe_allow_html=True,
            )
            _render_pb_tiles(pbs)
            any_rendered = True
            # Globalny best (do tabeli stref RSI) — z najwyższej wartości
            # niezależnie od wysokości (strefy Flanagana to ogólna referencja).
            if pd.isna(overall_best_rsi) or best_rsi_val > overall_best_rsi:
                overall_best_rsi = best_rsi_val
            if not pd.isna(mean_rsi_val) and (
                pd.isna(overall_mean_rsi) or mean_rsi_val > overall_mean_rsi
            ):
                overall_mean_rsi = mean_rsi_val

        if not any_rendered:
            st.info("Brak dopasowanych metryk dla tego typu testu.")
            return

        # Te same strefy RSI (Flight Time method) — wspólne dla HOP i DJ
        if not (pd.isna(overall_best_rsi) and pd.isna(overall_mean_rsi)):
            st.markdown("---")
            _render_rsi_zone_table(
                overall_best_rsi, overall_mean_rsi,
                mean_label="Best Mean RSI (top 3/dzień)",
            )

    else:
        # Fallback dla SJ/IMTP/UNKNOWN — pokaż wszystkie performance metryki tego typu
        pbs = []
        for m in METRICS_BY_TEST.get(test_type, []):
            if m.section != "performance":
                continue
            res = _best_pb_for(splits, test_type, m.label)
            if res is not None:
                pbs.append((f"{m.label} (peak)", res[0], res[1], 2))
        if not pbs:
            st.info("Brak dopasowanych metryk dla tego typu testu.")
            return
        _render_pb_tiles(pbs)


def _render_eur_section(splits: dict[str, pd.DataFrame]) -> None:
    """Sekcja EUR (Eccentric Utilization Ratio) — wymaga CMJ i SJ w bazie.
    EUR = best CMJ Jump Height / best SJ Jump Height (McGuigan et al. 2006)."""
    cmj_jh = _best_pb_for(splits, "CMJ", "Jump Height")
    sj_jh = _best_pb_for(splits, "SJ", "Jump Height")
    if not cmj_jh or not sj_jh:
        st.info(
            "EUR wymaga **i CMJ i SJ** w bazie — dorzuć brakujący test żeby "
            "zobaczyć wskaźnik."
        )
        return
    cmj_val = cmj_jh[0]
    sj_val = sj_jh[0]
    if sj_val <= 0:
        st.warning("Best SJ Jump Height = 0 — nie da się policzyć EUR.")
        return
    eur = cmj_val / sj_val
    zone = _eur_zone(eur)

    st.markdown(
        "<div style='font-size:0.85rem; font-weight:600; "
        "letter-spacing:0.08em; text-transform:uppercase; "
        "color:var(--aph-dim); margin-bottom:0.6rem;'>"
        "Eccentric Utilization Ratio"
        "</div>",
        unsafe_allow_html=True,
    )

    # Główny wskaźnik + komponenty
    cols = st.columns([1.2, 1, 1])
    zone_color = zone["color"] if zone else "#5E5E64"  # mute dim
    zone_name = zone["name"] if zone else "—"
    with cols[0]:
        st.markdown(
            f"<div style='font-size:0.72rem; color:var(--aph-mute); "
            f"text-transform:uppercase; letter-spacing:0.05em; "
            f"margin-bottom:0.1rem;'>EUR (CMJ ÷ SJ)</div>"
            f"<div style='font-size:2.2rem; font-weight:800; "
            f"color:{zone_color}; line-height:1;'>{eur:.2f}</div>"
            f"<div style='font-size:0.8rem; color:{zone_color}; "
            f"font-weight:600; margin-top:0.15rem;'>{zone_name}</div>",
            unsafe_allow_html=True,
        )
    with cols[1]:
        st.markdown(
            "<div style='font-size:0.72rem; color:var(--aph-mute); "
            "text-transform:uppercase; letter-spacing:0.05em; "
            "margin-bottom:0.1rem;'>Best CMJ JH</div>"
            f"<div style='font-size:1.55rem; font-weight:700; "
            f"color:var(--aph-ink); line-height:1.1;'>{cmj_val:.1f}"
            "<span style='font-size:0.85rem; font-weight:500; "
            "color:var(--aph-dim); margin-left:0.2rem;'>cm</span></div>",
            unsafe_allow_html=True,
        )
    with cols[2]:
        st.markdown(
            "<div style='font-size:0.72rem; color:var(--aph-mute); "
            "text-transform:uppercase; letter-spacing:0.05em; "
            "margin-bottom:0.1rem;'>Best SJ JH</div>"
            f"<div style='font-size:1.55rem; font-weight:700; "
            f"color:var(--aph-ink); line-height:1.1;'>{sj_val:.1f}"
            "<span style='font-size:0.85rem; font-weight:500; "
            "color:var(--aph-dim); margin-left:0.2rem;'>cm</span></div>",
            unsafe_allow_html=True,
        )

    # Tabela decyzyjna EUR — 4 kolumny zgodnie z eur_decision_table_v2_pl.html
    st.markdown(
        "<div style='font-size:0.78rem; color:var(--aph-dim); "
        "margin:1.1rem 0 0.5rem 0;'><b>Tabela decyzyjna</b></div>",
        unsafe_allow_html=True,
    )

    # Nagłówek tabeli
    header_html = (
        "<div style='display:grid; grid-template-columns:130px 1fr 1.2fr 150px; "
        "gap:0; font-size:0.7rem; font-weight:600; "
        "letter-spacing:0.08em; text-transform:uppercase; color:var(--aph-dim); "
        "border:1px solid rgba(14,14,16,0.10); border-bottom:none; "
        "border-top-left-radius:8px; border-top-right-radius:8px; "
        "background:rgba(14,14,16,0.04);'>"
        "<div style='padding:0.55rem 0.75rem; border-right:1px solid rgba(14,14,16,0.06);'>Zakres EUR</div>"
        "<div style='padding:0.55rem 0.75rem; border-right:1px solid rgba(14,14,16,0.06);'>Klasyfikacja</div>"
        "<div style='padding:0.55rem 0.75rem; border-right:1px solid rgba(14,14,16,0.06);'>Główny focus treningu</div>"
        "<div style='padding:0.55rem 0.75rem;'>Test uzupełniający</div>"
        "</div>"
    )

    rows_html: list[str] = []
    last_idx = len(EUR_ZONES) - 1
    for i, z in enumerate(EUR_ZONES):
        is_active = zone is not None and z["name"] == zone["name"]
        bg = f"{z['color']}1f" if is_active else "rgba(15,23,42,0.03)"
        border_bottom = (
            "border-bottom:1px solid rgba(15,23,42,0.10);"
            if i < last_idx else ""
        )
        radius = (
            "border-bottom-left-radius:8px; border-bottom-right-radius:8px;"
            if i == last_idx else ""
        )
        badge = (
            f"<span style='background:{z['color']}; color:#0E0E10; "
            f"font-size:0.58rem; font-weight:700; padding:0.1rem 0.4rem; "
            f"border-radius:3px; margin-left:0.4rem; letter-spacing:0.05em; "
            f"text-transform:uppercase;'>YOU</span>"
            if is_active else ""
        )

        rows_html.append(
            f"<div style='display:grid; grid-template-columns:130px 1fr 1.2fr 150px; "
            f"gap:0; background:{bg}; border-left:1px solid rgba(15,23,42,0.10); "
            f"border-right:1px solid rgba(15,23,42,0.10); {border_bottom} {radius}'>"
            # Kolumna 1: Zakres EUR z lewym paskiem koloru
            f"<div style='padding:0.7rem 0.75rem; border-left:4px solid {z['color']}; "
            f"border-right:1px solid rgba(15,23,42,0.05); "
            f"display:flex; flex-direction:column; gap:3px;'>"
            f"<div style='font-family:ui-monospace,monospace; font-size:0.9rem; "
            f"font-weight:600; color:var(--aph-ink);'>{z['label']}</div>"
            f"<div style='font-size:0.68rem; color:var(--aph-mute);'>{z['sub_label']}</div>"
            f"</div>"
            # Kolumna 2: Klasyfikacja + krótki opis
            f"<div style='padding:0.7rem 0.75rem; border-right:1px solid rgba(15,23,42,0.05); "
            f"font-size:0.78rem; line-height:1.4;'>"
            f"<div style='font-weight:600; color:{z['color']}; margin-bottom:3px;'>"
            f"{z['name']}{badge}</div>"
            f"<div style='color:var(--aph-dim); font-size:0.72rem;'>{z['desc']}</div>"
            f"</div>"
            # Kolumna 3: Focus treningu
            f"<div style='padding:0.7rem 0.75rem; border-right:1px solid rgba(15,23,42,0.05); "
            f"font-size:0.76rem; line-height:1.45; color:var(--aph-ink-2);'>{z['focus']}</div>"
            # Kolumna 4: Test uzupełniający
            f"<div style='padding:0.7rem 0.75rem; font-size:0.74rem; "
            f"line-height:1.45; color:var(--aph-dim);'>{z['next_test']}</div>"
            f"</div>"
        )
    st.markdown(header_html + "".join(rows_html), unsafe_allow_html=True)

    st.caption(
        "⚠️ EUR sam w sobie jest niewystarczający — zawsze interpretuj razem "
        "z absolutnymi wartościami CMJ i SJ. Dwóch zawodników z tym samym EUR "
        "może mieć dramatycznie różne capacity (np. 50 cm CMJ vs 20 cm CMJ)."
    )
    st.caption("Wzór: McGuigan et al. (2006)")


def _best_cmj_peak_force_n(cmj_df: pd.DataFrame) -> tuple[float, str] | None:
    """Best CMJ Peak Force (Concentric Peak Force) w N + data tego rep'a.
    UWAGA: w CMJ_PERFORMANCE nie ma dedicated MetricDef dla 'Concentric Peak Force'
    bo to nie jest key tile — fetch'ujemy ad-hoc po nazwie kolumny."""
    if cmj_df is None or cmj_df.empty:
        return None
    col = "Concentric Peak Force"
    if col not in cmj_df.columns:
        return None
    vals = pd.to_numeric(cmj_df[col], errors="coerce")
    if not vals.notna().any():
        return None
    bi = vals.idxmax()
    val = float(vals.loc[bi])
    date_str = "—"
    if "Date" in cmj_df.columns:
        try:
            date_str = pd.to_datetime(cmj_df.loc[bi, "Date"]).strftime("%-d %b · %H:%M")
        except Exception:
            pass
    return val, date_str


def _best_imtp_peak_force_n(imtp_df: pd.DataFrame) -> tuple[float, str] | None:
    """Best IMTP Peak Vertical Force w N + data."""
    if imtp_df is None or imtp_df.empty:
        return None
    col = "Peak Vertical Force"
    if col not in imtp_df.columns:
        return None
    vals = pd.to_numeric(imtp_df[col], errors="coerce")
    if not vals.notna().any():
        return None
    bi = vals.idxmax()
    val = float(vals.loc[bi])
    date_str = "—"
    if "Date" in imtp_df.columns:
        try:
            date_str = pd.to_datetime(imtp_df.loc[bi, "Date"]).strftime("%-d %b · %H:%M")
        except Exception:
            pass
    return val, date_str


def _render_dsi_section(splits: dict[str, pd.DataFrame]) -> None:
    """Sekcja DSI (Dynamic Strength Index) — wymaga CMJ i IMTP w bazie.
    DSI = best CMJ Concentric Peak Force [N] / best IMTP Peak Force [N].
    Wartości absolutne (N), bez normalizacji do BM. Sheppard 2011."""
    cmj_pf = _best_cmj_peak_force_n(splits.get("CMJ", pd.DataFrame()))
    imtp_pf = _best_imtp_peak_force_n(splits.get("IMTP", pd.DataFrame()))
    if not cmj_pf or not imtp_pf:
        missing = []
        if not cmj_pf:
            missing.append("CMJ")
        if not imtp_pf:
            missing.append("IMTP")
        st.info(
            f"**Brak wystarczających danych.**  \n"
            f"DSI = best CMJ Peak Force [N] ÷ best IMTP Peak Force [N]. "
            f"Brakuje testów: **{', '.join(missing)}**."
        )
        return
    cmj_val, cmj_date = cmj_pf
    imtp_val, imtp_date = imtp_pf
    if imtp_val <= 0:
        st.warning("Best IMTP Peak Force = 0 — nie da się policzyć DSI.")
        return
    dsi = cmj_val / imtp_val
    zone = _dsi_zone(dsi)

    st.markdown(
        "<div style='font-size:0.85rem; font-weight:600; "
        "letter-spacing:0.08em; text-transform:uppercase; "
        "color:var(--aph-dim); margin-bottom:0.6rem;'>"
        "Dynamic Strength Index"
        "</div>",
        unsafe_allow_html=True,
    )

    cols = st.columns([1.2, 1, 1])
    zone_color = zone["color"] if zone else "#5E5E64"
    zone_name = zone["name"] if zone else "—"
    with cols[0]:
        st.markdown(
            f"<div style='font-size:0.72rem; color:var(--aph-mute); "
            f"text-transform:uppercase; letter-spacing:0.05em; "
            f"margin-bottom:0.1rem;'>DSI (CMJ ÷ IMTP)</div>"
            f"<div style='font-size:2.2rem; font-weight:800; "
            f"color:{zone_color}; line-height:1;'>{dsi:.2f}</div>"
            f"<div style='font-size:0.8rem; color:{zone_color}; "
            f"font-weight:600; margin-top:0.15rem;'>{zone_name}</div>",
            unsafe_allow_html=True,
        )
    with cols[1]:
        st.markdown(
            "<div style='font-size:0.72rem; color:var(--aph-mute); "
            "text-transform:uppercase; letter-spacing:0.05em; "
            "margin-bottom:0.1rem;'>Best CMJ Peak Force</div>"
            f"<div style='font-size:1.55rem; font-weight:700; "
            f"color:var(--aph-ink); line-height:1.1;'>{cmj_val:.0f}"
            "<span style='font-size:0.85rem; font-weight:500; "
            "color:var(--aph-dim); margin-left:0.2rem;'>N</span></div>"
            f"<div style='font-size:0.65rem; color:var(--aph-mute); "
            f"margin-top:0.15rem;'>📅 {cmj_date}</div>",
            unsafe_allow_html=True,
        )
    with cols[2]:
        st.markdown(
            "<div style='font-size:0.72rem; color:var(--aph-mute); "
            "text-transform:uppercase; letter-spacing:0.05em; "
            "margin-bottom:0.1rem;'>Best IMTP Peak Force</div>"
            f"<div style='font-size:1.55rem; font-weight:700; "
            f"color:var(--aph-ink); line-height:1.1;'>{imtp_val:.0f}"
            "<span style='font-size:0.85rem; font-weight:500; "
            "color:var(--aph-dim); margin-left:0.2rem;'>N</span></div>"
            f"<div style='font-size:0.65rem; color:var(--aph-mute); "
            f"margin-top:0.15rem;'>📅 {imtp_date}</div>",
            unsafe_allow_html=True,
        )

    # Tabela decyzyjna DSI (identyczna struktura jak EUR)
    st.markdown(
        "<div style='font-size:0.78rem; color:var(--aph-dim); "
        "margin:1.1rem 0 0.5rem 0;'><b>Tabela decyzyjna</b></div>",
        unsafe_allow_html=True,
    )

    header_html = (
        "<div style='display:grid; grid-template-columns:130px 1fr 1.2fr 150px; "
        "gap:0; font-size:0.7rem; font-weight:600; "
        "letter-spacing:0.08em; text-transform:uppercase; color:var(--aph-dim); "
        "border:1px solid rgba(14,14,16,0.10); border-bottom:none; "
        "border-top-left-radius:8px; border-top-right-radius:8px; "
        "background:rgba(14,14,16,0.04);'>"
        "<div style='padding:0.55rem 0.75rem; border-right:1px solid rgba(14,14,16,0.06);'>Zakres DSI</div>"
        "<div style='padding:0.55rem 0.75rem; border-right:1px solid rgba(14,14,16,0.06);'>Klasyfikacja</div>"
        "<div style='padding:0.55rem 0.75rem; border-right:1px solid rgba(14,14,16,0.06);'>Główny focus treningu</div>"
        "<div style='padding:0.55rem 0.75rem;'>Test uzupełniający</div>"
        "</div>"
    )

    rows_html: list[str] = []
    last_idx = len(DSI_ZONES) - 1
    for i, z in enumerate(DSI_ZONES):
        is_active = zone is not None and z["name"] == zone["name"]
        bg = f"{z['color']}1f" if is_active else "rgba(15,23,42,0.03)"
        border_bottom = (
            "border-bottom:1px solid rgba(15,23,42,0.10);"
            if i < last_idx else ""
        )
        radius = (
            "border-bottom-left-radius:8px; border-bottom-right-radius:8px;"
            if i == last_idx else ""
        )
        badge = (
            f"<span style='background:{z['color']}; color:#0E0E10; "
            f"font-size:0.58rem; font-weight:700; padding:0.1rem 0.4rem; "
            f"border-radius:3px; margin-left:0.4rem; letter-spacing:0.05em; "
            f"text-transform:uppercase;'>YOU</span>"
            if is_active else ""
        )

        rows_html.append(
            f"<div style='display:grid; grid-template-columns:130px 1fr 1.2fr 150px; "
            f"gap:0; background:{bg}; border-left:1px solid rgba(15,23,42,0.10); "
            f"border-right:1px solid rgba(15,23,42,0.10); {border_bottom} {radius}'>"
            f"<div style='padding:0.7rem 0.75rem; border-left:4px solid {z['color']}; "
            f"border-right:1px solid rgba(15,23,42,0.05); "
            f"display:flex; flex-direction:column; gap:3px;'>"
            f"<div style='font-family:ui-monospace,monospace; font-size:0.9rem; "
            f"font-weight:600; color:var(--aph-ink);'>{z['label']}</div>"
            f"<div style='font-size:0.68rem; color:var(--aph-mute);'>{z['sub_label']}</div>"
            f"</div>"
            f"<div style='padding:0.7rem 0.75rem; border-right:1px solid rgba(15,23,42,0.05); "
            f"font-size:0.78rem; line-height:1.4;'>"
            f"<div style='font-weight:600; color:{z['color']}; margin-bottom:3px;'>"
            f"{z['name']}{badge}</div>"
            f"<div style='color:var(--aph-dim); font-size:0.72rem;'>{z['desc']}</div>"
            f"</div>"
            f"<div style='padding:0.7rem 0.75rem; border-right:1px solid rgba(15,23,42,0.05); "
            f"font-size:0.76rem; line-height:1.45; color:var(--aph-ink-2);'>{z['focus']}</div>"
            f"<div style='padding:0.7rem 0.75rem; font-size:0.74rem; "
            f"line-height:1.45; color:var(--aph-dim);'>{z['next_test']}</div>"
            f"</div>"
        )
    st.markdown(header_html + "".join(rows_html), unsafe_allow_html=True)

    st.caption(
        "⚠️ DSI to RATIO — interpretuj razem z absolutnymi wartościami. "
        "Wysokie DSI przy słabym IMTP ≠ to samo co wysokie DSI przy mocnym IMTP."
    )
    st.caption("Wzór: Sheppard et al. (2011), Comfort et al. (2018), Suchomel et al. (2020)")


@st.dialog("📊 NORMS", width="large")
def _athlete_profile_view_dialog(sections: list[str]) -> None:
    """Dialog z profilem zawodnika — personal bests per typ testu + EUR jako osobna zakładka."""
    splits = st.session_state.get("_profile_dialog_splits", {})
    if not splits or not sections:
        st.info("Brak testów do pokazania.")
        return

    def _label_for(section: str) -> str:
        # Krótkie etykiety — pełne nazwy ("CMJ — Counter Movement Jump",
        # "RSAIP — Run Specific Ankle Iso Push") rozpychały pasek zakładek
        # i wymuszały scroll w bok. Sam skrót wystarcza.
        if section == "HOP":
            return "10/5 HOP"
        return section  # CMJ / SJ / DJ / IMTP / RSAIP / RSKIP / EUR / DSI

    def _render_section(section: str) -> None:
        if section == "EUR":
            _render_eur_section(splits)
        elif section == "DSI":
            _render_dsi_section(splits)
        else:
            _render_profile_pb_section(splits, section)

    if len(sections) == 1:
        only = sections[0]
        st.markdown(f"### {_label_for(only)}")
        _render_section(only)
    else:
        tabs = st.tabs([_label_for(s) for s in sections])
        for tab, s in zip(tabs, sections):
            with tab:
                _render_section(s)


def _render_norms_chip(
    splits: dict[str, pd.DataFrame],
    *,
    key_suffix: str = "",
) -> None:
    """Klikalny chip 'NORMS' wyrównany z zakładkami CMJ/HOP/Overview po prawej.
    `key_suffix` — żeby rozróżnić button per tab (każdy test_type ma osobny render)."""
    test_keys = [t for t in ENABLED_TEST_TYPES if t in splits and not splits[t].empty]
    if not test_keys:
        return
    has_eur = (
        "CMJ" in splits and not splits["CMJ"].empty
        and "SJ" in splits and not splits["SJ"].empty
    )
    # DSI zawsze widoczne jako zakładka (jeśli jest jakikolwiek test w bazie) —
    # po kliknięciu pokaże komunikat "Brak wystarczających danych" gdy brak IMTP.
    # Tak Filip chce — żeby zawodnicy bez IMTP nadal wiedzieli że taki wskaźnik
    # istnieje i co go aktywuje.
    has_dsi = bool(test_keys)
    extras = (["EUR"] if has_eur else []) + (["DSI"] if has_dsi else [])
    sections = test_keys + extras

    if st.button(
        "📊 NORMS",
        key=f"btn_open_norms{key_suffix}",
        use_container_width=True,
        type="secondary",
        help="Personal bests + EUR + strefy RSI (M/K) — referencja do programowania.",
    ):
        st.session_state["_profile_dialog_splits"] = splits
        _athlete_profile_view_dialog(sections)


if __name__ == "__main__":
    main()
