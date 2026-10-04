"""
Plany treningowe (inspiracja Relay Athletics) — storage + model.

Model (v3 — kafelki, bez kalendarza; decyzja Filipa 2026-07-18):
  plan = {
    "id": str, "athlete": str, "name": str, "created": "YYYY-MM-DD",
    "start_date": "YYYY-MM-DD",         # początek zakresu dat planu
    "weeks": int,                        # długość → koniec = start + weeks*7-1
    "sessions": [                        # treningi A/B/C… (litera = pozycja)
      {"id": str,
       "title": "Lower Body Strength",
       "items": [  # rubryki wg stylu Filipa; dawki PER TYDZIEŃ (jak kolumny
                   # TYD.1–4 w jego Excelach) — progresja tygodniowa
         {"section": "Main",            # "Prep" | "Plyo & Power" | "Main"
          "slot": "1a",                 # superserie 1a/1b/2a… (tylko Main)
          "exercise": "BB Bench Press",
          "note": "pauza 1 sec",
          "weeks": {                    # klucz = numer tygodnia planu (str)
            "1": {"sets_n": "3", "reps": "6", "intent": "rpe 8",
                  "rest": "2-3 min",
                  "load": "80 / 85 / 82,5",  # WYKONANIE: ciężary kolejnych
                                             # serii — NIE dziedziczy się
                  "sets": []},               # (legacy wyniki S1–S4)
            "2": {"sets_n": "3", "reps": "5", "intent": "rpe 9", ...},
          }},
       ],
       "done_date": "YYYY-MM-DD"|""},   # data ostatniego wykonania
    ],
  Tydzień bez wpisu dziedziczy dawkę z najbliższego wcześniejszego
  (week_params) — rozpisanie T1 powiela się na T2, wprowadzasz tylko zmiany.
  Legacy: "workouts" {"w1d1": {...}} → ensure_sessions(); płaskie pola
  itemu (sets_n/reps/intent/sets, "target") → item_weeks() jako tydzień 1.
  }

Plik: <ValdLibrary>/training_plans.json → {"plans": [...]}. Zapis atomowy.
"""
from __future__ import annotations

import copy
import json
import os
import re
import threading
import uuid
from datetime import date, timedelta

from .library import LIBRARY_DIR

PLANS_PATH = LIBRARY_DIR / "training_plans.json"
KOSZ_PATH = LIBRARY_DIR / "training_plans_kosz.json"

PHASE_COLORS = ["#3BA776", "#D8553F", "#2F6BD8", "#E08A2B", "#7C6FF0", "#14B8A6"]
SLOT_LETTERS = list("ABCDEFGH")


_STORE_KEY = "training_plans"


# ── scalanie zapisu (magazyn trzyma JEDEN dokument ze wszystkimi planami)
# Telefon zawodnika i panel trenera piszą do tego samego klucza. Bez scalania
# zapis trenera cofał serie odklikane w międzyczasie na telefonie — a tego
# trener nie odtworzy, bo sam tego nie wpisywał (audyt 2026-09-20).
_WYKONANIE_SESJI = ("done_weeks", "started_weeks", "done_date")
# snapshot pól wykonania sprzed moich zmian — osobno dla każdego wątku.
# Telefon zawodnika i panel trenera to wątki JEDNEGO procesu Streamlit;
# wspólny słownik nadpisywał odczyt panelu w trakcie zapisu z telefonu
# i scalanie kasowało wykonanie z innego urządzenia (audyt 2026-09-24).
_watek = threading.local()


def _klucz_itemu(it: dict, i: int) -> str:
    """Item nie ma id — sklejam z pozycji i nazwy, to wystarcza do scalania."""
    return f"{i}|{(it.get('exercise') or '').strip().lower()}"


def _zbierz_wykonanie(data: dict) -> dict:
    """{plan_id: {sess_id: {"_sesja": {...}, klucz_itemu: {tydzień: {pola}}}}}"""
    out: dict = {}
    for p in data.get("plans", []):
        sesje = {}
        for s_ in (p.get("sessions") or []):
            poz = {"_sesja": {k: s_.get(k) for k in _WYKONANIE_SESJI
                              if s_.get(k) is not None}}
            for i, it in enumerate(s_.get("items") or []):
                tyg = {}
                for wk, par in (it.get("weeks") or {}).items():
                    exec_ = {k: par[k] for k in _EXEC_FIELDS if k in par}
                    if exec_:
                        tyg[wk] = exec_
                if tyg:
                    poz[_klucz_itemu(it, i)] = tyg
            sesje[s_.get("id") or ""] = poz
        out[p.get("id") or ""] = sesje
    # kopia: baza żyje dłużej niż odczyt (upsert_plan, SRV-02), a plan z tego
    # odczytu jest potem zmieniany w miejscu (oznacz_start, ustaw_serie)
    return copy.deepcopy(out)


def _scal_plany(swieze: dict, moje: dict) -> dict:
    """Moja rozpiska + cudze wykonanie, którego nie dotknąłem (scalanie 3-way).

    baza = stan sprzed moich zmian; jeśli pole wykonania w mojej wersji jest
    takie samo jak w bazie, a w świeżej inne — ktoś je zmienił po moim odczycie
    i to jego wartość zostaje.
    """
    baza = getattr(_watek, "baza", {})
    swieze_w = _zbierz_wykonanie(swieze)
    moje_id = {p.get("id") for p in moje.get("plans", [])}
    wynik = []
    for p in moje.get("plans", []):
        pid = p.get("id")
        s_plan, b_plan = swieze_w.get(pid, {}), baza.get(pid, {})
        for s_ in (p.get("sessions") or []):
            sid = s_.get("id") or ""
            s_sess, b_sess = s_plan.get(sid, {}), b_plan.get(sid, {})
            for k in _WYKONANIE_SESJI:            # done_weeks / started_weeks
                m, bz = s_.get(k), (b_sess.get("_sesja") or {}).get(k)
                sw = (s_sess.get("_sesja") or {}).get(k)
                if sw is not None and m == bz and sw != bz:
                    s_[k] = sw
            for i, it in enumerate(s_.get("items") or []):
                kl = _klucz_itemu(it, i)
                s_it, b_it = s_sess.get(kl, {}), b_sess.get(kl, {})
                for wk, sw_pola in s_it.items():
                    par = (it.get("weeks") or {}).get(wk)
                    if par is None:
                        # tydzień dziedziczony (bez własnej dawki), w którym
                        # zawodnik wpisał serie po moim odczycie — w mojej
                        # wersji tego klucza nie ma, a `continue` kasowało
                        # wpis przy KAŻDYM zapisie trenera, też w planach,
                        # których nie ruszał (audyt 2026-09-30, SRV-01).
                        # Brak w bazie = dopisane później, nie skasowane przeze mnie
                        if wk not in b_it and isinstance(it.get("weeks"), dict):
                            it["weeks"][wk] = dict(sw_pola)
                        continue
                    for pole, sw in sw_pola.items():
                        m, bz = par.get(pole), (b_it.get(wk) or {}).get(pole)
                        if m == bz and sw != bz:
                            par[pole] = sw
        wynik.append(p)
    # plan dodany przez kogoś innego po moim odczycie — nie kasuję go
    for p in swieze.get("plans", []):
        if p.get("id") not in moje_id and p.get("id") not in baza:
            wynik.append(p)
    out = dict(moje)
    out["plans"] = wynik
    return out


