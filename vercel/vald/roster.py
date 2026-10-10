"""
Profile podopiecznych — wszystko, co aplikacja wie o jednej osobie.

Po co: plany leżą w jednym worku i żeby zobaczyć historię zawodnika, trener
musiał przeglądać listę planów okiem. Tutaj to samo widać z perspektywy osoby:
plan, który trwa teraz, plany wcześniejsze i testy siły wyciągnięte z rozpisek.

Test siły rozpoznajemy po zapisie `test 3RM` w komórce tygodnia — taki, jaki
wstawia metoda „Test siły (RM)" w edytorze. Datę liczymy ze startu planu
i numeru tygodnia, więc test z 4. tygodnia planu startującego 24.08 wypada 14.09.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

# Podział testów na partie: bierzemy go z kategorii ćwiczenia w Bazie,
# żeby nie trzymać drugiej listy, która zaraz się rozjedzie z pierwszą.
GORA = {"Horizontal press", "Horizontal pull", "Vertical press", "Vertical pull",
        "Shoulder", "Biceps", "Triceps", "Wrist"}
DOL = {"Squat bilateral", "Squat unilateral", "Hinge bilateral", "Hinge unilateral",
       "Hip lock", "Deep tier", "Hip", "Knee", "Quad", "Hamstring", "Ankle"}


def _mapa_partii() -> dict[str, str]:
    """nazwa ćwiczenia → partia. Liczone raz na wywołanie profilu."""
    from . import exlib
    out: dict[str, str] = {}
    for e in exlib.exercises():
        nazwa = (e.get("name") or "").strip().lower()
        if not nazwa:
            continue
        katy = [e.get("cat"), e.get("cat2"), e.get("cat3"), e.get("cat4")]
        out[nazwa] = ("Upper" if any(k in GORA for k in katy)
                      else "Lower" if any(k in DOL for k in katy) else "Inne")
    return out


def partia(nazwa: str, mapa: "dict[str, str] | None" = None) -> str:
    """Upper / Lower / Inne — po kategorii ćwiczenia z Bazy."""
    mapa = _mapa_partii() if mapa is None else mapa
    return mapa.get((nazwa or "").strip().lower(), "Inne")


# „TEST 3 RM", „test 5RM", ale też samo „test" — Filip dyktuje różnie.
# Liczba powtórzeń wpada do grupy 1, gdy ją podał.
_TEST = re.compile(r"\btest\b(?:\s*(\d+)\s*RM)?", re.I)


def _iso(s: str) -> date | None:
    try:
        return date.fromisoformat((s or "")[:10])
    except (ValueError, TypeError):
        return None


def _zapis(v: dict) -> str:
    """Komórka tygodnia → jedna linia tekstu (tak jak widzi ją trener)."""
    v = v or {}
    s, r = (v.get("sets_n") or "").strip(), (v.get("reps") or "").strip()
    i = (v.get("intent") or "").strip()
    baza = f"{s} x {r}" if s and r else (r or s)
    return f"{baza} @ {i}" if baza and i else (baza or i)


def data_tygodnia(plan: dict, nr) -> str:
    """Kiedy wypada N-ty tydzień planu. Pusty string, gdy plan nie ma startu."""
    start = _iso(plan.get("start_date") or plan.get("created") or "")
    try:
        n = int(nr)
    except (TypeError, ValueError):
        return ""
    if not start or n < 1:
        return ""
    return (start + timedelta(days=(n - 1) * 7)).isoformat()


def testy_z_planu(plan: dict, mapa: "dict[str, str] | None" = None) -> list[dict]:
    """Wszystkie testy siły zapisane w planie, od najnowszego."""
    mapa = _mapa_partii() if mapa is None else mapa
    out: list[dict] = []
    for s in (plan.get("sessions") or []):
        for it in (s.get("items") or []):
            nazwa = (it.get("exercise") or "").strip()
            if not nazwa:
                continue
            for nr, v in (it.get("weeks") or {}).items():
                zapis = _zapis(v)
                m = _TEST.search(zapis)
                if not m:
                    continue
                out.append({
                    "exercise": nazwa,
                    "part": partia(nazwa, mapa),
                    "rm": m.group(1) or "",
                    "date": data_tygodnia(plan, nr),
                    "week": str(nr),
                    "dose": zapis,
                    # co zawodnik wpisał w telefonie po teście (jeśli wpisał)
                    "result": ((v or {}).get("load") or "").strip(),
                    "plan": plan.get("name", ""),
                    "plan_id": plan.get("id", ""),
                    "session": (s.get("name") or "").strip(),
                })
    out.sort(key=lambda t: (t["date"] or "0000", t["exercise"]), reverse=True)
    return out


def profil(name: str, plans: list[dict], *, dzis: date | None = None) -> dict:
    """Jedna osoba: plan bieżący, plany wcześniejsze, testy siły."""
    dzis = dzis or date.today()
    moje = [p for p in plans if (p.get("athlete") or "").strip() == name.strip()]

    def _sort(p: dict):
        return (p.get("start_date") or p.get("created") or "")

    moje.sort(key=_sort, reverse=True)

    # ręczne „Trwa" wygrywa z datami — plan bywa aktywny mimo starej daty
    # startu (Filip 2026-09-05: plan z 01.08 dalej jest jego planem)
    biezacy = next((p for p in moje
                    if (p.get("status_set") or "").strip() == "Trwa"), None)
    for p in moje:
        if biezacy:
            break
        start = _iso(p.get("start_date") or "")
        if not start:
            continue
        koniec = start + timedelta(weeks=int(p.get("weeks") or 4))
        if start <= dzis < koniec:
            biezacy = p
            break

    testy: list[dict] = []
    mapa = _mapa_partii()
    for p in moje:
        testy.extend(testy_z_planu(p, mapa))
    testy.sort(key=lambda t: (t["date"] or "0000"), reverse=True)

    return {
        "name": name,
        "plans": moje,
        "current": biezacy,
        "tests": testy,
        # ile testów czeka jeszcze przed zawodnikiem
        "tests_upcoming": sum(1 for t in testy if t["date"] and t["date"] >= dzis.isoformat()),
    }
