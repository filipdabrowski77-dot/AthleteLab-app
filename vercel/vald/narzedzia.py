"""Narzędzia (TOOLS) — tabele i wykresy rysowane w apce zamiast screenów
(Filip 2026-10-16: „przerób te screeny na nasze czarty, przejrzyste, z kolorami
tkanek, na całą stronę”).

Liczby przepisane 1:1 ze screenów od Filipa (źródło podane pod każdą tabelą):
- Tissue Healing Timelines (grafika TPF),
- Isometric Loading Prescription Table (we współpracy z Mario Artukovicem),
- Effort Levels + Prilepin's Chart (%1RM).
Nic z pamięci — zmiana liczby = zmiana tutaj, z nowego źródła.

html(id) zwraca fragment HTML z własnym <style> (klasy z prefiksem .nz, żeby
nic nie wyciekło na resztę strony); szerokie tabele przewijają się wewnątrz
ramki, strona nie przewija się w bok.
"""
from __future__ import annotations

from html import escape

NARZEDZIA = [
    {"id": "nz-gojenie", "tytul": "Tissue healing timelines"},
    {"id": "nz-izometria", "tytul": "Isometric loading prescription table"},
    {"id": "nz-1rm", "tytul": "%1RM · poziomy wysiłku · Prilepin"},
]

