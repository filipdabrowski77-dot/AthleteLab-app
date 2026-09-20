"""
App shell — powłoka aplikacji jako custom component (paczka Claude Design 4).

`render_shell()` rysuje Start / Training Plans / Plan zawodnika / Bazę ćwiczeń
przez `views/app_shell/index.html`; Python podaje dane (`build_data`) i obsługuje
akcje (`handle_action`). Performance testing zostaje w dotychczasowym widoku
Streamlit (Filip 2026-09-02: „nie chcę z Performance testing na razie").

Wartość komponentu trwa między rerunami — każda akcja jest deduplikowana po
`seq` (ta sama pułapka, co w panelu planu).
"""
from __future__ import annotations

import base64
import json
import socket
from datetime import date

import pandas as pd
import streamlit as st

from . import coaches
from . import roster, exlib, todos
from .library import LIBRARY_DIR, get_athletes_summary
from .profiles import (coach_of, hidden_names, list_profile_names, load_profiles,
                       names_for_coach, rename_profile, save_profile, set_coach,
                       set_hidden)
from .training import (create_plan, delete_plan, duplicate_as_next_block,
                       restore_plan,
                       ensure_sessions, get_all_plans,
                       get_or_create_share_token, is_current, new_id,
                       plan_end, regenerate_share_token, upsert_plan,
                       upsert_plans)

RECENT_PATH = LIBRARY_DIR / "recent_plans.json"
GROUPS_PATH = LIBRARY_DIR / "plan_groups.json"

# grupa = filtr i kolor badge'a w Bazie. Podział Filipa (2026-09-02):
# przygotowanie → plyometria → wzorce ruchu → staw/mięsień.
_WZORCE = {"Horizontal press", "Horizontal pull", "Vertical press",
           "Vertical pull", "Squat bilateral", "Squat unilateral",
           "Hinge bilateral", "Hinge unilateral"}
# Hip lock jest własną kategorią (nie podkategorią Hip) — decyzja Filipa
_STAWY = {"Hip lock", "Deep tier", "Hip", "Ankle", "Shoulder", "Knee", "Quad", "Hamstring",
          "Core", "Spine", "Neck", "Wrist",
          "Biceps", "Triceps"}


def _grupa(cat: str) -> str:
    c = (cat or "").strip()
    if c in ("Movement Prep", "Plyometrics", "Jump", "Throws", "Run",
             "Sled variation", "Isometrics", "Nieprzypisane"):
        return c
    if c in _WZORCE:
        return "Wzorce ruchu"
    if c in _STAWY:
        return "Staw / mięsień"
    return "Nieprzypisane"

CHROME_CSS = """<style>
header[data-testid="stHeader"]{display:none!important}
.stApp div[data-testid="stMainBlockContainer"],
.stApp div[data-testid="stAppViewBlockContainer"],
.stApp [data-testid="block-container"],
.stApp .block-container, .stApp .main .block-container
  {padding:0!important;max-width:100%!important}

section[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"],
[data-testid="collapsedControl"]{display:none!important}
.stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"]{background:#fbfbf9!important}
div[data-testid="stCustomComponentV1"]{display:block}
[data-testid="stMain"] [data-testid="stVerticalBlock"]{gap:0!important}
[data-testid="stToast"]{font-family:Archivo,system-ui,sans-serif}
</style>"""


# ---------------------------------------------------------------- pomocnicze
def _d(iso: str, fmt: str = "%d.%m.%Y") -> str:
    try:
        return pd.Timestamp(iso).strftime(fmt)
    except Exception:
        return ""


def _initials(name: str) -> str:
    parts = [p for p in (name or "").split() if p]
    return "".join(p[0].upper() for p in parts[:2]) or "—"


def _status(p: dict) -> str:
    reczny = (p.get("status_set") or "").strip()
    if reczny and reczny != "Auto":
        return reczny
    if is_current(p):
        return "Trwa"
    end = plan_end(p)
    if end and end < date.today():
        return "Zamknięty"
    return "Szkic"


def _treningi(n: int) -> str:
    if n == 1:
        return "1 trening"
    if 2 <= n <= 4:
        return f"{n} treningi"
    return f"{n} treningów"


def _letter(i: int) -> str:
    return chr(ord("A") + i) if i < 26 else str(i + 1)


_GROUPS_KEY = "plan_groups"


def _groups_defined() -> list[str]:
    """Nazwy folderów zapisane wprost. Foldery są wspólne dla obu paneli,
    tak jak baza planów; pusty folder też ma prawo istnieć (Filip
    2026-09-02: „dodaj folder")."""
    from . import store
    if store.enabled():
        d = store.kv_get(_GROUPS_KEY) or {}
        return [str(x) for x in (d.get("groups") or []) if str(x).strip()]
    try:
        d = json.load(open(GROUPS_PATH, encoding="utf-8"))
    except Exception:
        return []
    return [str(x) for x in (d.get("groups") or []) if str(x).strip()]


_POMINIETE_KEY = "film_pominiete"
POMINIETE_PATH = LIBRARY_DIR / "film_pominiete.json"


def _pominiete() -> list[str]:
    """Ćwiczenia, do których Filip świadomie nie doda filmu — znikają
    z katalogu „Bez filmu", ale zostają w rozpiskach (2026-09-05)."""
    from . import store
    if store.enabled():
        d = store.kv_get(_POMINIETE_KEY) or {}
        return [str(x) for x in (d.get("names") or []) if str(x).strip()]
    try:
        d = json.load(open(POMINIETE_PATH, encoding="utf-8"))
    except Exception:
        return []
    return [str(x) for x in (d.get("names") or []) if str(x).strip()]


def _pominiete_save(names: list[str]) -> None:
    from . import store
    czyste, widziane = [], set()
    for n in names:
        n = " ".join(str(n).split())
        if n and n.lower() not in widziane:
            widziane.add(n.lower())
            czyste.append(n)
    if store.enabled():
        store.kv_put(_POMINIETE_KEY, {"names": czyste})
    else:
        POMINIETE_PATH.parent.mkdir(parents=True, exist_ok=True)
        json.dump({"names": czyste}, open(POMINIETE_PATH, "w", encoding="utf-8"),
                  ensure_ascii=False)


def _groups_save(names: list[str]) -> None:
    from . import store
    czyste, widziane = [], set()
    for n in names:
        n = " ".join(str(n).split())
        if n and n.lower() not in widziane:
            widziane.add(n.lower())
            czyste.append(n)
    if store.enabled():
        store.kv_put(_GROUPS_KEY, {"groups": czyste})
    else:
        GROUPS_PATH.parent.mkdir(parents=True, exist_ok=True)
        json.dump({"groups": czyste}, open(GROUPS_PATH, "w", encoding="utf-8"),
                  ensure_ascii=False)


_RECENT_KEY = "recent_plans"


def _recent_all() -> dict:
    """{coach_id: [plan_id, …]} — wspólny magazyn, żeby lista przetrwała
    restart w chmurze; osobna per panel trenera."""
    from . import store
    if store.enabled():
        d = store.kv_get(_RECENT_KEY) or {}
        return d if isinstance(d, dict) else {}
    try:
        d = json.load(open(RECENT_PATH, encoding="utf-8"))
    except Exception:
        return {}
    if isinstance(d, list):          # stary format (jedna lista) = Filip
        return {"filip": d}
    return d if isinstance(d, dict) else {}


def _load_recent() -> list[str]:
    v = _recent_all().get(coaches.current()) or []
    return [i for i in v if isinstance(i, str)]


def _recent_save(d: dict) -> None:
    from . import store
    if store.enabled():
        store.kv_put(_RECENT_KEY, d)
        return
    try:
        RECENT_PATH.parent.mkdir(parents=True, exist_ok=True)
        json.dump(d, open(RECENT_PATH, "w", encoding="utf-8"))
    except Exception:
        pass


