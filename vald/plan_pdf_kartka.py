"""
Kartka robocza do druku (Filip 2026-08-24) — układ jak jego
Excel „I.L": bloki ćwiczeń obok siebie, każde z siatką serii SET/RP/KG
do wpisania ręcznie na treningu, movement prep w kolumnie po prawej.

Różnica wobec plan_pdf_green: to nie jest rozpiska do czytania, tylko
kartka na zwykły biały papier — minimum wypełnień kolorem, brak kolumny
FILM (na papierze i tak nie działa), puste wiersze na wynik.

Wejście: plan w modelu aplikacji (sekcje Prep/Plyo & Power/Main, sloty
1a/1b, dawki tekstowe). Serie do siatki wyliczam z dawki:
  „4 x 65, 4 x 75, 4 x 85 kg" → I 4/65, II 4/75, III 4/85
  sets_n=3, reps=10, intent=„15 kg"  → I-III 10/15
  uwaga „rozgrzewkowa 6 x 40 kg"     → wiersz R1
"""
from __future__ import annotations

import re
import tempfile
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (BaseDocTemplate, Flowable, Frame, Image,
                                PageTemplate, Paragraph, Spacer, Table,
                                TableStyle)

from .plan_pdf_adapter import _kap, _txt
from .training import ensure_sessions, normalize_slots, week_params

# ── font z polskimi znakami (jak w zielonym szablonie) ──────────────────
_FONT, _FONT_B = "Helvetica", "Helvetica-Bold"
for kat in ("/Library/Fonts", "/System/Library/Fonts/Supplemental",
            str(Path.home() / "Library/Fonts")):
    p_r, p_b = Path(kat) / "Arial.ttf", Path(kat) / "Arial Bold.ttf"
    if p_r.exists():
        try:
            pdfmetrics.registerFont(TTFont("AR", str(p_r)))
            _FONT = "AR"
            if p_b.exists():
                pdfmetrics.registerFont(TTFont("AR-B", str(p_b)))
                _FONT_B = "AR-B"
            break
        except Exception:
            pass

# paleta kartki: niebieska (Filip 2026-08-24) — zielony zostaje
# rozpiskom w plan_pdf_green, kartka robocza idzie na niebiesko
_ATRAMENT = colors.HexColor("#12202E")
_LINIA = colors.HexColor("#8FA6BE")
_LINIA_L = colors.HexColor("#C7D5E3")
_AKCENT = colors.HexColor("#2F5C8A")
_SZARE = colors.HexColor("#E9F0F7")
_OPIS = colors.HexColor("#4A6076")
_NAZWA = colors.HexColor("#1B3A57")      # nazwa ćwiczenia nad siatką
_TLO_SET = colors.HexColor("#F2F6FB")    # kolumna SET i co drugi wiersz prepu

# palety klubowe — plan z kluczem paleta="iskra" dostaje czerń + złoto
# (Filip 2026-09-14: kartki Iskry „kolorystycznie jak szablon"); domyślna
# to niebieska kartka klubowa
_PALETY = {
    "iskra": {"_AKCENT": "#141414", "_LINIA": "#C9A227", "_LINIA_L": "#E3D3A0",
              "_SZARE": "#F7F2E4", "_OPIS": "#6B5E3A", "_NAZWA": "#141414",
              "_TLO_SET": "#FBF7EC", "_ATRAMENT": "#141414"},
}
_DOMYSLNA = {k: globals()[k] for k in
             ("_AKCENT", "_LINIA", "_LINIA_L", "_SZARE", "_OPIS", "_NAZWA",
              "_TLO_SET", "_ATRAMENT")}


def _ustaw_palete(nazwa: str | None) -> None:
    for k, v in _DOMYSLNA.items():
        globals()[k] = colors.HexColor(_PALETY[nazwa][k]) if nazwa in _PALETY else v

_RZYMSKIE = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII"]

