"""
UI trybu treningowego — Plany (kafelki plan→treningi A/B/C, edytor
z progresją per tydzień, podgląd telefonu, udostępnianie), Baza ćwiczeń,
tryb SIŁOWNIA (?mode=gym) i widok ZAWODNIKA (?plan=<token>).

Wydzielone z app.py (2026-07-21) — moduł nie zależy od app.py; wszystkie
dane przez vald.training / vald.exlib / vald.library.
"""
from __future__ import annotations

import re

import pandas as pd
import streamlit as st

from .library import get_athletes_summary
from .profiles import list_profile_names
from .training import (
    copy_plan_to_athlete,
    current_week as current_week_of,
    ensure_sessions,
    find_plan_by_token,
    get_all_plans,
    get_plans,
    is_current,
    item_weeks,
    plan_end,
    upsert_plan,
    week_params,
)

# ─────────────────────────────────────────────────────────────────────────────
# TRYB: Plany treningowe — nawigacja w sidebarze.
# Widok kafelkowy (decyzja Filipa 2026-07-18, bez kalendarza):
# kafelki planów (nazwa + zakres dat, aktualny podświetlony) → klik →
# kafelki treningów A/B/C → klik → dialog treningu (ćwiczenia + wyniki).
# ─────────────────────────────────────────────────────────────────────────────

_TR_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _bazowa_dawka(nazwa: str) -> dict:
    """Bazowa dawka przy dodaniu ćwiczenia z Bazy (Filip 2026-08-30):
    kategoria Movement Prep dostaje od razu 1 x 8-12, plyometria 2 x 5.
    Zawsze do edycji — to tylko punkt startowy."""
    from vald import exlib as _ex_bd
    cat = ""
    for e in _ex_bd.exercises():
        if e["name"].strip().lower() == (nazwa or "").strip().lower():
            cat = (e.get("cat") or "").strip().lower()
            break
    if cat == "movement prep":
        return {"sets_n": "1", "reps": "8-12"}
    if cat in ("plyometrics", "plyometria"):
        return {"sets_n": "2", "reps": "5"}
    return {}


def _tr_letter(i: int) -> str:
    return _TR_LETTERS[i] if i < len(_TR_LETTERS) else str(i + 1)


@st.dialog("Edytuj plan")
def _tr_edit_plan_dialog(plan_id: str) -> None:
    plan = next((p for p in get_all_plans()
                 if p["id"] == plan_id), None)
    if not plan:
        st.info("Plan nie istnieje.")
        return
    pname = st.text_input("Nazwa planu", value=plan.get("name", ""),
                          key=f"trpe_name_{plan_id}")
    c1, c2 = st.columns(2)
    with c1:
        try:
            start_val = pd.Timestamp(plan.get("start_date")).date()
        except Exception:
            start_val = pd.Timestamp.now().date()
        start = st.date_input("Start (dzień 1)", value=start_val,
                              key=f"trpe_start_{plan_id}")
    with c2:
        weeks = st.number_input("Tygodnie", min_value=1, max_value=52,
                                value=int(plan.get("weeks", 4)),
                                key=f"trpe_weeks_{plan_id}")
    if st.button("Zapisz", type="primary", use_container_width=True,
                 key=f"trpe_save_{plan_id}"):
        if not pname.strip():
            st.warning("Podaj nazwę.")
            return
        plan["name"] = pname.strip()
        plan["start_date"] = str(start)
        plan["weeks"] = int(weeks)
        upsert_plan(plan)
        st.rerun()


_DYKT_WZOR = """plan: Imię Nazwisko | Nazwa planu | 2026-09-21 | 4
trening: A
prep
- 90/90 | 1x8-10
plyo
- 1a broad jump | 2x3
main
- 1a rumuński martwy ciąg | 2x5 rpe 7 | tempo: 3 sec ecc
- 1b swiss ball leg curl | 2x10-15 rpe 9 | uwagi: do upadku"""


_DYKT_NOWE = "➕ nowe ćwiczenie — wpisz dosłownie"


def _odmiana(n: int, poj: str, kilka: str, wiele: str) -> str:
    """1 trening, 2-4 treningi, 5+ (i 12-14) treningów."""
    n = abs(int(n))
    if n == 1:
        return poj
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return kilka
    return wiele


@st.dialog("Plan z dyktanda", width="large")
def _tr_dyktando_dialog() -> None:
    """Dyktando (Wispr Flow) wprost w apce — bez terminala i bez asystenta.
    Parser `vald/dyktando.py` jest czystym Pythonem: liczebniki słowne,
    pięć notacji dawek i dopasowanie nazw do Bazy działają też w chmurze.
    Nazwy, których nie ma pewnych, potwierdza się z listy — inaczej trzeba
    by znać składnię `=> Nazwa`, a tego nie da się zgadnąć."""
    from . import dyktando as dk
    from . import exlib as _ex
    st.caption("Wklej albo nadyktuj rozpiskę. Dawki przeliczę ze słów "
               "(„dwa x dziesięć rpe dziewięć”), nazwy dopasuję do Bazy.")
    tekst = st.text_area("Dyktando", height=240, key="dykt_tekst",
                         placeholder=_DYKT_WZOR, label_visibility="collapsed")
    with st.expander("Format — wzór do skopiowania"):
        st.code(_DYKT_WZOR, language=None)
        st.caption("Kolejne `|` z dawką to kolejne tygodnie (W1, W2, …). "
                   "Sekcje: prep, plyo, main, akcesoria.")
    # Streamlit oddaje treść pola dopiero po ⌘+Enter albo kliknięciu poza nie —
    # bez tego przycisku wklejenie tekstu nie robiło z pozoru NIC.
    st.button("Sprawdź dopasowania", use_container_width=True,
              key="dykt_sprawdz")
    if not (tekst or "").strip():
        return
    try:
        dane = dk.parsuj_dyktando(tekst)
    except Exception as e:
        st.error(f"Nie rozumiem tego zapisu: {e}")
        return
    nazwy = [e["name"] for e in _ex.exercises()]
    al = dk.aliasy()
    niepewne = []
    for t in dane["treningi"]:
        dk.rozstrzygnij(t["items"], nazwy, al)
        niepewne += [it for it in t["items"] if it["pewnosc"] < 0.999]
    p_ = dane["plan"]
    _tr_n = len(dane["treningi"])
    _poz = sum(len(t["items"]) for t in dane["treningi"])
    st.markdown(f"**{p_['athlete'] or '(brak zawodnika)'}** · "
                f"{p_['name'] or '(brak nazwy planu)'} · "
                f"{p_['weeks'] or 4} tyg. · "
                f"{_tr_n} {_odmiana(_tr_n, 'trening', 'treningi', 'treningów')} · "
                f"{_poz} {_odmiana(_poz, 'pozycja', 'pozycje', 'pozycji')}")
    for it in niepewne:
        kand = [n for n, _ in it["kandydaci"]]
        opcje = kand + [n for n in nazwy if n not in kand] + [_DYKT_NOWE]
        it["_wybor"] = st.selectbox(
            f"„{it['tekst']}” — potwierdź (linia {it['linia']})", opcje,
            key=f"dykt_w_{it['linia']}")
    with st.expander("Raport dopasowań", expanded=not niepewne):
        st.code(dk.raport(dane), language=None)
    if st.button("Utwórz plan", type="primary", use_container_width=True,
                 key="dykt_utworz"):
        for it in niepewne:
            if it.get("_wybor") == _DYKT_NOWE:
                it["nowe"] = True
            elif it.get("_wybor"):
                # ta sama droga co „=> Nazwa" w tekście: zapis planu utrwali
                # to jako alias, więc następne dyktando trafi od razu
                it["wskazana"] = it["_wybor"]
        try:
            plan = dk.zapisz_plan(dane)
        except ValueError as e:
            st.error(str(e))
            return
        from .shell import touch_recent
        touch_recent(plan["id"])
        ss = st.session_state
        ss["tr_open_plan"] = plan["id"]
        ss["app_mode"] = "training"
        st.rerun()


# Kolory badge grup superserii — z projektu Filipa (Claude Design,
# "Panel planu treningowego"): grupa 1 niebieska, 2 fioletowa, 3 morska,
# 4 śliwkowa; Prep zielony, Plyo pomarańczowy.
_TRV_GROUP_ACCENT = {
    "1": ("#dbe6ff", "#2f5fd0"), "2": ("#e6e3fb", "#5b52c9"),
    "3": ("#d6eef3", "#127c90"), "4": ("#efe0f7", "#8046b3"),
}


