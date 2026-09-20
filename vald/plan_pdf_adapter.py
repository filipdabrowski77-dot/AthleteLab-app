"""
Most: plan z aplikacji → zielony szablon PDF Filipa (vald/plan_pdf_green.py,
ten sam, którym robił wcześniejsze plany — reportlab, A4 poziomo,
jeden trening = jedna strona, klikalne FILM, auto-skalowanie).

Mapowanie sekcji na bloki szablonu:
  Prep          → blok „MOVEMENT PREP" w układzie prostym
                  (Ćwiczenie | Serie × powtórzenia | FILM)
  Plyo & Power  → blok „PLYO & POWER" z kolumnami WEEK 1..N
  Main          → blok „MAIN STRENGTH" z kolumnami WEEK 1..N
"""
from __future__ import annotations

import re
import tempfile
from pathlib import Path

from .training import (ensure_sessions, normalize_slots, plan_end,
                       week_params)

# Arial nie ma glifu ⚠ (wychodzi kwadracik) — podmiana przy renderze
_GLIF = {"⚠": "(!)", "🎬": "", "✅": "", "→": "-", "≥": ">=", "≤": "<="}


# skróty, które zostają WIELKIMI literami na początku nazwy
_SKROTY = {"sl": "SL", "cmj": "CMJ", "rdl": "RDL", "iso": "ISO",
           "db": "DB", "bb": "BB", "kb": "KB", "mb": "MB", "ohp": "OHP",
           "ff": "FF", "gh": "GH", "th": "TH", "ywt": "YWT",
           "rfess": "RFESS"}


def _kap(nazwa: str) -> str:
    """Nazwa ćwiczenia z wielkiej litery (Filip 2026-08-23);
    skrót na początku zostaje w całości wielkimi (sl → SL)."""
    n = (nazwa or "").strip()
    if not n:
        return n
    pierwsze = n.split()[0]
    if pierwsze.lower() in _SKROTY:
        return _SKROTY[pierwsze.lower()] + n[len(pierwsze):]
    return n[0].upper() + n[1:]


def _txt(s: str) -> str:
    out = s or ""
    for bad, good in _GLIF.items():
        out = out.replace(bad, good)
    # reportlab parsuje markup: gołe "&" w "Clamshell up&down" udaje encję
    out = re.sub(r"&(?!(?:amp|lt|gt|quot|apos|#\d+);)", "&amp;", out)
    return " ".join(out.split())

# Nagłówek planu: jak łączyć superserie + skala RPE i intensywność skoków
# (przeniesione 1:1 z Exceli Filipa)
_WSTEP = ""

# Skala RPE jako tabelka z gradientem (czerwień przy 10 -> jasne przy 1-4),
# obok niej krótkie wskazówki. Bez długich myślników i AI-owego stylu.
# Kolory RPE wg wzoru Filipa (zdjęcie tabeli): 10 czerwony, potem
# pomarańcz, żółty, róż, fiolet, niebieski, turkus, zielony przy 1-4.
_RPE = [("10", "Zero powtórzeń w rezerwie", "#D9655D"),
        ("9,5", "Może jedno powtórzenie w rezerwie", "#E2954E"),
        ("9", "Jedno powtórzenie w rezerwie", "#E0A85C"),
        ("8,5", "Jedno, może dwa powtórzenia w rezerwie", "#E0C263"),
        ("8", "Dwa powtórzenia w rezerwie", "#DD8CB6"),
        ("7,5", "Dwa, może trzy powtórzenia w rezerwie", "#9C89C6"),
        ("7", "Trzy powtórzenia w rezerwie", "#7FA9DD"),
        ("5-6", "Lekki wysiłek, 4-5 powtórzeń w rezerwie", "#80C9C1"),
        ("1-4", "Bardzo lekki wysiłek", "#8DCA80")]
_HDR = "#44603F"

_SUPERSERIE = ("<b>Superserie.</b> Ćwiczenia oznaczone tą samą cyfrą "
               "(1a/1b, 2a/2b) łączysz w superserię: 1a → ~30 sek przerwy "
               "→ 1b → dłuższa przerwa 2-3 min. Długość przerwy dobieraj "
               "do własnych odczuć.")

_CIEZAR = ("<b>Ciężar.</b> RPE mówi, ile powtórzeń zostaje Ci w zapasie. "
           "Dobierasz ciężar tak, żeby trafić w RPE zapisane przy serii.")

