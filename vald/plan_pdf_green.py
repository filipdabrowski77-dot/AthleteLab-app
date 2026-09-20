# -*- coding: utf-8 -*-
"""Plan treningowy → PDF (A4 poziomo, jeden dzień = dokładnie jedna strona).

Linki do filmów są klikalne bezpośrednio w PDF-ie — bez kroku „drukuj do PDF".
Dzień, który nie mieści się w pełnym rozmiarze, jest automatycznie skalowany
w dół aż wejdzie na stronę — zamiast przelewać się na następną.

Wywołanie z pliku danych:
    python3 plan_pdf.py _dane.py wyjscie.pdf "Imię Nazwisko" "GPP 1 · 01.08–28.08.2026"

Plik danych definiuje DNI i L. Struktura dnia:
    {'nr','tytul'?,'wstep'?,'legenda'?, 'bloki':[{'t', 'prosty'?, 'w':[
        {'nr','cw','uw','tempo'?,'tyg':[t1,t2,t3,t4],'rest'}]}]}
Blok z 'prosty': True dostaje układ Ćwiczenie | Serie × powtórzenia | Film.
Kolumna TEMPO pojawia się tylko w blokach, w których któryś wiersz ją ma.
"""
import os
import re
import sys
from datetime import date, timedelta

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, Frame, PageBreak, PageTemplate,
                                Paragraph, Spacer, Table, TableStyle)

# Wbudowana Helvetica nie ma polskich znaków — bez zarejestrowanego TTF
# ą/ć/ę/ł/ń/ś/ź/ż wychodzą w PDF-ie jako czarne kwadraty. Stąd twardy wymóg.
# Kolejność jest celowa: Arial to wygląd, który Filip zna z Maca, Liberation
# Sans ma identyczne metryki (Linux w chmurze — patrz packages.txt), DejaVu
# jest na każdym Debianie jako ostatnia deska ratunku.
KATALOGI = ['/System/Library/Fonts/Supplemental', '/Library/Fonts',
            os.path.expanduser('~/Library/Fonts'),
            '/usr/share/fonts/truetype/liberation',
            '/usr/share/fonts/truetype/liberation2',
            '/usr/share/fonts/truetype/msttcorefonts',
            '/usr/share/fonts/truetype/dejavu']
RODZINY = [('Arial.ttf', 'Arial Bold.ttf'),
           ('LiberationSans-Regular.ttf', 'LiberationSans-Bold.ttf'),
           ('DejaVuSans.ttf', 'DejaVuSans-Bold.ttf'),
           ('Verdana.ttf', 'Verdana Bold.ttf'),
           ('Tahoma.ttf', 'Tahoma Bold.ttf')]


def znajdz_rodzine(katalogi=None, rodziny=None):
    """Pierwsza para (zwykła, pogrubiona) TTF, która leży na dysku."""
    for zwykla, pogrubiona in (rodziny if rodziny is not None else RODZINY):
        for kat in (katalogi if katalogi is not None else KATALOGI):
            pz, pp = os.path.join(kat, zwykla), os.path.join(kat, pogrubiona)
            if os.path.exists(pz) and os.path.exists(pp):
                return pz, pp
    return None


_para = znajdz_rodzine()
if _para is None:
    # RuntimeError, nie sys.exit: sys.exit rzuca SystemExit (BaseException),
    # którego `except Exception` w apce NIE łapał — w chmurze (brak Ariala)
    # gasiło to cały render Streamlita zamiast pokazać komunikat.
    raise RuntimeError(
        'brak czcionki TTF z polskimi znakami (Arial / Liberation Sans / '
        'DejaVu) — PDF miałby kwadraty zamiast ą/ć/ę')
pdfmetrics.registerFont(TTFont('Plan', _para[0]))
pdfmetrics.registerFont(TTFont('Plan-B', _para[1]))
F, FB = 'Plan', 'Plan-B'

CZERN = colors.HexColor('#1A1A1A')
SZARY = colors.HexColor('#555555')
# Zieleń jak w oryginalnych planach — akcent, nie tło całości.
ZIELEN = colors.HexColor('#7B9A57')
ZIELEN_CIEMNA = colors.HexColor('#5C7540')
ZIELEN_JASNA = colors.HexColor('#A6BE82')
JASNY = colors.HexColor('#EFF4E4')
LINIA = colors.HexColor('#E2E7D8')
PASEK = colors.HexColor('#F8FAF3')