def _trv_chip(text: str, bg: str, fg: str, dashed: bool = False) -> str:
    border = "border:1px dashed #cfd4da;" if dashed else ""
    return (f"<span style='background:{bg};color:{fg};{border}"
            f"padding:2px 9px;border-radius:7px;font-size:11.5px;"
            f"font-weight:600;white-space:nowrap;'>{text}</span>")


@st.dialog("Kopiuj plan do zawodnika")
def _tr_copy_plan_dialog(plan_id: str) -> None:
    plan = next((p for p in get_all_plans() if p["id"] == plan_id), None)
    if not plan:
        st.info("Plan nie istnieje.")
        return
    names = sorted({a["name"] for a in get_athletes_summary()}
                   | set(list_profile_names())
                   | {p.get("athlete", "") for p in get_all_plans()}
                   - {""})
    target = st.selectbox("Zawodnik docelowy", options=names,
                          key=f"trcp_ath_{plan_id}")
    start = st.date_input("Start planu u zawodnika",
                          value=pd.Timestamp.now().date(),
                          key=f"trcp_start_{plan_id}")
    st.caption("Kopiuje całą rozpiskę, bez wyników i linku "
               "udostępniania.")
    if st.button("Kopiuj", type="primary", use_container_width=True,
                 key=f"trcp_go_{plan_id}"):
        newp = copy_plan_to_athlete(plan, target, start)
        st.toast(f"Skopiowano „{newp['name']}” → {target}", icon="✅")
        st.rerun()


def _pp_reset(plan_id: str, sid: str) -> None:
    """Otwarcie treningu z kafelka: stan edytora budowany od nowa z planu
    (draft po zamknieciu X bez zapisu jest odrzucany, jak w kazdym edytorze)."""
    # pp_ = wartosc widgetu komponentu — trwa po zamknieciu dialogu i bez
    # popa wracalaby jako "nowy" seq (draft wskrzeszony po reopen)
    for pre in ("ppw_", "ppui_", "pp_pdfc_", "ppseq_", "pp_"):
        st.session_state.pop(f"{pre}{plan_id}_{sid}", None)


