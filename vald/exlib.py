"""
Baza ćwiczeń (exercise library) — taksonomia Filipa + linki YouTube.

Model: <ValdLibrary>/exercise_library.json →
  {"exercises": [{"id": str, "name": "Pogo jumps",
                  "cat": "Plyometrics", "sub": "",
                  "cat2": "", "cat3": "", "cat4": "",   # dodatkowe kategorie
                  "url": "https://youtu.be/…"}]}

`cat2`, `cat3` i `cat4` obsługują ćwiczenia należące do kilku kategorii naraz
(Filip 2026-09-02: „Neck hip trust" ma być i w Hip, i w Neck; 2026-09-03:
wszystko z ISO w nazwie dostaje „Isometrics" jako kolejną). Puste = jedna
kategoria. Filtry i badge w Bazie uwzględniają wszystkie trzy.

Kategorie GŁÓWNE wg systemu Filipa; część ma podkategorie (Hip, Shoulder,
Trunk, Ankle, Knee). Nazwy ćwiczeń unikalne (case-insensitive) — nazwa
w planie treningowym jest kluczem do linku YT i sugestii wariacji.
"""
from __future__ import annotations

import json
import os
import uuid

from .library import LIBRARY_DIR

EXLIB_PATH = LIBRARY_DIR / "exercise_library.json"

# Kategoria główna → podkategorie (pusta lista = bez podpodziału)
CATEGORIES: dict[str, list[str]] = {
    # Taksonomia Filipa 2026-09-02: bez nadrzednych „Movement Prep /
    # Main Strength". Przygotowanie, skoki (Jump = jeden maksymalny,
    # Plyometrics = reaktywne i z ladowaniem), rzuty, wzorce ruchu,
    # potem staw/miesien — bez podpodzialow.
    "Movement Prep": [],
    # bez podkategorii — intensywność skoku wpisuje się w planie,
    # nie przy ćwiczeniu (Filip 2026-09-02)
    "Plyometrics": [],
    # pojedynczy skok maksymalny (CMJ, broad, box, step-up jump)
    "Jump": [],
    # medball throws i slamy
    "Throws": [],
    # bieg: przyspieszenia, hamowania, zmiany kierunku, wariacje
    "Run": [],
    # praca z saniami — osobno od biegu
    "Sled variation": [],
    # wszystko, co izometryczne — zwykle jako druga/trzecia kategoria
    "Isometrics": [],
    # wzorce ruchu
    "Horizontal press": [],
    "Horizontal pull": [],
    "Vertical press": [],
    "Vertical pull": [],
    "Squat bilateral": [],
    "Squat unilateral": [],
    "Hinge bilateral": [],
    "Hinge unilateral": [],
    # hip lock — wlasna kategoria, nie podkategoria Hip
    "Hip lock": [],
    # deep tier — jak hip lock: wlasna kategoria, zwykle druga
    # (np. Plyometrics + Deep tier)
    "Deep tier": [],
    # staw / miesien
    "Hip": [],
    "Ankle": [],
    "Shoulder": [],
    "Knee": [],
    "Quad": [],
    "Hamstring": [],
    "Core": [],
    "Spine": [],
    "Neck": [],
    "Wrist": [],
    "Biceps": [],
    "Triceps": [],
    # Cwiczenia wpisane wprost w planie ladujace tu automatycznie —
    # w panelu Bazy przenosisz je do wlasciwej kategorii.
    "Nieprzypisane": [],
}


_STORE_KEY = "exercise_library"
# Nakładka drugiego trenera. Klucz NIE jest w store._WSPOLNE_KEYS, więc
# magazyn prefiksuje go przestrzenią: `ws/maciek/exercise_library_own`.
# Filip 2026-09-20: „mógłby dodać ćwiczenie, które on widzi, a ja nie".
# Instancja gościa czyta wspólną Bazę, ale NIGDY do niej nie pisze:
# dodatki, poprawki i ukrycia lądują wyłącznie w jego nakładce.
_WLASNE_KEY = "exercise_library_own"
# id-y z ostatniego odczytu — potrzebne, żeby przy zapisie odróżnić „skasowałem
# to ćwiczenie" od „ktoś dodał swoje, gdy ja miałem bazę otwartą"
_ostatni_odczyt: set[str] = set()


