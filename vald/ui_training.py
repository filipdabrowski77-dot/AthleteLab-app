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


_DYKT_NOWE = "➕ nowe ćwiczenie"


def _odmiana(n: int, poj: str, kilka: str, wiele: str) -> str:
    """1 trening, 2-4 treningi, 5+ (i 12-14) treningów."""
    n = abs(int(n))
    if n == 1:
        return poj
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return kilka
    return wiele


# bez zamykania Esc i kliknięciem obok: wklejony tekst trafia do Pythona
# dopiero po wyjściu z pola, więc Esc kasował go bez śladu (audyt 2026-09-28)
@st.dialog("Plan z dyktanda", width="large", dismissible=False)
def _tr_dyktando_dialog() -> None:
    """Dyktando (Wispr Flow) wprost w apce — bez terminala i bez asystenta.
    Parser `vald/dyktando.py` jest czystym Pythonem: liczebniki słowne,
    pięć notacji dawek i dopasowanie nazw do Bazy działają też w chmurze.
    Nazwy, których nie ma pewnych, potwierdza się z listy — inaczej trzeba
    by znać składnię `=> Nazwa`, a tego nie da się zgadnąć."""
    from . import dyktando as dk
    from . import exlib as _ex
    ss = st.session_state
    # Claude w apce (Filip 2026-09-29): mówię do telefonu, Claude oddaje blok
    # planu, który wchodzi niżej jak zwykłe dyktando. Tylko z kluczem API.
    from . import claude_plan as _cp
    if _cp.dostepny():
        rozm = ss.setdefault("dykt_claude", [])
        for m in rozm[-4:]:
            st.markdown(("**Ty:** " if m["role"] == "user" else "**Claude:** ")
                        + (m["content"] if m["role"] == "user" or not _cp.wyciagnij_blok(m["content"])
                           else "plan poniżej ↓"))
        wpis = st.text_area("Do Claude", height=90, key="dykt_claude_wpis",
                            placeholder="Powiedz, dla kogo i co ma być w planie",
                            label_visibility="collapsed")
        _k1, _k2 = st.columns([3, 1])
        if _k1.button("Ułóż z Claude", type="primary", use_container_width=True,
                      key="dykt_claude_go") and (wpis or "").strip():
            from .shell import _all_names
            rozm.append({"role": "user", "content": wpis.strip()})
            try:
                with st.spinner("Claude układa…"):
                    odp = _cp.odpowiedz(rozm, [e["name"] for e in _ex.exercises()],
                                        _all_names())
            except Exception as e:
                rozm.pop()
                st.error(f"Claude nie odpowiedział: {e}")
                return
            rozm.append({"role": "assistant", "content": odp})
            blok = _cp.wyciagnij_blok(odp)
            if blok:
                ss["dykt_tekst"] = blok
            ss.pop("dykt_claude_wpis", None)
            st.rerun()
        if rozm and _k2.button("Od nowa", use_container_width=True, key="dykt_claude_reset"):
            ss["dykt_claude"] = []
            st.rerun()
        st.divider()
    tekst = st.text_area("Dyktando", height=240, key="dykt_tekst",
                         placeholder=_DYKT_WZOR, label_visibility="collapsed")
    with st.expander("Wzór"):
        st.code(_DYKT_WZOR, language=None)
        st.caption("Kolejne `|` z dawką to kolejne tygodnie (W1, W2, …). "
                   "Sekcje: prep, plyo, main, akcesoria.")
    # Streamlit oddaje treść pola dopiero po ⌘+Enter albo kliknięciu poza nie —
    # bez tego przycisku wklejenie tekstu nie robiło z pozoru NIC.
    _c1, _c2 = st.columns([3, 1])
    _c1.button("Sprawdź dopasowania", use_container_width=True,
               key="dykt_sprawdz")
    if _c2.button("Zamknij", use_container_width=True, key="dykt_zamknij"):
        st.rerun()
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
        ss.pop("dykt_claude", None)
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
    from . import store as _st
    # VALD = zawodnicy Filipa: w cudzej przestrzeni ich nazwisk nie podpowiadam
    vald = set() if _st.workspace() else {a["name"] for a in get_athletes_summary()}
    names = sorted(vald
                   | set(list_profile_names())
                   | {p.get("athlete", "") for p in get_all_plans()}
                   - {""})
    target = st.selectbox("Zawodnik docelowy", options=names,
                          key=f"trcp_ath_{plan_id}")
    start = st.date_input("Start planu u zawodnika",
                          value=pd.Timestamp.now().date(),
                          key=f"trcp_start_{plan_id}")
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
            # _zr = [indeks, nazwa] pozycji planu, z ktorej powstal wiersz —
            # panel przenosi klucz bez zmian, _pp_save wiaze po nim wykonanie
            _exs = [
                {**dict(it),
                 "tempo": it.get("tempo", ""),
                 "film": _yt_pp.get(
                     (it.get("exercise") or "").strip().lower(), ""),
                 "_zr": [j, it.get("exercise", "")]}
                for j, it in enumerate(ses.get("items") or [])]
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
        items = [{k: v for k, v in e.items() if k not in ("film", "_zr")}
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
        slownikow {"1": ..., "2": ...} — items[].weeks, done_weeks, started_weeks."""
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
        # ten sam filtr co w _pp_items — kolejnosc zgodna z items
        zrodla = [e.get("_zr") for e in _wk.get("exercises", [])
                  if (e.get("exercise") or "").strip()]
        # wykonanie zawodnika (load/sets_done/session_note) nie moze zginac
        # przy edycji rozpiski — wiersz z planu wiaze sie z pozycja, z ktorej
        # powstal (_zr; zmiana nazwy go nie odcina), nowy wiersz tylko po
        # nazwie. Bez dopasowania po pozycji: usuniecie wiersza + zmiana nazwy
        # innego dawaly przemianowanemu cwiczeniu cudze wykonanie (recenzja F6)
        used: set = set()
        for pos in sorted(range(len(items)), key=lambda p: not zrodla[p]):
            it = items[pos]
            j_old, szukana = None, it.get("exercise", "")
            if zrodla[pos]:
                j0, szukana = zrodla[pos]
                if isinstance(j0, int) and 0 <= j0 < len(old_items) \
                        and j0 not in used \
                        and old_items[j0].get("exercise", "") == szukana:
                    j_old = j0
            if j_old is None:     # nowy wiersz / plan zmieniony w tle: po nazwie
                j_old = next((j for j, o in enumerate(old_items)
                              if j not in used
                              and o.get("exercise", "") == szukana), None)
            if j_old is None:
                continue
            used.add(j_old)
            ow = _pp_shift(dict(old_items[j_old].get("weeks") or {}), ops)
            # wykonanie ZAWSZE ze swiezego planu, nie ze stanu edytora z chwili
            # otwarcia — zawodnik mogl w tym czasie odklikac kolejne serie
            # i zapis cofal 3 serie do 1 (audyt 2026-09-24). Panel nie edytuje
            # wykonania (setDose w index.html przenosi je bez zmian).
            for wk_k, nw in (it.get("weeks") or {}).items():
                if not isinstance(nw, dict):
                    continue
                pw = ow.get(wk_k) if isinstance(ow.get(wk_k), dict) else {}
                for f in _EXEC_F:
                    if pw.get(f):
                        nw[f] = pw[f]
                    else:
                        nw.pop(f, None)
            for wk_k, pw in ow.items():
                if not isinstance(pw, dict):
                    continue
                if it.setdefault("weeks", {}).get(wk_k) is None:
                    if any(pw.get(f) for f in _EXEC_F):
                        it["weeks"][wk_k] = {
                            **{f: pw[f] for f in _EXEC_F if pw.get(f)},
                            "sets_n": "", "reps": "", "intent": "", "rest": ""}
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
        # started_weeks razem z done_weeks — bez tego po usunieciu tygodnia
        # „w toku" zostawalo na starym numerze (tydzien, ktorego nikt nie zaczal)
        for _k in ("done_weeks", "started_weeks"):
            if ops and nowa.get(_k):
                nowa[_k] = _pp_shift(nowa[_k], ops)
        sessions[idx] = nowa
        if ops:          # tygodnie planu sa wspolne — przesun tez inne treningi
            for j, s_ in enumerate(sessions):
                if j == idx:
                    continue
                for it in (s_.get("items") or []):
                    if isinstance(it.get("weeks"), dict):
                        it["weeks"] = _pp_shift(it["weeks"], ops)
                for _k in ("done_weeks", "started_weeks"):
                    if s_.get(_k):
                        s_[_k] = _pp_shift(s_[_k], ops)
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
        st.toast("Zapisano", icon="✅")
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
                st.warning(f"Pominięto {_bez} wiersz(e) bez nazwy ćwiczenia — wpisz nazwę i zapisz ponownie.")
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
               ack=_ack, ui=ui, exlist=_sug,
               miejsce={"plan": plan_id, "sid": sid})   # wpis w historii (Wstecz)

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
            border-radius:999px !important; min-height:44px !important;
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
                              head: str = "", prowadzony: bool = False,
                              trener: bool = False) -> None:
    """Wspólne ciało widoku wykonania treningu (tryb SIŁOWNIA
    trenera i widok ZAWODNIKA z sekretnego linku): tygodnie,
    treningi A/B/C, karty ćwiczeń z wpisem kg/powt per seria,
    notatka, zapis → sets_done + Load + done_date.
    trener=True (z prowadzony=True): ten sam nagłówek i pigułki, zamiast
    kart zawodnika komponent trybu trenera (_render_trener_panel)."""
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
        st.info("Brak treningów.")
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
        # tryb trenera: tydzień z adresu — odświeżenie wraca w to samo miejsce
        _qw = str(st.query_params.get("w") or "") if trener else ""
        if _qw.isdigit() and 1 <= int(_qw) <= weeks_n:
            cw = int(_qw)
        st.session_state[wkk] = cw
    wk = int(st.session_state[wkk])
    if _end and _today > _end:
        st.warning(f"Plan zakończył się {_end:%d.%m.%Y}. Wpisy trafią "
                   f"do Week {wk} — "
                   + ("nowy plan wybierzesz wyżej." if trener else
                      "nowy plan = nowy link od trenera."))
    elif not _started:
        st.info(f"Plan startuje {plan.get('start_date', '')[8:10]}."
                f"{plan.get('start_date', '')[5:7]}.")
    st.markdown(
        f"<style>.stApp .st-key-gymwk_{plan['id']}_{wk} button{{"
        f"background:var(--aph-ink)!important;"
        f"border-color:var(--aph-ink)!important;}}"
        f".stApp .st-key-gymwk_{plan['id']}_{wk} button, "
        f".stApp .st-key-gymwk_{plan['id']}_{wk} button *{{"
        f"color:var(--aph-bone)!important;}}</style>",
        unsafe_allow_html=True,
    )
    # ── wybór treningu: duże przyciski A/B/C ────────────────────────────
    sk = f"gym_sess_{plan['id']}"
    if st.session_state.get(sk) not in {s["id"] for s in sessions}:
        _dom = sessions[0]["id"]
        if trener:
            # trening z adresu, a bez niego pierwszy niezakończony w tym
            # tygodniu — trener otwiera telefon i od razu ma dzisiejszy
            _qt = str(st.query_params.get("t") or "")
            _nz = next((s["id"] for s in sessions
                        if str(wk) not in (s.get("done_weeks") or {})), _dom)
            _dom = _qt if _qt in {s["id"] for s in sessions} else _nz
        st.session_state[sk] = _dom
    sel = st.session_state[sk]
    if trener:
        # tylko przy zmianie — każdy zapis adresu to wpis w historii przeglądarki
        for _k, _v in (("w", str(wk)), ("t", sel)):
            if st.query_params.get(_k) != _v:
                st.query_params[_k] = _v
    # tryb trenera: na przycisku tygodnia data wykonania WYBRANEGO treningu
    # („W2 · 12.09"), na przyciskach treningów data z bieżącego tygodnia
    _sel_s = next((s_ for s_ in sessions if s_["id"] == sel), None) if trener else None
    for row_start in range(0, weeks_n, 4):
        row_weeks = list(range(row_start + 1, min(row_start + 4, weeks_n) + 1))
        wk_cols = st.columns(len(row_weeks))
        for t, col in zip(row_weeks, wk_cols):
            _d = _trk_data(_sel_s, t) if trener else ""
            lbl = f"W{t} · {_d}" if _d else (f"W{t}" if trener else f"Week {t}")
            if col.button(lbl, key=f"gymwk_{plan['id']}_{t}",
                          use_container_width=True) and t != wk:
                st.session_state[wkk] = t
                st.rerun()

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
            _d = _trk_data(s, wk) if trener else ""
            lbl = (lbl[:16] + f" · {_d}") if _d else lbl[:16]
            if col.button(lbl, key=f"gymt_{s['id']}",
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
            f"<span class='pvbadge'>{_pv_status(w, wk)}"
            f"{(' ' + _trk_data(w, wk)) if trener and _trk_data(w, wk) else ''}</span></div>",
            unsafe_allow_html=True)
        if trener:
            _render_trener_panel(plan, w, wk)
            return
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
        /* audyt 2026-09-29: pola kg/powt. zlewały się z tłem i były niższe od ✓/✕ */
        .stApp [class*="st-key-trw_kg_"] [data-baseweb="input"],
        .stApp [class*="st-key-trw_rp_"] [data-baseweb="input"] {
            border:1px solid #e3e0d8 !important; border-radius:10px !important;
            background:#fdfdfb !important; min-height:44px; }
        .stApp [class*="st-key-trw_kg_"] input, .stApp [class*="st-key-trw_rp_"] input {
            font-size:16px !important; text-align:center; }
        .stApp [class*="st-key-trw_"] button { min-height:44px !important; }
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
                f"<div class='trwsum'>Zrobione: <b>{ok}</b> · "
                f"pominięte: <b>{sk}</b></div>",
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
            # audyt 2026-09-29: „×15" bez kg było nieczytelne
            opis = ", ".join(
                (f"{s['kg']} kg × {s['reps']}" if s["stan"] == "ok" and s["kg"] and s["reps"]
                 else f"{s['reps']} powt." if s["stan"] == "ok" and s["reps"]
                 else f"{s['kg']} kg" if s["stan"] == "ok" and s["kg"]
                 else "✓" if s["stan"] == "ok" else "✕")
                for s in p_["serie"]) or "—"
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
            st.success("Trening zapisany.")
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


# ── Tryb trenera na telefonie (?mode=gym) ────────────────────────────────────
# Filip 2026-09-27: „Prowadzę kogoś, mam jego treningi na telefonie i na
# treningu jednym kliknięciem wpisuję, ile zrobił powtórzeń, na jakim ciężarze
# … z opcją dodania RPE i notatki" + „mogą być te kółka, tylko nie musisz mieć
# linków. To ma być prosty widok dla trenera". Kółka i kolory sekcji jak
# u zawodnika (_pv_*), bez filmów. Serie wpisuje komponent views/trener_panel:
# klawiatury numerycznej (inputmode) i pól 44 px nie da się ustawić przez API
# Streamlita 1.50, a każde ✓ widżetem to przeładowanie całej strony.
_TRK_KOLEJNOSC = ("Prep", "Prep 2", "Plyo & Power", "Main")
_TRK_ZWINIETE = ("Prep", "Prep 2", "Plyo & Power")
_TRK_MAX_SERII = 20
_TRK_PAMIEC = 1000          # ile id zastosowanych operacji pamięta sesja
_TRK_STANY = ("ok", "skip", "")
# element listy na serie: „6", „6+6" (na stronę), „6-8"
_TRK_ELEMENT_LISTY = re.compile(r"^\d+(?:\s*[+\-–]\s*\d+)?$")
# „2 x 5", „1x 6-10", „1 x ISO…" → (liczba serii, powtórzenia albo nic)
_TRK_N_X_R = re.compile(r"(\d+)\s*[x×]\s*(\d+(?:\s*-\s*\d+)?)?", re.I)

_TRK_CSS = """<style>
        /* podopieczni jako kafelki, trzy obok siebie (Filip 2026-09-29):
           siatka na kontenerze, bo st.columns na telefonie idą pod siebie */
        .stApp .st-key-trk_kafle, .stApp .st-key-trk_kafle_reszta {
            display: grid !important; grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 8px !important; }
        .stApp .st-key-trk_kafle > div, .stApp .st-key-trk_kafle_reszta > div {
            width: auto !important; min-width: 0; }
        .stApp [class*="st-key-trk_z_"] button { min-height: 76px !important;
            height: 100%; padding: 8px 6px !important; white-space: normal !important;
            border-radius: 14px !important; }
        .stApp [class*="st-key-trk_z_"] button p { text-align: center;
            font-size: 14px; line-height: 1.25; overflow-wrap: break-word; hyphens: auto; }
        .stApp .st-key-trk_pop { display: none !important; }
        </style>"""


def _trk_powt_czlonu(c) -> str:
    """Powtórzenia z „2 x 5" do jednego stuknięcia ✓ — tylko sama liczba;
    zakres, „ISO", sekundy („1 x 30 sek") → puste pole."""
    r = c.group(2) or ""
    if re.match(r"(sek|sec|s\b|min|m\b|/)", c.string[c.end():].lstrip().lower()):
        return ""
    return r if r.isdigit() else ""


def _trk_serie_plan(it: dict, wk: int) -> tuple:
    """(liczba wierszy, powtórzenia per seria do jednego stuknięcia ✓,
    rozpiska powtórzeń jako podpowiedź).

    Powtórzenia wstawiamy tylko, gdy rozpiska mówi jednoznacznie: sama liczba
    („7") albo lista na serie („6, 6, 6"). Zakres „8-12", sekundy, „/str",
    „6+6" → puste pole z podpowiedzią — dolna granica zakresu byłaby
    wymyśloną liczbą udającą wynik. Liczba wierszy: sets_n (pierwsza liczba,
    jak u zawodnika), bez niej długość listy, minimum 1. Top set w jednej
    komórce („1 x 4 @ rpe 8 + 2 x 6-7", „rpe 9 + 2x 7" w intent) dokłada
    kolejne serie."""
    p = week_params(it, wk)
    reps = str(p.get("reps") or "").strip()
    czesci = [c.strip() for c in reps.split(",")] if "," in reps else []
    lista = len(czesci) >= 2 and all(_TRK_ELEMENT_LISTY.match(c) for c in czesci)
    # top set w jednej komórce: „1 x 4 @ rpe 8 + 2 x 6-7" → serie po kolei;
    # gdy któryś człon nie ma „N x R" (np. „4 opuszczania"), zostaje jak dotąd
    if "+" in reps and not lista:
        czlony = [_TRK_N_X_R.search(c) for c in reps.split("+")]
        if all(czlony):
            na_serie = []
            for c in czlony:
                na_serie += [_trk_powt_czlonu(c)] * int(c.group(1))
            na_serie = (na_serie or [""])[:_TRK_MAX_SERII]
            return len(na_serie), na_serie, reps
    m = re.match(r"\d+", str(p.get("sets_n") or "").strip())
    n = int(m.group()) if m else (len(czesci) if lista else 1)
    n = min(max(n, 1), _TRK_MAX_SERII)
    if re.fullmatch(r"\d+", reps):
        na_serie = [reps] * n
    elif lista:
        na_serie = [czesci[i] if i < len(czesci) and czesci[i].isdigit() else ""
                    for i in range(n)]
    else:
        na_serie = [""] * n
    # dalsze serie dopisane za RPE: „rpe 9 + 2x 7 rpe 7/8" → +2 wiersze po 7
    for c in re.finditer(r"\+\s*" + _TRK_N_X_R.pattern, str(p.get("intent") or ""), re.I):
        na_serie += [_trk_powt_czlonu(c)] * int(c.group(1))
    na_serie = na_serie[:_TRK_MAX_SERII]
    return len(na_serie), na_serie, reps


def _trk_seria_txt(s: dict) -> str:
    """„85×6 @9" / „40 kg" / „×10" / „✓" — jedna zrobiona seria."""
    from .training import przecinek_dziesietny
    kg = przecinek_dziesietny(s.get("kg"))
    reps = str(s.get("reps") or "").strip()
    rpe = przecinek_dziesietny(s.get("rpe"))
    txt = (f"{kg}×{reps}" if kg and reps else f"{kg} kg" if kg
           else f"×{reps}" if reps else "✓")
    return txt + (f" @{rpe}" if rpe else "")


def _trk_data(sess: dict | None, wk) -> str:
    """„12.09" — kiedy ten trening był zrobiony w tygodniu wk (done_weeks)."""
    iso = ((sess or {}).get("done_weeks") or {}).get(str(wk), "")
    try:
        return f"{pd.Timestamp(iso):%d.%m}" if iso else ""
    except Exception:
        return ""