def _load_all() -> dict:
    # Wspólny magazyn (Supabase) — Mac i chmura czytają to samo źródło.
    from . import store
    if store.enabled():
        data = store.kv_get(_STORE_KEY) or {"plans": []}
        if not (isinstance(data, dict) and isinstance(data.get("plans"), list)):
            raise RuntimeError(
                "Dane planów w magazynie mają nieoczekiwaną strukturę.")
        _watek.baza = _zbierz_wykonanie(data)
        return data
    # Tryb plikowy (lokalny dev / offline) — bez zmian.
    if not PLANS_PATH.exists():
        return {"plans": []}
    try:
        with open(PLANS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        # Plik JEST, ale się nie parsuje. Ciche {"plans": []} byłoby
        # katastrofą: apka pokazałaby pustkę, a pierwszy zapis nadpisałby
        # plik jednym planem, kasując resztę. Lepiej głośno paść.
        raise RuntimeError(
            f"{PLANS_PATH.name} jest uszkodzony — nie zapisuję nic, żeby "
            f"nie nadpisać danych. Przywróć kopię z "
            f"{PLANS_PATH.parent / 'backups'}/"
        ) from e
    if not (isinstance(data, dict) and isinstance(data.get("plans"), list)):
        raise RuntimeError(
            f"{PLANS_PATH.name} ma nieoczekiwaną strukturę — przywróć kopię "
            f"z {PLANS_PATH.parent / 'backups'}/")
    return data


def _save_all(data: dict) -> None:
    from . import store
    if store.enabled():
        store.invalidate(_STORE_KEY)
        swieze = store.kv_get(_STORE_KEY) or {"plans": []}
        store.kv_put(_STORE_KEY, _scal_plany(swieze, data))
        return
    from .library import daily_backup
    with _ZAPIS:
        daily_backup(PLANS_PATH)
        PLANS_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = PLANS_PATH.with_suffix(f".json.{os.getpid()}.{threading.get_ident()}.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, PLANS_PATH)


def new_id() -> str:
    return uuid.uuid4().hex[:10]


def get_plans(athlete: str) -> list[dict]:
    plans = [p for p in _load_all()["plans"] if p.get("athlete") == athlete]
    return sorted(plans, key=lambda p: p.get("created", ""), reverse=True)


def get_all_plans() -> list[dict]:
    return _load_all()["plans"]


# tryb plikowy (bez magazynu): trener i zawodnik to wątki jednego procesu —
# dwa zapisy naraz przeplatały się we wspólnym .tmp i psuły plik (weryfikacja
# 2026-09-30, OFF-V1-02). Odczyt-zmiana-zapis pod jedną blokadą.
_ZAPIS = threading.RLock()


def upsert_plan(plan: dict) -> None:
    with _ZAPIS:
        stara = getattr(_watek, "baza", {})
        data = _load_all()
        # zapisywany plan zbudowano z WCZEŚNIEJSZEGO odczytu — jego wykonanie
        # scalam względem tamtej bazy; baza z odczytu tuż przed zapisem
        # zawierała już serie zawodnika, więc stara wartość trenera je
        # kasowała (audyt 2026-09-30, SRV-02). Pozostałe plany: baza świeża.
        if plan.get("id") in stara and isinstance(getattr(_watek, "baza", None), dict):
            _watek.baza[plan.get("id")] = stara[plan.get("id")]
        data["plans"] = [p for p in data["plans"] if p.get("id") != plan.get("id")]
        data["plans"].append(plan)
        _save_all(data)


def upsert_plans(plans: list[dict]) -> None:
    """Kilka planów jednym zapisem. Zmiana nazwy ćwiczenia albo folderu
    dotyka kilkunastu planów naraz — osobny upsert na każdy to tyle samo
    PUT-ów całego magazynu do Supabase (2026-09-10: 160 KB × N)."""
    if not plans:
        return
    with _ZAPIS:
        stara = getattr(_watek, "baza", {})
        data = _load_all()
        ids = {p.get("id") for p in plans}
        if isinstance(getattr(_watek, "baza", None), dict):   # jak w upsert_plan (SRV-02)
            for pid in ids & set(stara):
                _watek.baza[pid] = stara[pid]
        data["plans"] = [p for p in data["plans"] if p.get("id") not in ids] + list(plans)
        _save_all(data)


# Kosz: w trybie chmury nie ma kopii dziennej (daily_backup działa tylko na
# plikach), więc usunięcie planu było nieodwracalne — Filip 2026-09-20.
_KOSZ_KEY = "training_plans_kosz"
_KOSZ_MAX = 20


def _kosz_load() -> list[dict]:
    from . import store
    if store.enabled():
        return (store.kv_get(_KOSZ_KEY) or {}).get("plans", [])
    if not KOSZ_PATH.exists():
        return []
    try:
        with open(KOSZ_PATH, "r", encoding="utf-8") as f:
            return json.load(f).get("plans", [])
    except Exception:
        return []


def _kosz_save(plany: list[dict]) -> None:
    from . import store
    dane = {"plans": plany[-_KOSZ_MAX:]}
    if store.enabled():
        store.kv_put(_KOSZ_KEY, dane)
        return
    KOSZ_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(KOSZ_PATH, "w", encoding="utf-8") as f:
        json.dump(dane, f, ensure_ascii=False, indent=2)


def delete_plan(plan_id: str) -> None:
    """Usuwa plan, ale odkłada kopię do kosza — patrz restore_plan."""
    data = _load_all()
    usuwany = next((p for p in data["plans"] if p.get("id") == plan_id), None)
    data["plans"] = [p for p in data["plans"] if p.get("id") != plan_id]
    _save_all(data)
    if usuwany is not None:
        kosz = [p for p in _kosz_load() if p.get("id") != plan_id]
        kosz.append({**usuwany, "_usuniety": date.today().isoformat()})
        _kosz_save(kosz)


def kosz_plany() -> list[dict]:
    """Usunięte plany, od najnowszego."""
    return list(reversed(_kosz_load()))


def restore_plan(plan_id: str = "") -> dict | None:
    """Przywraca plan z kosza (domyślnie ostatnio usunięty). Zwraca plan."""
    kosz = _kosz_load()
    if not kosz:
        return None
    if plan_id:
        wybrany = next((p for p in kosz if p.get("id") == plan_id), None)
    else:
        wybrany = kosz[-1]
    if wybrany is None:
        return None
    plan = {k: v for k, v in wybrany.items() if k != "_usuniety"}
    upsert_plan(plan)
    _kosz_save([p for p in kosz if p.get("id") != plan.get("id")])
    return plan


def create_plan(athlete: str, name: str, start: date, weeks: int = 4,
                group: str = "") -> dict:
    plan = {
        "id": new_id(), "athlete": athlete, "name": name,
        "group": (group or "").strip(),   # folder/klub
        "created": date.today().isoformat(),
        "start_date": start.isoformat(), "weeks": int(weeks),
        "sessions": [],
    }
    upsert_plan(plan)
    return plan


def plan_end(plan: dict) -> date | None:
    """Ostatni dzień zakresu planu (start + weeks·7 − 1)."""
    try:
        start = date.fromisoformat(plan["start_date"])
    except Exception:
        return None
    return start + timedelta(days=int(plan.get("weeks", 0)) * 7 - 1)


def is_current(plan: dict, on: date | None = None) -> bool:
    """Czy data (domyślnie dziś) mieści się w zakresie planu."""
    try:
        start = date.fromisoformat(plan["start_date"])
    except Exception:
        return False
    end = plan_end(plan)
    on = on or date.today()
    return bool(end and start <= on <= end)


def item_weeks(it: dict) -> dict:
    """Warianty tygodniowe itemu {"1": {sets_n,reps,intent,rest,sets}}.
    Legacy płaskie pola (sets_n/reps/… wprost na itemie) → tydzień 1."""
    ws = it.get("weeks")
    if isinstance(ws, dict) and ws:
        return ws
    legacy = {
        "sets_n": it.get("sets_n", ""),
        "reps": it.get("reps") or it.get("target", ""),
        "intent": it.get("intent", ""),
        "rest": it.get("rest", ""),
        "sets": it.get("sets") or [],
    }
    return {"1": legacy} if any(legacy.values()) else {}


# pola WYKONANIA (zawodnik) — nigdy nie dziedziczą na kolejne tygodnie;
# dziedziczy wyłącznie ROZPISKA (sets_n/reps/intent/rest)
_EXEC_FIELDS = ("load", "sets_done", "session_note", "sets")


def week_params(it: dict, wk: int) -> dict:
    """Dawka itemu dla tygodnia wk. Brak wpisu → dziedziczenie z najbliższego
    WCZEŚNIEJSZEGO tygodnia (auto-powielanie rozpiski przy progresji).
    Przy dziedziczeniu odcinamy pola wykonania — inaczej kg/serie/notatka
    z W1 wyglądałyby na telefonie jak już zrobione w W2/W3."""
    ws = item_weeks(it)
    for w in range(int(wk), 0, -1):
        p = ws.get(str(w))
        # PUŁAPKA: dict z samymi pustymi stringami jest truthy — wyczyszczony
        # tydzień zatrzymywał dziedziczenie i zabijał dawkę w nim ORAZ we
        # wszystkich kolejnych (audyt 2026-09-20). Liczy się treść rozpiski.
        if p and any(str(v or "").strip() for k, v in p.items()
                     if k not in _EXEC_FIELDS):
            if w != int(wk):
                p = {k: v for k, v in p.items() if k not in _EXEC_FIELDS}
            return p
        if p and w == int(wk) and any(p.get(k) for k in _EXEC_FIELDS):
            # sam wpis wykonania bez rozpiski: wykonanie z tego tygodnia,
            # dawka z najbliższego wcześniejszego (audyt 2026-09-30 — zawodnik
            # widział „—” zamiast dawki w tygodniu, w którym już coś wpisał)
            wyk = {k: v for k, v in p.items() if k in _EXEC_FIELDS}
            dawka = week_params(it, int(wk) - 1) if int(wk) > 1 else {}
            return {**{k: v for k, v in dawka.items() if k not in _EXEC_FIELDS}, **wyk}
    return {}


# ── wykonanie treningu przez zawodnika (telefon) ──────────────────────────
SERIA_OK, SERIA_SKIP = "ok", "skip"


def stan_serii(s: dict) -> str:
    """Stan jednej serii: "ok", "skip" albo "" (nietknięta).

    Zapisy sprzed trybu prowadzonego nie mają pola `stan` — tam wypełnione
    kg albo powtórzenia znaczy „zrobiona"."""
    if not isinstance(s, dict):
        return ""
    stan = (s.get("stan") or "").strip()
    if stan in (SERIA_OK, SERIA_SKIP):
        return stan
    if s.get("tkniete"):        # zawodnik świadomie cofnął — mimo kg w polach
        return ""
    return SERIA_OK if (s.get("reps") or s.get("kg")) else ""


def _load_z_serii(sets_done: list) -> str:
    """Load = ciężary kolejnych ZROBIONYCH serii; pominięta daje „—"."""
    kgs = [(s.get("kg") or "").strip() if stan_serii(s) == SERIA_OK else ""
           for s in sets_done]
    return " / ".join(k or "—" for k in kgs) if any(kgs) else ""


def load_tekstowy(params: dict) -> str:
    """Load wpisany tekstem, a nie wyliczony z serii („80 80 80", „BW",
    „20, 20, BW" — stare wpisy bez sets_done). "" gdy Load jest z serii."""
    load = str((params or {}).get("load") or "").strip()
    serie = [s if isinstance(s, dict) else {}
             for s in ((params or {}).get("sets_done") or [])]
    return load if load and load != _load_z_serii(serie) else ""


def _ustaw_load(params: dict, done: list) -> None:
    """Load po zmianie serii (params jeszcze ze STARYMI sets_done).
    Load z serii liczy się od nowa; Load tekstowy zostaje, dopóki nowe serie
    nie dadzą ciężaru — sama notatka albo ✓ bez kg nie może go skasować
    (recenzja 2026-09-27: 12 takich wpisów w training_plans.json)."""
    tekst = load_tekstowy(params)
    load = _load_z_serii(done)
    if load:
        params["load"] = load
    elif tekst:
        params["load"] = tekst
    else:
        params.pop("load", None)


def ustaw_serie(plan: dict, sess_id: str, item_i: int, wk: int, si: int,
                stan: str, reps: str = "", kg: str = "") -> dict:
    """Odklikanie jednej serii w trakcie treningu (zawodnik, telefon).

    stan: "ok" (zrobiona), "skip" (świadomie pominięta) albo "" (cofnięcie).
    Zapisuje do weeks[wk]["sets_done"][si] i przelicza Load. Zwraca plan —
    zapis do magazynu robi wołający (jeden upsert_plan na akcję)."""
    sess = next((s for s in ensure_sessions(plan) if s["id"] == sess_id), None)
    if sess is None:
        return plan
    items = sess.get("items") or []
    if not (0 <= item_i < len(items)):
        return plan
    it = items[item_i]
    params = dict(week_params(it, wk))
    done = [dict(x) for x in (params.get("sets_done") or [])]
    while len(done) <= si:
        done.append({})
    stare = done[si] if isinstance(done[si], dict) else {}
    nowy = {"reps": (reps or "").strip() or (stare.get("reps") or ""),
            "kg": (kg or "").strip() or (stare.get("kg") or ""),
            "stan": stan if stan in (SERIA_OK, SERIA_SKIP) else ""}
    # RPE wpisuje trener (tryb trenera) — klik zawodnika go nie kasuje
    if (stare.get("rpe") or "").strip():
        nowy["rpe"] = stare["rpe"]
    if not nowy["stan"]:
        nowy["tkniete"] = True   # cofnięcie: liczby zostają, stan pusty
    done[si] = nowy
    while done and not (done[-1].get("reps") or done[-1].get("kg")
                        or stan_serii(done[-1])):
        done.pop()
    _ustaw_load(params, done)
    params["sets_done"] = done
    it["weeks"] = dict(item_weeks(it))
    it["weeks"][str(wk)] = params
    return plan


def przecinek_dziesietny(x) -> str:
    """„82.5" → „82,5" (UI po polsku); tekst bez liczb zostaje bez zmian."""
    return re.sub(r"(?<=\d)\.(?=\d)", ",", str(x if x is not None else "").strip())


def zapisz_cwiczenie(plan: dict, sess_id: str, item_i: int, wk: int,
                     serie: list, notatka: str | None = None,
                     exercise: str = "") -> bool:
    """Pełny stan JEDNEGO ćwiczenia w tygodniu wk — tryb trenera (telefon).

    serie: [{"kg","reps","rpe","stan": "ok"|"skip"|""}] — każda seria ma
    własne liczby, niezależne od rozpiski (cięższe serie, falowanie).
    Wiersz z liczbami, ale bez ✓, dostaje stan "" + tkniete (jak cofnięcie
    u zawodnika) i nie liczy się do Load. notatka: None = bez zmian,
    "" = usuń, tekst = session_note tego tygodnia. Load wpisany tekstem
    (stary wpis bez serii) zostaje, dopóki serie nie dadzą ciężaru.

    Ćwiczenie szukane po indeksie i nazwie, potem po samej nazwie (trener
    mógł w międzyczasie przestawić rozpiskę na komputerze). Nie ma go —
    False i plan bez zmian. Zapis do magazynu robi wołający."""
    sess = next((s for s in ensure_sessions(plan) if s["id"] == sess_id), None)
    if sess is None:
        return False
    items = sess.get("items") or []
    nazwa = (exercise or "").strip().lower()

    def _nazwa(x: dict) -> str:
        return (x.get("exercise") or "").strip().lower()

    if 0 <= item_i < len(items) and (not nazwa or _nazwa(items[item_i]) == nazwa):
        it = items[item_i]
    else:
        pasujace = [j for j, x in enumerate(items) if nazwa and _nazwa(x) == nazwa]
        if not pasujace:
            return False
        it = items[min(pasujace, key=lambda j: abs(j - item_i))]

    done = []
    for s in serie or []:
        s = s if isinstance(s, dict) else {}
        stan = s.get("stan") if s.get("stan") in (SERIA_OK, SERIA_SKIP) else ""
        nowy = {"reps": str(s.get("reps") or "").strip(),
                "kg": przecinek_dziesietny(s.get("kg")), "stan": stan}
        rpe = przecinek_dziesietny(s.get("rpe"))
        if rpe:
            nowy["rpe"] = rpe
        if not stan and (nowy["reps"] or nowy["kg"] or rpe):
            nowy["tkniete"] = True
        done.append(nowy)
    while done and not (done[-1]["reps"] or done[-1]["kg"]
                        or done[-1].get("rpe") or done[-1]["stan"]):
        done.pop()

    wlasny = str(wk) in item_weeks(it)
    params = dict(week_params(it, wk))
    _ustaw_load(params, done)
    params["sets_done"] = done
    if notatka is not None:
        if notatka.strip():
            params["session_note"] = notatka.strip()
        else:
            params.pop("session_note", None)
    if not wlasny and not any(params.get(k) for k in _EXEC_FIELDS):
        return True       # nic do zapisania — dziedziczenie rozpiski zostaje żywe
    it["weeks"] = dict(item_weeks(it))
    it["weeks"][str(wk)] = params
    return True


def oznacz_start(plan: dict, sess_id: str, wk: int, dzien: str = "") -> dict:
    """„Zacznij trening" — trener widzi, że sesja jest w toku.
    dzien: data z telefonu — seria zrobiona bez zasięgu dostawała datę
    wysyłki, nie treningu (audyt 2026-09-30, SRV-07)."""
    sess = next((s for s in ensure_sessions(plan) if s["id"] == sess_id), None)
    if sess is not None:
        sess.setdefault("started_weeks", {})[str(wk)] = \
            _data_z_telefonu(dzien) if dzien else str(date.today())
    return plan


def oznacz_koniec(plan: dict, sess_id: str, wk: int, dzien: str = "") -> dict:
    """„Zakończ trening" — to samo pole, którego używa zapis z desktopu.
    dzien: data z telefonu (wpis wysłany po powrocie zasięgu następnego dnia
    ma datę treningu, nie wysyłki). Tydzień już zakończony zachowuje swoją
    datę — ponowne „Zakończ” po poprawce wpisów nie przesuwa „W1 · 08.09”
    na dziś (audyt 2026-09-30)."""
    sess = next((s for s in ensure_sessions(plan) if s["id"] == sess_id), None)
    if sess is not None:
        dw = sess.setdefault("done_weeks", {})
        if str(wk) in dw:
            return plan
        d = _data_z_telefonu(dzien)
        sess["done_date"] = d
        dw[str(wk)] = d
    return plan


def _data_z_telefonu(dzien: str) -> str:
    """Data RRRR-MM-DD z telefonu, jeśli wiarygodna (ostatnie 14 dni, nie
    później niż jutro — strefa czasowa telefonu), inaczej dzisiejsza."""
    from datetime import timedelta
    dzis = date.today()
    try:
        d = date.fromisoformat(str(dzien or "").strip())
    except ValueError:
        return str(dzis)
    return str(d) if dzis - timedelta(days=14) <= d <= dzis + timedelta(days=1) else str(dzis)


_POLA_SERII = ("kg", "reps", "rpe", "stan")


def scal_serie(baza: list, moje: list, obecne: list) -> list:
    """Scalanie trójstronne serii jednego ćwiczenia w tygodniu, pole po polu.

    baza — serie, które telefon widział, zanim coś zmienił; moje — serie
    z telefonu; obecne — serie w planie teraz. Pole zmienione na telefonie
    (moje ≠ baza) wygrywa, każde inne zostaje z planu. Trener i zawodnik
    wpisujący w tym samym ćwiczeniu nie kasują sobie serii, a wpis wysłany
    z opóźnieniem (brak zasięgu) nie cofa tego, czego telefon nie ruszał
    (audyt 2026-09-30: A3-01, OFF-09)."""
    def _s(lst, i):
        x = lst[i] if isinstance(lst, list) and i < len(lst) else {}
        return x if isinstance(x, dict) else {}

    def _v(x, f, plan=False):
        # stan z telefonu DOSŁOWNIE: "" z liczbami = „wpisane, bez ✓”;
        # stan_serii zrobiłby z tego „zrobiona” (weryfikacja 2026-09-30:
        # kg bez ✓ szło jako seria zrobiona, cofnięcia ✓ nie dało się zapisać).
        # Tylko wpis z planu może być stary, bez pola `stan` (kg = zrobiona).
        if f == "stan":
            return stan_serii(x) if plan else (str(x.get("stan") or "").strip()
                                               if x.get("stan") in (SERIA_OK, SERIA_SKIP) else "")
        return str(x.get(f) or "").strip()

    def _pole(b, m, c, f):
        if _v(m, f) == _v(b, f):
            return _v(c, f, plan=True)
        # liczba wstawiona samym ✓ (podpowiedź) ustępuje wpisanej przez drugą
        # stronę — ✓ trenera kasował 85×4 zawodnika (weryfikacja R1-02)
        if f in (m.get("auto") or ()) and _v(c, f, plan=True):
            return _v(c, f, plan=True)
        return _v(m, f)

    n = max(len(baza or []), len(moje or []), len(obecne or []))
    out = []
    for i in range(n):
        b, m, c = _s(baza, i), _s(moje, i), _s(obecne, i)
        out.append({f: _pole(b, m, c, f) for f in _POLA_SERII})
    while out and not any(out[-1].values()):
        out.pop()
    return out


# ── zmiany rozpiski z telefonu (tryb trenera, Filip 2026-09-28: „usunąć,
#    dodać, zamienić" w trakcie treningu) ────────────────────────────────────
def rozpiska_z_tekstu(dawka: str, inh: dict | None = None) -> dict:
    """„3 x 6 @ rpe 8" → {sets_n, reps, intent} — ta sama składnia co komórka
    siatki (apply_grid). Bez „@" intent dziedziczy z inh, pusty tekst → inh."""
    inh = inh or {}
    cell = (dawka or "").strip()
    if not cell:
        return {k: inh.get(k, "") for k in ("sets_n", "reps", "intent", "rest")}
    # zapis z dyktanda („4x6 rpe 8”, „2x 8-12 rb 9”) do jednej notacji: bez
    # tego RPE lądowało w powtórzeniach i ✓ nie wstawiał liczby (audyt 2026-10-04)
    from .dyktando import normalizuj_dawke
    cell = normalizuj_dawke(cell).strip() or cell
    intent = inh.get("intent", "")
    if "@" in cell:
        cell, _int = cell.split("@", 1)
        intent = _int.strip()
    s, r = split_dose(cell.strip())
    return {"sets_n": s, "reps": r, "intent": intent, "rest": inh.get("rest", "")}


def _znajdz_item(sess: dict, item_i: int, exercise: str) -> int:
    """Indeks ćwiczenia po pozycji i nazwie, potem po samej nazwie (jak
    w zapisz_cwiczenie). -1 = nie ma."""
    items = sess.get("items") or []
    nazwa = (exercise or "").strip().lower()

    def _nazwa(x: dict) -> str:
        return (x.get("exercise") or "").strip().lower()

    if 0 <= item_i < len(items) and (not nazwa or _nazwa(items[item_i]) == nazwa):
        return item_i
    pasujace = [j for j, x in enumerate(items) if nazwa and _nazwa(x) == nazwa]
    return min(pasujace, key=lambda j: abs(j - item_i)) if pasujace else -1


def usun_cwiczenie(plan: dict, sess_id: str, item_i: int, exercise: str = "") -> bool:
    """Ćwiczenie znika z planu (wszystkie tygodnie); z wpisami zawodnika →
    removed_items, tak jak przy usunięciu w edytorze. Numery porządkuje
    normalize_slots (samotne „1a" → „1")."""
    sess = next((s for s in ensure_sessions(plan) if s["id"] == sess_id), None)
    if sess is None:
        return False
    j = _znajdz_item(sess, item_i, exercise)
    if j < 0:
        return False
    it = sess["items"].pop(j)
    if item_has_content(it):
        sess["removed_items"] = list(sess.get("removed_items") or []) + [it]
    normalize_slots(sess["items"])
    return True


def dodaj_cwiczenie(plan: dict, sess_id: str, section: str, exercise: str,
                    dawka: str = "", wk: int = 1, slot: str = "") -> bool:
    """Nowe ćwiczenie na końcu sekcji; rozpiska od tygodnia wk (wcześniejsze
    tygodnie puste — nie dopisuję wstecz). Bez slotu dostaje kolejny numer."""
    sess = next((s for s in ensure_sessions(plan) if s["id"] == sess_id), None)
    nazwa = (exercise or "").strip()
    if sess is None or not nazwa:
        return False
    items = sess.setdefault("items", [])
    section = section or "Main"
    if not slot:
        numery = [int(m.group(1)) for x in items if x.get("section") == section
                  for m in [re.match(r"^\s*(\d+)", str(x.get("slot") or ""))] if m]
        slot = str(max(numery) + 1 if numery else 1)
    nowy = {"slot": slot, "exercise": nazwa, "section": section, "note": "",
            "weeks": {str(max(int(wk), 1)): rozpiska_z_tekstu(dawka)}}
    ostatni = max((j for j, x in enumerate(items) if x.get("section") == section),
                  default=-1)
    items.insert(ostatni + 1, nowy)
    return True


def zamien_cwiczenie(plan: dict, sess_id: str, item_i: int, exercise: str,
                     nowe: str, dawka: str = "", wk: int = 1) -> bool:
    """Inne ćwiczenie w tym samym miejscu (cały plan, numer i sekcja
    zostają). Nowa dawka — od tygodnia wk; wpisy tygodnia (kg/serie/
    notatka) zostają. Bez dawki rozpiska bez zmian."""
    sess = next((s for s in ensure_sessions(plan) if s["id"] == sess_id), None)
    nazwa = (nowe or "").strip()
    if sess is None or not nazwa:
        return False
    j = _znajdz_item(sess, item_i, exercise)
    if j < 0:
        return False
    it = sess["items"][j]
    it["exercise"] = nazwa
    if (dawka or "").strip():
        params = dict(week_params(it, wk))
        params.update(rozpiska_z_tekstu(dawka, params))
        it["weeks"] = dict(item_weeks(it))
        it["weeks"][str(wk)] = params
    return True


def wykonanie_sesji(sess: dict, wk: int) -> list[dict]:
    """Co zawodnik odklikał w tygodniu wk — dla panelu trenera.

    Zwraca po jednym wpisie na ćwiczenie, które ma jakikolwiek ślad:
    [{"exercise","slot","section","serie":[{"nr","stan","reps","kg","rpe"}],
      "zrobione","pominiete","note"}]."""
    out = []
    for it in (sess.get("items") or []):
        p = week_params(it, wk)
        done = p.get("sets_done") or []
        serie = [{"nr": i + 1, "stan": stan_serii(s),
                  "reps": (s.get("reps") or "").strip(),
                  "kg": (s.get("kg") or "").strip(),
                  "rpe": (s.get("rpe") or "").strip()}
                 for i, s in enumerate(done) if stan_serii(s) or s.get("reps")
                 or s.get("kg") or s.get("rpe")]
        if not serie and not (p.get("session_note") or "").strip():
            continue
        out.append({
            "exercise": it.get("exercise", ""),
            "slot": str(it.get("slot", "") or ""),
            "section": it.get("section", "Main"),
            "serie": serie,
            "zrobione": sum(1 for s in serie if s["stan"] == SERIA_OK),
            "pominiete": sum(1 for s in serie if s["stan"] == SERIA_SKIP),
            "note": (p.get("session_note") or "").strip(),
        })
    return out


def merge_week_rows(old_items: list[dict], new_rows: list[dict],
                    section: str, wk: int,
                    dropped: list | None = None) -> list[dict]:
    """Nowa lista itemów sekcji po edycji tygodnia wk.

    new_rows: [{"slot","exercise","note","params":{sets_n,reps,intent,rest,sets}}]
    Dawki INNYCH tygodni przenoszone ze starego itemu — dopasowanie po nazwie
    ćwiczenia, w drugiej kolejności po pozycji (rename zachowuje progresję).
    dropped (opcjonalnie): lista, do której trafią stare itemy USUNIĘTE
    w tym zapisie — pozwala wołającemu zarchiwizować wyniki zawodnika."""
    used: set[int] = set()
    out: list[dict] = []
    for pos, r in enumerate(new_rows):
        prev = None
        for j, o in enumerate(old_items):
            if j not in used and o.get("exercise", "") == r.get("exercise", ""):
                prev, _ = o, used.add(j)
                break
        if prev is None and pos < len(old_items) and pos not in used:
            prev = old_items[pos]
            used.add(pos)
        ws = dict(item_weeks(prev)) if prev else {}
        params = dict(r.get("params") or {})
        # Edytor trenera dotyka TYLKO rozpiski (sets_n/reps/intent/rest).
        # Dane WYKONANIA wpisane przez zawodnika (load, sets_done,
        # session_note) + legacy sets — zachowujemy ze starego wpisu tego
        # tygodnia, inaczej zapis trenera skasowałby wyniki podopiecznego.
        # Wyjątek: klucz JAWNIE dostarczony przez edytor (Main ma kolumnę
        # Load) wygrywa — puste pole = trener celowo wyczyścił.
        key_wk = str(int(wk))
        prev_wk = ws.get(key_wk) or {}
        for _exec in ("load", "sets_done", "session_note", "sets"):
            if _exec not in params and prev_wk.get(_exec):
                params[_exec] = prev_wk[_exec]
        # NIE materializuj tygodnia przy samym PRZEGLĄDANIU: jeśli ten
        # tydzień nie miał jawnego wpisu, a edytor oddaje dokładnie to,
        # co wynika z dziedziczenia (i zero wykonania) — zostaw
        # dziedziczenie żywe. Inaczej klikanie pigułek Week 2/3/4
        # zamrażałoby kopie i późniejsza poprawka W1 nie propagowałaby
        # (kontrakt: „rozpisanie T1 powiela się na T2").
        if key_wk not in ws:
            inh = week_params(prev, wk) if prev is not None else {}
            same_as_inh = all(
                (params.get(f) or "") == (inh.get(f) or "")
                for f in ("sets_n", "reps", "intent", "rest"))
            has_exec = any(params.get(f) for f in _EXEC_FIELDS)
            if same_as_inh and not has_exec:
                out.append({"section": section,
                            "slot": r.get("slot", ""),
                            "exercise": r.get("exercise", ""),
                            "note": r.get("note", ""),
                            "weeks": ws})
                continue
        ws[key_wk] = params
        out.append({"section": section,
                    "slot": r.get("slot", ""),
                    "exercise": r.get("exercise", ""),
                    "note": r.get("note", ""),
                    "weeks": ws})
    if dropped is not None:
        dropped.extend(o for j, o in enumerate(old_items) if j not in used)
    return out


def split_dose(dose: str) -> tuple[str, str]:
    """'3 x 5' → ('3','5'); '2 x 30 sec' → ('2','30 sec'); 'AMRAP' → ('','AMRAP').
    Jedno źródło parsowania dawki dla edytora tygodniowego i siatki."""
    m = re.match(r"^\s*(\d+(?:\s*-\s*\d+)?)\s*[x×X]\s*(.+)$", dose or "")
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return "", (dose or "").strip()


def apply_grid(old_items: list[dict], section: str, grid_rows: list[dict],
               weeks_n: int, dropped: list | None = None) -> list[dict]:
    """Zapis widoku SIATKI (Excel-owy: wiersz = ćwiczenie, kolumny W1..Wn).

    grid_rows: [{"slot","exercise","note",
                 "doses":{1:"3 x 5 @ rpe 8", 2:"", ...}}]
    Komórka Wk niesie pełną dawkę jak w Excelach Filipa:
    "sets x reps @ intent" (np. "3 x 6 @ rpe 8"); bez "@" → intent
    dziedziczony. PUSTA komórka = dziedzicz cały tydzień (nie
    materializuje — mechanizm same_as_inh w merge_week_rows).
    Rest i wyniki zawodnika (load/sets_done/notatki) nietykane —
    siatka nie dostarcza tych kluczy (Rest → widok Edytor)."""
    items = [it for it in old_items]
    first_dropped: list = []
    for wk in range(1, max(int(weeks_n), 1) + 1):
        used: set[int] = set()
        rows_wk = []
        for pos, g in enumerate(grid_rows):
            # dopasuj BIEŻĄCY item (po nazwie, potem pozycji) — po zapisie
            # W1 kaskada widzi już zaktualizowane itemy (rename działa)
            prev = None
            for j, o in enumerate(items):
                if j not in used and o.get("exercise", "") == \
                        g.get("exercise", ""):
                    prev, _ = o, used.add(j)
                    break
            if prev is None and pos < len(items) and pos not in used:
                prev = items[pos]
                used.add(pos)
            inh = week_params(prev, wk) if prev is not None else {}
            cell = (g.get("doses") or {}).get(wk, "") or \
                   (g.get("doses") or {}).get(str(wk), "")
            cell = (cell or "").strip()
            intent = inh.get("intent", "")
            if cell:
                if "@" in cell:
                    cell, _int = cell.split("@", 1)
                    intent = _int.strip()
                s, r = split_dose(cell.strip())
            else:
                s, r = inh.get("sets_n", ""), inh.get("reps", "")
            if wk == 1 and "rest" in g:
                rest = (g.get("rest") or "").strip()
            else:
                rest = inh.get("rest", "")
            rows_wk.append({"slot": g.get("slot", ""),
                            "exercise": g.get("exercise", ""),
                            "note": g.get("note", ""),
                            "params": {"sets_n": s, "reps": r,
                                       "intent": intent,
                                       "rest": rest}})
        drop_wk: list = []
        items = merge_week_rows(items, rows_wk, section, wk, drop_wk)
        if wk == 1:
            first_dropped = drop_wk
    if dropped is not None:
        dropped.extend(first_dropped)
    return items


def normalize_slots(items: list[dict]) -> list[dict]:
    """Litera przy numerze tylko gdy grupa ma ≥2 ćwiczenia (reguła Filipa):
    samotne „3a" → „3"; para „1a"+„1b" zostaje bez zmian. Grupy liczone
    osobno w każdej sekcji. Modyfikuje i zwraca tę samą listę."""
    counts: dict[tuple, int] = {}
    for it in items:
        m = re.match(r"^\s*(\d+)\s*[a-hA-H]?\s*$", str(it.get("slot") or ""))
        if m:
            key = (it.get("section", ""), m.group(1))
            counts[key] = counts.get(key, 0) + 1
    for it in items:
        slot = str(it.get("slot") or "")
        m = re.match(r"^\s*(\d+)\s*[a-hA-H]\s*$", slot)
        if m and counts.get((it.get("section", ""), m.group(1)), 0) == 1:
            it["slot"] = m.group(1)
    return items


def item_has_content(it: dict) -> bool:
    """Czy item ma JAKĄKOLWIEK treść (rozpiska lub wykonanie) w dowolnym
    tygodniu — używane do archiwizacji itemów usuwanych w edytorze."""
    for wv in (it.get("weeks") or {}).values():
        if any((wv or {}).get(f) for f in
               ("sets_n", "reps", "intent", "rest",
                "load", "sets_done", "session_note")):
            return True
    return False


def next_block_name(name: str) -> str:
    """'GPP blok 2' → 'GPP blok 3'; bez liczby na końcu → dopisz ' 2'."""
    import re as _re
    m = _re.match(r"^(.*?)(\d+)\s*$", name or "")
    if m:
        return f"{m.group(1)}{int(m.group(2)) + 1}"
    return f"{(name or 'Plan').strip()} 2"


def duplicate_as_next_block(plan: dict) -> dict:
    """Kolejny blok wg systemu Filipa: nowy plan startuje dzień po końcu
    poprzedniego, te same treningi A/B/C i ćwiczenia; DAWKA z ostatniego
    rozpisanego tygodnia staje się tygodniem 1 (punkt wyjścia progresji);
    Load/wyniki/done się NIE przenoszą (to wykonanie, nie plan)."""
    end = plan_end(plan)
    start = (end + timedelta(days=1)) if end else date.today()
    new = {
        "id": new_id(), "athlete": plan.get("athlete", ""),
        "name": next_block_name(plan.get("name", "")),
        "created": date.today().isoformat(),
        "start_date": start.isoformat(),
        "weeks": int(plan.get("weeks", 4)),
        "sessions": [],
    }
    for s in ensure_sessions(plan):
        items = []
        for it in s.get("items") or []:
            ws = item_weeks(it)
            last = {}
            for k in sorted(ws, key=lambda x: -int(x)):
                p = ws[k]
                if any(p.get(f) for f in ("sets_n", "reps", "intent", "rest")):
                    last = p
                    break
            w1 = {f: last.get(f, "") for f in
                  ("sets_n", "reps", "intent", "rest")}
            # wszystkie pola pozycji (tempo, dwie_kg…) — bez pól wykonania
            items.append({**{k: v for k, v in it.items()
                             if k not in _EXEC_FIELDS},
                          "weeks": {"1": {**w1, "sets": []}}
                          if any(w1.values()) else {}})
        new["sessions"].append({"id": new_id(),
                                "title": s.get("title", ""),
                                "items": items, "done_date": ""})
    upsert_plan(new)
    return new


def _clean_weeks_execution(weeks: dict) -> dict:
    """Kopia dawek tygodniowych BEZ danych wykonania (load, sets_done,
    session_note, legacy sets) — rozpiska zostaje, wyniki nie."""
    out = {}
    for k, p in (weeks or {}).items():
        out[k] = {f: p.get(f, "") for f in ("sets_n", "reps", "intent",
                                            "rest")}
        out[k]["sets"] = []
    return out


def duplicate_session(sess: dict, title_suffix: str = " (kopia)") -> dict:
    """Kopia treningu w ramach planu: pełna rozpiska (wszystkie tygodnie),
    wyczyszczone wykonanie i done_date."""
    # wszystkie pola pozycji (tempo, dwie_kg…) — bez pól wykonania
    items = [{**{k: v for k, v in it.items() if k not in _EXEC_FIELDS},
              "weeks": _clean_weeks_execution(item_weeks(it))}
             for it in (sess.get("items") or [])]
    title = (sess.get("title") or "").strip()
    return {"id": new_id(),
            "title": (title + title_suffix) if title else "",
            "items": items, "done_date": ""}


def copy_plan_to_athlete(plan: dict, athlete: str, start: date) -> dict:
    """Kopia planu dla INNEGO zawodnika: pełna progresja tygodni,
    zero wyników/notatek wykonania/done_date, świeże id, BEZ share_token
    (nowy zawodnik dostaje własny link po wygenerowaniu)."""
    new = {
        "id": new_id(), "athlete": athlete,
        "name": plan.get("name", "Plan"),
        "created": date.today().isoformat(),
        "start_date": start.isoformat(),
        "weeks": int(plan.get("weeks", 4)),
        # bez tego kopia znikała: lista „Wszystkie" pokazuje in_base=True,
        # a folder decyduje o pozostałych zakładkach (2026-09-06)
        "group": (plan.get("group") or "").strip(),
        "in_base": plan.get("in_base"),
        "sessions": [
            {**duplicate_session(s, title_suffix=""), }
            for s in ensure_sessions(plan)
        ],
    }
    upsert_plan(new)
    return new


def get_or_create_share_token(plan: dict) -> str:
    """Sekretny token linku dla zawodnika (per plan). Tworzony leniwie,
    zapisywany w planie. Regeneracja = unieważnienie starego linku."""
    tok = (plan.get("share_token") or "").strip()
    if not tok:
        tok = uuid.uuid4().hex + uuid.uuid4().hex[:8]
        plan["share_token"] = tok
        upsert_plan(plan)
    return tok


def regenerate_share_token(plan: dict) -> str:
    """Nowy link — stary przestaje działać. Linki wcześniejszych bloków tej
    osoby (ta sama nazwa i folder) też: po końcu bloku stary link przenosi
    na aktualny plan, więc bez tego „nowy link” nikogo nie odcinał (SEC-1)."""
    plan["share_token"] = uuid.uuid4().hex + uuid.uuid4().hex[:8]
    upsert_plan(plan)
    for p in get_plans(plan.get("athlete", "")):
        # tylko ZAKOŃCZONE — tylko one przenoszą; link trwającego równolegle
        # planu (np. bieganie obok siłowni) zostaje (weryfikacja V5-04)
        end = plan_end(p)
        if (p.get("id") != plan.get("id") and p.get("share_token")
                and ten_sam_folder(p, plan) and end and end < date.today()
                and (p.get("start_date") or "") <= (plan.get("start_date") or "")):
            p["share_token"] = uuid.uuid4().hex + uuid.uuid4().hex[:8]
            upsert_plan(p)
    return plan["share_token"]


def ten_sam_folder(a: dict, b: dict) -> bool:
    """Ta sama osoba w sensie linku: ta sama nazwa (wołający) i ten sam folder.
    Dwóch „Michałów” z dwóch klubów się nie łączy (A6-04). „Pusty pasuje do
    każdego” łączył prywatnego Michała z Michałem ze Ślepska — cudze wyniki
    w „Ostatnio” i zapis do cudzego planu (weryfikacja R3-04), więc ściśle."""
    ga = str(a.get("group") or "").strip().lower()
    gb = str(b.get("group") or "").strip().lower()
    return ga == gb


def find_plan_by_token(token: str) -> dict | None:
    token = (token or "").strip()
    if len(token) < 20:
        return None
    for p in _load_all()["plans"]:
        if p.get("share_token") == token:
            return p
    return None


def ensure_sessions(plan: dict) -> list[dict]:
    """Lista treningów planu; leniwa migracja legacy workouts {w1d1: …}
    (kolejność wg tygodnia/dnia). Puste legacy wpisy pomijane."""
    if not isinstance(plan.get("sessions"), list):
        def _order(k: str):
            try:
                return int(k.split("d")[0][1:]), int(k.split("d")[1])
            except Exception:
                return (9999, 9999)
        plan["sessions"] = [
            {"id": new_id(), "title": (w or {}).get("title", ""),
             "items": (w or {}).get("items") or [],
             "done_date": (w or {}).get("done_date", "")}
            for k, w in sorted((plan.get("workouts") or {}).items(),
                               key=lambda kv: _order(kv[0]))
            if (w or {}).get("title") or (w or {}).get("items")
        ]
    return plan["sessions"]


def current_week(plan: dict, on: date | None = None) -> int | None:
    """Numer tygodnia planu dla daty (None poza zakresem)."""
    try:
        start = date.fromisoformat(plan["start_date"])
    except Exception:
        return None
    on = on or date.today()
    wk = (on - start).days // 7 + 1
    if 1 <= wk <= int(plan.get("weeks", 0)):
        return wk
    return None