# herb klubu w nagłówku kartki (Filip 2026-08-24) — gdy pliku nie ma,
# nagłówek renderuje się bez niego, bez błędu
_LOGO = Path.home() / "Desktop" / "slepsk.png"


def _st(nazwa, rozm, bold=False, kolor=_ATRAMENT, lead=None, align=0):
    return ParagraphStyle(nazwa, fontName=_FONT_B if bold else _FONT,
                          fontSize=rozm, leading=lead or rozm + 1.6,
                          textColor=kolor, alignment=align)


class _PionowyNapis(Flowable):
    """Etykieta bloku pisana pionowo, obok kolumn ćwiczeń
    (Filip 2026-08-24: „obok każdego bloku daj nazwę taką pionową")."""

    def __init__(self, tekst: str, rozm: float = 8.4, szer: float = 13,
                 kolor=None, bold: bool = True):
        Flowable.__init__(self)
        self.tekst = tekst
        self.rozm = rozm
        self.szer = szer
        self.kolor = kolor if kolor is not None else _AKCENT
        self.font = _FONT_B if bold else _FONT
        self.wys = pdfmetrics.stringWidth(tekst, self.font, rozm) + 6

    def wrap(self, dost_szer, dost_wys):
        return self.szer, self.wys

    def draw(self):
        c = self.canv
        c.saveState()
        c.setFont(self.font, self.rozm)
        c.setFillColor(self.kolor)
        c.translate(self.szer / 2, self.wys / 2)
        c.rotate(90)
        c.drawCentredString(0, -self.rozm * 0.36, self.tekst)
        c.restoreState()