def _trk_ostatnio(plan: dict, it: dict, wk: int, plany=(), sess: dict | None = None) -> tuple:
    """(„W1: 70×7 · 80×7 · 85×6", kg pierwszej serii) — odniesienie na karcie.

    Najbliższy wcześniejszy tydzień TEGO ćwiczenia z seriami ✓, a gdy go nie
    ma (np. W1 nowego bloku) — wcześniejsze plany zawodnika (plany), po
    nazwie ćwiczenia, z dopiskiem nazwy planu. Tylko serie zrobione; bez
    nich stary Load wpisany tekstem („W1: 80 80 80", bez podpowiedzi kg).
    Bez etykiety „Ostatnio" — dokłada ją komponent."""
    from .training import (SERIA_OK, load_tekstowy, przecinek_dziesietny,
                           stan_serii)

    def _ok(tyg) -> list:
        return [s for s in ((tyg or {}).get("sets_done") or [])
                if isinstance(s, dict) and stan_serii(s) == SERIA_OK]

    def _wynik(serie: list, prefiks: str) -> tuple:
        kg = next((przecinek_dziesietny(s.get("kg")) for s in serie
                   if str(s.get("kg") or "").strip()), "")
        return f"{prefiks}: " + " · ".join(_trk_seria_txt(s) for s in serie), kg

    def _z_tygodnia(tyg, prefiks: str):
        ok = _ok(tyg)
        tekst = load_tekstowy(tyg if isinstance(tyg, dict) else {})
        if ok:                  # Load tekstowy zostaje tylko przy seriach bez kg
            txt, kg = _wynik(ok, prefiks)
            return (f"{txt} · Load {tekst}" if tekst else txt), kg
        return (f"{prefiks}: {tekst}", "") if tekst else None

    ws = item_weeks(it)
    for w_ in range(int(wk) - 1, 0, -1):
        # z datą wykonania (Filip 2026-09-29: „każdy tydzień miał datę")
        d_ = _trk_data(sess, w_)
        wynik = _z_tygodnia(ws.get(str(w_)), f"W{w_}" + (f" · {d_}" if d_ else ""))
        if wynik:
            return wynik
    nazwa = (it.get("exercise") or "").strip().lower()
    if not nazwa:
        return "", ""

    def _od(p: dict) -> str:
        return p.get("start_date") or p.get("created") or ""

    wczesniejsze = sorted((p for p in plany if p.get("id") != plan.get("id")
                           and _od(p) < _od(plan)), key=_od, reverse=True)
    for p in wczesniejsze:
        best = None
        for s_ in ensure_sessions(p):
            for x in (s_.get("items") or []):
                if (x.get("exercise") or "").strip().lower() != nazwa:
                    continue
                for k, tyg in item_weeks(x).items():
                    d_ = _trk_data(s_, k)
                    wynik = _z_tygodnia(tyg, f"{p.get('name', '')} W{k}"
                                        + (f" · {d_}" if d_ else ""))
                    if wynik and str(k).isdigit() and (best is None or int(k) > best[0]):
                        best = (int(k), wynik)
        if best:
            return best[1]
    return "", ""