class Style:
    """Komplet stylów przeskalowany współczynnikiem s (1.0 = rozmiar bazowy)."""

    def __init__(self, s=1.0):
        self.s = s

        def ps(nazwa, font, rozmiar, interlinia, kolor, **kw):
            return ParagraphStyle(nazwa, fontName=font, fontSize=rozmiar * s,
                                  leading=interlinia * s, textColor=kolor, **kw)

        self.tekst = ps('t', F, 7.6, 9.4, CZERN)
        self.cw = ps('cw', FB, 7.8, 9.6, CZERN)
        self.uw = ps('uw', F, 6.8, 8.4, SZARY)
        self.hdr = ps('h', FB, 6.3, 8, ZIELEN_CIEMNA, alignment=1)
        self.hdr_l = ParagraphStyle('hl', parent=self.hdr, alignment=0)
        self.srodek = ParagraphStyle('c', parent=self.tekst, alignment=1)
        self.nr = ParagraphStyle('n', parent=self.cw, alignment=1)
        self.rest = ParagraphStyle('r', parent=self.uw, alignment=1)
        self.wstep = ps('w', F, 7.6, 10.4, colors.HexColor('#333333'))
        self.film = ps('f', FB, 7.2, 9, ZIELEN_CIEMNA, alignment=1)
        self.dzien = ps('d', FB, 21, 24, CZERN)
        self.kto = ps('k', FB, 9, 11, CZERN, alignment=2)
        self.okres = ps('o', F, 7.5, 9.5, SZARY, alignment=2)
        self.lege = ps('lg', F, 6.6, 8.6, colors.HexColor('#4A5240'))
        self.blok = ps('b', FB, 7.6, 9.4, colors.white)
        self.tygodnie = []
        self.n_tyg = 4
        self.pad = max(1.5, 4 * s)          # odstęp w komórkach tabeli
        self.przerwa = max(3.0, 9 * s)      # odstęp między blokami