def _z_nakladka(wspolne: dict, wlasne: dict) -> dict:
    """Wspólna Baza + prywatne wpisy przestrzeni. Wpis własny o tym samym
    id przesłania wspólny, id z `ukryte` znika z widoku gościa."""
    ukryte = set(wlasne.get("ukryte") or [])
    moje = [e for e in (wlasne.get("exercises") or []) if isinstance(e, dict)]
    po_id = {e.get("id"): e for e in moje if e.get("id")}
    out = [po_id.get(e.get("id"), e) for e in wspolne.get("exercises", [])
           if e.get("id") not in ukryte]
    znane = {e.get("id") for e in out}
    out += [e for e in moje if e.get("id") not in znane]
    return {"exercises": out}


def _load_all() -> dict:
    from . import store
    if store.enabled():
        data = store.kv_get(_STORE_KEY) or {"exercises": []}
        if not (isinstance(data, dict)
                and isinstance(data.get("exercises"), list)):
            raise RuntimeError(
                "Baza ćwiczeń w magazynie ma nieoczekiwaną strukturę.")
        if store.workspace():
            wlasne = store.kv_get(_WLASNE_KEY) or {}
            data = _z_nakladka(data, wlasne if isinstance(wlasne, dict) else {})
        _zapamietaj(data)
        return data
    if not EXLIB_PATH.exists():
        return {"exercises": []}
    try:
        with open(EXLIB_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        # plik JEST, ale nieczytelny — głośno, bo cichy pusty stan +
        # kolejny zapis nadpisałby całą bazę ćwiczeń
        raise RuntimeError(
            f"{EXLIB_PATH.name} jest uszkodzony — przywróć kopię z "
            f"{EXLIB_PATH.parent / 'backups'}/") from e
    if not (isinstance(data, dict)
            and isinstance(data.get("exercises"), list)):
        raise RuntimeError(
            f"{EXLIB_PATH.name} ma nieoczekiwaną strukturę — przywróć "
            f"kopię z {EXLIB_PATH.parent / 'backups'}/")
    return data


def _zapamietaj(data: dict) -> None:
    _ostatni_odczyt.clear()
    _ostatni_odczyt.update(e.get("id") for e in data.get("exercises", [])
                           if e.get("id"))


def _scal(swieze: dict, moje: dict) -> dict:
    """Bazę ćwiczeń dzielą wszystkie przestrzenie, a magazyn zapisuje CAŁY
    dokument — bez scalania zapis drugiego trenera skasowałby ćwiczenie
    dodane w międzyczasie (Filip 2026-09-18, wyścig zapisu z 08.2026)."""
    moje_ex = moje.get("exercises", [])
    moje_id = {e.get("id") for e in moje_ex}
    skasowane = _ostatni_odczyt - moje_id
    obce = [e for e in swieze.get("exercises", [])
            if e.get("id") not in moje_id and e.get("id") not in skasowane]
    if not obce:
        return moje
    out = dict(moje)
    out["exercises"] = moje_ex + obce
    return out


def _save_all(data: dict) -> None:
    from . import store
    if store.enabled():
        store.invalidate(_STORE_KEY)
        swieze = store.kv_get(_STORE_KEY) or {"exercises": []}
        if store.workspace():
            store.invalidate(_WLASNE_KEY)
            store.kv_put(_WLASNE_KEY, _tylko_moje(swieze, data))
            _zapamietaj(data)
            return
        data = _scal(swieze, data)
        store.kv_put(_STORE_KEY, data)
        _zapamietaj(data)
        return
    from .library import daily_backup
    daily_backup(EXLIB_PATH)
    EXLIB_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = EXLIB_PATH.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, EXLIB_PATH)


def _tylko_moje(wspolne: dict, widok: dict) -> dict:
    """Różnica: co z widoku gościa jest jego własne (nowe albo poprawione)
    i które wpisy wspólne schował. Wspólnej Bazy to nie dotyka."""
    baza = {e.get("id"): e for e in wspolne.get("exercises", []) if e.get("id")}
    moje = [e for e in widok.get("exercises", []) if isinstance(e, dict)]
    widoczne = {e.get("id") for e in moje}
    return {"exercises": [e for e in moje
                          if e.get("id") not in baza or e != baza[e["id"]]],
            "ukryte": [i for i in baza if i not in widoczne]}


def exercises(cat: str | None = None) -> list[dict]:
    exs = _load_all()["exercises"]
    if cat:
        exs = [e for e in exs
               if cat in (e.get("cat"), e.get("cat2") or "",
                          e.get("cat3") or "", e.get("cat4") or "")]
    return sorted(exs, key=lambda e: (e.get("sub", ""),
                                      e.get("name", "").lower()))