def _trk_dane(plan: dict, sess: dict, wk: int, plany=()) -> dict:
    """Wszystko, czego komponent trybu trenera potrzebuje do narysowania
    treningu. Bez adresów URL — w trybie trenera nie ma filmów.
    Karta: i = indeks pozycji w sesji (adres zapisu), slot = treść kółka.
    Stary Load wpisany tekstem (bez serii) idzie do szczegółów — trener musi
    widzieć, co już jest zapisane w tym tygodniu."""
    from .training import load_tekstowy, przecinek_dziesietny, stan_serii
    items = sess.get("items") or []
    obecne: list = []
    for it in items:
        if (it.get("section") or "Main") not in obecne:
            obecne.append(it.get("section") or "Main")
    kolejnosc = sorted(obecne, key=lambda s_: (
        _TRK_KOLEJNOSC.index(s_) if s_ in _TRK_KOLEJNOSC else len(_TRK_KOLEJNOSC),
        obecne.index(s_)))
    sekcje, karty = [], []
    for sec in kolejnosc:
        acc, tint = _pv_sekcja_kolory(sec)
        sekcje.append({"key": sec, "tytul": _PV_SEKCJE.get(sec, (0, 0, sec))[2],
                       "acc": acc, "tint": tint, "zwinieta": sec in _TRK_ZWINIETE})
        w_sekcji = [(i, it) for i, it in enumerate(items)
                    if (it.get("section") or "Main") == sec]
        for idx, (i, it) in enumerate(w_sekcji):
            p = week_params(it, wk)
            dawka, intent = _pv_dawka(it, wk)
            load_txt = load_tekstowy(p)
            det = " · ".join(x for x in (
                f"Load {load_txt}" if load_txt else "",
                f"Rest {p['rest']}" if p.get("rest") else "",
                f"Tempo {it['tempo']}" if it.get("tempo") else "",
                str(it.get("note") or "").strip()) if x)
            n_plan, reps_plan, reps_hint = _trk_serie_plan(it, wk)
            ostatnio, kg_hint = _trk_ostatnio(plan, it, wk, plany, sess)
            serie = []
            for s in (p.get("sets_done") or []):
                s = s if isinstance(s, dict) else {}
                serie.append({"kg": przecinek_dziesietny(s.get("kg")),
                              "reps": str(s.get("reps") or "").strip(),
                              "rpe": przecinek_dziesietny(s.get("rpe")),
                              "stan": stan_serii(s)})
            karty.append({
                "i": i, "exercise": it.get("exercise", ""), "section": sec,
                "slot": _pv_slot_label(it, idx, sec), "dawka": dawka,
                "intent": intent, "det": det, "n_plan": n_plan,
                "reps_plan": reps_plan, "reps_hint": reps_hint,
                "ostatnio": ostatnio, "kg_hint": kg_hint, "serie": serie,
                "notatka": str(p.get("session_note") or "").strip(),
            })
    iso = (sess.get("done_weeks") or {}).get(str(wk), "")
    try:
        data = f"{pd.Timestamp(iso):%d.%m}" if iso else ""
    except Exception:
        data = str(iso)
    return {"ctx": {"plan_id": plan.get("id", ""), "sess_id": sess.get("id", ""),
                    "wk": int(wk)},
            "sekcje": sekcje, "karty": karty, "nazwy": _trk_nazwy(),
            "status": {"stan": _pv_status(sess, wk), "data": data}}