def _serie_z_dawki(it: dict) -> tuple[list, str]:
    """(wiersze siatki, dopisek) — wiersze to (etykieta, RP, KG).
    Etykiety R1/R2 dla rozgrzewkowych z uwagi, potem rzymskie serie."""
    p = week_params(it, 1)
    sets_n = str(p.get("sets_n") or "").strip()
    reps = str(p.get("reps") or "").strip()
    intent = str(p.get("intent") or "").strip()
    nota = str(it.get("note") or "").strip()

    # bez wierszy rozgrzewkowych R1/R2 (Filip 2026-08-24) — jeśli uwaga
    # niesie rozgrzewkową serię, ląduje jako pierwsza seria robocza
    wiersze, dopisek = [], ""
    m_r = re.search(r"rozgrzewkow\w*\s*(\d+)\s*[x×]\s*(\d+)\s*kg", nota, re.I)
    if m_r:
        wiersze.append(("I", m_r.group(1), m_r.group(2)))
        nota = re.sub(r",?\s*rozgrzewkow\w*\s*\d+\s*[x×]\s*\d+\s*kg", "",
                      nota, flags=re.I).strip(" ,")

    # rampa po przecinkach: „4 x 65, 4 x 75, 4 x 85 kg"; człon, który nie
    # jest „N x M", ląduje w RP jako tekst — tak zapisuję serię innego
    # rodzaju, np. „12 x 40, 12 x 50, 30-40 sek" (ostatnia to ISO)
    off = len(wiersze)          # rozgrzewkowa mogła zająć pierwszą serię
    # pusty człon („3, 3, 2, ") = wiersz serii zostawiony do wypełnienia
    # dzielimy po przecinku ze spacją, żeby „12 x 17,5" nie rozpadło się
    czlony = [c.strip() for c in re.split(r",(?=\s|$)", reps)]
    if not any(czlony):
        czlony = []
    if len(czlony) >= 2:
        rz = off                       # licznik serii roboczych
        for c in czlony:
            # człon „W: 2 x 4-6" = wiersz rozgrzewkowy przed seriami
            # roboczymi; nie wchodzi do numeracji rzymskiej
            m_w = re.match(
                r"^(warm[-\s]?up|ostatnio|last\s+week|last|W|R\d?)"
                r"\s*:\s*(.*)$",
                c, re.I)
            if m_w:
                _et = m_w.group(1)
                _low = _et.lower()
                _et = ("warm-up" if _low.startswith("w") and len(_et) > 1
                       else _low if _low in ("ostatnio", "last",
                                            "last week")
                       else _et.upper())
                _tr = m_w.group(2).strip()
                # „ostatnio: @ 150 / 0,55" — sam ciężar, kolumna RP pusta
                _ma = re.match(r"^(.*?)\s*@\s*(.+)$", _tr)
                if _ma:
                    wiersze.append((_et, _ma.group(1).strip(),
                                    _ma.group(2).strip()))
                    continue
                # rozgrzewkowa też może nieść ciężar: „warm-up: 10 x 40"
                _mm = re.match(r"^(\d+)\s*[x×]\s*(\d+(?:[.,]\d+)?)$", _tr)
                wiersze.append((_et, _mm.group(1), _mm.group(2)) if _mm
                               else (_et, _tr, ""))
                continue
            et = _RZYMSKIE[rz] if rz < len(_RZYMSKIE) else str(rz + 1)
            rz += 1
            m = re.match(r"^(\d+)\s*[x×]\s*(\d+(?:[.,]\d+)?)", c)
            if m:
                wiersze.append((et, m.group(1), m.group(2)))
            else:
                # człon opisowy; „30-40 sek @ ISO" → RP „30-40 sek", KG „ISO"
                m2 = re.match(r"^(.*?)\s*@\s*(.+)$", c)
                if m2:
                    wiersze.append((et, m2.group(1).strip(),
                                    m2.group(2).strip()))
                else:
                    wiersze.append((et, re.sub(r"\s*kg$", "", c,
                                               flags=re.I), ""))
    else:
        # klasyczne „N x M" z osobnym ciężarem w intencji („15 kg")
        try:
            n = int(sets_n)
        except ValueError:
            n = 0
        kg = ""
        m_kg = re.match(r"^(\d+(?:[.,]\d+)?)\s*kg$", intent, re.I)
        if m_kg:
            kg = m_kg.group(1)
        elif intent:
            dopisek = intent
        if n:
            for i in range(n):
                j = off + i
                wiersze.append((_RZYMSKIE[j] if j < len(_RZYMSKIE)
                                else str(j + 1), reps, kg))
        elif reps:
            # dawka opisowa („30 sek max", „3 długości/str") — jeden wiersz
            wiersze.append((_RZYMSKIE[off], reps, kg))

    if nota:
        dopisek = f"{dopisek}, {nota}" if dopisek else nota
    return wiersze, dopisek


def _pasek_cwiczenia(it: dict, szer: float):
    """Samotna pozycja z dawką opisową (np. AirBike „30 sek max") —
    jedna linijka zamiast całej siatki, żeby nie zżerać kartki."""
    p = week_params(it, 1)
    s_, r_ = str(p.get("sets_n") or ""), str(p.get("reps") or "")
    dawka = f"{s_} x {r_}" if s_ and r_ else (r_ or s_)
    uw = _txt(it.get("note") or "")
    rest = _txt(p.get("rest") or "")
    prawa = ", ".join(x for x in (uw, f"przerwa {rest}" if rest else "") if x)
    t = Table([[Paragraph(_kap(_txt(it.get("exercise") or "")),
                          _st("pn", 7.6, bold=True)),
                Paragraph(_txt(dawka), _st("pdw", 7.4, align=1)),
                Paragraph(prawa, _st("pu", 6.4, align=2,
                                     kolor=_OPIS))]],
               colWidths=[szer * 0.34, szer * 0.36, szer * 0.30])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("BACKGROUND", (1, 0), (1, 0), _SZARE),
        ("BOX", (0, 0), (-1, -1), 0.7, _LINIA),
        ("LINEBEFORE", (1, 0), (1, 0), 0.4, _LINIA_L),
        ("LINEBEFORE", (2, 0), (2, 0), 0.4, _LINIA_L)]))
    return [t]