# Intensywność skoków — ten sam blok w każdym planie
_INT = [("easy", "60% intencji, niskie skoki, szybki kontakt z ziemią",
         "#8DCA80"),
        ("medium", "80% intencji", "#E0C263"),
        ("high / max", "100%, szybko od ziemi, maksymalna wysokość",
         "#D9655D")]


def _int_tabela():
    b = lambda t: f'<b><font color="#1A1A1A">{t}</font></b>'
    d = lambda t: f'<font color="#1A1A1A">{t}</font>'
    return {"wiersze": [[b(k), d(v)] for k, v, _ in _INT],
            "bg": [[hx, hx] for _, _, hx in _INT],
            "kolw": [0.24, 0.76]}


def _rpe_tabela():
    b = lambda t: f'<b><font color="#1A1A1A">{t}</font></b>'
    d = lambda t: f'<font color="#1A1A1A">{t}</font>'
    w = lambda t: f'<b><font color="#FFFFFF">{t}</font></b>'
    wiersze = [[w("RPE"), w("Znaczenie")]]
    bg = [[_HDR, _HDR]]
    for rpe, zn, hx in _RPE:
        wiersze.append([b(rpe), d(zn)])
        bg.append([hx, hx])
    return {"wiersze": wiersze, "bg": bg, "kolw": [0.09, 0.91]}


def _prep_tabela(rows):
    """Movement prep jako tabelka w nagłówku (Filip 2026-08-24): nazwa
    ćwiczenia + dawka, bez kolumny FILM."""
    b = lambda t: f'<b><font color="#1A1A1A">{t}</font></b>'
    d = lambda t: f'<font color="#1A1A1A">{t}</font>'
    w = lambda t: f'<b><font color="#FFFFFF">{t}</font></b>'
    wiersze = [[w("ĆWICZENIE"), w("DAWKA")]]
    bg = [[_HDR, _HDR]]
    for i, (nazwa, dawka) in enumerate(rows):
        wiersze.append([b(nazwa), d(dawka)])
        tlo = "#EFF4E4" if i % 2 == 0 else "#F7F9F3"
        bg.append([tlo, tlo])
    return {"wiersze": wiersze, "bg": bg, "kolw": [0.56, 0.44]}


def _legenda(prep_rows=None, cond_rows=None):
    """Nagłówek planu: skala RPE po lewej. Po prawej domyślnie trzy
    wskazówki (superserie, ciężar, intensywność skoków), a gdy plan trzyma
    prep w nagłówku — tabelka MOVEMENT PREP, obok niej CONDITIONING."""
    if prep_rows or cond_rows:
        rzad = []
        if prep_rows:
            rzad.append({"tytul": "MOVEMENT PREP",
                         "tabela": _prep_tabela(prep_rows), "udzial": 0.62})
        if cond_rows:
            rzad.append({"tytul": "CONDITIONING",
                         "tabela": _prep_tabela(cond_rows), "udzial": 0.38})
        return [{"tytul": "SKALA RPE", "tabela": _rpe_tabela(), "szer": 0.40,
                 "obok": [rzad if len(rzad) > 1 else rzad[0]]}]
    return [{"tytul": "SKALA RPE", "tabela": _rpe_tabela(), "szer": 0.56,
             "obok": [_SUPERSERIE, _CIEZAR,
                      {"tytul": "INTENSYWNOŚĆ SKOKÓW",
                       "tabela": _int_tabela()}]}]

_SEC_BLOKI = (("Prep", "MOVEMENT PREP", True),
              ("Plyo & Power", "PLYO & POWER", False),
              ("Main", "MAIN STRENGTH", False))
_LITERY = "ABCDEFGH"


def _dawka(it: dict, wk: int) -> str:
    """„3×6 @ rpe 8" — dokładnie to, co widać w siatce Tygodnie."""
    p = week_params(it, wk)
    s, r = p.get("sets_n", ""), p.get("reps", "")
    out = f"{s}×{r}" if s and r else (r or s)
    if out and p.get("intent"):
        out += f" @ {p['intent']}"
    return out


def _sec_items(items: list, section: str) -> list:
    if section == "Main":
        return [it for it in items
                if it.get("section") not in ("Prep", "Plyo & Power",
                                             "Conditioning")]
    return [it for it in items if it.get("section") == section]