def _trk_nazwy() -> list:
    """Nazwy z Bazy ćwiczeń do podpowiedzi przy zamianie/dodaniu. Baza
    niedostępna → pusta lista, trener wpisuje ręcznie."""
    try:
        from . import exlib
        return sorted({str(e.get("name") or "").strip() for e in exlib.exercises()
                       if str(e.get("name") or "").strip()}, key=str.lower)
    except Exception:
        return []


def _trk_tekst(v, n: int) -> str:
    return str(v if v is not None else "").strip()[:n]


def _trk_op_cwiczenie(plan: dict, sess: dict, wk: int, op: dict) -> str:
    """Pełny stan jednego ćwiczenia. Zwraca "" albo powód odrzucenia."""
    from .training import SERIA_OK, oznacz_start, zapisz_cwiczenie
    serie = op.get("serie")
    if not isinstance(serie, list):
        return "Nieprawidłowa lista serii"
    if len(serie) > _TRK_MAX_SERII:
        return f"Za dużo serii (najwyżej {_TRK_MAX_SERII})"
    czyste = []
    for s in serie:
        if not isinstance(s, dict) or (s.get("stan") or "") not in _TRK_STANY:
            return "Nieprawidłowa seria"
        czyste.append({"kg": _trk_tekst(s.get("kg"), 12),
                       "reps": _trk_tekst(s.get("reps"), 12),
                       "rpe": _trk_tekst(s.get("rpe"), 5),
                       "stan": s.get("stan") or ""})
    notatka = op.get("notatka")
    notatka = None if notatka is None else _trk_tekst(notatka, 500)
    try:
        i = int(op.get("i"))
    except (TypeError, ValueError):
        i = -1                                  # zostaje szukanie po nazwie
    if not zapisz_cwiczenie(plan, sess["id"], i, wk, czyste, notatka=notatka,
                            exercise=str(op.get("exercise") or "")):
        return "Plan zmienił się — wpisz ponownie"
    if any(s["stan"] == SERIA_OK for s in czyste) \
            and str(wk) not in (sess.get("started_weeks") or {}):
        oznacz_start(plan, sess["id"], wk)      # trener na desktopie: „w toku"
    return ""