def _tr_workout_body(plan_id: str, sid: str) -> None:
    """Struktura treningu wg Filipa: Prep → Plyo & Power → Main (superserie
    1a/1b… prefill z przerwami między grupami). Dawka jako JEDNA kolumna
    "Sets x reps" (+ RPE/Intent, Notatka, Rest), rozpisywana PER TYDZIEŃ:
    przełącznik Week 1..N NAD sekcjami, tydzień bez wpisu dziedziczy
    z poprzedniego (auto-powielanie), zmiana tygodnia zapisuje bieżący."""
    plan = next((p for p in get_all_plans()
                 if p["id"] == plan_id), None)
    if not plan:
        st.info("Plan nie istnieje.")
        return
    sessions = ensure_sessions(plan)
    idx = next((i for i, s in enumerate(sessions) if s.get("id") == sid), None)
    if idx is None:
        st.info("Trening nie istnieje.")
        return
    w = sessions[idx]
    key = f"{plan_id}_{sid}"
    weeks_n = max(int(plan.get("weeks", 4)), 1)

    # ── Panel z handoffu Claude Design (views/plan_panel/) — jedyny
    #    widok treningu (Filip 2026-09-01: „użyj kodu jak jest, podłącz
    #    tylko zapis, Bazę i datę") ────────────────────────────────────
    from views.plan_panel import plan_panel
    from vald import exlib as _exl_pp

    _ppk = f"ppw_{key}"

    # pusta sekcja dostaje gotowe wiersze do wypelnienia — Filip 2026-09-02:
    # „jak tworze nowy plan daj bazowo 4 / 4 / 8, jako puste, zebym nie
    # musial klikac". Sekcja, w ktorej cos juz jest, zostaje nietknieta.
    _PP_PUSTE = (("Prep", 4), ("Plyo & Power", 4), ("Main", 8))

    def _pp_cache() -> dict:
        """Stan edytora w session_state, budowany z zapisanej sesji planu
        (po zapisie: sessions[idx] = swieza wersja z filmami z Bazy)."""
        if _ppk not in st.session_state:
            _yt_pp = _exl_pp.url_map()
            ses = sessions[idx] if idx < len(sessions) else w
            _exs = [
                {**dict(it),
                 "tempo": it.get("tempo", ""),
                 "film": _yt_pp.get(
                     (it.get("exercise") or "").strip().lower(), "")}
                for it in (ses.get("items") or [])]
            # sekcja jest UZUPELNIANA do minimum, nie tylko wypelniana gdy
            # pusta — inaczej po pierwszym zapisie i po powrocie z Bazy
            # wiersze znikaja i trzeba znowu klikac „Dodaj cwiczenie".
            # Trening, ktory ma juz jakies cwiczenia, NIE dostaje sekcji,
            # ktorej w nim nie ma (plany Slepska nie maja Plyo & Power).
            _nowy = not _exs or bool(ses.get("pp_seed"))
            for _sec, _ile in _PP_PUSTE:
                _ma = sum(1 for e in _exs if e.get("section") == _sec)
                if _ma == 0 and not _nowy:
                    continue
                _brak = _ile - _ma
                if _brak > 0:
                    _exs += [{"section": _sec, "slot": "", "exercise": "",
                              "note": "", "tempo": "", "film": "",
                              "weeks": {}} for _ in range(_brak)]
            st.session_state[_ppk] = {
                "id": sid,
                "name": ses.get("title", "") or f"Trening {_tr_letter(idx)}",
                "date": ses.get("plan_date", ""),   # data rozpiski ≠ done_date (wykonanie)
                "weeks": int(plan.get("weeks") or weeks_n),
                "exercises": _exs,
            }
        return st.session_state[_ppk]
    _wk = _pp_cache()

    def _pp_items() -> list:
        from vald.training import normalize_slots
        items = [{k: v for k, v in e.items() if k != "film"}
                 for e in _wk.get("exercises", [])
                 if (e.get("exercise") or "").strip()]
        normalize_slots(items)
        return items

    def _pp_bez_nazwy() -> int:
        """Wiersze z dawka/uwaga/tempem, ale bez nazwy cwiczenia — przy
        zapisie przepadaja, wiec ostrzegam zamiast po cichu je gubic."""
        n = 0
        for e in _wk.get("exercises", []):
            if (e.get("exercise") or "").strip():
                continue
            if (e.get("note") or "").strip() or (e.get("tempo") or "").strip() \
                    or any((v or {}).get(f) for v in (e.get("weeks") or {}).values()
                           for f in ("sets_n", "reps", "intent")):
                n += 1
        return n

    _EXEC_F = ("load", "sets_done", "session_note", "sets")

    def _pp_shift(d: dict, ops: list) -> dict:
        """Ta sama mapa przesuniec tygodni (insert/remove z edytora) dla
        slownikow {"1": ..., "2": ...} — items[].weeks i done_weeks."""
        for op in ops:
            at = int(op.get("at") or 0)
            out = {}
            for k, v in (d or {}).items():
                try:
                    i = int(k)
                except (TypeError, ValueError):
                    out[k] = v
                    continue
                if op.get("op") == "insert":
                    out[str(i + 1 if i > at else i)] = v
                elif op.get("op") == "remove":
                    if i == at:
                        continue
                    out[str(i - 1 if i > at else i)] = v
                else:
                    out[k] = v
            d = out
        return d

    def _pp_save(ops=None) -> None:
        _exl_pp.sync_from_plan(
            [(e.get("exercise", ""), e.get("film", ""))
             for e in _wk.get("exercises", [])])
        ops = list(ops or [])
        old_items = list(sessions[idx].get("items") or []) \
            if idx < len(sessions) else []
        items = _pp_items()
        # wykonanie zawodnika (load/sets_done/session_note) nie moze zginac
        # przy edycji rozpiski — dopasowanie po nazwie, potem po pozycji
        used: set = set()
        for pos, it in enumerate(items):
            j_old = next((j for j, o in enumerate(old_items)
                          if j not in used and o.get("exercise", "")
                          == it.get("exercise", "")), None)
            if j_old is None and pos < len(old_items) and pos not in used:
                j_old = pos
            if j_old is None:
                continue
            used.add(j_old)
            ow = _pp_shift(dict(old_items[j_old].get("weeks") or {}), ops)
            for wk_k, pw in ow.items():
                if not isinstance(pw, dict):
                    continue
                nw = it.setdefault("weeks", {}).get(wk_k)
                if nw is None:
                    if any(pw.get(f) for f in _EXEC_F):
                        it["weeks"][wk_k] = {
                            **{f: pw[f] for f in _EXEC_F if pw.get(f)},
                            "sets_n": "", "reps": "", "intent": "", "rest": ""}
                    continue
                for f in _EXEC_F:
                    if not nw.get(f) and pw.get(f):
                        nw[f] = pw[f]
        dropped = [o for j, o in enumerate(old_items) if j not in used
                   and any(any((pw or {}).get(f) for f in _EXEC_F)
                           for pw in (o.get("weeks") or {}).values()
                           if isinstance(pw, dict))]
        nowa = dict(w)
        nowa.update({"id": sid,
                     "title": (_wk.get("name") or "").strip(),
                     "items": items,
                     "plan_date": _wk.get("date", "")})
        if dropped:      # usuniete cwiczenia z wynikami zawodnika → archiwum
            nowa["removed_items"] = list(nowa.get("removed_items") or []) + dropped
        if ops and nowa.get("done_weeks"):
            nowa["done_weeks"] = _pp_shift(nowa["done_weeks"], ops)
        sessions[idx] = nowa
        if ops:          # tygodnie planu sa wspolne — przesun tez inne treningi
            for j, s_ in enumerate(sessions):
                if j == idx:
                    continue
                for it in (s_.get("items") or []):
                    if isinstance(it.get("weeks"), dict):
                        it["weeks"] = _pp_shift(it["weeks"], ops)
                if s_.get("done_weeks"):
                    s_["done_weeks"] = _pp_shift(s_["done_weeks"], ops)
        plan["weeks"] = int(_wk.get("weeks") or plan.get("weeks", 4))
        upsert_plan(plan)
        try:                    # ślad do „Ostatnio edytowane" na Start
            from .shell import touch_recent as _tr_touch
            _tr_touch(plan["id"])
        except Exception:
            pass
        st.session_state.pop(_ppk, None)   # swiezy load (filmy z Bazy)

    def _pp_library(sec_key: str, ops=None) -> None:
        _pp_save(ops)
        # plan właśnie zapisany — bez tego powrót z Bazy pytał „Zapisać
        # zmiany?", choć wszystko już siedziało w bazie (audyt 2026-09-05)
        st.session_state["pp_dirty"] = False
        st.session_state["exlib_pick"] = {"plan": plan_id, "sid": sid}
        st.session_state["exlib_pick_sec"] = sec_key
        st.session_state["app_mode"] = "exlib"
        st.rerun()

    def _pp_pod() -> dict:
        """Plan z BIEZACYM stanem edytora (bez zapisu) — PDF i Excel
        pokazuja to, co widac w siatce, nie ostatnio zapisana wersje."""
        pod = dict(plan)
        ses = [dict(x) for x in sessions]
        ses[idx] = {**dict(w), "id": sid,
                    "title": (_wk.get("name") or "").strip(),
                    "items": _pp_items(), "plan_date": _wk.get("date", "")}
        pod["sessions"] = ses
        pod["weeks"] = int(_wk.get("weeks") or plan.get("weeks", 4))
        return pod

    def _pp_pdf_bytes() -> bytes:
        from .plan_pdf_adapter import build_plan_pdf_green
        return build_plan_pdf_green(_pp_pod(), _exl_pp.url_map())

    def _pp_pdf_cached() -> tuple:
        """(pdf_bytes, png_data_uri) po odcisku tresci — generator nie
        biega przy kazdym rerunie."""
        import base64 as _b64
        import json as _js
        import fitz as _fz
        odcisk = _js.dumps(_wk, sort_keys=True, default=str)
        ck = f"pp_pdfc_{key}"
        c = st.session_state.get(ck)
        if c and c[0] == odcisk:
            return c[1], c[2]
        pdf = _pp_pdf_bytes()
        dok = _fz.open(stream=pdf, filetype="pdf")
        nr = min(max(0, idx), dok.page_count - 1)
        png = dok[nr].get_pixmap(dpi=150).tobytes("png")
        uri = "data:image/png;base64," + _b64.b64encode(png).decode()
        st.session_state[ck] = (odcisk, pdf, uri)
        return pdf, uri

    # modal na 96vw — panel ma min. 1080 px (CLAUDE_CODE.md pkt 5)
    st.markdown(
        "<style>div[data-testid='stDialog'] div[role='dialog']"
        "{max-width:96vw!important;width:96vw!important;"
        "background:#fbfbf9}</style>",
        unsafe_allow_html=True)

    _ath_pp = plan.get("athlete", "")
    if any(t and t in (plan.get("name", "").lower())
           for t in _ath_pp.lower().split()):
        _ath_pp = ""     # nazwa planu juz zawiera zawodnika — bez dubla

    _uik, _seqk = f"ppui_{key}", f"ppseq_{key}"
    ui = st.session_state.get(_uik) or {}

    # ── wartosc komponentu z poprzedniego SEND konsumujemy PRZED renderem:
    #    iframe ma dostac aktualny stan (inaczej jest o krok wstecz — od 2.
    #    edycji cofa wpisana wartosc i zabiera fokus). Wartosc trzyma sie
    #    miedzy rerunami, wiec akcje tylko dla nowego seq (inaczej petla).
    _val = st.session_state.get(f"pp_{key}")
    _ack = _val.get("seq") if isinstance(_val, dict) else None
    if isinstance(_val, dict) and "dirty" in _val:
        st.session_state["pp_dirty"] = bool(_val.get("dirty"))

    # „Zapisz i wróć" z paska nad edytorem — zapis żyje w tym domknięciu,
    # więc pasek tylko podnosi flagę, a wykonanie jest tutaj
    if st.session_state.pop("pp_zapisz_i_wyjdz", False):
        _pp_save()
        st.session_state["pp_dirty"] = False
        st.session_state.pop("tr_open_workout", None)
        st.toast("Zapisano i wrócono do planu", icon="✅")
        st.rerun()
    if isinstance(_val, dict) and _val.get("seq") != st.session_state.get(_seqk):
        st.session_state[_seqk] = _val.get("seq")
        ui = _val.get("ui") or {}
        st.session_state[_uik] = ui
        if isinstance(_val.get("workout"), dict):
            _wk.clear()
            _wk.update(_val["workout"])
        _act = _val.get("action")
        if _act == "save":
            _bez = _pp_bez_nazwy()
            _pp_save(_val.get("weekOps"))
            _wk = _pp_cache()      # swiezy stan (filmy z Bazy) w tym samym przebiegu
            st.session_state["pp_dirty"] = False
            st.toast("Plan zapisany", icon="✅")
            if _bez:
                st.warning(
                    f"Pominięto {_bez} wiersz(e) z rozpiską, ale bez nazwy "
                    f"ćwiczenia — wpisz nazwę i zapisz ponownie.")
        elif _act == "usun_trening":
            # dodanie treningu było dotąd nieodwracalne (Filip 2026-09-05)
            _p = next((x for x in get_all_plans() if x["id"] == plan_id), None)
            if _p is not None:
                _ses = ensure_sessions(_p)
                _p["sessions"] = [x for x in _ses if x.get("id") != sid]
                upsert_plan(_p)
                st.session_state.pop("tr_open_workout", None)
                st.session_state["pp_dirty"] = False
                st.toast("Trening usunięty", icon="🗑")
                st.rerun()

        elif _act == "library":
            _pp_library(_val.get("section") or "Main",
                        _val.get("weekOps"))              # st.rerun() → Baza

    w_pdf = ui.get("view") == "podglad" and ui.get("pvMode") == "pdf"
    pdf_uri, pdf_bytes, pdf_err = "", b"", ""
    if w_pdf:
        try:
            pdf_bytes, pdf_uri = _pp_pdf_cached()
        except Exception as e:                 # brak PyMuPDF / blad generatora
            pdf_err = f"{type(e).__name__}: {e}"

    # baza ćwiczeń do podpowiedzi w polu nazwy (Filip 2026-09-02: wpisuję
    # „hip" i mam listę dopasowań, klik pobiera nazwę razem z filmem)
    _sug = [{"name": e.get("name", ""), "url": e.get("url", "") or "",
             "cat": e.get("cat", "") or ""}
            for e in _exl_pp.exercises() if (e.get("name") or "").strip()]
    plan_panel({"athlete": _ath_pp, "name": plan.get("name", "")},
               _wk, key=f"pp_{key}", pdf_png=pdf_uri, pdf_err=pdf_err,
               ack=_ack, ui=ui, exlist=_sug)

    if w_pdf and pdf_bytes:
        from .plan_xlsx import build_plan_xlsx
        _d1, _d2, _ = st.columns([1.1, 1.25, 3.4])
        _d1.download_button(
            "Pobierz PDF", data=pdf_bytes,
            file_name=f"{plan.get('name', 'plan')}.pdf",
            mime="application/pdf", type="primary",
            key=f"ppdf_{key}", use_container_width=True)
        _d2.download_button(
            "Pobierz Excel", data=build_plan_xlsx(_pp_pod(), _exl_pp.url_map()),
            file_name=f"{plan.get('name', 'plan')}.xlsx",
            mime=("application/vnd.openxmlformats-officedocument"
                  ".spreadsheetml.sheet"),
            key=f"ppxl_{key}", use_container_width=True)
    return