def _tabela_cwiczenia(it: dict, wys_wierszy: int, szer: float,
                      h_wiersza: float = 11.4, font_naz: float = 7.6,
                      pas_dopisku: bool = False, dwie_kg: bool = False):
    """Jedna kolumna bloku: nagłówek z nazwą i przerwą + siatka SET/RP/KG."""
    nazwa = _kap(_txt(it.get("exercise") or ""))
    rest = _txt(week_params(it, 1).get("rest") or "")
    wiersze, dopisek = _serie_z_dawki(it)

    s_naz = _st("naz", font_naz, bold=True, lead=font_naz + 1.2,
                kolor=_NAZWA, align=1)
    s_hdr = _st("hdr", 6.0, bold=True, kolor=colors.white)
    s_kom = _st("kom", 7.0, align=1)
    s_lab = _st("lab", 6.6, bold=True, align=1, kolor=_OPIS)
    s_dop = _st("dop", 7.2, kolor=_OPIS, lead=8.6, align=1)

    # główne ćwiczenia siłowe: dwie kolumny KG — dzisiejszy ciężar
    # i miejsce na kolejną sesję (Filip 2026-08-27)
    dane = [[Paragraph("SET", s_hdr), Paragraph("REP", s_hdr),
             Paragraph("KG", s_hdr)]
            + ([Paragraph("KG", s_hdr)] if dwie_kg else [])]
    # puste wiersze na dopisanie serii — numeracja rzymska biegnie dalej
    # od ostatniej rozpisanej (III → IV, nie przeskakuje)
    n_rzym = sum(1 for w in wiersze if not w[0].startswith("R"))
    for i in range(wys_wierszy):
        if i < len(wiersze):
            et, rp, kg = wiersze[i]
        else:
            # tylko wyrownanie wysokosci do sasiada w bloku — bez
            # rzymskiej etykiety, zeby nie sugerowac kolejnej serii
            et, rp, kg = "", "", ""
        if len(et) <= 3:
            _sl = s_lab
        else:
            _f = 5.6 if szer > 172 else 4.6
            _sl = _st("lab2", _f, bold=True, align=1, kolor=_OPIS,
                      lead=_f + 1.0)
        dane.append([Paragraph(et, _sl), Paragraph(str(rp), s_kom),
                     Paragraph(str(kg), s_kom)]
                    + ([Paragraph("", s_kom)] if dwie_kg else []))
    # dopisek („max intent", „wyciąg górny") jako wiersz TEJ tabeli —
    # wyśrodkowany i w ramce, żeby trzymał się ćwiczenia (Filip 2026-08-24)
    # pusty pas, gdy sąsiad w bloku ma dopisek — inaczej tabelki
    # kończyłyby się na różnej wysokości
    if dopisek or pas_dopisku:
        dane.append([Paragraph(_txt(dopisek), s_dop), "", ""]
                    + ([""] if dwie_kg else []))

    # wąska kolumna SET (same rzymskie) — miejsce idzie na RP i KG,
    # gdzie zawodnik wpisuje wynik (Filip 2026-08-24)
    # dłuższa etykieta serii („warm-up") potrzebuje szerszej kolumny SET
    _dl = any(len(w[0]) > 3 for w in wiersze)
    if dwie_kg:
        kol = ([szer * 0.20, szer * 0.28, szer * 0.26, szer * 0.26] if _dl
               else [szer * 0.13, szer * 0.33, szer * 0.27, szer * 0.27])
    else:
        kol = ([szer * 0.22, szer * 0.39, szer * 0.39] if _dl
               else [szer * 0.15, szer * 0.425, szer * 0.425])
    t = Table(dane, colWidths=kol,
              rowHeights=[9] + [h_wiersza] * wys_wierszy
              + ([None] if (dopisek or pas_dopisku) else []))
    cmds = [("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 1),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
            ("LEFTPADDING", (0, 0), (-1, -1), 2),
            ("RIGHTPADDING", (0, 0), (-1, -1), 2),
            ("BACKGROUND", (0, 0), (-1, 0), _AKCENT),
            ("GRID", (0, 0), (-1, -1), 0.4, _LINIA_L),
            ("BOX", (0, 0), (-1, -1), 0.7, _LINIA),
            ("LINEAFTER", (0, 1), (0, -1), 0.7, _LINIA),
            ("BACKGROUND", (0, 1), (0, -1), _TLO_SET)]
    # zaplanowane serie na szarym tle — puste wiersze zostają na wynik
    for i, _ in enumerate(wiersze[:wys_wierszy]):
        cmds.append(("BACKGROUND", (1, i + 1), (2, i + 1), _SZARE))
    if dopisek or pas_dopisku:
        cmds += [("SPAN", (0, len(dane) - 1), (-1, len(dane) - 1)),
                 ("BACKGROUND", (0, len(dane) - 1), (-1, len(dane) - 1),
                  colors.white),
                 ("LINEABOVE", (0, len(dane) - 1), (-1, len(dane) - 1),
                  0.7, _LINIA),
                 ("TOPPADDING", (0, len(dane) - 1), (-1, len(dane) - 1), 3),
                 ("BOTTOMPADDING", (0, len(dane) - 1), (-1, len(dane) - 1),
                  3),
                 ("LEFTPADDING", (0, len(dane) - 1), (-1, len(dane) - 1), 4),
                 ("RIGHTPADDING", (0, len(dane) - 1), (-1, len(dane) - 1),
                  4)]
    t.setStyle(TableStyle(cmds))

    # stała wysokość nagłówka — długa nazwa łamie się na dwie linie i bez
    # tego rozjeżdżała siatki sąsiednich ćwiczeń w bloku
    gora = Table([[Paragraph(nazwa, s_naz), ""]],
                 colWidths=[szer * 0.99, szer * 0.01],
                 rowHeights=[font_naz * 2 + 4])
    gora.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LINEBELOW", (0, 0), (-1, -1), 0.9, _AKCENT)]))

    return [gora, Spacer(1, 2.4), t]


def _kolumna_prep(items: list, szer: float, tytul: str = "MOVEMENT PREP",
                  ety: dict | None = None):
    """Spis po prawej (movement prep, conditioning) — nazwa + dawka,
    bez miejsca na wynik."""
    s_hdr = _st("ph", 7.0, bold=True, kolor=colors.white)
    s_naz = _st("pn", 7.0, bold=True)
    s_daw = _st("pd", 6.6, kolor=_OPIS, lead=8)
    _e = ety or _ETY["pl"]
    dane = [[Paragraph(tytul, s_hdr), Paragraph("", s_hdr)]]
    for it in items:
        p = week_params(it, 1)
        s_, r_ = str(p.get("sets_n") or ""), str(p.get("reps") or "")
        dawka = f"{s_} x {r_}" if s_ and r_ else (r_ or s_)
        uw = _txt(it.get("note") or "")
        if uw:
            dawka = f"{dawka}, {uw}" if dawka else uw
        dane.append([Paragraph(_kap(_txt(it.get("exercise") or "")), s_naz),
                     Paragraph(_txt(dawka), s_daw)])
    # pusty wiersz (szablon do wpisania ręcznie) dostaje wysokość na długopis
    t = Table(dane, colWidths=[szer * 0.52, szer * 0.48],
              rowHeights=[None] + [None if (it.get("exercise") or "").strip() else 16
                                   for it in items])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("SPAN", (0, 0), (1, 0)),
        ("BACKGROUND", (0, 0), (-1, 0), _AKCENT),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("GRID", (0, 1), (-1, -1), 0.4, _LINIA_L),
        ("BOX", (0, 0), (-1, -1), 0.7, _LINIA)]
        + [("BACKGROUND", (0, r), (-1, r), _TLO_SET)
           for r in range(1, len(dane)) if r % 2]))
    return t