def touch_recent(plan_id: str) -> None:
    """Ślad edycji — TYLKO na liście trenera, który właśnie zapisuje.
    Panele nie mieszają się nawzajem, choć baza planów jest wspólna."""
    d = _recent_all()
    ids = [i for i in (d.get(coaches.current()) or []) if i != plan_id]
    ids.insert(0, plan_id)
    d[coaches.current()] = ids[:8]
    _recent_save(d)


def _wroc_do_rozpiski(pick: dict | None) -> None:
    """Z Bazy ćwiczeń z powrotem do treningu, z którego przyszliśmy."""
    ss = st.session_state
    ss.pop("exlib_pick", None)
    ss.pop("exlib_pick_n", None)
    if pick:
        plan = next((p for p in get_all_plans()
                     if p["id"] == pick["plan"]), None)
        ss["tr_athlete_pending"] = plan.get("athlete", "") if plan else ""
        ss["tr_open_plan"] = pick["plan"]
        ss["tr_reopen_workout"] = (pick["plan"], pick["sid"])
    ss["app_mode"] = "training"


def forget_recent(plan_id: str) -> None:
    """Usunięty plan znika z list obu trenerów — inaczej zostaje martwy
    wpis, który zjada miejsce w „Ostatnio edytowane"."""
    if not plan_id:
        return
    d = _recent_all()
    zmiana = False
    for c, ids in list(d.items()):
        czyste = [i for i in (ids or []) if i != plan_id]
        if len(czyste) != len(ids or []):
            d[c] = czyste
            zmiana = True
    if zmiana:
        _recent_save(d)


_SHARE_BASE: list[str] = []


def _share_base() -> str:
    """Adres apki do linków — liczony raz na proces (bez sekretu i pliku
    szło przez socket do 8.8.8.8 przy każdym renderze ekranu planu)."""
    if _SHARE_BASE:
        return _SHARE_BASE[0]
    from .store import share_base
    base = share_base()
    if not base:
        try:
            base = (LIBRARY_DIR / "share_base_url.txt").read_text().strip().rstrip("/")
        except Exception:
            pass
    if not base:
        ip = "localhost"
        try:
            s_ = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s_.connect(("8.8.8.8", 80))
            ip = s_.getsockname()[0]
            s_.close()
        except Exception:
            pass
        base = f"http://{ip}:8501"
    _SHARE_BASE.append(base)
    return base


def _share_url(plan: dict) -> str:
    """Link dla zawodnika. W instancji gościa doklejam &ws=<przestrzeń>:
    apka zawodnika czyta domyślną przestrzeń i bez tego nie znajdowała planu
    („Ten link jest nieaktywny", choć token był dobry) — audyt 2026-09-20."""
    from .store import workspace
    url = f"{_share_base()}/?plan={get_or_create_share_token(plan)}"
    ws = workspace()
    return f"{url}&ws={ws}" if ws else url


def _all_names() -> list[str]:
    """Zawodnicy AKTYWNEGO trenera. Plany są wspólne, więc nie dociągam
    nazwisk z planów — inaczej panele widziałyby swoich podopiecznych
    nawzajem (Filip 2026-09-02)."""
    vald = {a["name"] for a in get_athletes_summary()}
    return names_for_coach(coaches.current(), vald_names=vald)


def _przypisz_zawodnika(name: str) -> None:
    """Nowa osoba wpisana w formularzu planu — profil trafia do panelu
    trenera, który ją dodał (inaczej zniknęłaby z jego listy)."""
    name = " ".join((name or "").split())
    if not name:
        return
    if name in load_profiles():
        if not coach_of(name):
            set_coach(name, coaches.current())
    else:
        save_profile(name, coach=coaches.current())


def _braki_filmow(plans: list[dict], yt: dict) -> dict[str, list[str]]:
    """nazwa ćwiczenia bez filmu → plany, w których występuje."""
    braki: dict[str, list[str]] = {}
    for p in plans:
        for s in (p.get("sessions") or []):
            for it in (s.get("items") or []):
                n = (it.get("exercise") or "").strip()
                if n and not yt.get(n.lower()):
                    lst = braki.setdefault(n, [])
                    if p["name"] not in lst:
                        lst.append(p["name"])
    return braki


# ---------------------------------------------------------------- dane
_KLUCZE = ("training_plans", "exercise_library", "athlete_profiles",
           "plan_todos", "recent_plans", "plan_groups", "film_pominiete")


def _planow(n: int) -> str:
    if n == 1:
        return "plan"
    return "plany" if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else "planów"


def _plany_trenera(plans: list[dict]) -> list[dict]:
    """Plany widoczne w panelu aktywnego trenera.

    Baza planów jest wspólna (jeden magazyn), ale każdy panel ma pokazywać
    tylko swoje — inaczej lista puchnie o cudze rozpiski (Filip 2026-09-05).
    Przypisanie idzie po zawodniku: profil bez znacznika trenera należy do
    Filipa, więc plany klubowe i osób sprzed podziału zostają u niego.
    """
    from . import profiles as _pr
    kto = (coaches.current() or "").strip().lower()
    trener_by = {n.strip().lower(): (p.get("coach") or "").strip().lower()
                 for n, p in _pr.load_profiles().items()}

    def moj(plan: dict) -> bool:
        c = trener_by.get((plan.get("athlete") or "").strip().lower(), "")
        return c == kto or (not c and kto == "filip")

    return [p for p in plans if moj(p)]


def _profil_karta(name: str, plans: list[dict]) -> dict:
    """Kafelek na liście podopiecznych — tyle, ile widać bez wchodzenia."""
    d = roster.profil(name, plans)
    biez = d["current"]
    return {
        "name": name,
        "initials": _initials(name),
        "plans_n": len(d["plans"]),
        "tests_n": len(d["tests"]),
        "current": (biez or {}).get("name", ""),
        "current_id": (biez or {}).get("id", ""),
        "last": _d(d["plans"][0].get("start_date") or d["plans"][0].get("created") or "")
                if d["plans"] else "",
    }


def _wykonanie_profilu(plany: list[dict]) -> list[dict]:
    """Co zawodnik odklikał na telefonie — do panelu trenera, najnowsze pierwsze.

    Jeden wpis = jeden trening w jednym tygodniu: serie z ciężarem i powtórzeniami
    plus to, czego zawodnik świadomie nie zrobił (Filip 2026-09-18)."""
    from .training import wykonanie_sesji
    out = []
    for p in plany:
        sesje = ensure_sessions(p)
        for i, s in enumerate(sesje):
            zrobione = s.get("done_weeks") or {}
            zaczete = s.get("started_weeks") or {}
            for wk in range(1, int(p.get("weeks") or 4) + 1):
                poz = wykonanie_sesji(s, wk)
                if not poz:
                    continue
                iso = zrobione.get(str(wk)) or zaczete.get(str(wk)) or ""
                out.append({
                    "plan": p.get("name", ""),
                    "plan_id": p.get("id", ""),
                    "trening": (s.get("title") or "").strip() or chr(65 + i),
                    "week": wk,
                    "date": _d(iso) if iso else "—",
                    "iso": iso,
                    "status": ("zapisany" if str(wk) in zrobione
                               else "w toku" if str(wk) in zaczete else "wpisy"),
                    "zrobione": sum(x["zrobione"] for x in poz),
                    "pominiete": sum(x["pominiete"] for x in poz),
                    "pozycje": poz,
                })
    out.sort(key=lambda r: (r["iso"], r["week"]), reverse=True)
    return out[:12]