def _trk_op_koniec(plan: dict, sess: dict, wk: int, op: dict) -> str:
    from .training import oznacz_koniec
    oznacz_koniec(plan, sess["id"], wk)
    return ""


def _trk_op_usun(plan: dict, sess: dict, wk: int, op: dict) -> str:
    from .training import usun_cwiczenie
    try:
        i = int(op.get("i"))
    except (TypeError, ValueError):
        i = -1
    if not usun_cwiczenie(plan, sess["id"], i, str(op.get("exercise") or "")):
        return "Tego ćwiczenia już nie ma w planie"
    return ""


def _trk_op_dodaj(plan: dict, sess: dict, wk: int, op: dict) -> str:
    from .training import dodaj_cwiczenie
    nazwa = _trk_tekst(op.get("nowe"), 80)
    if not nazwa:
        return "Wpisz nazwę ćwiczenia"
    if not dodaj_cwiczenie(plan, sess["id"], _trk_tekst(op.get("section"), 40),
                           nazwa, _trk_tekst(op.get("dawka"), 40), wk):
        return "Nie udało się dodać"
    return ""


def _trk_op_zamien(plan: dict, sess: dict, wk: int, op: dict) -> str:
    from .training import zamien_cwiczenie
    nazwa = _trk_tekst(op.get("nowe"), 80)
    if not nazwa:
        return "Wpisz nazwę ćwiczenia"
    try:
        i = int(op.get("i"))
    except (TypeError, ValueError):
        i = -1
    if not zamien_cwiczenie(plan, sess["id"], i, str(op.get("exercise") or ""),
                            nazwa, _trk_tekst(op.get("dawka"), 40), wk):
        return "Tego ćwiczenia już nie ma w planie"
    return ""