def build_plan_pdf_green(plan: dict, url_map: dict | None = None) -> bytes:
    """PDF planu w zielonym szablonie. Zwraca bajty (jak build_plan_pdf)."""
    from . import plan_pdf_green as G

    url_map = url_map or {}
    weeks_n = max(int(plan.get("weeks", 4)), 1)
    sessions = ensure_sessions(plan) or []

    # plan może trzymać movement prep w nagłówku (tabelka obok skali RPE)
    # zamiast jako blok w tabeli — decyzja per plan, flaga w danych
    prep_w_nag = bool(plan.get("prep_w_naglowku"))

    dni, linki = [], {}
    for i, sess in enumerate(sessions):
        # normalizacja przy renderze: samotne „3a" → „3" także w planach
        # zapisanych przed wprowadzeniem reguły (kopia, nie ruszamy danych)
        items = normalize_slots([dict(it) for it in (sess.get("items") or [])])
        def _naglowkowe(sec):
            out = []
            for it in _sec_items(items, sec):
                dawka = _txt(_dawka(it, 1))
                uw = _txt(it.get("note") or "")
                out.append((_kap(_txt(it.get("exercise") or "")),
                            f"{dawka}, {uw}" if dawka and uw
                            else (dawka or uw)))
            return out

        # conditioning zawsze ląduje w nagłówku (mała tabelka obok prepu)
        cond_rows = _naglowkowe("Conditioning")
        prep_rows = _naglowkowe("Prep") if prep_w_nag else []
        bloki = []
        for section, tytul, prosty in _SEC_BLOKI:
            if prep_w_nag and section == "Prep":
                continue
            secit = _sec_items(items, section)
            if not secit:
                continue
            wiersze = []
            for it in secit:
                nazwa = (it.get("exercise") or "").strip()
                url = url_map.get(nazwa.lower(), "")
                if url:
                    # klucz MUSI być po _kap/_txt — szablon szuka linku po
                    # nazwie, którą drukuje. Bez tego „Bound & Land" (po _txt
                    # „Bound &amp; Land") gubiło FILM w PDF.
                    linki[_kap(_txt(nazwa))] = url
                _slot = (it.get("slot") or "").strip()
                w = {"nr": "" if section == "Plyo & Power" else _slot,
                     "grupa": _slot,
                     "cw": _kap(_txt(nazwa)),
                     "uw": _txt(it.get("note") or ""),
                     "tempo": _txt(it.get("tempo") or ""),
                     "rest": week_params(it, 1).get("rest", "")}
                if prosty:
                    # blok prosty: cała dawka ląduje w kolumnie „serie ×
                    # powtórzenia" (prep nie ma progresji tygodniowej)
                    w["uw"] = _txt(_dawka(it, 1)) + (
                        f" · {w['uw']}" if w["uw"] else "")
                    w["tyg"] = []
                else:
                    w["tyg"] = [_txt(_dawka(it, k))
                                for k in range(1, weeks_n + 1)]
                wiersze.append(w)
            blok = {"t": tytul, "w": wiersze}
            if prosty:
                blok["prosty"] = True
            bloki.append(blok)
        litera = _LITERY[i] if i < len(_LITERY) else str(i + 1)
        # nagłówek = sama nazwa treningu, bez myślników i dopisków
        # (Filip 2026-08-23); brak nazwy → „Trening A/B"
        tytul_dnia = _txt(sess.get("title") or "") or f"Trening {litera}"
        # legenda (RPE + wskazówki) TYLKO nad pierwszym treningiem —
        # nie powtarzamy jej na stronie B, C…
        dzien = {"nr": tytul_dnia, "bloki": bloki}
        if i == 0 and not plan.get("bez_legendy"):
            dzien["wstep"] = _WSTEP
            # tabelka intensywności tylko tam, gdzie Filip jej używa
            dzien["legenda"] = _legenda(prep_rows, cond_rows)
        dni.append(dzien)

    if not dni:
        dni = [{"nr": "Trening A", "bloki": [
            {"t": "PLAN", "prosty": True,
             "w": [{"nr": "", "cw": "Plan nie ma jeszcze treningów",
                    "uw": "", "tyg": [], "rest": ""}]}]}]

    start_txt = plan.get("start_date") or ""
    # prawy górny róg: sama nazwa planu (Filip: bez daty, bez dublowania
    # nazwiska — nazwa planu i tak je zawiera)
    naglowek = _txt(plan.get("name", "")) or _txt(plan.get("athlete", ""))

    with tempfile.TemporaryDirectory() as tmp:
        out = str(Path(tmp) / "plan.pdf")
        G.buduj(dni, linki, out, zawodnik=naglowek,
                okres="", start=None, n_tygodni=weeks_n)
        return Path(out).read_bytes()