def _profil_pelny(name: str, plans: list[dict]) -> dict:
    """Cały profil jednej osoby: plan bieżący, historia, testy z datami."""
    d = roster.profil(name, plans)
    biez_id = (d["current"] or {}).get("id", "")

    def _plan(p: dict) -> dict:
        return {
            "id": p.get("id", ""),
            "name": p.get("name", ""),
            "date": _d(p.get("start_date") or p.get("created") or ""),
            "weeks": int(p.get("weeks") or 4),
            "workouts": _treningi(len(ensure_sessions(p) or [])),
            "status": _status(p),
            "group": (p.get("group") or "").strip(),
        }

    # plan, który dopiero wystartuje, nie jest „wcześniejszy" — idzie osobno
    dzis = date.today().isoformat()
    przyszle = [p for p in d["plans"]
                if p.get("id") != biez_id and (p.get("start_date") or "") > dzis]
    minione = [p for p in d["plans"]
               if p.get("id") != biez_id and (p.get("start_date") or "") <= dzis]

    return {
        "name": name,
        "initials": _initials(name),
        "wykonanie": _wykonanie_profilu(d["plans"]),
        "current": _plan(d["current"]) if d["current"] else None,
        "upcoming": [_plan(p) for p in przyszle],
        "plans": [_plan(p) for p in minione],
        "tests": [{
            "exercise": t["exercise"],
            "part": t.get("part", "Inne"),
            "date": _d(t["date"]) if t["date"] else "—",
            "iso": t["date"],
            "rm": t["rm"],
            "dose": t["dose"],
            "result": t["result"],
            "plan": t["plan"],
            "plan_id": t["plan_id"],
            "week": t["week"],
            "future": bool(t["date"] and t["date"] >= date.today().isoformat()),
        } for t in d["tests"]],
    }


def _zmien_nazwe_cwiczenia(stara: str, nowa: str) -> tuple[int, str]:
    """Nowa nazwa wchodzi do Bazy i do wszystkich rozpisek.

    Lista „Bez filmu” jest budowana z nazw w planach, więc sama poprawka
    w Bazie nic by nie dała — pozycja wróciłaby ze starą nazwą (Filip
    2026-09-05). Zwraca (ile pozycji w planach, komunikat o Bazie).
    """
    exs = exlib.exercises()
    wpis = next((e for e in exs
                 if (e.get("name") or "").strip().lower() == stara.lower()), None)
    kolizja = next((e for e in exs
                    if (e.get("name") or "").strip().lower() == nowa.lower()
                    and (wpis is None or e.get("id") != wpis.get("id"))), None)
    info = ""
    if kolizja:
        info = f'w Bazie było już „{kolizja.get("name")}” — rozpiski idą na ten wpis'
    elif wpis:
        e2 = dict(wpis)
        e2["name"] = nowa
        exlib.upsert_exercise(e2)
    else:
        info = "tego ćwiczenia nie ma w Bazie — poprawione tylko w rozpiskach"

    ile, zmienione = 0, []
    for pl in get_all_plans():
        zmiana = False
        for sesja in (pl.get("sessions") or []):
            for it in (sesja.get("items") or []):
                if (it.get("exercise") or "").strip().lower() == stara.lower():
                    it["exercise"] = nowa
                    zmiana = True
                    ile += 1
        if zmiana:
            zmienione.append(pl)
    upsert_plans(zmienione)
    return ile, info