def all_names() -> list[str]:
    """Unikalne nazwy do sugestii w planach (sort alfabetyczny)."""
    seen: dict[str, str] = {}
    for e in _load_all()["exercises"]:
        n = (e.get("name") or "").strip()
        if n and n.lower() not in seen:
            seen[n.lower()] = n
    return sorted(seen.values(), key=str.lower)


def url_map() -> dict[str, str]:
    """name.lower() → url (tylko wpisy z linkiem)."""
    out: dict[str, str] = {}
    for e in _load_all()["exercises"]:
        n = (e.get("name") or "").strip().lower()
        u = (e.get("url") or "").strip()
        if n and u:
            out[n] = u
    return out


def add_exercise(name: str, cat: str, sub: str = "", url: str = "") -> bool:
    """Dodaj wpis (False gdy nazwa już istnieje — case-insensitive)."""
    name = (name or "").strip()
    if not name:
        return False
    data = _load_all()
    if any((e.get("name") or "").strip().lower() == name.lower()
           for e in data["exercises"]):
        return False
    data["exercises"].append({
        "id": uuid.uuid4().hex[:10], "name": name,
        "cat": cat, "sub": (sub or "").strip(), "url": (url or "").strip(),
    })
    _save_all(data)
    return True


def sync_from_plan(entries: list[tuple[str, str]]) -> None:
    """(nazwa, link) z zapisywanego treningu → baza: nieznana nazwa jest
    dodawana TYLKO gdy ma niepusty link (decyzja Filipa 2026-07-21 —
    wpis roboczy bez linku nie zaśmieca Bazy); znana nazwa z NIEPUSTYM
    linkiem dostaje aktualizację linku. Puste linki niczego nie kasują."""
    data = _load_all()
    by_name = {(e.get("name") or "").strip().lower(): e
               for e in data["exercises"]}
    changed = False
    for name, url in entries:
        name = (name or "").strip()
        url = (url or "").strip()
        if not name:
            continue
        e = by_name.get(name.lower())
        if e is None:
            if not url:
                continue
            e = {"id": uuid.uuid4().hex[:10], "name": name,
                 "cat": "Nieprzypisane", "sub": "", "url": url}
            data["exercises"].append(e)
            by_name[name.lower()] = e
            changed = True
        elif url and e.get("url") != url:
            e["url"] = url
            changed = True
    if changed:
        _save_all(data)


def upsert_exercise(ex: dict) -> bool:
    """Zapisz po id (nowe id = dodaj). False, gdy nazwa koliduje z INNYM
    wpisem (case-insensitive) albo jest pusta."""
    name = (ex.get("name") or "").strip()
    if not name:
        return False
    data = _load_all()
    for e in data["exercises"]:
        if (e.get("id") != ex.get("id")
                and (e.get("name") or "").strip().lower() == name.lower()):
            return False
    # brak klucza "cat2" w wejściu = stary formularz; zachowaj to, co jest
    # w bazie, żeby edycja z innego ekranu cicho nie kasowała 2. kategorii
    stary = next((e for e in data["exercises"]
                  if e.get("id") == ex.get("id")), {})
    cat2 = ((ex.get("cat2") if "cat2" in ex else stary.get("cat2")) or "").strip()
    cat3 = ((ex.get("cat3") if "cat3" in ex else stary.get("cat3")) or "").strip()
    cat4 = ((ex.get("cat4") if "cat4" in ex else stary.get("cat4")) or "").strip()
    rec = {"id": ex.get("id") or uuid.uuid4().hex[:10], "name": name,
           "cat": ex.get("cat") or "Nieprzypisane",
           "sub": (ex.get("sub") or "").strip(),
           "cat2": cat2 if cat2 != (ex.get("cat") or "") else "",
           "cat3": cat3 if cat3 not in ((ex.get("cat") or ""), cat2) else "",
           "cat4": cat4 if cat4 not in ((ex.get("cat") or ""), cat2, cat3) else "",
           "url": (ex.get("url") or "").strip()}
    data["exercises"] = [e for e in data["exercises"]
                         if e.get("id") != rec["id"]] + [rec]
    _save_all(data)
    return True


def delete_exercise(ex_id: str) -> None:
    data = _load_all()
    data["exercises"] = [e for e in data["exercises"]
                         if e.get("id") != ex_id]
    _save_all(data)