# typ operacji z komponentu → obsługa (test kontraktu pilnuje zgodności z JS)
_TRK_EDYCJE = ("usun", "dodaj", "zamien")
_TRK_OPS_TEL = 50           # ile id zmian rozpiski pamięta trening
_TRK_OPY = {"cwiczenie": _trk_op_cwiczenie, "koniec": _trk_op_koniec,
            "usun": _trk_op_usun, "dodaj": _trk_op_dodaj, "zamien": _trk_op_zamien}


def _trk_zastosuj(ops, zastosowane: list) -> dict:
    """Operacje z komponentu → plany; czysta logika, bez Streamlita.

    Komponent wysyła WSZYSTKIE niepotwierdzone operacje (kolejka na
    telefonie), więc ta sama może przyjść kilka razy — id z `zastosowane`
    tylko potwierdzam. Plany czytam raz, na świeżo; jeden upsert_plan na
    plan. Błąd magazynu (odczyt albo zapis): nic nowego nie jest
    potwierdzone ani odrzucone, wpisy zostają w kolejce telefonu i przyjdą
    ponownie (każda operacja to pełny stan).
    Zwraca {"ack": [id], "odrzucone": [{"id","powod"}], "blad": str}."""
    ack: list = []
    odrzucone: list = []
    blad = ""
    plany = None
    zmienione: dict = {}
    for op in (ops if isinstance(ops, list) else []):
        if not isinstance(op, dict) or not op.get("id"):
            continue
        oid = str(op["id"])
        if oid in zastosowane:
            ack.append(oid)
            continue
        if plany is None and not blad:
            from . import store
            try:
                if store.enabled():
                    store.invalidate("training_plans")
                plany = {p.get("id"): p for p in get_all_plans()}
            except (RuntimeError, OSError) as e:
                blad = str(e) or "Nie udało się wczytać planów"
        if blad:
            continue        # odczyt padł: bez ack i bez odrzucenia — telefon ponowi
        obsluga = _TRK_OPY.get(op.get("typ"))
        plan = plany.get(op.get("plan_id"))
        sess = next((s for s in ensure_sessions(plan)
                     if s.get("id") == op.get("sess_id")), None) if plan else None
        try:
            wk = int(op.get("wk"))
        except (TypeError, ValueError):
            wk = 0
        if (op.get("typ") in _TRK_EDYCJE and sess is not None
                and oid in (sess.get("ops_tel") or [])):
            # zmiana rozpiski już jest w planie (ack zgubiony, telefon ponowił
            # z innej sesji) — drugi raz dodałaby/usunęła inne ćwiczenie
            ack.append(oid)
            zastosowane.append(oid)
            continue
        if obsluga is None:
            powod = "Nieznana operacja"
        elif plan is None:
            powod = "Plan nie istnieje"
        elif sess is None:
            powod = "Trening nie istnieje"
        elif not 1 <= wk <= int(plan.get("weeks") or 0):
            powod = "Zły tydzień"
        else:
            powod = obsluga(plan, sess, wk, op)
        if powod:
            odrzucone.append({"id": oid, "powod": powod})
            continue
        if op.get("typ") in _TRK_EDYCJE:
            # ślad w samym planie: przeżywa restart serwera i nową sesję
            sess["ops_tel"] = (list(sess.get("ops_tel") or []) + [oid])[-_TRK_OPS_TEL:]
        zmienione.setdefault(plan.get("id"), []).append(oid)
    for pid, ids in zmienione.items():
        try:
            upsert_plan(plany[pid])
        except (RuntimeError, OSError) as e:
            blad = str(e) or "Nie udało się zapisać"
            continue
        ack.extend(ids)
        zastosowane.extend(ids)
    del zastosowane[:-_TRK_PAMIEC]
    return {"ack": ack, "odrzucone": odrzucone, "blad": blad}