def build_data(screen: str) -> dict:
    # jedno zapytanie zamiast sześciu — reszta funkcji czyta z cache
    from . import store as _st
    if _st.enabled():
        _st.kv_get_many(list(_KLUCZE))
    plans = get_all_plans()
    yt = exlib.url_map()
    exs = exlib.exercises()
    braki = _braki_filmow(plans, yt)
    # raz na render — wcześniej _pominiete() leciało w pętli po każdej nazwie
    pominiete = {n.lower() for n in _pominiete()}

    _c = coaches.current()
    # instancja gościa (workspace + tylko_plany) ma JEDEN panel — przełącznik
    # „Coach Filip / Coach Kuba" to panele Filipa i nie ma go co pokazywać
    _ws = _st.workspace()
    _solo = bool(_ws) and _st.tylko_plany()
    if _ws:
        # w przestrzeni gościa stopka pokazywała „Coach Filip" — czyli
        # drugiego trenera cudzym nazwiskiem
        _nazwa = _st.coach_name() or f"Coach {_ws.capitalize()}"
        # inicjały z imienia i nazwiska, bez tytułu: „Coach Jan Kowalski" → JK
        _slowa = [w for w in _nazwa.split()
                  if w.lower() not in ("coach", "trener")] or _nazwa.split()
        _ini = "".join(w[0] for w in _slowa[:2]).upper() or "?"
    else:
        _nazwa, _ini = coaches.name(_c), coaches.info(_c)["initials"]
    data: dict = {"user": {"name": _nazwa, "initials": _ini},
                  "coaches": [] if _solo else coaches.as_data(), "coach": _c}
    # Start to pulpit JEDNEGO trenera (Filip 2026-09-02): liczby liczą tylko
    # jego podopiecznych i ich plany. Baza planów w Training Plans zostaje
    # wspólna — tam widać wszystko.
    moi = set(_all_names())
    moje_plany = [p for p in plans if p.get("athlete", "") in moi]
    data["stats"] = {
        "plans": len(moje_plany),
        "plans_active": sum(1 for p in moje_plany if is_current(p)),
        "athletes": len(moi),
        "no_film": len([n for n in braki if n.lower() not in pominiete]),
    }
    data["queue"] = [{
        "id": t["id"],
        "date": _d(t.get("due"), "%d.%m") if t.get("due") else "—",
        "name": t.get("osoba") or t.get("text") or "",
        "plan": t.get("plan") or "",
    } for t in todos.list_todos(coach=_c)]
    by_id = {p["id"]: p for p in plans}
    # „Ostatnio edytowane przez Ciebie" — 3 plany, które ten trener
    # ostatnio zapisywał (nie: otwierał)
    data["recent"] = [{
        "initials": _initials(by_id[i].get("athlete", "")),
        "plan": by_id[i].get("name", ""),
        "meta": f"{by_id[i].get('athlete', '')} · "
                f"{_treningi(len(ensure_sessions(by_id[i]) or []))}",
        "id": i,
    } for i in _load_recent() if i in by_id][:3]
    data["athletes_list"] = _all_names()
    data["undo"] = st.session_state.get("cofnij_usuniety") or None
    # instancja drugiego trenera: powłoka ma nie rysować Performance testing
    data["tylko_plany"] = _st.tylko_plany()

    # Podopieczni: profil = plan bieżący + historia + testy siły z rozpisek.
    # Zawsze (koszt ~10 ms): powłoka rysuje ekran od razu po kliknięciu, więc
    # bez tego pierwsze wejście w Podopiecznych pokazywało pustą listę, dopóki
    # Python nie odpowiedział (2026-09-10).
    _r = [_profil_karta(n, plans) for n in _all_names()]
    _r.sort(key=lambda k: (0 if k["current"] else 1, k["name"].lower()))
    data["roster"] = _r
    kto = st.session_state.get("profil_osoby") or ""
    data["athlete"] = _profil_pelny(kto, plans) if kto else None
    # zdjęci z listy — bez tego usunięcie byłoby nieodwracalne
    data["hidden"] = hidden_names()
    # lista planów: od najnowszego; „group" = folder klubu (Filip 2026-09-02)
    widoczne_plany = _plany_trenera(plans)
    data["plans"] = [{
        "date": _d(p.get("created") or p.get("start_date") or ""),
        "name": p.get("name", ""), "athlete": p.get("athlete", ""),
        "status": _status(p), "id": p["id"],
        "group": (p.get("group") or "").strip(),
        "status_set": (p.get("status_set") or "").strip() or "Auto",
        "in_base": p.get("in_base"),
    } for p in sorted(widoczne_plany, key=lambda p: (p.get("created")
                                            or p.get("start_date") or ""),
                      reverse=True)]
    uzyte = {(p.get("group") or "").strip()
             for p in plans if (p.get("group") or "").strip()}
    data["groups"] = sorted(uzyte | set(_groups_defined()), key=str.lower)

    pid = st.session_state.get("tr_open_plan")
    plan = by_id.get(pid) if pid else None
    if plan is not None:
        sessions = ensure_sessions(plan)
        end = plan_end(plan)
        rng = ""
        try:
            rng = (f"{pd.Timestamp(plan.get('start_date')):%d.%m} – "
                   f"{end:%d.%m.%Y}") if end else ""
        except Exception:
            pass
        workouts = []
        for i, s in enumerate(sessions):
            items = [it for it in (s.get("items") or [])
                     if (it.get("exercise") or "").strip()]
            # kafelek nie może krzyczeć o brak filmu przy ćwiczeniu, które
            # Filip świadomie zdjął z katalogu (2026-09-06)
            no_film = sum(1 for it in items
                          if not yt.get(it["exercise"].strip().lower())
                          and it["exercise"].strip().lower() not in pominiete)
            dw = s.get("done_weeks") or {}
            done = ("W" + " W".join(sorted(dw, key=int)) if dw
                    else (_d(s.get("done_date"), "%d.%m")
                          if s.get("done_date") else ""))
            workouts.append({
                "letter": _letter(i), "sid": s.get("id", ""),
                "name": s.get("title") or f"Trening {_letter(i)}",
                "count": len(items), "no_film": no_film, "done": done,
            })
        data["plan"] = {
            "id": plan["id"], "name": plan.get("name", ""),
            "athlete": plan.get("athlete", ""), "status": _status(plan),
            "range": rng, "weeks": int(plan.get("weeks") or 4),
            "share_url": _share_url(plan), "workouts": workouts,
            "in_base": plan.get("in_base"),
            "skad": st.session_state.get("plan_skad") or "plans",
        }

    # Baza ćwiczeń — pełna taksonomia Filipa, grupa tylko do koloru badge'a
    data["categories"] = [{"name": c, "subs": list(subs)}
                          for c, subs in exlib.CATEGORIES.items()]
    from .ui_training import _yt_thumb
    data["exercises"] = [{
        "id": e.get("id", ""), "name": e.get("name", ""),
        "cat": e.get("cat") or "Nieprzypisane",
        "group": _grupa(e.get("cat") or "Nieprzypisane"),
        "cat2": e.get("cat2") or "",
        "group2": _grupa(e["cat2"]) if (e.get("cat2") or "").strip() else "",
        "cat3": e.get("cat3") or "",
        "group3": _grupa(e["cat3"]) if (e.get("cat3") or "").strip() else "",
        "cat4": e.get("cat4") or "",
        "group4": _grupa(e["cat4"]) if (e.get("cat4") or "").strip() else "",
        "sub": e.get("sub", "") or "", "url": e.get("url", "") or "",
        "intensity": e.get("sub", "") or "—",
        "has_film": bool((e.get("url") or "").strip()),
        "thumb": _yt_thumb(e.get("url", "")) or "",
    } for e in sorted(exs, key=lambda e: e.get("name", "").lower())]
    data["exercises_total"] = len(exs)
    # plany podajemy tylko po to, żeby pytanie przed usunięciem ćwiczenia
    # mówiło, z czego dokładnie zniknie (Filip 2026-09-05)
    data["no_film"] = [{"name": n, "plany": braki[n]}
                       for n in sorted(braki, key=str.lower)
                       if n.lower() not in pominiete]
    data["no_film_total"] = len(data["no_film"])
    data["no_film_skipped"] = sorted(_pominiete(), key=str.lower)
    bezkat = [e for e in exs if e.get("cat") == "Nieprzypisane"]
    uzycia: dict[str, list[str]] = {}
    for pl in plans:
        for sesja in (pl.get("sessions") or []):
            for it in (sesja.get("items") or []):
                n = (it.get("exercise") or "").strip().lower()
                if n and pl["name"] not in uzycia.setdefault(n, []):
                    uzycia[n].append(pl["name"])
    data["no_cat"] = [{"name": e.get("name", ""), "id": e.get("id", ""),
                       "plany": uzycia.get((e.get("name") or "").strip().lower(), [])}
                      for e in sorted(bezkat, key=lambda e: e.get("name", "").lower())]
    data["no_cat_total"] = len(bezkat)

    # tryb wyboru z edytora treningu („Baza ćwiczeń" w sekcji)
    pick = st.session_state.get("exlib_pick")
    if pick and screen == "exercises":
        pp = by_id.get(pick.get("plan"))
        if pp is not None:
            ses = ensure_sessions(pp)
            sidx = next((i for i, s in enumerate(ses)
                         if s.get("id") == pick.get("sid")), 0)
            data["pick"] = {
                "plan_name": pp.get("name", ""),
                "session_title": (ses[sidx].get("title") if sidx < len(ses)
                                  else "") or f"Trening {_letter(sidx)}",
                "section": st.session_state.get("exlib_pick_sec", "Main"),
                "added": st.session_state.get("exlib_pick_n", 0),
            }
        else:
            st.session_state.pop("exlib_pick", None)
    return data


# ---------------------------------------------------------------- akcje
def _open_workout(plan_id: str, sid: str) -> None:
    """Edytor treningu na CALA strone (Filip 2026-09-02: „duza przestrzen
    pracy", bez okna z innym tlem) — stan + rerun, rysuje render_shell."""
    from .ui_training import _pp_reset
    _pp_reset(plan_id, sid)
    st.session_state["tr_open_workout"] = (plan_id, sid)
    st.rerun()


def _download(pdf: bytes, name: str) -> None:
    st.session_state["shell_download"] = {
        "b64": base64.b64encode(pdf).decode(), "name": name,
        "mime": "application/pdf", "nonce": new_id(),
    }


def _pick_add(pick: dict, name: str, section: str) -> None:
    """Dopisz ćwiczenie z Bazy do treningu (logika jak w starym widoku)."""
    from .ui_training import _bazowa_dawka
    plan_ = next((p for p in get_all_plans() if p["id"] == pick["plan"]), None)
    if plan_ is None:
        return
    sess_ = ensure_sessions(plan_)
    s_ = next((x for x in sess_ if x.get("id") == pick.get("sid")),
              sess_[0] if sess_ else None)
    if s_ is None:
        return
    bd = _bazowa_dawka(name)
    s_.setdefault("items", []).append({
        "section": section, "slot": "", "exercise": name, "note": "",
        "weeks": ({"1": {"sets_n": bd["sets_n"], "reps": bd["reps"],
                         "intent": "", "rest": ""}} if bd else {}),
    })
    upsert_plan(plan_)
    kk = f"{pick['plan']}_{pick['sid']}"
    for k_ in list(st.session_state):
        if k_.startswith("trg_") and k_.endswith(kk):
            st.session_state.pop(k_, None)
    st.session_state.pop(f"ppw_{kk}", None)
    st.session_state["exlib_pick_n"] = st.session_state.get("exlib_pick_n", 0) + 1
    st.toast(f"＋ {name} → {section}", icon="✅")