def _yt_thumb(url: str) -> "str | None":
    """Miniatura YouTube z linku (jak w Relay): img.youtube.com/vi/<id>."""
    m = re.search(r"(?:v=|youtu\.be/|shorts/|embed/)([A-Za-z0-9_-]{11})",
                  url or "")
    return (f"https://img.youtube.com/vi/{m.group(1)}/default.jpg"
            if m else None)


# ── Widok zawodnika „z kółkami" — 1:1 z podglądu Mobile app w edytorze
#    (views/plan_panel/index.html: .pv-slot/.pv-row, kolory SECTIONS).
#    Filip 2026-09-18: „niech to będzie ten widok na telefon, który był z kółkami".
_PV_SEKCJE = {
    "Prep": ("oklch(0.58 0.13 155)", "oklch(0.97 0.02 155)", "Movement Prep", True),
    "Plyo & Power": ("oklch(0.58 0.13 60)", "oklch(0.97 0.02 60)", "Plyo & Power", False),
    "Main": ("oklch(0.58 0.13 255)", "oklch(0.97 0.02 255)", "Main Strength", False),
}
_PV_INNE = ("oklch(0.55 0.02 90)", "oklch(0.97 0.005 90)")


def _pv_sekcja_kolory(section: str) -> tuple[str, str]:
    """(accent, tint) kółka i nagłówka — koloruje SEKCJA, nie grupa superserii."""
    return _PV_SEKCJE.get(section, (_PV_INNE[0], _PV_INNE[1]))[:2]


def _pv_slot_label(it: dict, idx: int, section: str) -> str:
    """Treść kółka: slot z rozpiski; Prep zawsze P1, P2…; reszta → numer.

    W Prep slot NIE oznacza superserii — służy tylko do odstępu między
    blokami w PDF (zielony szablon grupuje wiersze po numerze). Gdyby kółko
    brało go wprost, cała rozgrzewka miałaby „1" i wyglądała jak jedna
    superseria (Filip 2026-09-20, plan Michała 2.0)."""
    if _PV_SEKCJE.get(section, (0, 0, 0, False))[3]:
        return f"P{idx + 1}"
    slot = str(it.get("slot", "") or "").strip()
    return slot or str(idx + 1)


def _pv_dawka(it: dict, wk: int) -> tuple[str, str]:
    """(dawka z ×, intent) dla tygodnia — przez week_params, więc dziedziczy."""
    p = week_params(it, wk)
    s_n, r = p.get("sets_n", ""), p.get("reps", "")
    dawka = f"{s_n} × {r}" if s_n and r else (r or s_n or "—")
    return dawka, (p.get("intent") or "")


def _pv_karta_html(it: dict, wk: int, idx: int, section: str, yt: dict) -> str:
    from html import escape as _esc
    acc, tint = _pv_sekcja_kolory(section)
    nazwa = it.get("exercise", "")
    url = yt.get(nazwa.strip().lower())
    dawka, intent = _pv_dawka(it, wk)
    nazwa_html = (f"<a class='pvname' href='{_esc(url)}' target='_blank'>{_esc(nazwa)}</a>"
                  if url else f"<span class='pvname'>{_esc(nazwa)}</span>")
    chip = f" <span class='pvintent'>{_esc(intent)}</span>" if intent else ""
    det = []
    if url:
        det.append(f"<a href='{_esc(url)}' target='_blank'>▶ Zobacz film</a>")
    if it.get("tempo"):
        det.append(f"<span>Tempo: {_esc(it['tempo'])}</span>")
    if it.get("note"):
        det.append(f"<span>{_esc(it['note'])}</span>")
    det_html = (f"<div class='pvdet'>{''.join(det)}</div>"
                if (it.get("tempo") or it.get("note")) else "")
    return (f"<div class='pvrow'><span class='pvslot' style='background:{tint};"
            f"color:{acc};'>{_esc(_pv_slot_label(it, idx, section))}</span>"
            f"<div class='pvcol'>{nazwa_html}<span class='pvdose'>{_esc(dawka)}{chip}</span>"
            f"{det_html}</div></div>")


def _pv_sekcja_html(section: str) -> str:
    acc, _ = _pv_sekcja_kolory(section)
    tytul = _PV_SEKCJE.get(section, (0, 0, section))[2]
    return (f"<div class='pvsec' style='color:{acc};'><i style='background:{acc};'></i>"
            f"{tytul}</div>")


def _pv_status(sess: dict, wk: int) -> str:
    if str(wk) in (sess.get("done_weeks") or {}):
        return "Zapisany"
    if str(wk) in (sess.get("started_weeks") or {}):
        return "W toku"
    return "Zaplanowany"


_PV_CSS = """<style>
        /* publiczna apka zawodnika nie ma motywu z app.py — bez tych
           zmiennych var(--aph-…) jest nieważne i style po cichu znikają
           (np. czarna pigułka aktywnego tygodnia) */
        .stApp { --aph-ink:#1c1b18; --aph-bone:#ffffff; --aph-dim:#6f6b61;
            --aph-mute:#8a867c; --aph-card:#ffffff; --aph-line:#e6e3db;
            --aph-shadow:0 1px 2px rgba(28,27,24,.06);
            --aph-display:-apple-system,"Segoe UI",system-ui,sans-serif;
            --aph-text:-apple-system,"Segoe UI",system-ui,sans-serif; }
        .stApp .pvhead { display:flex; justify-content:space-between;
            align-items:flex-start; gap:12px; padding: 6px 0 2px; }
        .stApp .pvhead .pvtitle { font-family: var(--aph-display); font-size:21px;
            font-weight:800; color:#1c1b18; line-height:1.15; }
        .stApp .pvhead .pvsub { font-family: var(--aph-text); font-size:13px;
            color:#8a867c; margin-top:2px; }
        .stApp .pvbadge { font-family: var(--aph-text); font-size:12px;
            font-weight:600; color:#6f6b61; background:#f2f1ec;
            border-radius:999px; padding:5px 13px; white-space:nowrap; }
        .stApp .pvsec { display:flex; align-items:center; gap:8px;
            font-family: var(--aph-text); font-size:12px; font-weight:800;
            letter-spacing:.1em; text-transform:uppercase;
            margin:20px 0 14px; }
        .stApp .pvsec i { display:inline-block; width:4px; height:15px;
            border-radius:2px; }
        .stApp .pvrow { display:flex; gap:12px; align-items:flex-start;
            border-bottom:1px solid #f5f4f0; padding-bottom:14px;
            margin-bottom:16px; overflow-wrap:anywhere; }
        .stApp .pvslot { width:32px; height:32px; border-radius:999px;
            font-family: var(--aph-text); font-size:12px; font-weight:700;
            display:inline-flex; align-items:center; justify-content:center;
            flex-shrink:0; }
        .stApp .pvcol { display:flex; flex-direction:column; gap:4px;
            min-width:0; }
        .stApp .pvname { font-family: var(--aph-text); font-size:16px;
            font-weight:700; color:#3d63c9; text-decoration:none; }
        .stApp .pvdose { font-family: var(--aph-text); font-size:15px;
            font-weight:700; color:#1c1b18; font-variant-numeric:tabular-nums; }
        .stApp .pvintent { font-family: var(--aph-text); font-size:12px;
            font-weight:600; color:oklch(.5 .13 60); background:oklch(.96 .04 75);
            border-radius:6px; padding:2px 8px; vertical-align:1px; }
        .stApp .pvdet { display:flex; flex-direction:column; gap:6px;
            background:#f8f7f4; border-radius:10px; padding:10px 12px;
            margin-top:4px; font-family: var(--aph-text); font-size:13px;
            color:#6f6b61; }
        .stApp .pvdet a { color:#3d63c9; font-weight:700; text-decoration:none; }
        /* pigułki tygodni i treningów jak .wkpill z designu */
        .stApp [class*="st-key-gymwk_"] button,
        .stApp [class*="st-key-gymt_"] button {
            border:1px solid #e6e3db; background:#fff; color:#6f6b61;
            font-size:12px !important; font-weight:600 !important;
            border-radius:999px !important; min-height:0 !important;
            padding:6px 13px !important; }
        </style>"""

