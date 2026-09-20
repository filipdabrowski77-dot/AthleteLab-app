"""
Biblioteka zawodników — persystencja zmergowanych testów ForceDecks.

Lokalizacja:
- LOKALNY DEV: ~/Documents/ValdLibrary/library.parquet (jeśli istnieje)
- DEPLOY (Streamlit Cloud): data/library.parquet (commitowane w repo)

Pierwszy znaleziony plik wygrywa — pozwala działać identycznie lokalnie i na cloudzie.
- Jeden plik, wszyscy zawodnicy razem
- Schemat = ta sama struktura co DataFrame z merge_max_avg
- Dedupe na (Name, Date) — nowsze wpisy nadpisują
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import TypedDict

import pandas as pd


# Path detection: lokalny dev (Documents) > repo data/ (deploy)
_LOCAL_DIR = Path.home() / "Documents" / "ValdLibrary"
_REPO_DIR = Path(__file__).resolve().parent.parent / "data"

def _workspace_dir():
    """Drugi trener (sekret/env `workspace`): własny katalog na dane
    plikowe — bez biblioteki testów i profili zawodników z repo."""
    try:
        from .store import workspace
        w = workspace()
    except Exception:
        w = ""
    if not w:
        return None
    d = _REPO_DIR / f"ws_{w}"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:
        return None
    return d


_WS_DIR = _workspace_dir()
if _WS_DIR is not None:
    LIBRARY_DIR = _WS_DIR
elif (_LOCAL_DIR / "library.parquet").exists():
    LIBRARY_DIR = _LOCAL_DIR
elif (_REPO_DIR / "library.parquet").exists():
    LIBRARY_DIR = _REPO_DIR
else:
    # Brak danych — używamy lokalnej ścieżki jako default do zapisu
    LIBRARY_DIR = _LOCAL_DIR if _LOCAL_DIR.exists() else _REPO_DIR

LIBRARY_PATH = LIBRARY_DIR / "library.parquet"


def _atomic_to_parquet(df: pd.DataFrame) -> None:
    """Zapis parquet ATOMOWO: temp + os.replace (atomic rename na tym samym FS).
    Bez tego przerwany zapis (rerun Streamlita/kill/OOM/disk-full/restart kontenera)
    zostawia UCIĘTY single-file library.parquet — a load_library() pokazuje wtedy
    pustą bazę nieodróżnialnie od 'brak zawodników'. os.replace gwarantuje, że plik
    docelowy zawsze jest albo starą, albo nową pełną wersją — nigdy w połowie."""
    LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    tmp = LIBRARY_PATH.with_suffix(".parquet.tmp")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, LIBRARY_PATH)


class AthleteSummary(TypedDict):
    name: str
    n_tests: int
    last_test: pd.Timestamp | None


def _resolve_vald_duplicate_columns(df: pd.DataFrame) -> pd.DataFrame:
    """VALD CSV quirk: niektóre metryki są eksportowane DWA RAZY z tym samym
    nagłówkiem ale różnymi wartościami (np. raz w N, raz w N/kg). pandas przy
    read dodaje '.1' suffix dla drugiego wariantu. Konkretnie znany przypadek:

      'Force at Zero Velocity / BM [N/kg] '     mean=2082  ← surowe N, mylny header
      'Force at Zero Velocity / BM [N/kg] .1'   mean=25    ← prawidłowe /BM

    Heurystyka: jeśli istnieje para (X, X.1), porównujemy max wartości po abs.
    Gdy X.1 ma 10× mniejsze max — uznajemy że X to "surowa" wartość, a X.1
    jest "/BM" (lub innym podzieleniem). Wtedy DROP X i rename X.1 → X.

    Bezpieczne dla innych przypadków: jeśli max'y są podobne (X.1 to po prostu
    duplikat danych) — nic nie robimy. Filtruje tylko jednoznaczne unit mismatch.
    """
    pairs: list[tuple[str, str]] = []
    for c in df.columns:
        if c.endswith(".1"):
            base = c[:-2]
            if base in df.columns:
                pairs.append((base, c))

    for base, dup in pairs:
        try:
            v_base = pd.to_numeric(df[base], errors="coerce").abs().dropna()
            v_dup = pd.to_numeric(df[dup], errors="coerce").abs().dropna()
            if v_base.empty or v_dup.empty:
                continue
            max_base = float(v_base.max())
            max_dup = float(v_dup.max())
            if max_base > 0 and max_dup / max_base < 0.1:
                # X.1 jest rząd wielkości mniejsze → poprawna jednostka z headera
                df = df.drop(columns=[base])
                df = df.rename(columns={dup: base})
        except Exception:
            continue
    return df


# Cache load_library po mtime pliku — Streamlit wykonuje CAŁY skrypt przy
# każdym kliku, a bez cache każdy rerun czytał ~2k×300 parquet + resolve
# duplikatów (dziesiątki ms × wiele wywołań = odczuwalne "zamulanie").
# Inwalidacja: każda zmiana pliku (save/delete/import) zmienia mtime_ns.
_LOAD_CACHE: dict = {"mtime": None, "df": None}


def load_library() -> pd.DataFrame | None:
    """Wczytaj cały plik biblioteki. None gdy nie istnieje.

    Stosuje `_resolve_vald_duplicate_columns` żeby naprawić znany quirk VALD
    (kolumny eksportowane jako duplikat z różnymi jednostkami).
    Wynik cache'owany po mtime; zwracamy KOPIĘ (callers dopisują kolumny
    robocze typu _day — mutacja wspólnego obiektu = ciche korupcje)."""
    if not LIBRARY_PATH.exists():
        return None
    try:
        mtime = LIBRARY_PATH.stat().st_mtime_ns
        if _LOAD_CACHE["mtime"] == mtime and _LOAD_CACHE["df"] is not None:
            return _LOAD_CACHE["df"].copy()
        df = pd.read_parquet(LIBRARY_PATH)
    except Exception as e:
        # Plik ISTNIEJE, ale nie da się go odczytać = USZKODZONY (nie 'brak danych').
        # Zwracamy None (UI nie crashuje), ale logujemy do stderr — bez tego utrata
        # całej biblioteki wygląda identycznie jak pusta baza. _atomic_to_parquet()
        # powinno temu zapobiegać; ten log to ostatnia linia obrony / widoczność.
        import sys
        print(
            f"⚠️ load_library: NIE MOŻNA ODCZYTAĆ {LIBRARY_PATH} "
            f"(plik uszkodzony?): {e}",
            file=sys.stderr,
        )
        return None
    resolved = _resolve_vald_duplicate_columns(df)
    _LOAD_CACHE["mtime"] = mtime
    _LOAD_CACHE["df"] = resolved
    return resolved.copy()


class SaveStats(TypedDict):
    total: int       # łączna liczba testów w bibliotece po zapisie
    added: int       # ile NOWYCH wierszy z uploadu trafiło do bazy
    replaced: int    # ile wierszy z uploadu nadpisało istniejące (duplikat Name+Date)
    same_day: int    # ile par (Name, ten sam dzień) zostało po dedupie — możliwe że to OK
                     # (np. 2 testy 17:15 i 17:18), ale warto pokazać użytkownikowi


def save_to_library(df: pd.DataFrame) -> SaveStats:
    """Dodaj wiersze do biblioteki. Dedupe na (Name, Date) — nowsze wygrywają.
    Zwraca statystyki: ile dodano, ile nadpisało duplikaty, ile zostało par
    z tym samym dniem (może być prawidłowe — kilka testów w jednym dniu)."""
    stats: SaveStats = {"total": 0, "added": 0, "replaced": 0, "same_day": 0}
    if df is None or df.empty:
        return stats

    df = df.copy()
    df["__saved_at__"] = pd.Timestamp.now()

    LIBRARY_DIR.mkdir(parents=True, exist_ok=True)

    if LIBRARY_PATH.exists():
        try:
            existing = pd.read_parquet(LIBRARY_PATH)
        except Exception:
            existing = pd.DataFrame()
    else:
        existing = pd.DataFrame()

    # Policz ile wierszy z uploadu już jest w bazie (Name+Date match)
    if (
        not existing.empty
        and "Name" in df.columns and "Date" in df.columns
        and "Name" in existing.columns and "Date" in existing.columns
    ):
        existing_keys = set(zip(existing["Name"].astype(str), existing["Date"]))
        upload_keys = list(zip(df["Name"].astype(str), df["Date"]))
        stats["replaced"] = sum(1 for k in upload_keys if k in existing_keys)
        stats["added"] = len(upload_keys) - stats["replaced"]
    else:
        stats["added"] = int(len(df))

    # Upload z TestId (API pipeline) niesie PEŁNE testy — usuń z bazy stare
    # wersje tych testów zanim doklejisz nowe. Bez tego stary wiersz (np. 1 rep
    # ocalały z bugowatego dedupe) + nowe pełne repy dawałyby duplikaty.
    if (
        not existing.empty
        and "TestId" in df.columns and "TestId" in existing.columns
    ):
        upload_test_ids = set(df["TestId"].dropna().astype(str))
        if upload_test_ids:
            keep_mask = ~existing["TestId"].astype(str).isin(upload_test_ids)
            existing = existing[keep_mask]

    combined = (
        pd.concat([existing, df], ignore_index=True, sort=False)
        if not existing.empty else df
    )

    if "Name" in combined.columns and "Date" in combined.columns:
        # Klucz dedupe rozszerzony o identyfikatory repa gdy dostępne.
        # 🔴 (Name, Date) samo NIE wystarcza: test DJ ma N repów z IDENTYCZNYM
        # timestampem (VALD API nie daje per-rep offsetu czasu dla DJ) —
        # dedupe po (Name, Date) zostawiał 1 rep z 11 (bug 2026-06-12).
        # NaN==NaN w drop_duplicates → stare wiersze bez TrialId/Rep nadal
        # dedupują się po (Name, Date) jak dotychczas.
        dedupe_keys = ["Name", "Date"] + [
            k for k in ("TestId", "TrialId", "Rep", "TrialLimb")
            if k in combined.columns
        ]
        combined = combined.drop_duplicates(
            subset=dedupe_keys, keep="last"
        ).reset_index(drop=True)

        # Wykryj "podejrzane" pary: ten sam Name + ten sam dzień ale różne
        # timestampy. Może być OK (kilka testów w dniu), ale jeśli Vald
        # przypadkiem wyeksportował dwukrotnie z mikroróżnicą — to duplikat.
        if pd.api.types.is_datetime64_any_dtype(combined["Date"]):
            day_grp = combined.groupby(
                [combined["Name"].astype(str), combined["Date"].dt.date]
            ).size()
            stats["same_day"] = int((day_grp > 1).sum())

    _atomic_to_parquet(combined)
    stats["total"] = int(len(combined))
    return stats


def get_athletes_summary() -> list[AthleteSummary]:
    """Lista zawodników w bibliotece z liczbą testów i datą ostatniego."""
    df = load_library()
    if df is None or "Name" not in df.columns or df.empty:
        return []
    out: list[AthleteSummary] = []
    for name, g in df.groupby("Name"):
        clean_name = " ".join(str(name).split())
        last_test = None
        if "Date" in g.columns:
            try:
                lt = pd.to_datetime(g["Date"], errors="coerce").max()
                # NaT jest "truthy" → `x['last_test'] or fallback` NIE zadziała;
                # normalizujemy do None, żeby sort-fallback (1970) faktycznie zepchnął
                # zawodników bez ważnej daty na koniec.
                last_test = None if pd.isna(lt) else lt
            except Exception:
                last_test = None
        out.append(
            {
                "name": clean_name,
                "n_tests": int(len(g)),
                "last_test": last_test,
            }
        )
    return sorted(
        out,
        key=lambda x: x["last_test"] or pd.Timestamp("1970-01-01"),
        reverse=True,
    )


def get_athlete_data(name: str) -> pd.DataFrame | None:
    """Dane jednego zawodnika z biblioteki (bez kolumn meta __*)."""
    df = load_library()
    if df is None or "Name" not in df.columns:
        return None
    # Match niezależnie od podwójnych spacji
    clean = " ".join(str(name).split())
    df_clean_names = df["Name"].astype(str).map(lambda s: " ".join(s.split()))
    sub = df[df_clean_names == clean].copy().reset_index(drop=True)
    if sub.empty:
        return None
    # Usuń wewnętrzne kolumny meta
    meta_cols = [c for c in sub.columns if c.startswith("__")]
    sub = sub.drop(columns=meta_cols, errors="ignore")
    return sub


def rename_athlete(old: str, new: str) -> int:
    """Zmień imię zawodnika we wszystkich wierszach biblioteki testów.
    Zwraca liczbę zmodyfikowanych wierszy. 0 gdy brak zmian (brak danych,
    nazwa identyczna po normalizacji, pusta nowa nazwa)."""
    new_clean = " ".join(str(new).split())
    old_clean = " ".join(str(old).split())
    if not new_clean or old_clean == new_clean:
        return 0
    df = load_library()
    if df is None or "Name" not in df.columns or df.empty:
        return 0
    mask = df["Name"].astype(str).map(lambda s: " ".join(s.split())) == old_clean
    n = int(mask.sum())
    if n == 0:
        return 0
    df = df.copy()
    df.loc[mask, "Name"] = new_clean
    _atomic_to_parquet(df)
    return n


def get_athlete_test_type_counts(name: str) -> dict[str, int]:
    """Zwróć liczbę testów per znormalizowany typ dla zawodnika.
    Np. {"CMJ": 6, "HOP": 4}. Pusty dict gdy zawodnik nie istnieje."""
    from .parser import _match_test_type
    df = load_library()
    if df is None or df.empty or "Name" not in df.columns:
        return {}
    clean = " ".join(str(name).split())
    df_clean_names = df["Name"].astype(str).map(lambda s: " ".join(s.split()))
    sub = df[df_clean_names == clean]
    if sub.empty or "Test Type" not in sub.columns:
        return {}
    matched = sub["Test Type"].apply(_match_test_type)
    counts = matched.value_counts().to_dict()
    # Usuń UNKNOWN — nie chcemy oferować usuwania niezidentyfikowanych testów
    counts.pop("UNKNOWN", None)
    return {k: int(v) for k, v in counts.items()}


def delete_athlete_test_type(name: str, test_type: str) -> int:
    """Usuń z biblioteki wszystkie testy danego typu (CMJ/HOP/...) konkretnego
    zawodnika. Zwraca liczbę usuniętych wierszy."""
    from .parser import _match_test_type
    df = load_library()
    if df is None or df.empty:
        return 0
    if "Name" not in df.columns or "Test Type" not in df.columns:
        return 0
    clean = " ".join(str(name).split())
    df_clean_names = df["Name"].astype(str).map(lambda s: " ".join(s.split()))
    type_matched = df["Test Type"].apply(_match_test_type)
    mask = (df_clean_names == clean) & (type_matched == test_type)
    n = int(mask.sum())
    if n == 0:
        return 0
    new = df[~mask].reset_index(drop=True)
    if new.empty:
        try:
            LIBRARY_PATH.unlink()
        except FileNotFoundError:
            pass
    else:
        _atomic_to_parquet(new)
    return n


def get_athlete_test_days(name: str, test_type: str) -> list[tuple[str, int]]:
    """Zwróć listę dni testowych (YYYY-MM-DD) zawodnika dla danego typu testu
    + liczba rep'ów w każdym dniu. Sortowane od najnowszego do najstarszego.
    Używane do UI per-day delete."""
    from .parser import _match_test_type
    df = load_library()
    if df is None or df.empty:
        return []
    if "Name" not in df.columns or "Test Type" not in df.columns or "Date" not in df.columns:
        return []
    clean = " ".join(str(name).split())
    df_clean_names = df["Name"].astype(str).map(lambda s: " ".join(s.split()))
    type_matched = df["Test Type"].apply(_match_test_type)
    sub = df[(df_clean_names == clean) & (type_matched == test_type)]
    if sub.empty:
        return []
    days = pd.to_datetime(sub["Date"], errors="coerce").dt.date
    counts = days.value_counts().sort_index(ascending=False)
    return [(d.strftime("%Y-%m-%d"), int(n)) for d, n in counts.items() if d is not None]


def delete_athlete_test_day(name: str, test_type: str, day: str) -> int:
    """Usuń wszystkie rep'y zawodnika dla danego typu testu z konkretnego DNIA
    (YYYY-MM-DD). Zwraca liczbę usuniętych wierszy.
    Wszystkie rep'y tego samego dnia + typu testu = "jeden test" z perspektywy
    użytkownika (sesja testowa). Dzień to granica naturalna."""
    from .parser import _match_test_type
    df = load_library()
    if df is None or df.empty:
        return 0
    if "Name" not in df.columns or "Test Type" not in df.columns or "Date" not in df.columns:
        return 0
    clean = " ".join(str(name).split())
    df_clean_names = df["Name"].astype(str).map(lambda s: " ".join(s.split()))
    type_matched = df["Test Type"].apply(_match_test_type)
    try:
        target_day = pd.to_datetime(day, errors="coerce").date()
    except Exception:
        return 0
    if target_day is None:
        return 0
    row_days = pd.to_datetime(df["Date"], errors="coerce").dt.date
    mask = (df_clean_names == clean) & (type_matched == test_type) & (row_days == target_day)
    n = int(mask.sum())
    if n == 0:
        return 0
    new = df[~mask].reset_index(drop=True)
    if new.empty:
        try:
            LIBRARY_PATH.unlink()
        except FileNotFoundError:
            pass
    else:
        _atomic_to_parquet(new)
    return n


def delete_athlete_test_series(name: str, test_id: str) -> int:
    """Usuń wszystkie rep'y zawodnika z konkretnej serii (TestId).
    Jeden TestId = jeden test w VALD = jedna seria z perspektywy coacha
    (np. 3 skoki z jednej "rolki" testowej).
    Zwraca liczbę usuniętych wierszy."""
    df = load_library()
    if df is None or df.empty:
        return 0
    if "Name" not in df.columns or "TestId" not in df.columns:
        return 0
    clean = " ".join(str(name).split())
    df_clean_names = df["Name"].astype(str).map(lambda s: " ".join(s.split()))
    mask = (df_clean_names == clean) & (df["TestId"].astype(str) == str(test_id))
    n = int(mask.sum())
    if n == 0:
        return 0
    new = df[~mask].reset_index(drop=True)
    if new.empty:
        try:
            LIBRARY_PATH.unlink()
        except FileNotFoundError:
            pass
    else:
        _atomic_to_parquet(new)
    return n


def delete_athlete_trial(
    name: str, date_iso: str, *,
    test_id: str | None = None, trial_id: str | None = None,
    rep=None, trial_limb: str | None = None,
) -> int:
    """Usuń POJEDYNCZY rep zawodnika.

    Preferowana identyfikacja: tożsamościowy klucz z dostępnych identyfikatorów
    (TestId, TrialId, Rep, TrialLimb) — DETERMINISTYCZNY i odporny na repy
    dzielące ten sam timestamp Date. KRYTYCZNE dla DJ: test Drop Jump ma N repów
    z IDENTYCZNYM Date (VALD nie daje per-rep offsetu czasu) → poprzednie okno
    Date±1s usuwało WSZYSTKIE repy zamiast jednego.

    Fallback (gdy brak identyfikatorów — legacy / manual upload): okno czasu
    Date±1s. Zwraca liczbę usuniętych wierszy (typowo 1)."""
    df = load_library()
    if df is None or df.empty:
        return 0
    if "Name" not in df.columns or "Date" not in df.columns:
        return 0
    clean = " ".join(str(name).split())
    df_clean_names = df["Name"].astype(str).map(lambda s: " ".join(s.split()))

    # 1) Tożsamościowy klucz (preferowany) — z dostępnych identyfikatorów repa.
    id_masks = []
    for col, val in (
        ("TestId", test_id), ("TrialId", trial_id),
        ("Rep", rep), ("TrialLimb", trial_limb),
    ):
        if val is not None and not (isinstance(val, float) and pd.isna(val)) \
                and col in df.columns:
            id_masks.append(df[col].astype(str) == str(val))

    if id_masks:
        mask = df_clean_names == clean
        for m in id_masks:
            mask = mask & m
    else:
        # 2) Fallback legacy: okno Date±1s (Date ma mikrosekundy, ISO często bez).
        target_ts = pd.to_datetime(date_iso, errors="coerce")
        if pd.isna(target_ts):
            return 0
        row_ts = pd.to_datetime(df["Date"], errors="coerce")
        mask = (df_clean_names == clean) & (
            (row_ts - target_ts).abs() < pd.Timedelta(seconds=1)
        )
    n = int(mask.sum())
    if n == 0:
        return 0
    new = df[~mask].reset_index(drop=True)
    if new.empty:
        try:
            LIBRARY_PATH.unlink()
        except FileNotFoundError:
            pass
    else:
        _atomic_to_parquet(new)
    return n


def delete_athlete(name: str) -> bool:
    """Usuń wszystkie testy zawodnika z biblioteki."""
    df = load_library()
    if df is None or "Name" not in df.columns:
        return False
    clean = " ".join(str(name).split())
    df_clean_names = df["Name"].astype(str).map(lambda s: " ".join(s.split()))
    new = df[df_clean_names != clean].reset_index(drop=True)
    if new.empty:
        try:
            LIBRARY_PATH.unlink()
        except FileNotFoundError:
            pass
    else:
        _atomic_to_parquet(new)
    return True


def daily_backup(path) -> None:
    """Kopia dzienna pliku danych do <ValdLibrary>/backups/ (przed
    nadpisaniem). Jedna kopia na dzień, rotacja: 30 najnowszych."""
    import shutil
    from datetime import date as _date
    from pathlib import Path as _Path
    p = _Path(path)
    if not p.exists():
        return
    bdir = LIBRARY_DIR / "backups"
    bdir.mkdir(parents=True, exist_ok=True)
    dst = bdir / f"{p.stem}.{_date.today():%Y%m%d}{p.suffix}"
    if dst.exists():
        return
    try:
        shutil.copy2(p, dst)
        old = sorted(bdir.glob(f"{p.stem}.*{p.suffix}"))
        for f in old[:-30]:
            f.unlink(missing_ok=True)
    except Exception:
        pass  # backup nie może blokować zapisu danych