def _zamknij_plan(ss) -> None:
    """„← …" na ekranie planu wraca tam, skąd plan został otwarty."""
    ss.pop("tr_open_plan", None)
    ss.pop("tr_open_workout", None)
    skad = ss.pop("plan_skad", "") or "plans"
    if skad == "athletes" and ss.get("profil_osoby"):
        ss["app_mode"] = "athletes"
    elif skad == "start":
        ss["app_mode"] = "home"
    else:
        ss["app_mode"] = "training"


def handle_action(ev: dict) -> None:
    from .ui_training import _tr_copy_plan_dialog, _tr_edit_plan_dialog
    a = ev.get("action")
    ss = st.session_state

    if a == "switch_coach":
        coaches.set_current(ev.get("id", ""))
        # czysty start w nowym panelu: bez otwartego planu, edytora i trybu
        # wyboru z Bazy; JS też wraca na Start, więc app_mode musi to gonić
        ss["app_mode"] = "home"
        for k in ("tr_open_plan", "tr_open_workout", "exlib_pick",
                  "exlib_pick_sec", "exlib_pick_n", "tr_reopen_workout",
                  "tr_athlete", "tr_athlete_pending"):
            ss.pop(k, None)
        st.toast(f"Panel: {coaches.name()}", icon="✅")
        st.rerun()

    elif a == "navigate":
        to = ev.get("to")
        # Menu przełącza MODUŁ i wraca do niego tam, gdzie w nim byłem
        # (Filip 2026-09-05: „zostajesz w tym samym momencie, gdzie byłeś").
        # Otwarty plan i otwarty profil zostają — zamykają je własne przyciski
        # „← Plany" / „← Podopieczni". Czyścimy tylko stan tymczasowy:
        # otwarty edytor, tryb wyboru ćwiczenia z Bazy i pytanie o zapis.
        # Bez tego (audyt 2026-09-05) tryb wyboru wyciekał poza Bazę — klik
        # w ćwiczenie dopisywał je do treningu sprzed kilku kliknięć — a dialog
        # „Zapisać zmiany?" zostawał otwarty nad kolejnymi ekranami.
        for k in ("tr_open_workout", "exlib_pick", "exlib_pick_sec",
                  "wk_exit_ask", "pp_dirty", "pp_zapisz_i_wyjdz"):
            ss.pop(k, None)
        if to == "plans" and ss.get("tr_open_plan"):
            # przyszedłeś z bocznego menu — powrót ma prowadzić na listę,
            # nie do profilu, z którego plan otwarto wcześniej
            ss["plan_skad"] = "plans"
        ss["app_mode"] = {"start": "home", "plans": "training",
                          "exercises": "exlib", "testing": "tests",
                          "athletes": "athletes"}.get(to, "home")
        st.rerun()

    elif a == "close_plan":
        _zamknij_plan(ss)
        st.rerun()

    elif a in ("open_plan", "queue_open"):
        ss.pop("tr_open_workout", None)
        # skąd otwarto plan — „← …" na jego ekranie wraca dokładnie tam
        ss["plan_skad"] = "start" if a == "queue_open" else (ev.get("skad") or "plans")
        pid = ev.get("id")
        if a == "queue_open":
            it = ev.get("item") or {}
            kto, jaki = (it.get("name") or "").strip(), (it.get("plan") or "").strip()
            cands = [p for p in get_all_plans()
                     if p.get("athlete", "").lower() == kto.lower()]
            hit = next((p for p in cands
                        if jaki and p.get("name", "").lower() == jaki.lower()),
                       None)
            if hit is None and cands and not jaki:
                hit = sorted(cands, key=lambda p: p.get("created", ""),
                             reverse=True)[0]
            if hit is None:
                # nie ma takiego planu → formularz nowego planu z wypełnioną osobą
                ss["app_mode"] = "training"
                ss.pop("tr_open_plan", None)
                ss["shell_prefill"] = {"athlete": kto, "name": jaki,
                                       "nonce": new_id()}
                st.rerun()
            pid = hit["id"]
        plan = next((p for p in get_all_plans() if p["id"] == pid), None)
        if plan is None:
            st.toast("Plan nie istnieje.")
            st.rerun()
        ss["tr_athlete_pending"] = plan.get("athlete", "")
        ss["tr_open_plan"] = pid
        ss["app_mode"] = "training"
        st.rerun()

    elif a == "save_athlete":
        stara = (ev.get("old") or "").strip()
        nowa = (ev.get("name") or "").strip()
        trener = (ev.get("coach") or coaches.current() or "").strip().lower()
        przypisz = [x for x in (ev.get("plans") or []) if x]
        znane = {n.lower() for n in list_profile_names()}

        if not nowa:
            st.toast("Podaj imię i nazwisko.")
            st.rerun()
        if not stara and nowa.lower() in znane:
            st.toast(f"„{nowa}” już jest na liście.")
            st.rerun()

        if not stara:                       # nowy podopieczny
            save_profile(nowa, coach=trener)
        else:
            # profil może nie istnieć — zawodnik znany tylko z testów VALD
            if stara.lower() not in znane:
                save_profile(stara, coach=trener)
            if nowa != stara:
                if not rename_profile(stara, nowa):
                    st.toast(f"Nie zmieniłem nazwy — „{nowa}” już istnieje.")
                    nowa = stara
                else:
                    # plany trzymają zawodnika po nazwie, więc idą za zmianą
                    za_nazwa = [pl for pl in get_all_plans()
                                if (pl.get("athlete") or "").strip() == stara]
                    for pl in za_nazwa:
                        pl["athlete"] = nowa
                    upsert_plans(za_nazwa)
            set_coach(nowa, trener)
            if st.session_state.get("profil_osoby") == stara:
                st.session_state["profil_osoby"] = nowa

        if przypisz:
            wsz = {p["id"]: p for p in get_all_plans()}
            zmienione = []
            for pid in przypisz:
                pl = wsz.get(pid)
                if pl is not None and (pl.get("athlete") or "").strip() != nowa:
                    pl["athlete"] = nowa
                    zmienione.append(pl)
            upsert_plans(zmienione)

        ile = len(przypisz)
        st.toast(f"Zapisano: {nowa}"
                 + (f" · przypisano {ile} {_planow(ile)}" if ile else ""))
        st.rerun()

    elif a == "hide_athlete":
        kto = (ev.get("name") or "").strip()
        if kto.lower() not in {n.lower() for n in list_profile_names()}:
            save_profile(kto, coach=coaches.current())
        set_hidden(kto, True)
        if st.session_state.get("profil_osoby") == kto:
            st.session_state.pop("profil_osoby", None)
        st.toast(f"{kto} zniknął z listy. Plany zostały.")
        st.rerun()

    elif a == "unhide_athlete":
        set_hidden((ev.get("name") or "").strip(), False)
        st.rerun()

    elif a == "open_athlete":
        ss["profil_osoby"] = (ev.get("name") or "").strip()
        ss["app_mode"] = "athletes"
        st.rerun()

    elif a == "close_athlete":
        ss.pop("profil_osoby", None)
        st.rerun()

    elif a == "queue_add":
        it = ev.get("item") or {}
        if (it.get("name") or "").strip():
            todos.add_todo(osoba=it.get("name", ""), plan=it.get("plan", ""),
                           due=(it.get("date") or "").strip(),
                           coach=coaches.current())
        st.rerun()

    elif a == "queue_del":
        if ev.get("id"):
            todos.set_done(ev["id"])
        st.rerun()

    elif a == "open_workout":
        _open_workout(ev.get("plan_id"), ev.get("sid"))

    elif a == "create_plan":
        f = ev.get("form") or {}
        kto = (f.get("new_athlete") or "").strip()
        if not kto:
            sel = (f.get("athlete") or "").strip()
            kto = "" if sel.startswith("wybierz") else sel
        nazwa = (f.get("name") or "").strip()
        if not kto or not nazwa:
            st.toast("Podaj zawodnika i nazwę planu.")
            return
        try:
            start = date.fromisoformat((f.get("start") or "").strip())
            if not (2000 <= start.year <= 2100):
                start = date.today()
        except Exception:
            start = date.today()
        try:
            weeks = max(1, min(52, int(str(f.get("weeks") or "4").strip())))
        except Exception:
            weeks = 4
        _przypisz_zawodnika(kto)
        grupa = (f.get("group") or "").strip()
        if not grupa:
            # zawodnik ma już plany w folderze klubowym →
            # nowy plan ląduje tam sam, bez klikania
            for q in sorted(get_all_plans(),
                            key=lambda x: (x.get("created") or ""), reverse=True):
                if q.get("athlete") == kto and (q.get("group") or "").strip():
                    grupa = q["group"].strip()
                    break
        plan = create_plan(kto, nazwa, start, weeks, group=grupa)
        # pelny znacznik czasu — lista sortuje po "created", sama data
        # ladowalaby pod planami z godzina z tego samego dnia
        import datetime as _dt
        plan["created"] = _dt.datetime.now().isoformat(timespec="seconds")
        plan["sessions"] = [
            {"id": new_id(), "title": "", "items": [], "done_date": "",
             "pp_seed": True} for _ in range(2)]
        upsert_plan(plan)
        ss["tr_athlete_pending"] = kto
        ss["tr_open_plan"] = plan["id"]
        ss["app_mode"] = "training"
        touch_recent(plan["id"])
        st.rerun()

    elif a in ("pdf", "pdf_kartka"):
        plan = next((p for p in get_all_plans() if p["id"] == ev.get("plan_id")), None)
        if plan is None:
            return
        fn = (plan.get("name", "plan").replace(" ", "_") + "_"
              + plan.get("athlete", "").split(" ")[0])
        if a == "pdf_kartka":
            from .plan_pdf_kartka import build_plan_pdf_kartka
            _download(build_plan_pdf_kartka(plan), fn + "_kartka.pdf")
        else:
            # Zielony szablon i tylko on (Filip 2026-09-20). Dawniej awaria
            # podmieniała go po cichu na PDF zapasowy — wyglądem inny plan
            # szedł do zawodnika, a w apce był tylko toast.
            try:
                from .plan_pdf_adapter import build_plan_pdf_green
                pdf = build_plan_pdf_green(plan, exlib.url_map())
            except Exception as e:
                st.error(f"Nie zrobiłem PDF-u planu: {e}")
                return
            _download(pdf, fn + ".pdf")
        st.rerun()

    elif a == "dyktando":
        from .ui_training import _tr_dyktando_dialog
        _tr_dyktando_dialog()

    elif a == "copy_link":
        st.toast("Link skopiowany", icon="✅")

    elif a == "regen_link":
        plan = next((p for p in get_all_plans() if p["id"] == ev.get("plan_id")), None)
        if plan is not None:
            regenerate_share_token(plan)
            st.toast("Nowy link — stary przestał działać")
        st.rerun()

    elif a == "add_workout":
        plan = next((p for p in get_all_plans() if p["id"] == ev.get("plan_id")), None)
        if plan is None:
            return
        touch_recent(plan["id"])
        sessions = ensure_sessions(plan)
        new_s = {"id": new_id(), "title": "", "items": [], "done_date": "",
                 "pp_seed": True}
        sessions.append(new_s)
        upsert_plan(plan)
        ss["tr_reopen_workout"] = (plan["id"], new_s["id"])
        st.rerun()

    elif a == "edit_plan":
        touch_recent(ev.get("plan_id", ""))
        _tr_edit_plan_dialog(ev.get("plan_id"))

    elif a == "add_group":
        n = " ".join((ev.get("name") or "").split())
        if not n:
            st.toast("Podaj nazwę folderu.")
        elif n.lower() in {g.lower() for g in _groups_defined()}:
            st.toast(f'Folder „{n}” już jest.')
        else:
            _groups_save(_groups_defined() + [n])
            st.toast(f"Folder: {n}", icon="✅")
        st.rerun()

    elif a == "rename_group":
        stara = " ".join((ev.get("old") or "").split())
        nowa = " ".join((ev.get("name") or "").split())
        if not (stara and nowa) or stara == nowa:
            st.rerun()
        elif nowa.lower() in {g.lower() for g in _groups_defined()
                              if g.lower() != stara.lower()}:
            st.toast(f'Folder „{nowa}” już jest.')
            st.rerun()
        else:
            _groups_save([nowa if g.lower() == stara.lower() else g
                          for g in _groups_defined()] + [nowa])
            w_folderze = [pl for pl in get_all_plans()
                          if (pl.get("group") or "").strip().lower() == stara.lower()]
            for pl in w_folderze:
                pl["group"] = nowa
            upsert_plans(w_folderze)
            ile = len(w_folderze)
            if ss.get("plans_group") == stara:
                ss["plans_group"] = nowa
            st.toast(f"{stara} → {nowa} ({ile} planów)", icon="✅")
            st.rerun()

    elif a == "delete_group":
        n = " ".join((ev.get("name") or "").split())
        _groups_save([g for g in _groups_defined() if g.lower() != n.lower()])
        w_folderze = [pl for pl in get_all_plans()   # plany zostają, tracą przypisanie
                      if (pl.get("group") or "").strip().lower() == n.lower()]
        for pl in w_folderze:
            pl["group"] = ""
        upsert_plans(w_folderze)
        ile = len(w_folderze)
        st.toast(f'Usunięto folder „{n}” — {ile} planów bez folderu', icon="🗑")
        st.rerun()

    elif a == "plan_in_base":
        # „w bazie planów" = plan widoczny na liście „Wszystkie". Bez tego
        # zostaje w swoim folderze i w profilu zawodnika (Filip 2026-09-05).
        plan = next((p for p in get_all_plans() if p["id"] == ev.get("plan_id")), None)
        if plan is not None:
            plan["in_base"] = bool(ev.get("yes"))
            upsert_plan(plan)
            st.toast("Plan w bazie planów" if plan["in_base"]
                     else "Plan zostaje tylko w folderze", icon="✅")
        if ev.get("zamknij"):
            _zamknij_plan(ss)
        st.rerun()

    elif a == "save_plan_meta":
        plan = next((p for p in get_all_plans()
                     if p["id"] == ev.get("plan_id")), None)
        if plan is None:
            st.rerun()
        nazwa = " ".join((ev.get("name") or "").split())
        kto = " ".join((ev.get("athlete") or "").split())
        if not nazwa:
            st.toast("Podaj nazwę planu.")
            st.rerun()
        plan["name"] = nazwa
        if kto and kto != plan.get("athlete"):
            plan["athlete"] = kto
            _przypisz_zawodnika(kto)
        plan["group"] = (ev.get("group") or "").strip()
        st_ = (ev.get("status") or "Auto").strip()
        plan["status_set"] = "" if st_ == "Auto" else st_
        upsert_plan(plan)
        touch_recent(plan["id"])
        st.toast(f"Zapisano: {nazwa}", icon="✅")
        st.rerun()

    elif a == "set_group":
        # plan_id przychodzi z otwartego planu albo z wiersza listy
        plan = next((p for p in get_all_plans() if p["id"] == ev.get("plan_id")), None)
        if plan is not None:
            plan["group"] = (ev.get("group") or "").strip()
            upsert_plan(plan)
            touch_recent(plan["id"])
            st.toast(f"Folder: {plan['group'] or 'brak'}", icon="✅")
        st.rerun()

    elif a == "copy_plan":
        _tr_copy_plan_dialog(ev.get("plan_id"))

    elif a == "dup_plan":
        plan = next((p for p in get_all_plans() if p["id"] == ev.get("plan_id")), None)
        if plan is not None:
            new = duplicate_as_next_block(plan)
            if (plan.get("group") or "").strip() and not (new.get("group") or "").strip():
                new["group"] = plan["group"]
                upsert_plan(new)
            ss["tr_open_plan"] = new["id"]
            touch_recent(new["id"])
        st.rerun()

    elif a == "delete_plan":
        ss.pop("pp_dirty", None)
        ss.pop("wk_exit_ask", None)
        pid = ev.get("plan_id")
        nazwa = next((p.get("name", "") for p in get_all_plans()
                      if p.get("id") == pid), "")
        forget_recent(pid)
        delete_plan(pid)
        # plan trafia do kosza — powłoka pokazuje pasek „Cofnij"
        ss["cofnij_usuniety"] = {"id": pid, "name": nazwa}
        ss.pop("tr_open_plan", None)
        st.rerun()

    elif a == "undo_delete_plan":
        wrocil = restore_plan(ss.get("cofnij_usuniety", {}).get("id", ""))
        ss.pop("cofnij_usuniety", None)
        if wrocil:
            st.toast(f"Przywrócono plan {wrocil.get('name', '')}", icon="↩️")
        st.rerun()

    elif a == "zamknij_cofnij":
        ss.pop("cofnij_usuniety", None)
        st.rerun()

    elif a == "pick_exercise":
        pick = ss.get("exlib_pick")
        if pick:
            sec = ev.get("section") or "Main"
            ss["exlib_pick_sec"] = sec
            _pick_add(pick, ev.get("name", ""), sec)
            # Filip 2026-09-03: po kliknięciu ćwiczenia wracamy OD RAZU do
            # rozpiski — bez szukania przycisku powrotu
            _wroc_do_rozpiski(pick)
        st.rerun()

    elif a == "pick_back":
        pick = ss.pop("exlib_pick", None)
        ss.pop("exlib_pick_n", None)
        _wroc_do_rozpiski(pick)
        st.rerun()

    elif a == "save_film":
        stara = (ev.get("name") or "").strip()
        nazwa = " ".join((ev.get("newname") or "").split()) or stara
        u = (ev.get("url") or "").strip()
        kat = (ev.get("cat") or "").strip()
        kat2 = (ev.get("cat2") or "").strip()
        kat = kat if kat in exlib.CATEGORIES else ""
        kat2 = kat2 if (kat2 in exlib.CATEGORIES and kat2 != kat) else ""
        if not stara or (nazwa == stara and not u and not kat):
            st.toast("Wklej link, wybierz kategorię albo popraw nazwę.")
            st.rerun()

        czesci = []
        if nazwa.lower() != stara.lower() or nazwa != stara:
            ile, info = _zmien_nazwe_cwiczenia(stara, nazwa)
            czesci.append(f'„{stara}” → „{nazwa}”'
                          + (f" ({ile} w rozpiskach)" if ile else ""))
            if info:
                czesci.append(info)
        if u or kat:
            ist = next((e for e in exlib.exercises()
                        if e["name"].strip().lower() == nazwa.lower()), None)
            if ist:
                e2 = dict(ist)
                if u:
                    e2["url"] = u
                if kat:
                    e2["cat"], e2["cat2"] = kat, kat2
                exlib.upsert_exercise(e2)
            elif u:
                # bez filmu do Bazy nie wchodzimy (reguła Filipa 2026-09-05)
                exlib.add_exercise(nazwa, kat or "Nieprzypisane", "", u)
                if kat2:
                    nowy = next((e for e in exlib.exercises()
                                 if e["name"].strip().lower() == nazwa.lower()), None)
                    if nowy:
                        nowy = dict(nowy)
                        nowy["cat2"] = kat2
                        exlib.upsert_exercise(nowy)
            else:
                # nazwa mogła się już zmienić w rozpiskach — powiedz o tym,
                # zamiast zgubić komunikat przed rerunem (2026-09-06)
                czesci.append("kategoria czeka na link — bez filmu wpis "
                              "nie wchodzi do Bazy")
                st.toast(" · ".join(czesci), icon="⚠️")
                st.rerun()
            if u:
                czesci.append("film zapisany")
            if kat:
                czesci.append(" + ".join([kat] + ([kat2] if kat2 else [])))
        st.toast(" · ".join(czesci), icon="✅")
        st.rerun()

    elif a == "pomin_film":
        # „nie dodam do tego filmu" — nazwa znika z katalogu, rozpiski zostają
        nazwa = (ev.get("name") or "").strip()
        if nazwa:
            _pominiete_save(_pominiete() + [nazwa])
            st.toast(f'„{nazwa}” — już nie w katalogu Bez filmu', icon="✅")
        st.rerun()

    elif a == "pomin_film_wszystkie":
        yt2 = exlib.url_map()
        byly = _pominiete()
        znane = {n.lower() for n in byly}
        nowe = {n for p in get_all_plans() for sesja in (p.get("sessions") or [])
                for it in (sesja.get("items") or [])
                if (n := (it.get("exercise") or "").strip())
                and not yt2.get(n.lower()) and n.lower() not in znane}
        _pominiete_save(byly + sorted(nowe))
        st.toast(f"Katalog Bez filmu wyczyszczony ({len(nowe)} pozycji)", icon="✅")
        st.rerun()

    elif a == "przywroc_film":
        nazwa = (ev.get("name") or "").strip()
        _pominiete_save([n for n in _pominiete() if n.lower() != nazwa.lower()])
        st.rerun()

    elif a == "usun_cwiczenie":
        # z panelu porządkowego kasujemy wszędzie: wpis w Bazie i pozycje
        # w rozpiskach. Sam wpis by nie wystarczył — listy są budowane
        # z nazw w planach, więc ćwiczenie zaraz by wróciło.
        nazwa = (ev.get("name") or "").strip()
        if not nazwa:
            st.rerun()
        ist = next((e for e in exlib.exercises()
                    if e["name"].strip().lower() == nazwa.lower()), None)
        if ist:
            exlib.delete_exercise(ist["id"])
        ile, zmienione = 0, []
        for pl in get_all_plans():
            zmiana = False
            for sesja in (pl.get("sessions") or []):
                items = sesja.get("items") or []
                zostaje = [it for it in items
                           if (it.get("exercise") or "").strip().lower() != nazwa.lower()]
                if len(zostaje) != len(items):
                    sesja["items"] = zostaje
                    ile += len(items) - len(zostaje)
                    zmiana = True
            if zmiana:
                zmienione.append(pl)
        upsert_plans(zmienione)
        czesci = ["z Bazy"] if ist else []
        if ile:
            czesci.append(f"{ile} z rozpisek")
        st.toast(f'Usunięto „{nazwa}”' + (" — " + " i ".join(czesci) if czesci else ""),
                 icon="🗑")
        st.rerun()

    elif a == "save_cat":
        stara = (ev.get("name") or "").strip()
        nazwa = " ".join((ev.get("newname") or "").split()) or stara
        cat = (ev.get("cat") or "").strip()
        kat23 = [(ev.get(k) or "").strip() for k in ("cat2", "cat3")]
        kat23 = [c for c in kat23 if c in exlib.CATEGORIES and c != cat]

        czesci = []
        if stara and (nazwa.lower() != stara.lower() or nazwa != stara):
            ile, info = _zmien_nazwe_cwiczenia(stara, nazwa)
            czesci.append(f'„{stara}” → „{nazwa}”'
                          + (f" ({ile} w rozpiskach)" if ile else ""))
            if info:
                czesci.append(info)

        if nazwa and cat and cat in exlib.CATEGORIES:
            ist = next((e for e in exlib.exercises()
                        if e["name"].strip().lower() == nazwa.lower()), None)
            if ist:
                e2 = dict(ist)
                e2["cat"], e2["sub"] = cat, (ev.get("sub") or "").strip()
                e2["cat2"] = kat23[0] if len(kat23) > 0 else ""
                e2["cat3"] = kat23[1] if len(kat23) > 1 else ""
                exlib.upsert_exercise(e2)
                czesci.append(" + ".join([cat] + kat23))
                st.toast(" · ".join(czesci), icon="✅")
            else:
                # Do Bazy wchodzą tylko ćwiczenia z filmem (Filip 2026-09-05).
                # Bez tego każda nazwa wpisana w planie — także wariant różniący
                # się dwiema literami albo pozycja użyta raz — zakładała nowy
                # wpis bez linku i lista puchła.
                st.toast(f'„{nazwa}” nie ma jeszcze filmu — dodaj link '
                         f'w zakładce „Bez filmu”, wtedy trafi do Bazy.')
        elif czesci:
            st.toast(" · ".join(czesci), icon="✅")
        else:
            st.toast("Wybierz kategorię albo popraw nazwę.")
        st.rerun()

    elif a == "save_exercise":
        f = ev.get("form") or {}
        ok = exlib.upsert_exercise({
            "id": (f.get("id") or "").strip() or None,
            "name": f.get("name", ""), "cat": f.get("cat") or "Nieprzypisane",
            "sub": f.get("sub", ""), "cat2": f.get("cat2", ""),
            "cat3": f.get("cat3", ""), "cat4": f.get("cat4", ""),
            "url": f.get("film", "")})
        if ok:
            st.toast(f"Zapisano: {f.get('name', '')}", icon="✅")
        else:
            st.warning("Pusta nazwa albo taka nazwa już jest w bazie.")
        st.rerun()

    elif a == "delete_exercise":
        if ev.get("id"):
            exlib.delete_exercise(ev["id"])
        st.rerun()