_GYM_CSS = """<style>
        [data-testid="stSidebar"], [data-testid="collapsedControl"],
        #MainMenu, header[data-testid="stHeader"] { display: none !important; }
        .block-container { padding: 0.8rem 0.9rem 4rem !important;
            max-width: 640px !important; }
        .stApp .gymhead { font-family: var(--aph-display); font-size: 20px;
            letter-spacing: -0.02em; color: var(--aph-ink); }
        .stApp .gymsub { font-family: var(--aph-text); font-size: 12px;
            color: var(--aph-mute); margin-bottom: 4px; }
        .stApp .gymsec { font-family: var(--aph-text); font-size: 11px;
            font-weight: 700; letter-spacing: 0.08em;
            text-transform: uppercase; margin: 14px 0 4px; }
        .stApp .gymro { background: var(--aph-card);
            border: 1px solid var(--aph-line); border-radius: 10px;
            padding: 8px 12px; margin-bottom: 6px; }
        .stApp .gymro b { font-size: 14px; color: var(--aph-ink); }
        .stApp .gymro .d { font-family: var(--aph-text); font-size: 12.5px;
            color: var(--aph-dim); }
        .stApp .gymro .n { font-family: var(--aph-text); font-size: 12px;
            color: var(--aph-mute); margin-top: 2px; }
        .stApp .gymex, .stApp .gymro { overflow-wrap: anywhere; }
        .stApp .gymex { background: var(--aph-card);
            border: 1px solid var(--aph-line); border-radius: 12px;
            padding: 10px 12px 2px; margin-bottom: 8px;
            box-shadow: var(--aph-shadow); }
        .stApp .gymex .t { font-size: 15px; font-weight: 700;
            color: var(--aph-ink); }
        .stApp .gymslot { display: inline-flex; align-items: center;
            justify-content: center; width: 30px; height: 30px;
            border-radius: 50%; font-family: ui-monospace, Menlo, monospace;
            font-size: 10.5px; font-weight: 700;
            margin-right: 8px; vertical-align: -9px; }
        .stApp .gymex .d { font-family: var(--aph-text); font-size: 12.5px;
            color: var(--aph-dim); margin: 2px 0 6px; }
        .stApp .gym-sn { font-family: var(--aph-text); font-size: 12px;
            color: var(--aph-mute); padding-top: 10px; }
        div[class*="st-key-gym_"] input { font-size: 16px !important; }
        /* mobile: kolumny (S | powt. | kg, przyciski tygodni/treningów)
           w JEDNYM wierszu — bez streamlitowego stackowania na wąskich
           ekranach; proporcje szerokości z st.columns() ZACHOWANE
           (tylko brak zawijania + brak nadmiaru) */
        .stApp [data-testid="stHorizontalBlock"] {
            flex-wrap: nowrap !important; flex-direction: row !important;
            gap: 6px !important; }
        .stApp [data-testid="stHorizontalBlock"] [data-testid="stColumn"] {
            min-width: 0 !important; }
        .stApp [data-testid="stColumn"] button {
            padding-left: 6px !important; padding-right: 6px !important;
            white-space: nowrap !important; }
        </style>"""