_CSS = """<style>
.nz{font-family:Archivo,system-ui,-apple-system,sans-serif;color:#1c1b18;
  --ink:#1c1b18;--dim:#6f6b61;--mute:#8a867c;--line:#e6e3db;--hair:#f0eee8}
.nz *{box-sizing:border-box}
.nz h2{font-family:'Archivo Black',Archivo,sans-serif;font-size:clamp(18px,2vw,24px);
  letter-spacing:-.02em;line-height:1.1;margin:0 0 2px}
.nz .pod{font-size:13px;color:var(--dim);margin:0 0 10px}
.nz .ramka{overflow-x:auto;-webkit-overflow-scrolling:touch;border:1px solid var(--line);
  border-radius:14px;background:#fff}
.nz .zrodlo{font-size:11.5px;color:var(--mute);margin:8px 0 0}
.nz table{border-collapse:separate;border-spacing:0;width:100%}
.nz th,.nz td{font-variant-numeric:tabular-nums}
/* gojenie tkanek */
.nz .gt{min-width:860px}
.nz .gt-wiersz{display:grid;grid-template-columns:170px repeat(9,minmax(0,1fr));border-bottom:1px solid var(--hair)}
.nz .gt-wiersz:last-child{border-bottom:0}
.nz .gt-glowa{background:#faf9f6}
.nz .gt-glowa div{padding:7px 4px;font-size:10.5px;font-weight:700;letter-spacing:.04em;
  text-transform:uppercase;color:var(--dim);text-align:center;border-left:1px solid var(--hair)}
.nz .gt-glowa div:first-child{text-align:left;padding-left:16px;border-left:0}
.nz .gt-nazwa{display:flex;align-items:center;gap:8px;padding:3px 10px 3px 14px;
  font-size:13px;font-weight:700;position:sticky;left:0;z-index:2;background:#fff;
  box-shadow:1px 0 0 var(--hair)}
.nz .gt-glowa div:first-child{position:sticky;left:0;z-index:2;background:#faf9f6;box-shadow:1px 0 0 var(--hair)}
/* telefon: węższa kolumna nazw (przyklejona przy przewijaniu osi) */
@media (max-width:600px){
  .nz .gt{min-width:780px}
  .nz .gt-wiersz{grid-template-columns:104px repeat(9,minmax(0,1fr))}
  .nz .gt-nazwa{font-size:12.5px;padding:8px 8px 8px 10px;gap:6px}
  .nz .gt-glowa div:first-child{padding-left:10px}
}
.nz .gt-kropka{width:9px;height:9px;border-radius:999px;flex:none}
.nz .gt-tor{grid-column:2/-1;display:grid;grid-template-columns:repeat(9,minmax(0,1fr));
  row-gap:2px;padding:3px 0;position:relative;
  background-image:repeating-linear-gradient(90deg,transparent 0,transparent calc(100%/9 - 1px),var(--hair) calc(100%/9 - 1px),var(--hair) calc(100%/9))}
.nz .gt-pas{height:18px;margin:0 3px;border-radius:5px;display:flex;align-items:center;
  padding:0 7px;font-size:11.5px;font-weight:600;white-space:nowrap;overflow:visible;
  border-left:3px solid var(--k);background:color-mix(in srgb,var(--k) var(--s),#fff)}
.nz .gt-pas b{font-weight:800;margin-right:5px}
.nz .czynniki{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:8px;margin-top:10px}
.nz .czynnik{border:1px solid var(--line);border-radius:10px;padding:7px 10px;background:#fff}
.nz .czynnik b{display:block;font-size:12.5px;margin-bottom:2px}
.nz .czynnik span{display:block;font-size:12px;line-height:1.3;color:#3c3a33}
/* izometria */
.nz .iz{min-width:900px}
.nz .iz th,.nz .iz td{padding:12px 12px;border-bottom:1px solid var(--hair);border-left:1px solid var(--hair);
  font-size:13.5px;text-align:center;vertical-align:middle}
.nz .iz thead th{font-size:13px;font-weight:800;color:#fff!important;background:var(--k);border-left-color:rgba(255,255,255,.25)}
.nz .iz thead th:first-child,.nz .iz tbody th{background:#f2f1ec!important;color:#1c1b18!important;
  font-size:12px;font-weight:800;letter-spacing:.06em;text-transform:uppercase;text-align:left;
  border-left:0;width:120px}
.nz .iz td.ad{font-size:12.5px;line-height:1.4;text-align:left;vertical-align:top;color:#3c3a33}
.nz .iz tbody td{background:color-mix(in srgb,var(--k) 7%,#fff)}
.nz .iz .pasy td{font-weight:700;font-size:13px;background:color-mix(in srgb,var(--k) 18%,#fff);color:var(--ink)}
.nz .iz .pasy th{background:#fff;color:var(--mute)}
.nz .strzalka{display:flex;align-items:center;gap:12px;margin:16px 4px 0;font-size:14px;font-weight:800}
.nz .strzalka i{flex:1;height:6px;border-radius:999px;background:linear-gradient(90deg,#3f9a50,#3f7fd8,#e08a2e)}
/* %1RM */
.nz .rm-uklad{display:grid;grid-template-columns:minmax(0,1.6fr) minmax(0,1fr);gap:16px;align-items:start}
@media (max-width:1100px){.nz .rm-uklad{grid-template-columns:minmax(0,1fr)}}
.nz .rm{min-width:640px}
.nz .rm th,.nz .rm td{padding:2px 6px;border-bottom:1px solid var(--hair);font-size:12.5px;line-height:1.35;text-align:center}
.nz .rm td{white-space:nowrap}
.nz .rm thead th{font-size:10.5px;font-weight:700;color:var(--dim);background:#faf9f6;line-height:1.2;vertical-align:bottom;padding:4px 5px}
.nz .rm thead th small{display:block;font-weight:500;font-size:9.5px;color:var(--mute)}
.nz .rm thead tr:first-child th{font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:var(--ink);background:#f2f1ec}
.nz .rm thead tr:first-child th.pril,.nz .rm td.pril{background:#fdf6e3}
.nz .rm td.proc{font-weight:800}
.nz .rm td.lvl{font-weight:800;font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:#fff;
  background:var(--k);text-align:left;padding-left:10px;width:72px}
.nz .rm td.ef{font-weight:600;background:color-mix(in srgb,#3f7fd8 var(--s),#fff)}
.nz .rm tr.gr td{border-top:2px solid #fff}
.nz .rev{min-width:380px}
.nz .rev td.hm{font-weight:600;background:color-mix(in srgb,#1c1b18 var(--s),#fff);color:var(--c)}
</style>"""

# ── Tissue Healing Timelines ────────────────────────────────────────────────
# kolumny osi: indeksy 0..8 (od 1–2 tygodni do „może się nie wygoić”)
_OS = ["1–2 tyg.", "3–4 tyg.", "5–7 tyg.", "2–3 mies.", "4–6 mies.", "7–9 mies.",
       "10–12 mies.", "1–2 lata", "może się nie wygoić"]