def _wciecie(flow, lewo: float, szer: float):
    """Pozycja bez etykiety bloku (np. AirBike) wyrównana do kolumn
    ćwiczeń — pusta kolumna szerokości etykiety po lewej."""
    t = Table([["", flow]], colWidths=[lewo, szer])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    return t


def _sec_items(items, section):
    if section == "Main":
        return [it for it in items
                if it.get("section") not in ("Prep", "Prep 2", "Plyo & Power",
                                             "Conditioning")]
    return [it for it in items if it.get("section") == section]


def _grupy(items: list) -> list[list]:
    """Bloki = ćwiczenia o tym samym numerze slotu (1a/1b/1c → BLOK 1);
    pozycja bez numeru staje się własnym blokiem."""
    out, biezacy, klucz = [], [], None
    for it in items:
        m = re.match(r"\s*(\d+)", str(it.get("slot") or ""))
        k = m.group(1) if m else None
        if biezacy and (k is None or k != klucz):
            out.append(biezacy)
            biezacy = []
        biezacy.append(it)
        klucz = k
    if biezacy:
        out.append(biezacy)
    return out


_ETY = {"pl": {"blok": "BLOK", "prep": "MOVEMENT PREP",
               "prep2": "MOVEMENT PREP 2",
               "cond": "CONDITIONING (AFTER GYM)", "cw": "ĆWICZENIE",
               "dawka": "DAWKA"},
        "en": {"blok": "BLOCK", "prep": "MOVEMENT PREP",
               "prep2": "MOVEMENT PREP 2",
               "cond": "CONDITIONING (AFTER GYM)", "cw": "EXERCISE",
               "dawka": "DOSE"}}