# ---------------------------------------------------------------- widok
EDITOR_CSS = """<style>
.stApp .st-key-wk_back button{min-height:34px!important;height:34px!important;
  padding:0 14px!important;border-radius:6px!important;border:1px solid #d8d5cc!important;
  background:#fff!important;font-size:13px!important;font-weight:600!important;color:#1c1b18!important}
.stApp .st-key-wk_back button:hover{background:#f2f1ec!important}
.stApp .st-key-wk_bar{padding:18px 40px 0}
.aph-wk-eyebrow{font-family:Archivo,system-ui,sans-serif;font-size:12.5px;font-weight:700;
  letter-spacing:.08em;text-transform:uppercase;color:#8a867c;padding-top:8px}
.aph-wk-warn{font-family:Archivo,system-ui,sans-serif;font-size:13px;font-weight:600;
  color:#a8452f;padding-top:9px}
</style>"""


@st.dialog("Zapisać zmiany?")
def _pytanie_o_zapis() -> None:
    """Wyjście z edytora nie może po cichu wyrzucić rozpiski."""
    # zdejmujemy flagę od razu: zamknięcie okna krzyżykiem ma wrócić
    # do edytora, a nie otwierać to samo pytanie w kółko
    st.session_state.pop("wk_exit_ask", None)
    # edytor ustawia WSZYSTKIM dialogom 96vw (dla podglądu PDF) — to okno
    # ma być wąskie, więc celujemy w nie po znaczniku w treści
    st.markdown(
        "<span class='aph-pyt-zapis'></span><style>"
        "div[data-testid='stDialog'] div[role='dialog']:has(.aph-pyt-zapis)"
        "{max-width:min(420px,92vw)!important;width:min(420px,92vw)!important;"
        "margin-top:14vh!important;border-radius:14px!important;"
        "box-shadow:0 18px 48px rgba(28,27,24,.18)!important}</style>",
        unsafe_allow_html=True)
    st.write("W tym treningu są zmiany, których jeszcze nie zapisałeś.")
    c1, c2 = st.columns(2)
    if c1.button("Zapisz", key="wk_save_back", type="primary",
                 use_container_width=True):
        st.session_state["pp_zapisz_i_wyjdz"] = True
        st.rerun()
    if c2.button("Nie zapisuj", key="wk_drop", use_container_width=True):
        st.session_state["pp_dirty"] = False
        st.session_state.pop("tr_open_workout", None)
        st.rerun()