def _render_plan_workout_body(plan: dict, sub: str,
                              head: str = "", prowadzony: bool = False) -> None:
    """Wspólne ciało widoku wykonania treningu (tryb SIŁOWNIA
    trenera i widok ZAWODNIKA z sekretnego linku): tygodnie,
    treningi A/B/C, karty ćwiczeń z wpisem kg/powt per seria,
    notatka, zapis → sets_done + Load + done_date."""
    from html import escape as _html_esc
    weeks_n = max(int(plan.get("weeks", 4)), 1)
    sessions = ensure_sessions(plan)
    if prowadzony:
        st.markdown(_PV_CSS, unsafe_allow_html=True)
    else:
        st.markdown(
            f"<div class='gymhead'>"
            f"{_html_esc(head or plan.get('name', ''))}</div>"
            f"<div class='gymsub'>{_html_esc(sub)}</div>",
            unsafe_allow_html=True,
        )
    if not sessions:
        st.info("Plan nie ma jeszcze treningów.")
        return

    # tydzień planu — przełączany, zmienia dawki WSZYSTKICH treningów;
    # start = tydzień wynikający z dzisiejszej daty. Poza zakresem planu
    # NIE wolno po cichu wpaść na Week 1 (zaległy trening w poniedziałek
    # po końcu bloku nadpisałby wyniki z tygodnia 1) — po końcu domyślnie
    # OSTATNI tydzień + wyraźny baner.
    _today = pd.Timestamp.now().date()
    _end = plan_end(plan)
    _started = True
    try:
        from datetime import date as _date
        _started = _date.fromisoformat(plan.get("start_date", "")) <= _today
    except Exception:
        pass
    wkk = f"gym_wk_{plan['id']}"
    if st.session_state.get(wkk) not in range(1, weeks_n + 1):
        cw = current_week_of(plan)
        if cw is None:
            cw = weeks_n if (_end and _today > _end) else 1
        st.session_state[wkk] = cw
    wk = int(st.session_state[wkk])
    if _end and _today > _end:
        st.warning(f"Ten plan zakończył się {_end:%d.%m.%Y}. Wpisy trafią "
                   f"do Week {wk} tego bloku — jeśli masz nowy plan, "
                   f"użyj nowego linku.")
    elif not _started:
        st.info(f"Plan startuje {plan.get('start_date', '')[8:10]}."
                f"{plan.get('start_date', '')[5:7]} — poniżej podgląd.")
    st.markdown(
        f"<style>.stApp .st-key-gymwk_{plan['id']}_{wk} button{{"
        f"background:var(--aph-ink)!important;"
        f"border-color:var(--aph-ink)!important;}}"
        f".stApp .st-key-gymwk_{plan['id']}_{wk} button, "
        f".stApp .st-key-gymwk_{plan['id']}_{wk} button *{{"
        f"color:var(--aph-bone)!important;}}</style>",
        unsafe_allow_html=True,
    )
    for row_start in range(0, weeks_n, 4):
        row_weeks = list(range(row_start + 1, min(row_start + 4, weeks_n) + 1))
        wk_cols = st.columns(len(row_weeks))
        for t, col in zip(row_weeks, wk_cols):
            if col.button(f"Week {t}", key=f"gymwk_{plan['id']}_{t}",
                          use_container_width=True) and t != wk:
                st.session_state[wkk] = t
                st.rerun()

    # ── wybór treningu: duże przyciski A/B/C ────────────────────────────
    sk = f"gym_sess_{plan['id']}"
    if st.session_state.get(sk) not in {s["id"] for s in sessions}:
        st.session_state[sk] = sessions[0]["id"]
    sel = st.session_state[sk]
    st.markdown(
        f"<style>.stApp .st-key-gymt_{sel} button{{"
        f"background:var(--aph-ink)!important;"
        f"border-color:var(--aph-ink)!important;}}"
        f".stApp .st-key-gymt_{sel} button, "
        f".stApp .st-key-gymt_{sel} button p, "
        f".stApp .st-key-gymt_{sel} button *{{"
        f"color:var(--aph-bone)!important;}}</style>",
        unsafe_allow_html=True,
    )
    # wiersze po max 5 — przy 6+ treningach każdy musi być dostępny
    for _t0 in range(0, len(sessions), 5):
        _chunk = sessions[_t0:_t0 + 5]
        tcols = st.columns(len(_chunk))
        for s, col in zip(_chunk, tcols):
            i = sessions.index(s)
            _t = (s.get("title") or "").strip()
            lbl = _tr_letter(i) + (f" · {_t}" if _t and _t.upper() != _tr_letter(i) else "")
            if col.button(lbl[:16], key=f"gymt_{s['id']}",
                          use_container_width=True) and s["id"] != sel:
                st.session_state[sk] = s["id"]
                st.rerun()
    w = next(s for s in sessions if s["id"] == st.session_state[sk])
    items = w.get("items") or []
    prep = [it for it in items if it.get("section") == "Prep"]
    plyo = [it for it in items if it.get("section") == "Plyo & Power"]
    mains = [it for it in items
             if it.get("section") not in ("Prep", "Plyo & Power")]
    yt = __import__("vald.exlib", fromlist=["url_map"]).url_map()

    def _dose_txt(it):
        from html import escape as _esc
        p = week_params(it, wk)
        s_n, r = p.get("sets_n", ""), p.get("reps", "")
        sets = (f"{_esc(s_n)}&times;{_esc(r)}" if s_n and r
                else _esc(r or s_n))
        out = (f"<span style='font-weight:700;color:var(--aph-ink);"
               f"font-variant-numeric:tabular-nums;'>{sets}</span>")
        if p.get("intent"):
            out += " " + _trv_chip(_esc(p["intent"]), "#fbefe1", "#b26a17")
        if p.get("rest"):
            out += " " + _trv_chip(f"Rest {_esc(p['rest'])}",
                                   "#eef0f2", "#5b616b")
        return out

    def _name_html(it):
        from html import escape as _esc
        n = it.get("exercise", "")
        u = yt.get(n.strip().lower())
        return (f"<a href='{_esc(u)}' target='_blank'>{_esc(n)}</a>"
                if u else _esc(n))

    def _gym_sec(label, color):
        st.markdown(
            f"<div class='gymsec' style='color:{color};display:flex;"
            f"align-items:center;gap:8px;'><span style='width:4px;"
            f"height:13px;border-radius:2px;background:{color};"
            f"display:inline-block;'></span>{label}</div>",
            unsafe_allow_html=True,
        )

    if prowadzony:
        # nagłówek jak w podglądzie Mobile app: trening, zawodnik · plan, status
        _lit = _tr_letter(sessions.index(w))
        _tyt = (w.get("title") or "").strip()
        _tyt = f"Trening {_lit}" if (not _tyt or _tyt.upper() == _lit) else _tyt
        st.markdown(
            f"<div class='pvhead'><div><div class='pvtitle'>{_html_esc(_tyt)}</div>"
            f"<div class='pvsub'>{_html_esc(plan.get('athlete', ''))} · "
            f"{_html_esc(plan.get('name', ''))}</div></div>"
            f"<span class='pvbadge'>{_pv_status(w, wk)}</span></div>",
            unsafe_allow_html=True)
        if _render_trening_prowadzony(plan, w, wk, yt):
            return
        for sec, lst in (("Prep", prep), ("Plyo & Power", plyo), ("Main", mains)):
            if not lst:
                continue
            st.markdown(_pv_sekcja_html(sec) + "".join(
                _pv_karta_html(it, wk, i, sec, yt) for i, it in enumerate(lst)),
                unsafe_allow_html=True)
        return

    # ── Prep / Plyo: tylko odczyt ───────────────────────────────────────
    for label, color, lst in (("Movement Prep", "#16a34a", prep),
                              ("Plyo & Power", "#dd8412", plyo)):
        if not lst:
            continue
        _gym_sec(label, color)
        for it in lst:
            note_html = (f"<div class='n'>{_html_esc(it['note'])}</div>"
                        if it.get("note") else "")
            st.markdown(
                f"<div class='gymro'><b>{_name_html(it)}</b> "
                f"<span class='d'>{_dose_txt(it)}</span>{note_html}</div>",
                unsafe_allow_html=True,
            )

    # ── Main Strength: karty z wpisem KG / POWT. per seria.
    #    CAŁOŚĆ w st.form → wpisywanie NIE robi rerunu przy każdym polu
    #    (przez tunel każdy rerun = widoczny lag); jeden rerun przy 💾.
    #    Zamiast „＋ Set" zawsze jest 1 zapasowy pusty wiersz — po zapisie
    #    z wypełnionym zapasem pojawia się kolejny. ─────────────────────
    def _n_rows(it) -> int:
        p_ = week_params(it, wk)
        done_ = p_.get("sets_done") or []
        try:
            n_plan_ = int(re.match(r"\d+",
                                   str(p_.get("sets_n", ""))).group())
        except Exception:
            n_plan_ = 3
        return max(len(done_), n_plan_, 1) + 1

    if mains:
        _gym_sec("Main Strength", "#2563eb")
    # enter_to_submit=False: „gotowe"/Enter na klawiaturze telefonu NIE
    # może zapisywać treningu w połowie wpisywania
    _form = st.form(key=f"gym_form_{w['id']}_{wk}", border=False,
                    enter_to_submit=False) if mains else None
    submitted = False
    if _form is not None:
        with _form:
            for mi, it in enumerate(mains):
                p = week_params(it, wk)
                done = p.get("sets_done") or []
                n_sets = _n_rows(it)
                _slot = str(it.get("slot", "") or "")
                _mg = re.match(r"\d+", _slot)
                _bg, _fg = _TRV_GROUP_ACCENT.get(
                    _mg.group() if _mg else "1", _TRV_GROUP_ACCENT["1"])
                slot_html = (
                    f"<span class='gymslot' style='background:{_bg};"
                    f"color:{_fg};'>{_slot}</span>" if _slot else "")
                note = (f" {_html_esc(it['note'])}"
                        if it.get("note") else "")
                # Load rozpisany przez trenera (jawny wpis TEGO tygodnia,
                # bez dziedziczenia) — zawodnik musi go widzieć na karcie
                _ld = (item_weeks(it).get(str(wk)) or {}).get("load", "")
                ld_chip = (" " + _trv_chip(f"Load {_html_esc(_ld)}",
                                           "#eef0f2", "#3a404b")
                           if _ld else "")
                st.markdown(
                    f"<div class='gymex'>{slot_html}<span class='t'>"
                    f"{_name_html(it)}</span><div class='d'>"
                    f"{_dose_txt(it)}{ld_chip}{note}</div></div>",
                    unsafe_allow_html=True,
                )
                for si in range(n_sets):
                    prev = done[si] if si < len(done) else {}
                    cs, cr, ckg = st.columns([0.8, 1.6, 1.6])
                    cs.markdown(
                        f"<div class='gym-sn'>Set {si + 1}</div>",
                        unsafe_allow_html=True)
                    cr.text_input("Powt.", value=prev.get("reps", ""),
                                  placeholder=p.get("reps", "") or "powt.",
                                  key=f"gym_r_{w['id']}_{mi}_{si}_{wk}",
                                  label_visibility="collapsed")
                    ckg.text_input("Kg", value=prev.get("kg", ""),
                                   placeholder="kg",
                                   key=f"gym_k_{w['id']}_{mi}_{si}_{wk}",
                                   label_visibility="collapsed")
                st.text_input("Notatka", value=p.get("session_note", ""),
                              placeholder="np. za łatwe, +2,5 kg",
                              key=f"gym_note_{w['id']}_{mi}_{wk}",
                              label_visibility="collapsed")
            submitted = st.form_submit_button(
                "💾 Zapisz trening", type="primary",
                use_container_width=True)
        # trwały sygnał zapisu (toast łatwo przegapić przy klawiaturze)
        _dwx = w.get("done_weeks") or {}
        if str(wk) in _dwx:
            try:
                _dd = f"{pd.Timestamp(_dwx[str(wk)]):%d.%m}"
            except Exception:
                _dd = _dwx[str(wk)]
            st.caption(f"✅ Trening zapisany w tym tygodniu ({_dd})")

    if mains and submitted:
        any_entry = False
        for mi, it in enumerate(mains):
            # tyle wierszy, ile wyrenderował formularz (te same dane,
            # ten sam przebieg skryptu → ta sama liczba)
            n_sets = _n_rows(it)
            sets_done = []
            for si in range(n_sets):
                r = st.session_state.get(
                    f"gym_r_{w['id']}_{mi}_{si}_{wk}", "").strip()
                kg = st.session_state.get(
                    f"gym_k_{w['id']}_{mi}_{si}_{wk}", "").strip()
                sets_done.append({"reps": r, "kg": kg})
            while sets_done and not (sets_done[-1]["reps"]
                                     or sets_done[-1]["kg"]):
                sets_done.pop()
            params = dict(week_params(it, wk))
            params["sets_done"] = sets_done
            params["session_note"] = st.session_state.get(
                f"gym_note_{w['id']}_{mi}_{wk}", "").strip()
            kgs = [s["kg"] for s in sets_done]
            if any(kgs):
                params["load"] = " / ".join(k or "—" for k in kgs)
            elif not sets_done:
                # wszystkie pola wyczyszczone → bez widmowego Load
                # z poprzedniego zapisu tego tygodnia
                params.pop("load", None)
            if sets_done or params["session_note"]:
                any_entry = True
            it["weeks"] = dict(item_weeks(it))
            it["weeks"][str(wk)] = params
        # "wykonany" tylko przy realnym wpisie; done_date = OSTATNIE
        # wykonanie (kontrakt modelu), done_weeks = które tygodnie zrobione
        if any_entry:
            _dnow = str(pd.Timestamp.now().date())
            w["done_date"] = _dnow
            w.setdefault("done_weeks", {})[str(wk)] = _dnow
        upsert_plan(plan)
        st.toast("Zapisano trening", icon="✅")
        st.rerun()