# (tkanka, kolor, [(etykieta, czas, od, do)]) — czas i etykiety ze screena TPF;
# od/do = kolumny osi, w które wpada podany zakres
_TKANKI = [
    ("Mięsień", "#d9534f", [("stopień 1", "1–4 tyg.", 0, 1), ("stopień 2", "2–4 mies.", 3, 4),
                            ("stopień 3", "6–9+ mies.", 4, 5)]),
    ("Więzadło", "#e8873a", [("stopień 1", "2–8 tyg.", 0, 3), ("stopień 2", "2–6 mies.", 3, 4),
                             ("stopień 3", "6–12 mies.", 4, 6), ("przeszczep (ACL)", "12–24+ mies.", 6, 7)]),
    ("Ścięgno", "#d4a72c", [("ostre", "2–6 tyg.", 0, 2), ("przewlekłe", "3–9 mies.", 3, 5),
                            ("zerwanie / naprawa", "4–12+ mies.", 4, 6)]),
    ("Kość / złamanie", "#8c6d4f", [("", "5–12 tyg.", 2, 3)]),
    ("Skóra", "#d9729b", [("", "1 tydz. – 6+ mies.", 0, 4)]),
    ("Chrząstka stawowa", "#7a5cc4", [("", "9–24 mies.+ lub może się nie wygoić", 5, 8)]),
    ("Nerw obwodowy", "#3f7fd8", [("mniejszy", "4–5 mies.", 4, 4), ("większy", "6–12 mies.", 4, 6)]),
    ("Dysk", "#2a9d8f", [("", "3–6+ mies.", 3, 4)]),
    ("Łąkotka / obrąbek", "#4c9a4c", [("", "6–12+ mies.", 4, 6)]),
    ("Uraz mózgu", "#6b7280", [("łagodny TBI", "3–4 mies.", 3, 4),
                               ("ciężki (udar / OUN)", "6–24+ mies.", 4, 7)]),
]
_CZYNNIKI = [
    ("Ciężkość urazu", "Im poważniejszy uraz, tym dłużej się goi."),
    ("Nawodnienie", "Odwodnione tkanki goją się wolniej i łatwiej je uszkodzić."),
    ("Odżywianie", "W czasie gojenia rośnie zapotrzebowanie na białko."),
    ("Sen", "Kluczowy dla naprawy tkanek i kontroli stanu zapalnego."),
    ("Rehabilitacja", "Odpowiednie obciążanie i ćwiczenia wspierają gojenie, gdy to właściwe."),
]


