"""
Metadane zawodników — sport, urazy, cele, notatki.

Plik: ~/Documents/ValdLibrary/athletes_meta.json
Klucz = imię i nazwisko (znormalizowane spacje, jak w bibliotece testów).
"""
from __future__ import annotations

import json
import os
from typing import TypedDict

from .library import LIBRARY_DIR, daily_backup

PROFILES_PATH = LIBRARY_DIR / "athletes_meta.json"
_STORE_KEY = "athlete_profiles"


def _save_profiles(profiles: dict) -> None:
    """Zapis ATOMOWO (temp + os.replace) + kopia dzienna — jak plany/baza.
    Bez tego crash w połowie json.dump zostawiał uszkodzony plik ze
    WSZYSTKIMI profilami (sport/uraz/cele/płeć-do-norm/notatki testowe).
    Ze wspólnym magazynem (Supabase) idzie tam, nie do pliku — inaczej
    w chmurze profil dodany przez trenera znika przy restarcie."""
    from . import store
    if store.enabled():
        store.kv_put(_STORE_KEY, {"profiles": profiles})
        return
    daily_backup(PROFILES_PATH)
    PROFILES_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = PROFILES_PATH.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(profiles, f, indent=2, ensure_ascii=False)
    os.replace(tmp, PROFILES_PATH)


class AthleteProfile(TypedDict, total=False):
    sport: str
    injury: str
    goals: str
    notes: str
    sex: str  # "male" | "female" | "" — używane do doboru norm (RSI, etc.), nie pokazywane w UI
    test_notes: dict  # {"YYYY-MM-DD": "notatka coacha do testu z tego dnia"}


def _normalize(name: str) -> str:
    return " ".join(str(name).split())


