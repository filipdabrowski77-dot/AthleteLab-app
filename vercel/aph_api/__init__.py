"""
Link zawodnika na Vercelu — wspólna logika dla api/plan.py i api/zapisz.py.

Ten sam kod co w apce Streamlita: plan z tokenu (`ui_training._plan_zawodnika`),
dane dla komponentu telefonu (`_trk_dane`) i zapis operacji z telefonu
(`_trk_zastosuj` → `upsert_plan` ze scalaniem 3-way). Zapis idzie do TEGO
SAMEGO dokumentu `training_plans` w Supabase, który czyta panel trenera —
trener widzi wpisy zawodnika jak dotąd.

Strona (public/index.html) rysuje tygodnie, treningi i nagłówek, a listę
ćwiczeń z seriami rysuje nietknięty komponent views/trener_panel/index.html
(public/panel.html) — strona udaje mu hosta Streamlita (streamlit:render /
setComponentValue).
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # vercel/
if KORZEN not in sys.path:
    sys.path.insert(0, KORZEN)                 # atrapa streamlit + kopia vald
if not os.path.isdir(os.path.join(KORZEN, "vald")):
    # lokalny dev: vald leży w repo obok, kopię robi dopiero sync_coach_repo.sh
    _repo = os.path.dirname(KORZEN)
    if _repo not in sys.path:
        sys.path.append(_repo)

TYPY_ZAWODNIKA = ("cwiczenie", "koniec")


def _ws(ws: str) -> None:
    """Przestrzeń z linku (?ws=…) — jak w athlete_app.py. Pusta = domyślna
    instancji (env APH_WORKSPACE). Ustawiana przy KAŻDYM żądaniu: ciepła
    funkcja obsługuje kolejne żądania w tym samym procesie."""
    from vald import store
    czysta = "".join(c for c in (ws or "") if c.isalnum() or c in "-_").lower()
    store.set_workspace(czysta)


def _baner(plan: dict, info: str, wk: int) -> dict:
    """Komunikaty nad tygodniami — 1:1 z _render_plan_workout_body."""
    from vald.training import plan_end
    dzis = date.today()
    koniec = plan_end(plan)
    start = str(plan.get("start_date") or "")
    if koniec and dzis > koniec:
        return {"rodzaj": "uwaga",
                "tekst": f"Plan zakończył się {koniec:%d.%m.%Y}. Wpisy trafią do "
                         f"Week {wk} — nowy plan = nowy link od trenera."}
    try:
        if date.fromisoformat(start) > dzis:
            return {"rodzaj": "info", "tekst": f"Plan startuje {start[8:10]}.{start[5:7]}."}
    except ValueError:
        pass
    if info:
        return {"rodzaj": "info", "tekst": info}
    return {}


def ladunek(token: str, ws: str = "") -> dict | None:
    """Wszystko, czego strona zawodnika potrzebuje: plan, tygodnie, treningi
    i dane komponentu dla KAŻDEGO treningu × tygodnia (zmiana tygodnia na
    telefonie nie idzie po sieci). None = link nieaktywny."""
    _ws(ws)
    from vald import ui_training as ut
    from vald.training import current_week, ensure_sessions, plan_end
    plan, info = ut._plan_zawodnika(token)
    if not plan:
        return None
    sesje = ensure_sessions(plan)
    n_tyg = max(int(plan.get("weeks") or 4), 1)
    plany = ut._plany_tej_osoby(plan)
    dzis = date.today()
    koniec = plan_end(plan)
    cw = current_week(plan)
    if cw is None:
        cw = n_tyg if (koniec and dzis > koniec) else 1
    treningi = []
    for i, s in enumerate(sesje):
        treningi.append({
            "id": s.get("id") or "",
            "litera": ut._tr_litera_treningu(s, i),
            "ma_cw": bool(s.get("items")),
            "done": sorted(str(k) for k in (s.get("done_weeks") or {})),
            "started": sorted(str(k) for k in (s.get("started_weeks") or {})),
        })
    dane = {}
    for s in sesje:
        for wk in range(1, n_tyg + 1):
            dane[f"{s.get('id')}|{wk}"] = ut._trk_dane(plan, s, wk, plany, zawodnik=True)
    return {
        "plan": {"id": plan.get("id", ""), "nazwa": plan.get("name", ""),
                 "imie": (plan.get("athlete") or "").split(" ")[0],
                 "tygodnie": n_tyg, "start": str(plan.get("start_date") or "")},
        "baner": _baner(plan, info, cw),
        "biezacy_tydzien": cw,
        "treningi": treningi,
        "kolejka": ut._klucz_kolejki(plan),
        "dane": dane,
    }


def zapisz(token: str, ops: list, ws: str = "") -> dict | None:
    """Operacje z telefonu → plany (ta sama droga co _trk_konsumuj w apce).
    Dozwolone: tylko plany tej osoby i tylko serie / „Zakończ trening”.
    Funkcja jest bezstanowa, więc lista zastosowanych id jest pusta —
    operacja „cwiczenie” niesie pełny stan, „koniec” nie przesuwa daty,
    ponowienie po zgubionym ack niczego nie psuje."""
    _ws(ws)
    from vald import ui_training as ut
    plan, _ = ut._plan_zawodnika(token)
    if not plan:
        return None
    dozw = {"plan_id": {p.get("id") for p in ut._plany_tej_osoby(plan)} | {plan.get("id")},
            "typy": TYPY_ZAWODNIKA}
    ops = [op for op in (ops if isinstance(ops, list) else []) if isinstance(op, dict)][:200]
    return ut._trk_zastosuj(ops, [], dozw)


# ── HTTP (BaseHTTPRequestHandler, jak chce Vercel) ───────────────────────────
def _zapytanie(path: str) -> dict:
    from urllib.parse import parse_qs, urlparse
    q = parse_qs(urlparse(path).query)
    return {k: (v[0] if v else "") for k, v in q.items()}


def odpowiedz(h, kod: int, cialo: dict) -> None:
    dane = json.dumps(cialo, ensure_ascii=False).encode("utf-8")
    h.send_response(kod)
    h.send_header("Content-Type", "application/json; charset=utf-8")
    h.send_header("Cache-Control", "no-store")
    h.send_header("Content-Length", str(len(dane)))
    h.end_headers()
    h.wfile.write(dane)


def obsluz_plan(h) -> None:
    q = _zapytanie(h.path)
    try:
        wynik = ladunek((q.get("plan") or "").strip(), q.get("ws") or "")
    except (RuntimeError, OSError) as e:
        odpowiedz(h, 503, {"blad": "Nie mogę teraz wczytać planu.", "szczegoly": str(e)[:200]})
        return
    if wynik is None:
        odpowiedz(h, 404, {"blad": "Ten link jest nieaktywny"})
        return
    odpowiedz(h, 200, wynik)


def obsluz_zapisz(h) -> None:
    q = _zapytanie(h.path)
    try:
        n = int(h.headers.get("Content-Length") or 0)
    except ValueError:
        n = 0
    if n > 2_000_000:
        odpowiedz(h, 413, {"blad": "Za duża wysyłka"})
        return
    try:
        cialo = json.loads(h.rfile.read(n).decode("utf-8") or "{}")
    except (ValueError, UnicodeDecodeError):
        odpowiedz(h, 400, {"blad": "Zły format"})
        return
    token = (q.get("plan") or (cialo.get("plan") if isinstance(cialo, dict) else "") or "").strip()
    ws = q.get("ws") or ""
    ops = cialo.get("ops") if isinstance(cialo, dict) else []
    try:
        wynik = zapisz(token, ops, ws)
        if wynik is None:
            odpowiedz(h, 404, {"blad": "Ten link jest nieaktywny"})
            return
        swieze = ladunek(token, ws) or {}
    except (RuntimeError, OSError) as e:
        odpowiedz(h, 503, {"blad": "Nie mogę teraz zapisać.", "szczegoly": str(e)[:200],
                           "ack": [], "odrzucone": []})
        return
    swieze.update(ack=list(wynik.get("ack") or []),
                  odrzucone=list(wynik.get("odrzucone") or []),
                  blad=wynik.get("blad") or "")
    odpowiedz(h, 200, swieze)