def _elementy_dnia(d, W, linki, S, wys_wspolne=None):
    """Buduje flowables jednego dnia. Zwraca (elementy, zmierzone wysokości wierszy).

    wys_wspolne pozwala narzucić wysokość wiersza wspólną dla całego dokumentu,
    żeby siatka była identyczna na wszystkich stronach.
    """
    el = []

    lewa = [Paragraph(d['nr'], S.dzien)]
    prawa = [Paragraph(S.zawodnik, S.kto)] if S.zawodnik else []
    if S.okres_txt:
        prawa.append(Paragraph(S.okres_txt, S.okres))
    nag = Table([[lewa, prawa or '']], colWidths=[W * .62, W * .38])
    nag.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'BOTTOM'),
        ('LINEBELOW', (0, 0), (-1, -1), 1.6, ZIELEN),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5 * S.s),
        ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0)]))
    el += [nag, Spacer(1, 6 * S.s)]

    legenda = d.get('legenda') or []
    if d.get('wstep') or legenda:
        tresc = []
        if d.get('wstep'):
            tresc.append(Paragraph(d['wstep'], S.wstep))
        # Legenda w kolumnach — pionowa lista RPE zjadała trzecią część strony.
        for grupa in legenda:
            # wariant TABELA: siatka z kolorowanym tłem komórek
            # (skala RPE — gradient od czerwieni przy 10 do jasnego przy 1-4)
            spec = grupa.get('tabela')
            if spec:
                wt = spec['wiersze']
                bg = spec.get('bg') or []
                ncol = len(wt[0])
                par = ncol // 2
                szer = float(grupa.get('szer', 1.0))
                frac = spec.get('kolw')
                if frac:
                    colw = [W * szer * f for f in frac]
                    skala = 1.0
                else:
                    colw = [W * .045, W * .275] * par if ncol % 2 == 0 \
                        else [W / ncol] * ncol
                    skala = (W * szer - 18) / sum(colw)
                colw = [c * skala for c in colw]
                dane_t = [[Paragraph(str(c), S.lege) for c in row]
                          for row in wt]
                t = Table(dane_t, colWidths=colw)
                cmds = [('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                        ('TOPPADDING', (0, 0), (-1, -1), 2),
                        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
                        ('LEFTPADDING', (0, 0), (-1, -1), 5),
                        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
                        ('GRID', (0, 0), (-1, -1), 0.5, colors.white)]
                for sp in (spec.get('span') or []):
                    cmds.append(('SPAN', tuple(sp[0]), tuple(sp[1])))
                for r, rowbg in enumerate(bg):
                    for c, hx in enumerate(rowbg):
                        if hx:
                            cmds.append(('BACKGROUND', (c, r), (c, r),
                                         colors.HexColor(hx)))
                t.setStyle(TableStyle(cmds))
                lewo = [Paragraph(f'<b>{grupa["tytul"]}</b>', S.lege), t]
                obok = grupa.get('obok') or []
                if obok:
                    # tabelka RPE po lewej, wskazówki tuż obok po prawej;
                    # element może być tekstem, własną mini-tabelką albo
                    # LISTĄ mini-tabelek — wtedy stają w jednym rzędzie
                    # (movement prep i conditioning ramię w ramię)
                    szer_prawej = W * (1 - float(grupa.get('szer', .62))
                                       - .02)

                    def _mini(linia, szer_dost):
                        mt = linia['tabela']
                        mw = [szer_dost * f
                              for f in mt.get('kolw', [.22, .78])]
                        md = [[Paragraph(str(c), S.lege) for c in row]
                              for row in mt['wiersze']]
                        mtab = Table(md, colWidths=mw)
                        mc = [('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                              ('TOPPADDING', (0, 0), (-1, -1), 2),
                              ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
                              ('LEFTPADDING', (0, 0), (-1, -1), 5),
                              ('RIGHTPADDING', (0, 0), (-1, -1), 5),
                              ('GRID', (0, 0), (-1, -1), 0.5, colors.white)]
                        for r2, rb in enumerate(mt.get('bg') or []):
                            for c2, hx2 in enumerate(rb):
                                if hx2:
                                    mc.append(('BACKGROUND', (c2, r2),
                                               (c2, r2),
                                               colors.HexColor(hx2)))
                        mtab.setStyle(TableStyle(mc))
                        czesci = []
                        if linia.get('tytul'):
                            czesci.append(Paragraph(
                                f"<b>{linia['tytul']}</b>", S.lege))
                        czesci.append(mtab)
                        return czesci

                    prawo = []
                    for j, linia in enumerate(obok):
                        if j:
                            prawo.append(Spacer(1, 3 * S.s))
                        if isinstance(linia, (list, tuple)):
                            # rząd mini-tabelek: szerokości wg 'udzial'
                            ud = [float(x.get('udzial', 1 / len(linia)))
                                  for x in linia]
                            suma = sum(ud) or 1.0
                            kolw = [szer_prawej * (u / suma) - 4 for u in ud]
                            kom = [_mini(x, kolw[i])
                                   for i, x in enumerate(linia)]
                            rzad = Table([kom],
                                         colWidths=[c + 4 for c in kolw])
                            rzad.setStyle(TableStyle([
                                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                                ('LEFTPADDING', (0, 0), (-1, -1), 0),
                                ('RIGHTPADDING', (0, 0), (-2, -1), 4),
                                ('RIGHTPADDING', (-1, 0), (-1, -1), 0),
                                ('TOPPADDING', (0, 0), (-1, -1), 0),
                                ('BOTTOMPADDING', (0, 0), (-1, -1), 0)]))
                            prawo.append(rzad)
                            continue
                        if isinstance(linia, dict):
                            prawo += _mini(linia, szer_prawej)
                            continue
                        prawo.append(Paragraph(linia, S.lege))
                    zew = Table([[lewo, prawo]],
                                colWidths=[W * float(grupa.get('szer', .62)),
                                           W * (1 - float(
                                               grupa.get('szer', .62))) - 8])
                    zew.setStyle(TableStyle([
                        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                        ('LEFTPADDING', (0, 0), (0, -1), 0),
                        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                        ('LEFTPADDING', (1, 0), (1, -1), 14),
                        ('TOPPADDING', (0, 0), (-1, -1), 0),
                        ('BOTTOMPADDING', (0, 0), (-1, -1), 0)]))
                    tresc += [Spacer(1, 3 * S.s), zew]
                else:
                    tresc += [Spacer(1, 3 * S.s)] + lewo
                continue
            poz = grupa.get('pozycje') or []
            if not poz:
                continue
            n = grupa.get('kolumny', 3)
            wierszy = -(-len(poz) // n)
            siatka = [[poz[k * wierszy + i] if k * wierszy + i < len(poz) else ''
                       for k in range(n)] for i in range(wierszy)]
            tab = Table([[Paragraph(c, S.lege) for c in r] for r in siatka],
                        colWidths=[(W - 16) / n] * n)
            tab.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('TOPPADDING', (0, 0), (-1, -1), 0),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
                ('LEFTPADDING', (0, 0), (0, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 6)]))
            tresc += [Spacer(1, 3 * S.s), Paragraph(f'<b>{grupa["tytul"]}</b>', S.lege), tab]
        ws = Table([[tresc]], colWidths=[W])
        ws.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), JASNY),
            ('LINEBEFORE', (0, 0), (0, -1), 2.6, ZIELEN),
            ('LEFTPADDING', (0, 0), (-1, -1), 8), ('RIGHTPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 5 * S.s),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5 * S.s)]))
        el += [ws, Spacer(1, 8 * S.s)]

    def wpisz(tekst, styl, szer):
        """Paragraf zmieszczony w jednej linii — długi tekst dostaje mniejszy
        stopień pisma zamiast zawijać się i podnosić wysokość CAŁEJ siatki."""
        tekst = tekst or ''
        czysty = re.sub(r'<[^>]+>', '', tekst)
        if not czysty:
            return Paragraph(tekst, styl)
        potrzeba = pdfmetrics.stringWidth(czysty, styl.fontName, styl.fontSize)
        dost = szer - 10
        if potrzeba <= dost:
            return Paragraph(tekst, styl)
        wsp = max(0.76, dost / potrzeba)
        maly = ParagraphStyle('x', parent=styl, fontSize=styl.fontSize * wsp,
                              leading=styl.leading * wsp)
        return Paragraph(tekst, maly)

    def film(cw, jawny=None):
        url = jawny if jawny is not None else linki.get(cw)
        if not url:
            return Paragraph('<font color="#CCCCCC">-</font>', S.srodek)
        return Paragraph(f'<link href="{url}"><u>FILM</u></link>', S.film)

    zwykle = [x for b in d['bloki'] if not b.get('prosty') for x in b['w']]
    kolumny_dnia = (any(x.get('tempo') for x in zwykle), any(x.get('rest') for x in zwykle))

    def zawartosc(b):
        """Wiersze bloku + ich typy ('hdr' / 'tresc' / 'sep') + szerokości kolumn."""
        wiersze = b['w']
        if b.get('prosty'):
            kol = [W * .30, W * .62, W * .08]
            dane = [[Paragraph('ĆWICZENIE', S.hdr_l), Paragraph('SERIE × POWTÓRZENIA', S.hdr_l),
                     Paragraph('FILM', S.hdr)]]
            typy = ['hdr']
            # odstęp między grupami także w prepie — Filip prosi o przerwę
            # między blokami rozgrzewki (2026-09-03); numeru tu nie drukujemy
            poprz = None
            for x in wiersze:
                g = re.match(r'\d+', (x.get('grupa') or ''))
                g = g.group() if g else None
                if poprz is not None and g != poprz:
                    dane.append(['', '', ''])
                    typy.append('sep')
                poprz = g
                dane.append([Paragraph(x['cw'], S.cw), Paragraph(x.get('uw', ''), S.uw),
                             film(x['cw'], x.get('link'))])
                typy.append('tresc')
            return dane, typy, kol, 2, None

        # Obecność kolumn TEMPO/REST liczona dla całego dnia, nie bloku —
        # inaczej tygodnie rozjeżdżają się między blokami na tej samej stronie.
        ma_tempo, ma_rest = kolumny_dnia
        szer_cw, szer_uw = (.15, .205) if ma_tempo else (.20, .18)
        kol = [W * .035, W * szer_cw, W * szer_uw]
        gl = [Paragraph('#', S.hdr), Paragraph('ĆWICZENIE', S.hdr_l), Paragraph('UWAGI', S.hdr_l)]
        i_tempo = None
        if ma_tempo:
            kol.append(W * .095)
            gl.append(Paragraph('TEMPO', S.hdr_l))
            i_tempo = len(kol) - 1
        reszta = 1 - sum(kol) / W - (.075 if ma_rest else 0) - .055
        n_t = max(1, int(getattr(S, 'n_tyg', 4)))
        for i in range(1, n_t + 1):
            kol.append(W * reszta / n_t)
            # plan jednotygodniowy: bez „WEEK 1" — sama rozpiska
            gl.append(Paragraph('SERIE × POWTÓRZENIA' if n_t == 1
                                else f'WEEK {i}', S.hdr))
        if ma_rest:
            kol.append(W * .075)
            gl.append(Paragraph('REST', S.hdr))
        kol.append(W * .055)
        gl.append(Paragraph('FILM', S.hdr))

        dane, typy = [gl], ['hdr']
        # Odstęp między grupami superserii: 1a/1b | 2a/2b | 3 — żeby było widać,
        # co z czym się łączy. Grupa = wiodąca cyfra numeru.
        # 'grupa' = klucz grupowania NIEZALEŻNY od drukowanego numeru —
        # w Plyo Filip nie chce widocznych 1a/1b (dublują się z Main),
        # ale odstęp między łączonymi ćwiczeniami ma zostać.
        grupy = [re.match(r'\d+', (x.get('grupa') or x.get('nr', '') or ''))
                 for x in wiersze]
        def _klucz(m):
            return m.group() if m else None
        for i, x in enumerate(wiersze):
            # przerwa przy KAŻDEJ zmianie grupy, także gdy numerowana para
            # zaczyna się po luźnych wierszach (pogosy → box jump + medball)
            if i and (grupy[i - 1] or grupy[i]) \
                    and _klucz(grupy[i - 1]) != _klucz(grupy[i]):
                dane.append([''] * len(kol))
                typy.append('sep')
            r = [Paragraph(x.get('nr', ''), S.nr), Paragraph(x['cw'], S.cw),
                 Paragraph(x.get('uw', ''), S.uw)]
            if ma_tempo:
                r.append(Paragraph(x.get('tempo', ''), S.uw))
            _tyg = list(x['tyg'])[:n_t] + [''] * max(0, n_t - len(x['tyg']))
            r += [Paragraph(t, S.srodek) for t in _tyg]
            if ma_rest:
                # sama liczba w REST to sekundy — dopisujemy jednostkę
                rest = (x.get('rest') or '').strip()
                if rest and re.fullmatch(r'[\d\s\-–]+', rest):
                    rest = f'{rest} sec'
                r.append(Paragraph(rest, S.rest))
            r.append(film(x['cw'], x.get('link')))
            dane.append(r)
            typy.append('tresc')
        return dane, typy, kol, len(kol) - 1, i_tempo

    def zloz(dane, typy, kol, wys=None, i_tempo=None):
        t = Table(dane, colWidths=kol,
                  rowHeights=[wys[y] for y in typy] if wys else None)
        sty = [('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
               ('BACKGROUND', (0, 0), (-1, 0), JASNY),
               ('LINEBELOW', (0, 0), (-1, 0), 1.1, ZIELEN_JASNA),
               ('TOPPADDING', (0, 0), (-1, -1), S.pad),
               ('BOTTOMPADDING', (0, 0), (-1, -1), S.pad),
               ('LEFTPADDING', (0, 0), (-1, -1), 5), ('RIGHTPADDING', (0, 0), (-1, -1), 5)]
        if i_tempo is not None:          # oddech między UWAGI a TEMPO
            sty.append(('LEFTPADDING', (i_tempo, 0), (i_tempo, -1), 14))
        parzysty = 0
        for i, y in enumerate(typy):
            if y == 'sep':
                sty.append(('LINEABOVE', (0, i), (-1, i), 0.8, ZIELEN_JASNA))
                sty.append(('TOPPADDING', (0, i), (-1, i), 0))
                sty.append(('BOTTOMPADDING', (0, i), (-1, i), 0))
            elif y == 'tresc':
                if i < len(typy) - 1 and typy[i + 1] == 'tresc':
                    sty.append(('LINEBELOW', (0, i), (-1, i), 0.4, LINIA))
                if parzysty % 2:
                    sty.append(('BACKGROUND', (0, i), (-1, i), PASEK))
                parzysty += 1
        t.setStyle(TableStyle(sty))
        return t

    # Dwa przebiegi: najpierw pomiar naturalnych wysokości, potem złożenie
    # z jedną wysokością wiersza na cały dzień — inaczej wiersze z dłuższą
    # nazwą ćwiczenia są wyższe i siatka się rozjeżdża między blokami.
    bloki = [zawartosc(b) for b in d['bloki']]
    zmierzone = {'hdr': 0.0, 'tresc': 0.0, 'sep': 7.0 * S.s}
    wys_blok = []
    for dane, typy, kol, _, i_tempo in bloki:
        proba = zloz(dane, typy, kol, i_tempo=i_tempo)
        proba.wrap(W, 10000)
        lok = {'hdr': 0.0, 'tresc': 0.0, 'sep': 7.0 * S.s}
        for y, h in zip(typy, proba._rowHeights):
            if y != 'sep':
                lok[y] = max(lok[y], h)
                zmierzone[y] = max(zmierzone[y], h)
        wys_blok.append(lok)
    # Wyrównujemy wysokość wiersza w obrębie bloku, nie całego dokumentu —
    # inaczej jedna trzylinijkowa komórka podnosi każdy wiersz w planie
    # i cała rozpiska musi zjechać do nieczytelnego stopnia pisma.
    naglowek = (wys_wspolne or zmierzone)['hdr']
    for lok in wys_blok:
        lok['hdr'] = naglowek

    for b, (dane, typy, kol, _, i_tempo), wys in zip(d['bloki'], bloki, wys_blok):
        tyt = Table([[Paragraph(b['t'], S.blok)]], colWidths=[W])
        tyt.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), CZERN), ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), S.pad), ('BOTTOMPADDING', (0, 0), (-1, -1), S.pad)]))
        el += [tyt, zloz(dane, typy, kol, wys, i_tempo), Spacer(1, S.przerwa)]

    return el[:-1], zmierzone  # bez ostatniego odstępu