def load_profiles() -> dict[str, AthleteProfile]:
    from . import store
    if store.enabled():
        data = store.kv_get(_STORE_KEY) or {}
        prof = data.get("profiles") if isinstance(data, dict) else None
        return prof if isinstance(prof, dict) else {}
    if not PROFILES_PATH.exists():
        return {}
    try:
        with open(PROFILES_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        # plik JEST, ale uszkodzony — cichy {} + kolejny save = utrata
        # wszystkich profili; głośno, z podpowiedzią gdzie kopia
        raise RuntimeError(
            f"{PROFILES_PATH.name} jest uszkodzony — przywróć kopię z "
            f"{PROFILES_PATH.parent / 'backups'}/") from e
    except OSError:
        return {}
    return data if isinstance(data, dict) else {}


def save_profile(
    name: str,
    *,
    sport: str = "",
    injury: str = "",
    goals: str = "",
    notes: str = "",
    sex: str = "",
    coach: str = "",
) -> None:
    """Zapisz / zaktualizuj profil zawodnika. Zachowuje istniejące test_notes."""
    profiles = load_profiles()
    key = _normalize(name)
    if not key:
        return
    existing = profiles.get(key, {})
    profiles[key] = {
        "sport": sport.strip(),
        "injury": injury.strip(),
        "goals": goals.strip(),
        "notes": notes.strip(),
        "sex": sex.strip().lower(),
        # do kogo należy zawodnik (Coach Filip / Coach Kuba) — puste = Filip
        "coach": (coach or existing.get("coach") or "").strip().lower(),
        # Notatki do dni testowych są zarządzane osobno (save_test_note) —
        # tutaj tylko zachowujemy istniejące przy update'cie reszty profilu.
        "test_notes": existing.get("test_notes", {}),
    }
    _save_profiles(profiles)


def _day_key(day) -> str:
    """Konwersja dnia (date / datetime / str) na klucz YYYY-MM-DD."""
    if hasattr(day, "isoformat"):
        s = day.isoformat()
        return s[:10]  # date.isoformat() = "YYYY-MM-DD", datetime też się zmieści
    return str(day)[:10]


def save_test_note(athlete: str, day, note: str) -> None:
    """Zapisz / nadpisz / usuń notatkę coacha do testu danego dnia.
    Pusta notatka kasuje wpis. Jeśli profil zawodnika nie istnieje — tworzy szkielet."""
    profiles = load_profiles()
    key = _normalize(athlete)
    if not key:
        return
    profile = profiles.get(key, {})
    test_notes = dict(profile.get("test_notes") or {})
    dkey = _day_key(day)
    if note.strip():
        test_notes[dkey] = note.strip()
    else:
        test_notes.pop(dkey, None)
    profile["test_notes"] = test_notes
    profiles[key] = profile
    _save_profiles(profiles)


def get_test_note(athlete: str, day) -> str:
    """Notatka do testu z danego dnia. Pusty string gdy brak."""
    profiles = load_profiles()
    key = _normalize(athlete)
    if not key:
        return ""
    return (profiles.get(key, {}).get("test_notes") or {}).get(_day_key(day), "")


def get_profile(name: str) -> AthleteProfile:
    return load_profiles().get(_normalize(name), {})


def list_profile_names() -> list[str]:
    """Lista imion zawodników którzy mają profil (mogą jeszcze nie mieć testów)."""
    return sorted(load_profiles().keys())


def rename_profile(old: str, new: str) -> bool:
    """Przenieś profil pod nowy klucz. Zwraca True jeśli przeniesiono.
    Nie nadpisuje istniejącego profilu o nowym kluczu — wtedy False."""
    profiles = load_profiles()
    old_key = _normalize(old)
    new_key = _normalize(new)
    if not new_key or old_key == new_key:
        return False
    if old_key not in profiles:
        return False
    if new_key in profiles:
        return False  # kolizja — caller decyduje co zrobić
    profiles[new_key] = profiles.pop(old_key)
    _save_profiles(profiles)
    return True


def delete_profile(name: str) -> None:
    profiles = load_profiles()
    key = _normalize(name)
    if key not in profiles:
        return
    del profiles[key]
    if profiles:
        _save_profiles(profiles)
    else:
        daily_backup(PROFILES_PATH)
        try:
            PROFILES_PATH.unlink()
        except FileNotFoundError:
            pass


def coach_of(name: str) -> str:
    """Trener zawodnika; puste = Coach Filip (dane sprzed podziału)."""
    return (get_profile(name).get("coach") or "").strip().lower()


def set_coach(name: str, coach: str) -> None:
    profiles = load_profiles()
    key = _normalize(name)
    if not key:
        return
    prof = dict(profiles.get(key) or {})
    prof["coach"] = (coach or "").strip().lower()
    profiles[key] = prof
    _save_profiles(profiles)


def set_hidden(name: str, hidden: bool = True) -> None:
    """Ukryj/pokaż zawodnika na liście wyboru (dane i plany zostają)."""
    profs = load_profiles()
    key = next((n for n in profs if n.strip().lower() == (name or "").strip().lower()), "")
    if not key:
        return
    if hidden:
        profs[key]["hidden"] = True
    else:
        profs[key].pop("hidden", None)
    _save_profiles(profs)


def hidden_names() -> list[str]:
    """Kto jest ukryty — do panelu, żeby dało się cofnąć."""
    return sorted(n for n, p in load_profiles().items() if p.get("hidden"))


def names_for_coach(coach: str, *, vald_names: "set[str] | None" = None) -> list[str]:
    """Zawodnicy tego trenera do listy wyboru. Baza testów VALD i profile
    bez znacznika należą do Filipa — to jego dane sprzed rozdzielenia
    paneli. Profile z `hidden` są pomijane (Filip 2026-09-02: zawodnicy
    klubu nie mają się pokazywać przy rozpisywaniu planu)."""
    coach = (coach or "").strip().lower()
    profs = load_profiles()
    out = set()
    for n, prof in profs.items():
        if prof.get("hidden"):
            continue          # ukryty — np. jednorazowa robota dla klubu
        c = (prof.get("coach") or "").strip().lower()
        if c == coach or (not c and coach == "filip"):
            out.add(n)
    if coach == "filip" and vald_names:
        out |= {n for n in vald_names
                if not ((profs.get(n) or {}).get("coach") or "")
                and not (profs.get(n) or {}).get("hidden")}
    return sorted(out)