def build_plan_pdf_kartka(plan: dict) -> bytes:
    """Kartka robocza A4 poziomo — jedna strona na trening.
    Plan z kluczem lang="en" dostaje angielskie etykiety.
    Wysokość wiersza schodzi w dół, dopóki wszystko nie zmieści się
    na jednej stronie (dopisek potrafi zająć dwie linie)."""
    for _skala in (1.0, 0.88, 0.78, 0.68, 0.60, 0.52):
        _b, _stron = _zbuduj(plan, _skala)
        if _stron <= len(ensure_sessions(plan) or [1]):
            return _b
    return _b


def _zbuduj(plan: dict, skala: float = 1.0) -> tuple[bytes, int]:
    _ustaw_palete(plan.get("paleta"))
    ety = _ETY.get(str(plan.get("lang") or "pl"), _ETY["pl"])
    sessions = ensure_sessions(plan) or []
    szer_str, wys_str = landscape(A4)
    MARG = 9 * mm
    W = szer_str - 2 * MARG

    with tempfile.TemporaryDirectory() as tmp:
        out = str(Path(tmp) / "kartka.pdf")
        doc = BaseDocTemplate(out, pagesize=landscape(A4),
                              leftMargin=MARG, rightMargin=MARG,
                              topMargin=MARG, bottomMargin=MARG,
                              title=plan.get("name", "Plan"))
        doc.addPageTemplates([PageTemplate(
            id="k", frames=[Frame(MARG, MARG, W, wys_str - 2 * MARG,
                                  leftPadding=0, rightPadding=0,
                                  topPadding=0, bottomPadding=0)])])

        el = []
        for si, sess in enumerate(sessions):
            items = normalize_slots([dict(it)
                                     for it in (sess.get("items") or [])])
            prep = _sec_items(items, "Prep")
            prep2 = _sec_items(items, "Prep 2")
            cond = _sec_items(items, "Conditioning")
            reszta = [it for it in items if it.get("section") == "Plyo & Power"] \
                + _sec_items(items, "Main")

            # nagłówek: po lewej trening i zawodnik, na środku herb klubu,
            # po prawej data (Filip 2026-08-24 — nazwa planu z rogu znika)
            tyt = _txt(sess.get("title") or "") or "Trening"
            _sd = str(plan.get("start_date") or "")
            data_txt = (f"{_sd[8:10]}.{_sd[5:7]}.{_sd[:4]}"
                        if len(_sd) >= 10 else "")
            # lewa strona pusta — nazwa treningu i zawodnik wypadły
            # (Filip 2026-08-24); zawodnik stoi teraz nad datą po prawej
            lewo_n = ""
            srodek = ""
            # herb z planu (inne kluby, Filip 2026-09-14), inaczej domyślny
            # klucz „logo" w planie: ścieżka = ten herb, pusty = bez herbu
            _logo = (Path(plan["logo"]) if plan.get("logo")
                     else (None if "logo" in plan else _LOGO))
            if _logo and _logo.exists():
                _iw, _ih = ImageReader(str(_logo)).getSize()
                h_logo = 40
                srodek = Image(str(_logo), width=h_logo * _iw / _ih,
                               height=h_logo, mask="auto")
            nag = Table([[lewo_n, srodek,
                          [Paragraph(_txt(plan.get("athlete", "")),
                                     _st("z", 11, bold=True, align=2)),
                           Paragraph(data_txt,
                                     _st("d", 9, bold=True, align=2,
                                         kolor=_OPIS))]]],
                        colWidths=[W * 0.40, W * 0.20, W * 0.40])
            nag.setStyle(TableStyle([
                ("VALIGN", (0, 0), (0, 0), "BOTTOM"),
                ("VALIGN", (1, 0), (1, 0), "MIDDLE"),
                ("VALIGN", (2, 0), (2, 0), "BOTTOM"),
                ("ALIGN", (1, 0), (1, 0), "CENTER"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LINEBELOW", (0, -1), (-1, -1), 1.1, _AKCENT)]))
            el += [nag, Spacer(1, 5)]

            grupy = _grupy(reszta)
            # siatka ma TYLKO rozpisane serie — bez pustych IV/V/VI
            # (Filip 2026-08-24: „wyjeb te serie, bo i tak nic nie ma").
            # Wysokość liczona per blok, żeby siatki w rzędzie były równe.
            wys_bloku = {}
            for gi_, g_ in enumerate(grupy):
                wys_bloku[gi_] = max(
                    [len(_serie_z_dawki(x)[0]) for x in g_] or [1])

            # kartka ma zmieścić się na JEDNEJ stronie — wysokość wiersza
            # dobieram do liczby bloków (stałe: nagłówek grupy 13,4 +
            # nagłówek siatki 9 + dopisek 9 + odstęp 5)
            pelne = [gi_ for gi_, g_ in enumerate(grupy)
                     if not (len(g_) == 1
                             and len(_serie_z_dawki(g_[0])[0]) <= 3)]
            dost = wys_str - 2 * MARG - 46 - 26 * (len(grupy) - len(pelne))
            # stałe na blok: nagłówek 19,2 + odstęp 2,4 + pasek SET 9
            #                + dopisek 9 + przerwa między blokami 5
            stale = 44.6 * len(pelne)
            suma_w = sum(wys_bloku[gi_] for gi_ in pelne) or 1
            h_w = (dost - stale) / suma_w
            # bez pustych wierszy zostaje zapas — wyższe wiersze wygodniej
            # zapisać długopisem, ale nie rozciągam ich w nieskończoność
            h_w = max(9.0, min(22.0, h_w)) * skala

            szer_prep = W * 0.19 if (prep or prep2 or cond) else 0
            szer_lewa = W - szer_prep - (6 if prep else 0)

            SZER_ET = 15           # kolumna na pionową etykietę bloku
            lewa, nr_bloku = [], 0
            for gi, g in enumerate(grupy):
                if gi:
                    lewa.append(Spacer(1, 5))
                # przerwa stoi PIONOWO między kolumną KG jednego ćwiczenia
                # a SET następnego (Filip 2026-08-24), nie nad tabelką
                SZER_PRZ = 20
                szer_cw = szer_lewa - SZER_ET
                szer_kol = (szer_cw - SZER_PRZ * len(g)) / len(g)
                if len(g) == 1 and len(_serie_z_dawki(g[0])[0]) <= 3:
                    lewa.append(_wciecie(_pasek_cwiczenia(g[0], szer_cw)[0],
                                         SZER_ET, szer_cw))
                    continue
                nr_bloku += 1
                f_naz = 6.9 if len(g) >= 4 else 7.6
                ma_dop = any(_serie_z_dawki(it)[1] for it in g)
                kom, kolw = [], []
                for it in g:
                    # wszystkie tabelki w bloku tej samej wysokości —
                    # krótsza rozpiska dostaje pusty wiersz na dole
                    # (Filip 2026-08-24)
                    # dwie kolumny KG: pozycje „a" w bloku albo ćwiczenie
                    # z jawną flagą w danych
                    # plan z jedna_kg=True ma wszędzie jedną kolumnę KG
                    # (Filip 2026-08-30: ostatni tydzień bloku)
                    _dwie = (not plan.get("jedna_kg")
                             and (str(it.get("slot") or "").endswith("a")
                                  or bool(it.get("dwie_kg"))))
                    kom.append(_tabela_cwiczenia(it, wys_bloku[gi], szer_kol,
                                                 h_w, f_naz, ma_dop, _dwie))
                    kolw.append(szer_kol)
                    _r = _txt(week_params(it, 1).get("rest") or "")
                    kom.append(_PionowyNapis(_r, 7.0, SZER_PRZ, _OPIS,
                                             bold=False) if _r else "")
                    kolw.append(SZER_PRZ)
                tg = Table([kom], colWidths=kolw)
                _cm = [("VALIGN", (0, 0), (-1, -1), "TOP"),
                       ("LEFTPADDING", (0, 0), (-1, -1), 0),
                       ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                       ("TOPPADDING", (0, 0), (-1, -1), 0),
                       ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]
                for _i in range(1, len(kom), 2):      # kolumny z przerwami
                    _cm += [("VALIGN", (_i, 0), (_i, 0), "MIDDLE"),
                            ("ALIGN", (_i, 0), (_i, 0), "CENTER")]
                tg.setStyle(TableStyle(_cm))
                z_et = Table([[_PionowyNapis(f'{ety["blok"]} {nr_bloku}'), tg]],
                             colWidths=[SZER_ET, szer_cw])
                z_et.setStyle(TableStyle([
                    ("VALIGN", (0, 0), (0, 0), "MIDDLE"),
                    ("VALIGN", (1, 0), (1, 0), "TOP"),
                    ("ALIGN", (0, 0), (0, 0), "CENTER"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                    ("LINEAFTER", (0, 0), (0, 0), 1.1, _AKCENT)]))
                lewa.append(z_et)

            if prep or prep2 or cond:
                prawa = []
                if prep:
                    prawa.append(_kolumna_prep(prep, szer_prep,
                                               ety["prep"], ety))
                if prep2:
                    if prawa:
                        prawa.append(Spacer(1, 7))
                    prawa.append(_kolumna_prep(prep2, szer_prep,
                                               ety["prep2"], ety))
                if cond:
                    if prawa:
                        prawa.append(Spacer(1, 7))
                    prawa.append(_kolumna_prep(cond, szer_prep,
                                               ety["cond"], ety))
                zew = Table([[lewa, prawa]],
                            colWidths=[szer_lewa + 6, szer_prep])
                zew.setStyle(TableStyle([
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
                el.append(zew)
            else:
                el += lewa

            if si < len(sessions) - 1:
                from reportlab.platypus import PageBreak
                el.append(PageBreak())

        doc.build(el)
        return Path(out).read_bytes(), doc.page