# ── Tryb prowadzonego treningu (telefon zawodnika) ───────────────────────────
# Filip 2026-09-18: „startujesz trening, przeklikujesz ćwiczenia, po serii
# wpisujesz ciężar i powtórzenia; serię można też zamknąć bez wpisu i oznaczyć,
# że jej nie zrobiłeś — a trener to widzi".
_TRW_CSS = """<style>
        .stApp .trwprog { font-family: var(--aph-text); font-size: 12px;
            color: var(--aph-dim); display:flex; justify-content:space-between;
            align-items:center; margin: 2px 0 6px; }
        .stApp .trwbar { height:6px; border-radius:3px; background:#e8ebef;
            overflow:hidden; margin-bottom:14px; }
        .stApp .trwbar i { display:block; height:100%; background:var(--aph-ink); }
        .stApp .trwname { font-family: var(--aph-display); font-size:21px;
            font-weight:800; color:var(--aph-ink); line-height:1.15;
            margin:2px 0 4px; }
        .stApp .trwname a { color:inherit; text-decoration:none;
            border-bottom:2px solid #c9d2dd; }
        .stApp .trwdose { font-family: var(--aph-text); font-size:14px;
            color:var(--aph-dim); margin-bottom:2px; }
        .stApp .trwnote { font-family: var(--aph-text); font-size:12.5px;
            color:#8a5a12; background:#fdf3e3; border-radius:8px;
            padding:6px 9px; margin:8px 0 2px; }
        .stApp .trwset { font-family: var(--aph-text); font-size:13px;
            font-weight:700; color:var(--aph-ink); padding-top:9px; }
        .stApp .trwstan { font-family: var(--aph-text); font-size:12px;
            padding-top:10px; }
        .stApp .trwsum { font-family: var(--aph-text); font-size:13.5px;
            color:var(--aph-ink); background:var(--aph-card);
            border:1px solid #e6e9ee; border-radius:10px; padding:10px 12px;
            margin:6px 0; }
        </style>"""


def _trw_dawka(it, wk):
    """Rozpiska trenera na ten tydzień, jednym wierszem."""
    from html import escape as _esc
    p = week_params(it, wk)
    s_n, r = p.get("sets_n", ""), p.get("reps", "")
    txt = (f"{s_n} × {r}" if s_n and r else (r or s_n or ""))
    for pole in ("intent", "rest"):
        if p.get(pole):
            txt += f" · {p[pole]}"
    if it.get("tempo"):
        txt += f" · {it['tempo']}"
    return _esc(txt)


def _trw_ile_serii(it, wk) -> int:
    """Ile serii odklikać: tyle, ile rozpisał trener (minimum 1)."""
    p = week_params(it, wk)
    try:
        return max(int(re.match(r"\d+", str(p.get("sets_n", ""))).group()), 1)
    except Exception:
        return max(len(p.get("sets_done") or []), 1)


def _trw_karta(plan, sess, wk, it, item_i, yt):
    """Jedno ćwiczenie: nazwa, film, rozpiska i serie do odklikania."""
    from html import escape as _esc
    from .training import SERIA_OK, SERIA_SKIP, stan_serii, ustaw_serie
    nazwa = it.get("exercise", "")
    url = yt.get(nazwa.strip().lower())
    sekcja = it.get("section") or "Main"
    acc, tint = _pv_sekcja_kolory(sekcja)
    w_sekcji = [x for x in (sess.get("items") or []) if (x.get("section") or "Main") == sekcja]
    idx = next((i for i, x in enumerate(w_sekcji) if x is it), 0)
    slot = _pv_slot_label(it, idx, sekcja)
    nazwa_html = (f"<a href='{_esc(url)}' target='_blank'>{_esc(nazwa)}</a>"
                  if url else _esc(nazwa))
    st.markdown(
        f"<div class='pvrow' style='border:0;padding:0;margin:0 0 6px;align-items:center;'>"
        f"<span class='pvslot' style='background:{tint};color:{acc};'>{_esc(slot)}</span>"
        f"<div class='trwname' style='margin:0;'>{nazwa_html}</div></div>"
        f"<div class='trwdose'>{_trw_dawka(it, wk)}</div>",
        unsafe_allow_html=True)
    if it.get("note"):
        st.markdown(f"<div class='trwnote'>{_esc(it['note'])}</div>",
                    unsafe_allow_html=True)

    p = week_params(it, wk)
    done = p.get("sets_done") or []
    n = max(_trw_ile_serii(it, wk), len(done))
    glowna = it.get("section") not in ("Prep", "Plyo & Power")
    for si in range(n):
        biezaca = done[si] if si < len(done) else {}
        stan = stan_serii(biezaca)
        if glowna:
            c0, ckg, crep, cok, cno = st.columns([0.9, 1.25, 1.25, 0.8, 0.8])
        else:
            c0, cok, cno = st.columns([3.4, 0.8, 0.8])
        c0.markdown(f"<div class='trwset'>Seria {si + 1}</div>",
                    unsafe_allow_html=True)
        kg_k = f"trw_kg_{sess['id']}_{item_i}_{si}_{wk}"
        rep_k = f"trw_rp_{sess['id']}_{item_i}_{si}_{wk}"
        if glowna:
            ckg.text_input("kg", value=biezaca.get("kg", ""), placeholder="kg",
                           key=kg_k, label_visibility="collapsed")
            crep.text_input("powt", value=biezaca.get("reps", ""),
                            placeholder=p.get("reps", "") or "powt.",
                            key=rep_k, label_visibility="collapsed")
        zrobiona, pominieta = stan == SERIA_OK, stan == SERIA_SKIP
        if cok.button("✓", key=f"trw_ok_{sess['id']}_{item_i}_{si}_{wk}",
                      use_container_width=True,
                      type="primary" if zrobiona else "secondary",
                      help="seria zrobiona"):
            ustaw_serie(plan, sess["id"], item_i, wk, si,
                        "" if zrobiona else SERIA_OK,
                        reps=st.session_state.get(rep_k, "") if glowna else "",
                        kg=st.session_state.get(kg_k, "") if glowna else "")
            upsert_plan(plan)
            st.rerun()
        if cno.button("✕", key=f"trw_no_{sess['id']}_{item_i}_{si}_{wk}",
                      use_container_width=True,
                      type="primary" if pominieta else "secondary",
                      help="nie zrobiłem tej serii"):
            ustaw_serie(plan, sess["id"], item_i, wk, si,
                        "" if pominieta else SERIA_SKIP)
            upsert_plan(plan)
            st.rerun()


def _trw_podsumowanie(sess, wk):
    from .training import wykonanie_sesji
    poz = wykonanie_sesji(sess, wk)
    ok = sum(p["zrobione"] for p in poz)
    sk = sum(p["pominiete"] for p in poz)
    return poz, ok, sk