def _render_workout_page(plan_id: str, sid: str) -> None:
    """Edytor treningu na pelnej szerokosci strony, z paskiem powrotu."""
    from .ui_training import _tr_workout_body
    plan = next((p for p in get_all_plans() if p["id"] == plan_id), None)
    if plan is None:
        st.session_state.pop("tr_open_workout", None)
        st.rerun()
    ses = ensure_sessions(plan)
    idx = next((i for i, s_ in enumerate(ses) if s_.get("id") == sid), None)
    if idx is None:
        st.session_state.pop("tr_open_workout", None)
        st.rerun()
    st.markdown(EDITOR_CSS, unsafe_allow_html=True)
    brudny = bool(st.session_state.get("pp_dirty"))
    if brudny and st.session_state.get("wk_exit_ask"):
        _pytanie_o_zapis()
    with st.container(key="wk_bar"):
        c1, c2 = st.columns([1.3, 7], vertical_alignment="center")
        if c1.button("← Wróć do planu", key="wk_back"):
            if brudny:
                st.session_state["wk_exit_ask"] = True
            else:
                st.session_state.pop("tr_open_workout", None)
            st.rerun()
        c2.markdown(
            f"<div class='aph-wk-eyebrow'>{plan.get('athlete', '')} · "
            f"{plan.get('name', '')} · "
            f"{ses[idx].get('title') or 'Trening ' + _letter(idx)}</div>",
            unsafe_allow_html=True)
    _tr_workout_body(plan_id, sid)