def _trk_konsumuj() -> None:
    """Wartość komponentu z poprzedniego wysłania — PRZED jego narysowaniem
    (wartość trwa między rerunami: bez seq zapis poszedłby dwa razy, a bez
    konsumpcji przed renderem komponent dostałby dane o krok wstecz)."""
    val = st.session_state.get("trk_panel")
    if not isinstance(val, dict) or not val.get("seq") \
            or val.get("seq") == st.session_state.get("trk_seq"):
        return
    st.session_state["trk_seq"] = val["seq"]
    zast = st.session_state.setdefault("trk_zastosowane", [])
    st.session_state["trk_wynik"] = _trk_zastosuj(val.get("ops") or [], zast)


def _render_trener_panel(plan: dict, sess: dict, wk: int) -> None:
    """Lista ćwiczeń z wpisywaniem serii. Klucz komponentu STAŁY — kolejka
    niezapisanych wpisów przeżywa zmianę treningu, tygodnia i zawodnika."""
    from views.trener_panel import trener_panel
    dane = _trk_dane(plan, sess, wk, get_plans(plan.get("athlete", "")))
    wynik = st.session_state.get("trk_wynik") or {}
    dane.update(ack=list(wynik.get("ack") or []),
                odrzucone=list(wynik.get("odrzucone") or []),
                blad=wynik.get("blad") or "")
    trener_panel(dane, key="trk_panel")


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
            st.info(f"Poprzedni blok zakończony. Aktualny plan: "
                    f"{plan.get('name', '')}.")
    first = (plan.get("athlete", "") or "").split(" ")[0]
    _render_plan_workout_body(
        plan, f"{plan.get('name', '')} · Twój plan",
        head=f"Cześć, {first}!" if first else "Twój plan",
        prowadzony=True,
    )


def _trk_lista_zawodnikow(plans: list) -> None:
    """Ekran startowy trybu trenera: najpierw osoby z aktualnym planem,
    reszta zwinięta. Filtr jak w panelu trenera, bez ukrytych profili."""
    import hashlib
    from html import escape as _esc
    from . import coaches, shell, store
    from .profiles import hidden_names
    # instancja gościa: ta sama nazwa co w stopce powłoki (shell.build_data),
    # inaczej drugi trener widział tu „Coach Filip"
    _ws = store.workspace()
    kto = (store.coach_name() or f"Coach {_ws.capitalize()}") if _ws else coaches.name()
    if st.button("← Start", key="trk_start"):
        st.session_state["app_mode"] = "home"
        for k in ("mode", "p", "t", "w"):
            st.query_params.pop(k, None)
        st.rerun()
    st.markdown(
        f"<div class='pvhead'><div><div class='pvtitle'>Prowadzenie treningu</div>"
        f"<div class='pvsub'>{_esc(kto)}</div>"
        f"</div></div>", unsafe_allow_html=True)
    ukryci = {n.strip().lower() for n in hidden_names()}
    po_osobie: dict = {}
    for p in shell._plany_trenera(plans):
        ath = (p.get("athlete") or "").strip()
        if ath and ath.lower() not in ukryci:
            po_osobie.setdefault(ath, []).append(p)
    teraz, reszta = [], []
    for ath in sorted(po_osobie, key=str.lower):
        ps = sorted(po_osobie[ath], reverse=True,
                    key=lambda p: p.get("start_date") or p.get("created") or "")
        cur = [p for p in ps if is_current(p)]
        (teraz if cur else reszta).append((ath, (cur or ps)[0]))
    if not teraz and not reszta:
        st.info("Brak planów.")
        return

    def _przycisk(ath: str, plan: dict) -> None:
        # kafelek = imię i nazwisko; plan (aktualny albo ostatni) otwiera się
        # po stuknięciu, starszy wybiera się już w środku (Filip 2026-09-29)
        klucz = "trk_z_" + hashlib.md5(ath.encode("utf-8")).hexdigest()[:10]
        if st.button(ath, key=klucz, use_container_width=True):
            st.query_params["p"] = plan["id"]
            for k in ("t", "w"):
                st.query_params.pop(k, None)
            st.rerun()

    with st.container(key="trk_kafle"):
        for ath, plan in teraz:
            _przycisk(ath, plan)
    if reszta:
        with st.expander(f"Pozostali ({len(reszta)})"):
            with st.container(key="trk_kafle_reszta"):
                for ath, plan in reszta:
                    _przycisk(ath, plan)