def _render_trening_prowadzony(plan, sess, wk, yt) -> bool:
    """Prowadzony trening zawodnika. Zwraca True, gdy przejął ekran
    (wtedy podgląd rozpiski się nie renderuje)."""
    from html import escape as _esc
    from .training import oznacz_koniec, oznacz_start
    st.markdown(_TRW_CSS + _PV_CSS, unsafe_allow_html=True)
    # kolejność sekcji jak w podglądzie i PDF — bez tego ćwiczenie dopisane
    # do prepu po rozpisaniu Main wypadało na końcu treningu (audyt 2026-09-20).
    # Trzymam (indeks_w_sesji, item): ustaw_serie adresuje po indeksie z sesji.
    _sur = list(enumerate(sess.get("items") or []))
    _kolejnosc = {"Prep": 0, "Plyo & Power": 1}
    items = sorted(_sur, key=lambda p_: _kolejnosc.get(p_[1].get("section"), 2))
    if not items:
        return False
    klucz = f"trw_on_{plan['id']}_{sess['id']}_{wk}"
    idx_k = f"trw_i_{plan['id']}_{sess['id']}_{wk}"

    if not st.session_state.get(klucz):
        poz, ok, sk = _trw_podsumowanie(sess, wk)
        if ok or sk:
            st.markdown(
                f"<div class='trwsum'>W tym tygodniu masz odklikane "
                f"<b>{ok}</b> serii, pominięte <b>{sk}</b>.</div>",
                unsafe_allow_html=True)
        if st.button("▶  Zacznij trening", type="primary",
                     use_container_width=True,
                     key=f"trw_go_{plan['id']}_{sess['id']}_{wk}"):
            oznacz_start(plan, sess["id"], wk)
            upsert_plan(plan)
            st.session_state[klucz] = True
            st.session_state[idx_k] = 0
            st.rerun()
        return False

    i = max(0, min(int(st.session_state.get(idx_k, 0)), len(items)))
    if i >= len(items):                      # ekran końcowy
        poz, ok, sk = _trw_podsumowanie(sess, wk)
        st.markdown(
            f"<div class='trwname'>Koniec treningu</div>"
            f"<div class='trwdose'>{ok} serii zrobionych"
            f"{f', {sk} pominiętych' if sk else ''}</div>",
            unsafe_allow_html=True)
        for p_ in poz:
            opis = ", ".join(
                (f"{s['kg']}×{s['reps']}" if s["stan"] == "ok" and (s["kg"] or s["reps"])
                 else "✓" if s["stan"] == "ok" else "✕")
                for s in p_["serie"])
            st.markdown(f"<div class='trwsum'><b>{_esc(p_['exercise'])}</b>"
                        f"<br>{_esc(opis)}</div>", unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        if c1.button("← Popraw wpisy", use_container_width=True,
                     key=f"trw_back_{sess['id']}_{wk}"):
            st.session_state[idx_k] = len(items) - 1
            st.rerun()
        if c2.button("✔  Zakończ trening", type="primary",
                     use_container_width=True,
                     key=f"trw_end_{sess['id']}_{wk}"):
            oznacz_koniec(plan, sess["id"], wk)
            upsert_plan(plan)
            st.session_state[klucz] = False
            st.success("Trening zapisany — trener już to widzi.")
            st.rerun()
        return True

    _idx, it = items[i]
    sekcja = it.get("section") or "Main"
    st.markdown(
        f"<div class='trwprog'><span>{_esc(sekcja)}</span>"
        f"<span>{i + 1} / {len(items)}</span></div>"
        f"<div class='trwbar'><i style='width:{(i) * 100 // len(items)}%'></i></div>",
        unsafe_allow_html=True)
    _trw_karta(plan, sess, wk, it, _idx, yt)

    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
    c1, c2 = st.columns([1, 1.6])
    if c1.button("←", use_container_width=True, disabled=i == 0,
                 key=f"trw_prev_{sess['id']}_{i}_{wk}"):
        st.session_state[idx_k] = i - 1
        st.rerun()
    ostatnie = i == len(items) - 1
    if c2.button("Gotowe, dalej →" if not ostatnie else "Podsumowanie →",
                 type="primary", use_container_width=True,
                 key=f"trw_next_{sess['id']}_{i}_{wk}"):
        st.session_state[idx_k] = i + 1
        st.rerun()
    if st.button("Przerwij trening", use_container_width=True,
                 key=f"trw_stop_{sess['id']}_{wk}"):
        st.session_state[klucz] = False
        st.rerun()
    return True


def _render_athlete_mode(token: str) -> None:
    """Widok PODOPIECZNEGO z sekretnego linku (?plan=<token>): wyłącznie
    JEDEN plan — bez selektorów, sidebara i dostępu do reszty aplikacji.
    Zawodnik widzi rozpiskę (z filmami), wpisuje kg/powtórzenia per seria
    i zapisuje — trener widzi Load i ✓ wykonania w edytorze."""
    st.markdown(_GYM_CSS, unsafe_allow_html=True)
    plan = find_plan_by_token(token)
    if not plan:
        st.markdown(
            "<div style='max-width:420px;margin:80px auto;text-align:center;"
            "font-family:var(--aph-text);color:var(--aph-dim);'>"
            "<div style='font-size:40px;'>🔒</div>"
            "<div style='font-size:17px;font-weight:700;color:var(--aph-ink);"
            "margin:8px 0 4px;'>Ten link jest nieaktywny</div>"
            "Poproś trenera o nowy link do planu.</div>",
            unsafe_allow_html=True,
        )
        return
    # Stary link po końcu bloku: jeśli ten sam zawodnik ma nowszy plan,
    # przekieruj na niego — zawodnik zawsze ląduje w aktualnym bloku,
    # nawet gdy trener nie zdążył wysłać nowego linku.
    _today = pd.Timestamp.now().date()
    _end = plan_end(plan)
    if _end and _today > _end:
        cand = [p for p in get_plans(plan.get("athlete", ""))
                if p.get("id") != plan.get("id")]
        succ = next((p for p in cand if is_current(p)), None)
        if succ is None:
            later = sorted(
                (p for p in cand
                 if (p.get("start_date") or "") > (plan.get("start_date")
                                                   or "")),
                key=lambda p: p.get("start_date", ""))
            succ = later[0] if later else None
        if succ is not None:
            plan = succ
            st.info(f"Poprzedni blok się zakończył — poniżej Twój "
                    f"aktualny plan: {plan.get('name', '')}.")
    first = (plan.get("athlete", "") or "").split(" ")[0]
    _render_plan_workout_body(
        plan, f"{plan.get('name', '')} · Twój plan",
        head=f"Cześć, {first}!" if first else "Twój plan",
        prowadzony=True,
    )


def _render_gym_mode() -> None:
    """Tryb SIŁOWNIA (telefon, ?mode=gym): plan zawodnika na dziś w prostym
    widoku — Prep/Plyo do odczytu, Main z wpisywaniem KG i POWTÓRZEŃ per
    seria. Zapis → weeks[wk]["sets_done"] + złożone Load (widoczne też na
    desktopie). Zawodnicy brani z samych planów (działa bez danych VALD)."""
    st.markdown(_GYM_CSS, unsafe_allow_html=True)

    plans = get_all_plans()
    athletes = sorted({p.get("athlete", "") for p in plans if p.get("athlete")})
    if not athletes:
        st.info("Brak planów treningowych.")
        return
    c1, c2 = st.columns([2.4, 1])
    with c1:
        ath = st.selectbox("Zawodnik", athletes, key="gym_athlete",
                           label_visibility="collapsed")
    aplans = sorted([p for p in plans if p.get("athlete") == ath],
                    key=lambda p: p.get("created", ""), reverse=True)
    cur = [p for p in aplans if is_current(p)]
    pool = cur or aplans
    with c2:
        if len(pool) > 1:
            pid = st.selectbox("Plan", [p["id"] for p in pool],
                               key=f"gym_plan_{ath}",
                               format_func=lambda i: next(
                                   p["name"] for p in pool if p["id"] == i),
                               label_visibility="collapsed")
            plan = next(p for p in pool if p["id"] == pid)
        else:
            plan = pool[0]

    _render_plan_workout_body(plan, ath)