def render_shell() -> None:
    from views.app_shell import app_shell
    from .ui_training import _pp_reset

    st.markdown(CHROME_CSS, unsafe_allow_html=True)
    mode = st.session_state.get("app_mode", "home")

    # powrot z Bazy cwiczen / nowy trening → od razu edytor
    rw = st.session_state.pop("tr_reopen_workout", None)
    if rw and mode == "training":
        _pp_reset(rw[0], rw[1])
        st.session_state["tr_open_workout"] = (rw[0], rw[1])
    ow = st.session_state.get("tr_open_workout")
    if ow and mode == "training":
        _render_workout_page(ow[0], ow[1])
        return
    screen = {"home": "start", "training": "plans", "exlib": "exercises",
              "athletes": "athletes"}.get(mode, "start")
    if mode == "training" and st.session_state.get("tr_open_plan"):
        if not any(p["id"] == st.session_state["tr_open_plan"] for p in get_all_plans()):
            st.session_state.pop("tr_open_plan", None)
        else:
            screen = "plan"

    data = build_data(screen)
    extra = {}
    dl = st.session_state.pop("shell_download", None)
    if dl:
        extra["download"] = dl
    pf = st.session_state.pop("shell_prefill", None)
    if pf:
        extra["prefill"] = pf

    # widok Bazy (zakładka, filtr, szukajka) wraca do komponentu po rerunie
    exview = st.session_state.get("shell_exview")
    if exview:
        extra["exview"] = exview

    ev = app_shell(screen=screen, data=data, height=980, key="aph_shell", **extra)

    if isinstance(ev, dict) and ev.get("seq") \
            and ev.get("seq") != st.session_state.get("shell_seq"):
        st.session_state["shell_seq"] = ev["seq"]
        if isinstance(ev.get("exview"), dict):
            st.session_state["shell_exview"] = ev["exview"]
        handle_action(ev)