def _gojenie() -> str:
    glowa = "".join(f"<div>{escape(o)}</div>" for o in ["Tkanka", *_OS])
    wiersze = []
    for nazwa, kolor, etapy in _TKANKI:
        n = len(etapy)
        pasy = []
        for i, (et, czas, od, do) in enumerate(etapy):
            nasycenie = 18 + (34 * i // max(n - 1, 1)) if n > 1 else 26   # kolejny etap = mocniejszy kolor
            opis = (f"<b>{escape(et)}</b>" if et else "") + escape(czas)
            pasy.append(f'<div class="gt-pas" style="grid-column:{od + 1}/{do + 2};grid-row:{i + 1};'
                        f'--k:{kolor};--s:{nasycenie}%">{opis}</div>')
        wiersze.append(
            f'<div class="gt-wiersz"><div class="gt-nazwa"><span class="gt-kropka" style="background:{kolor}"></span>'
            f'{escape(nazwa)}</div><div class="gt-tor">{"".join(pasy)}</div></div>')
    czynniki = "".join(f'<div class="czynnik"><b>{escape(t)}</b><span>{escape(o)}</span></div>' for t, o in _CZYNNIKI)
    return (f'<div class="nz"><h2>Tissue healing timelines</h2>'
            f'<p class="pod">Orientacyjny czas gojenia tkanek — każdy etap w osobnej linii.</p>'
            f'<div class="ramka"><div class="gt"><div class="gt-wiersz gt-glowa">{glowa}</div>{"".join(wiersze)}</div></div>'
            f'<div class="czynniki">{czynniki}</div>'
            f'<p class="zrodlo">Źródło: grafika „Tissue Healing Timelines” (TPF) ze screena od Filipa — czasy przepisane 1:1, '
            f'paski ustawione w kolumnach osi według podanych zakresów.</p></div>')


# ── Isometric Loading Prescription Table ────────────────────────────────────
_IZ_METODY = ["Long duration holds", "Light yielding", "Moderate yielding", "Heavy yielding",
              "Maximal yielding / submax overcoming", "Maximal overcoming"]
_IZ_KOLORY = ["#3f9a50", "#2f8f7a", "#3f7fd8", "#5b5fc7", "#b8752a", "#e08a2e"]
_IZ_WIERSZE = [
    ("Load", ["Bodyweight", "30–60% 1RM", "60–80% 1RM, 60% MVIC", "80–100% 1RM, 60–70% MVIC",
              "100–110% 1RM, 70–80% MVIC", "110–130% 1RM, 80–100% MVIC"]),
    ("Rep TUT", ["60 s", "30–60 s, 3–5 s", "30–60 s, 3–5 s", "10–30 s, 2–10 s", "3–10 s",
                 "0,5–3 s, explode vs ramp"]),
    ("Reps", ["1", "1, 3–5", "1, 3–5", "1, 1–5", "1–5", "2–5"]),
    ("Sets", ["1–5", "3–5", "3–5", "3–5", "2–4", "2–3"]),
    ("Adaptation", ["Work capacity, technical competency, motor control",
                    "General strength development, introduction to loaded isometrics",
                    "General strength development, introduction to heavy isometrics",
                    "Tendon thickness, tendon stiffness, analgesia, muscle force, muscle hypertrophy "
                    "at long muscle lengths, muscle architecture",
                    "Tendon stiffness, RFD, muscle force, peak force",
                    "Tendon stiffness, RFD (explode), muscle force, peak force (ramp)"]),
]
_IZ_PASY = [("Low training age / youth athletes — introductory isometrics", 2, "#3f9a50"),
            ("Muscle morphology / tendon", 2, "#3f7fd8"),
            ("Tendon morphology / neural", 2, "#e08a2e")]


def _izometria() -> str:
    glowa = "<th>Iso method</th>" + "".join(
        f'<th style="--k:{k}">{escape(m)}</th>' for m, k in zip(_IZ_METODY, _IZ_KOLORY))
    wiersze = []
    for nazwa, wartosci in _IZ_WIERSZE:
        kl = ' class="ad"' if nazwa == "Adaptation" else ""
        wiersze.append(f"<tr><th>{escape(nazwa)}</th>" + "".join(
            f'<td{kl} style="--k:{k}">{escape(v)}</td>' for v, k in zip(wartosci, _IZ_KOLORY)) + "</tr>")
    pasy = '<tr class="pasy"><th></th>' + "".join(
        f'<td colspan="{n}" style="--k:{k}">{escape(t)}</td>' for t, n, k in _IZ_PASY) + "</tr>"
    return (f'<div class="nz"><h2>Isometric loading prescription table</h2>'
            f'<p class="pod">Od rehabilitacji do performance — dobór obciążenia, czasu napięcia, powtórzeń i serii.</p>'
            f'<div class="ramka"><table class="iz"><thead><tr>{glowa}</tr></thead>'
            f'<tbody>{"".join(wiersze)}{pasy}</tbody></table></div>'
            f'<div class="strzalka"><span>Rehabilitation</span><i></i><span>Performance</span></div>'
            f'<p class="zrodlo">Źródło: „Isometric Loading Prescription Table” (we współpracy z Mario Artukovicem, '
            f'@martukovic19) ze screena od Filipa, przepisana 1:1.</p></div>')


# ── %1RM · Effort levels · Prilepin ─────────────────────────────────────────
# (poziom, kolor, [(%1RM, ME, NME, HE, MHE)], (powt./seria, optymalnie, zakres))
_RM = [
    ("Heavy+", "#b23b33", [(100, 1, None, None, None), (95, 2, 1, None, None), (92, 3, 2, None, None)], ("1–2", "7", "4–10")),
    ("Heavy", "#d9773a", [(89, 4, 3, 1, None), (86, 5, 4, 2, None), (83, 6, 5, 3, 1), (81, 7, 6, 4, 2)], ("2–4", "15", "10–20")),
    ("Medium", "#c9a227", [(79, 8, 7, 5, 3), (77, 9, 8, 6, 4), (75, 10, 9, 7, 5), (73, 11, 10, 8, 6),
                           (71, 12, 11, 9, 7)], ("3–6", "18", "12–24")),
    ("Light", "#4c9a4c", [(70, 13, 12, 10, 8), (68, 14, 13, 11, 9), (67, 15, 14, 12, 10), (65, 16, 15, 13, 11),
                          (64, 17, 16, 14, 12), (63, 18, 17, 15, 13), (62, 19, 18, 16, 14),
                          (61, 20, 19, 17, 15)], ("3–6", "24", "18–30")),
]
# odwrotnie: powtórzenia w serii → %1RM dla ME / NME / HE / MHE (prawa tabela ze screena)
_REV = [(1, 100, 95, 89, 83), (2, 95, 92, 86, 81), (3, 92, 89, 83, 79), (4, 89, 86, 81, 77),
        (5, 86, 83, 79, 75), (6, 83, 81, 77, 73), (7, 81, 79, 75, 71), (8, 79, 77, 73, 70),
        (9, 77, 75, 71, 68), (10, 75, 73, 70, 67), (11, 73, 71, 68, 65), (12, 71, 70, 67, 64),
        (13, 70, 68, 65, 63), (14, 68, 67, 64, 62), (15, 67, 65, 63, 61), (16, 65, 64, 62, None),
        (17, 64, 63, 61, None), (18, 63, 62, None, None), (19, 62, 61, None, None), (20, 61, None, None, None)]
_EF = [("Max effort", "ME", "do upadku"), ("Near max", "NME", "1 powt. w zapasie"),
       ("Hard", "HE", "3 powt. w zapasie"), ("Medium hard", "MHE", "5 powt. w zapasie")]


def _1rm() -> str:
    ef_glowa = "".join(f"<th>{escape(n)} ({s})<small>{escape(o)}</small></th>" for n, s, o in _EF)
    wiersze = []
    for poziom, kolor, rzedy, (pps, opt, zakres) in _RM:
        for j, (proc, *ef) in enumerate(rzedy):
            komorki = "".join(
                f'<td class="ef" style="--s:{8 + 6 * (3 - i)}%">{v}</td>' if v is not None else '<td></td>'
                for i, v in enumerate(ef))
            lvl = (f'<td class="lvl" rowspan="{len(rzedy)}" style="--k:{kolor}">{escape(poziom)}</td>' if j == 0 else "")
            wiersze.append(f'<tr class="{"gr" if j == 0 else ""}">{lvl}<td class="proc">{proc}%</td>{komorki}'
                           f'<td class="pril">{pps}</td><td class="pril">{opt}</td><td class="pril">{zakres}</td></tr>')
    rev = []
    for powt, *procs in _REV:
        kom = []
        for p in procs:
            if p is None:
                kom.append("<td></td>")
                continue
            s = max(4, min(70, (p - 58) * 1.6))           # cieniowanie: im ciężej, tym ciemniej
            kom.append(f'<td class="hm" style="--s:{s:.0f}%;--c:{"#fff" if s > 45 else "#1c1b18"}">{p}%</td>')
        rev.append(f'<tr><td class="proc">{powt}</td>{"".join(kom)}</tr>')
    rev_glowa = "".join(f"<th>{s}<small>{escape(o)}</small></th>" for _, s, o in _EF)
    return (f'<div class="nz"><h2>%1RM · poziomy wysiłku · Prilepin</h2>'
            f'<p class="pod">Ile powtórzeń przy danym %1RM na każdym poziomie wysiłku i ile powtórzeń w serii daje dany %1RM.</p>'
            f'<div class="rm-uklad">'
            f'<div class="ramka"><table class="rm"><thead>'
            f'<tr><th colspan="2">Intensywność</th><th colspan="4">Effort levels — powtórzenia</th>'
            f'<th class="pril" colspan="3">Prilepin\'s chart</th></tr>'
            f'<tr><th>Poziom</th><th>%1RM</th>{ef_glowa}<th>Powt. / seria</th><th>Optymalnie</th><th>Zakres</th></tr>'
            f'</thead><tbody>{"".join(wiersze)}</tbody></table></div>'
            f'<div class="ramka"><table class="rm rev"><thead>'
            f'<tr><th colspan="5">Powtórzenia w serii → %1RM</th></tr>'
            f'<tr><th>Powt.</th>{rev_glowa}</tr></thead><tbody>{"".join(rev)}</tbody></table></div>'
            f'</div>'
            f'<p class="zrodlo">Źródło: tabela „Effort Levels” + „Prilepin\'s Chart” ze screena od Filipa, przepisana 1:1.</p></div>')


_HTML = {"nz-gojenie": _gojenie, "nz-izometria": _izometria, "nz-1rm": _1rm}


def jest(id_: str) -> bool:
    return id_ in _HTML


def css() -> str:
    """Sam <style> narzędzi — wstrzykiwany osobno: globalna reguła apki chowa
    kontener, w którym jest <style> (app.py, „Kontenery z samym <style>”)."""
    return _CSS


def tresc(id_: str) -> str:
    """Treść narzędzia bez <style> (do st.html) albo pusty napis."""
    f = _HTML.get(id_)
    return f() if f else ""


def html(id_: str) -> str:
    """Pełny fragment: styl + treść (np. do zapisu/podglądu poza apką)."""
    t = tresc(id_)
    return (_CSS + t) if t else ""