def _wysokosc(elementy, W, H):
    return sum(e.wrap(W, H)[1] for e in elementy)


def buduj(dni, linki, wyjscie, zawodnik='', okres='', start=None,
          n_tygodni=4):
    doc = BaseDocTemplate(wyjscie, pagesize=landscape(A4),
                          leftMargin=11 * mm, rightMargin=11 * mm,
                          topMargin=6 * mm, bottomMargin=6 * mm,
                          title=f'{zawodnik} — {okres}'.strip(' —'), author='Filip Dąbrowski')
    doc.addPageTemplates([PageTemplate(id='p', frames=[
        Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id='n',
              leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)])])
    W, H = doc.width, doc.height

    # start bloku → zakresy dat czterech tygodni (Week 1 = start … start+6 dni)
    tygodnie = []
    if start:
        d0 = date(*map(int, start.split('-')))
        for i in range(max(1, int(n_tygodni or 4))):
            a, b = d0 + timedelta(days=7 * i), d0 + timedelta(days=7 * i + 6)
            tygodnie.append(f'{a.day:02d}.{a.month:02d}–{b.day:02d}.{b.month:02d}')

    def styl(s):
        S = Style(s)
        S.zawodnik, S.okres_txt, S.tygodnie = zawodnik, okres, tygodnie
        S.n_tyg = max(1, int(n_tygodni or 4))
        return S

    # Jedna skala dla całego dokumentu — największa, przy której KAŻDY dzień
    # mieści się na stronie. Różne skale na kolejnych stronach same w sobie
    # byłyby rozjazdem: inny stopień pisma i inna wysokość wiersza.
    SKALE = [1.0, .97, .94, .91, .88, .85, .82, .79, .76, .73, .70, .66, .62, .58, .54]
    def warstwy_dla(s):
        S = styl(s)
        pomiar = [_elementy_dnia(d, W, linki, S)[1] for d in dni]
        wspolne = {k: max(p[k] for p in pomiar) for k in pomiar[0]}
        return [_elementy_dnia(d, W, linki, S, wspolne)[0] for d in dni]

    uzyta, warstwy = SKALE[-1], None
    for s in SKALE:
        proba = warstwy_dla(s)
        if all(_wysokosc(el, W, H) <= H for el in proba):
            uzyta, warstwy = s, proba
            break
    if warstwy is None:
        warstwy = warstwy_dla(uzyta)

    flow = []
    for indeks, el in enumerate(warstwy):
        if indeks:
            flow.append(PageBreak())
        flow += el

    doc.build(flow)
    return wyjscie, [(d['nr'], uzyta) for d in dni]


if __name__ == '__main__':
    zakres = {}
    exec(open(sys.argv[1], encoding='utf-8').read(), zakres)
    plik, rap = buduj(zakres['DNI'], zakres['L'], sys.argv[2],
                      sys.argv[3] if len(sys.argv) > 3 else '',
                      sys.argv[4] if len(sys.argv) > 4 else '',
                      sys.argv[5] if len(sys.argv) > 5 else None)
    print('OK →', plik)
    for nazwa, s in rap:
        print(f'   {nazwa}: skala {s:.0%}')