def _render_gym_mode() -> None:
    """Tryb TRENERA na telefonie (?mode=gym): zawodnik → plan → trening →
    tydzień, serie wpisuje komponent views/trener_panel (kółka i sekcje jak
    u zawodnika, bez filmów). Wybór siedzi w adresie: &p=<id planu>
    &t=<id treningu>&w=<tydzień> — odświeżenie wraca w to samo miejsce,
    nazwisk w adresie nie ma. Stoi za bramą hasła (app.py → sprawdz_haslo);
    obejście tokenem ma tylko link zawodnika (?plan=)."""
    # osobno: sklejone bloki dają jeden <style> z tekstem „</style><style>"
    # w środku i pierwsza reguła każdego kolejnego bloku przepada
    for _css in (_GYM_CSS, _PV_CSS, _TRK_CSS):
        st.markdown(_css, unsafe_allow_html=True)
    _trk_wstecz()
    _trk_konsumuj()
    try:
        _trk_widok()
    except (RuntimeError, OSError) as e:
        _trk_bez_magazynu(e)


def _trk_wstecz() -> None:
    """Wstecz/Dalej przeglądarki w trybie trenera. Wybór siedzi w adresie
    (&p, &t, &w), ale Wstecz zmieniał tylko adres, a ekran stał (audyt
    2026-09-28). Po popstate skrypt klika ukryty przycisk: przebieg bierze
    tydzień i trening z adresu, a adres bez ?mode=gym wraca na Start."""
    import streamlit.components.v1 as components
    with st.container(key="trk_pop"):
        if st.button("wstecz", key="trk_popstate"):
            if st.query_params.get("mode") != "gym":
                st.session_state["app_mode"] = "home"
            for k in [k for k in st.session_state
                      if str(k).startswith(("gym_wk_", "gym_sess_"))]:
                st.session_state.pop(k, None)
            st.rerun()
        components.html("""<script>
        try {
          const P = window.parent;
          if (P.__aphGymPop) P.removeEventListener("popstate", P.__aphGymPop);
          P.__aphGymPop = () => {
            // wpisy pośrednie (plan bez tygodnia/treningu) powstają przy
            // zapisie adresu; przebieg dopisałby brakujące pole i Wstecz
            // kręciłby się w miejscu — przeskakujemy je
            const q = new URLSearchParams(P.location.search);
            if (q.get("mode") === "gym" && q.get("p") && !(q.get("w") && q.get("t"))) {
              P.history.back(); return;
            }
            const b = P.document.querySelector(".st-key-trk_popstate button");
            if (b) b.click();
          };
          P.addEventListener("popstate", P.__aphGymPop);
        } catch (e) {}
        </script>""", height=0)


def _trk_bez_magazynu(e: Exception) -> None:
    """Magazyn planów nie odpowiada (sieć na siłowni, Supabase) — zdanie
    zamiast tracebacku. Komponent zostaje narysowany bez treningu: jego
    kolejka niezapisanych wpisów dalej ponawia wysyłkę co 10 s i zapisze
    się sama, gdy magazyn wróci. Drugiego trk_panel w tym przebiegu nie ma:
    w _trk_widok komponent rysuje się jako ostatni, więc błąd odczytu
    przychodzi zawsze przed nim."""
    from views.trener_panel import trener_panel
    from . import store
    st.error("Nie mogę połączyć się z magazynem planów. Niezapisane wpisy "
             "czekają w telefonie i pójdą same, gdy połączenie wróci.")
    st.caption(str(e))
    if st.button("Spróbuj ponownie", key="trk_ponow", type="primary"):
        store.invalidate()
        st.rerun()
    wynik = st.session_state.get("trk_wynik") or {}
    trener_panel({"ctx": None, "sekcje": [], "karty": [], "status": {},
                  "ack": list(wynik.get("ack") or []),
                  "odrzucone": list(wynik.get("odrzucone") or []),
                  "blad": wynik.get("blad") or str(e) or "Brak połączenia"},
                 key="trk_panel")


def _trk_widok() -> None:
    """Lista zawodników albo wybrany plan z treningiem — wszystko, co czyta
    magazyn (błąd łapie _render_gym_mode)."""
    plans = get_all_plans()
    pid = str(st.query_params.get("p") or "")
    plan = next((p for p in plans if p.get("id") == pid), None)
    if plan is None:
        _trk_lista_zawodnikow(plans)
        return
    if not st.query_params.get("t") and not st.query_params.get("w"):
        # świeże wejście w plan (lista, zmiana planu, przycisk z komputera):
        # tydzień i trening liczone od nowa, nie z poprzedniej wizyty w sesji
        for k in (f"gym_wk_{pid}", f"gym_sess_{pid}"):
            st.session_state.pop(k, None)
    if st.button("← Zawodnicy", key="trk_wroc"):
        for k in ("p", "t", "w"):
            st.query_params.pop(k, None)
        st.rerun()
    ath = plan.get("athlete", "")
    aplans = sorted([p for p in plans if p.get("athlete") == ath], reverse=True,
                    key=lambda p: p.get("start_date") or p.get("created") or "")
    if len(aplans) > 1:
        kp = f"trk_plan_{pid}"          # klucz z id: po zmianie nowy widżet

        def _zmien_plan() -> None:
            st.query_params["p"] = st.session_state[kp]
            for k in ("t", "w"):
                st.query_params.pop(k, None)

        st.selectbox(
            "Plan", [p["id"] for p in aplans], key=kp,
            index=[p["id"] for p in aplans].index(pid), on_change=_zmien_plan,
            format_func=lambda i: next(
                f"{p.get('name', '')} · " + ("aktualny" if is_current(p) else
                                             (p.get("start_date") or "")[:10])
                for p in aplans if p["id"] == i),
            label_visibility="collapsed")

    _render_plan_workout_body(plan, ath, prowadzony=True, trener=True)


