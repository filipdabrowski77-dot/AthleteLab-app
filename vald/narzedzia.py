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
    {"id": "nz-vbt", "tytul": "Vitruve VBT chart"},
    {"id": "nz-strefy", "tytul": "Velocity Zones"},
    {"id": "nz-jordan", "tytul": "Matt Jordan · Loading parameters"},
    {"id": "nz-energia", "tytul": "Matt Jordan · Energy system"},
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
.nz .rm thead th small{display:block;font-weight:700;font-size:10px;color:#3c3a33!important}
.nz .rm thead tr:first-child th{font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:var(--ink);background:#f2f1ec}
.nz .rm thead tr:first-child th.pril,.nz .rm td.pril{background:#fdf6e3}
.nz .rm td.proc{font-weight:800}
.nz .rm td.lvl{font-weight:800;font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:#fff;
  background:var(--k);text-align:left;padding-left:10px;width:72px}
.nz .rm td.ef{font-weight:600;background:color-mix(in srgb,#3f7fd8 var(--s),#fff)}
.nz .rm tr.gr td{border-top:2px solid #fff}
.nz .rev{min-width:380px}
.nz .rev td.hm{font-weight:600;background:color-mix(in srgb,#1c1b18 var(--s),#fff);color:var(--c)}
/* VBT (Vitruve) i strefy prędkości — zwarte, nie na całą szerokość okna (Filip 2026-10-18) */
.nz .waska{max-width:1040px}
.nz .vbt{min-width:760px}
.nz .vbt th,.nz .vbt td{padding:3px 6px;font-size:13px;text-align:center;white-space:nowrap}
.nz .vbt thead th{font-size:12px;font-weight:800;color:#fff!important;background:#3f3d8f;border-left:1px solid rgba(255,255,255,.18)}
.nz .vbt thead th.rm1{background:#f3d77a;color:#1c1b18!important}
.nz .vbt thead th:first-child{background:#f2f1ec;color:var(--dim)!important;text-align:left;font-size:10.5px;
  letter-spacing:.06em;text-transform:uppercase;position:sticky;left:0;z-index:2}
.nz .vbt th.cw{text-align:left;font-size:13px;font-weight:800;background:#fff;position:sticky;left:0;z-index:2;
  box-shadow:1px 0 0 var(--hair);border-bottom:1px solid var(--line);width:128px}
.nz .vbt td.zr{font-size:10.5px;color:var(--mute);text-align:center;padding:4px 6px 0;white-space:normal}
.nz .vbt td.v{font-weight:700;background:color-mix(in srgb,#3f3d8f 7%,#fff);border-bottom:1px solid var(--line);
  border-left:1px dashed #d6d4e8}
.nz .vbt td.v.rm1{background:#fbf1cf}
.nz .vbt td.v.brak{color:#b8b4aa;font-weight:500}
@media (max-width:600px){.nz .vbt th.cw{width:96px;font-size:12px}}
.nz .vz{min-width:720px;padding:26px 30px 14px}
.nz .vz-os,.nz .vz-pr{position:relative;height:20px}
.nz .vz-os span{position:absolute;transform:translateX(-50%);font-size:12px;font-weight:800;white-space:nowrap}
.nz .vz-os b{position:absolute;left:0;top:-16px;font-size:10.5px;letter-spacing:.06em;color:var(--dim)}
.nz .vz-pas{position:relative;height:84px;border-radius:10px;margin:4px 0 6px;
  background:linear-gradient(90deg,#2fbf4a 0%,#5aa53c 28%,#7f8d3a 48%,#b4613b 70%,#d23b3b 100%)}
.nz .vz-seg{position:absolute;top:0;bottom:0;display:flex;align-items:center;justify-content:center;
  text-align:center;font-size:11.5px;font-weight:800;letter-spacing:.05em;text-transform:uppercase;
  color:rgba(28,27,24,.78);padding:0 6px;line-height:1.25}
.nz .vz-seg+.vz-seg{border-left:2px solid rgba(28,27,24,.55)}
.nz .vz-seg small{font-size:10.5px;font-weight:700;margin-right:12px;opacity:.75}
.nz .vz-pr span{position:absolute;transform:translateX(-50%);font-size:12.5px;font-weight:800;white-space:nowrap}
.nz .vz-pr b{position:absolute;left:0;font-size:10.5px;letter-spacing:.06em;color:var(--dim);top:2px}
/* Matt Jordan — kolory komórek jak na grafice (Filip 2026-10-18: „utrzymaj kolory tabelki”) */
.nz .mj-ramka{overflow-x:auto;-webkit-overflow-scrolling:touch;background:#000;border-radius:12px;padding:3px;max-width:1280px}
.nz .mj{min-width:1060px;border-collapse:separate;border-spacing:3px}
.nz .mj th,.nz .mj td{font-size:12.5px;font-weight:700;text-align:center;padding:4px 6px;color:#111!important;line-height:1.2}
.nz .mj thead th{background:#0b1a5e;color:#fff!important;font-size:12.5px;padding:7px 6px}
.nz .mj thead th.pion{writing-mode:vertical-rl;transform:rotate(180deg);font-size:11px;padding:6px 3px;width:26px}
.nz .mj td.boczny{position:relative;padding:0;width:30px}
.nz .mj td.boczny span{position:absolute;left:50%;transform:translate(-50%,-50%) rotate(180deg);writing-mode:vertical-rl;
  white-space:nowrap;font-size:12px;font-weight:800}
.nz .mj td.strefa span{writing-mode:vertical-rl;transform:rotate(180deg);font-size:12.5px;font-weight:800}
.nz .mj td.puste{background:#000}
.nz .mj td.adapt{padding:6px 0;width:34px;vertical-align:middle}
.nz .mj td.adapt span{display:inline-block;writing-mode:vertical-rl;white-space:nowrap;font-size:12px;font-weight:800}
.nz .mj td.adapt.neur{background:linear-gradient(180deg,#5cc3f7,#9db6dc)}
.nz .mj td.adapt.morf{background:linear-gradient(180deg,#b5b0d4,#e9a3ad)}
/* Energy system (JSCEP) — niebieska skala strefy 1→7 jak na grafice */
.nz .es-ramka{max-width:980px}
.nz .es{border-collapse:separate;border-spacing:6px 5px;min-width:600px}
.nz .es th{font-size:13px;font-weight:800;color:var(--ink);padding:2px 8px;text-align:center}
.nz .es td{font-size:14px;font-weight:800;text-align:center;padding:6px 10px;border:2.5px solid #111;border-radius:9px;
  color:#111!important;line-height:1.2}
.nz .es td small{display:block;font-size:12.5px;font-weight:700;color:#111!important}
.nz .mj td.tut{background:linear-gradient(180deg,#169fe8 0%,#13a9e4 38%,#14bf63 55%,#e0605a 80%,#f06b6b 100%)}
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
# podpis kolumny = RPE zamiast „powt. w zapasie” (Filip 2026-10-17: do upadku RPE 10,
# 1 w zapasie RPE 9, 3 w zapasie RPE 7, 5 w zapasie RPE 5) — w obu tabelach
_EF = [("Max effort", "ME", "RPE 10"), ("Near max", "NME", "RPE 9"),
       ("Hard", "HE", "RPE 7"), ("Medium hard", "MHE", "RPE 5")]


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
    # pełne nazwy także w prawej tabeli, nie same skróty (Filip 2026-10-17)
    rev_glowa = ef_glowa
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
            f'<p class="zrodlo">Źródło: tabela „Effort Levels” + „Prilepin\'s Chart” ze screena od Filipa, przepisana 1:1; podpisy RPE od Filipa.</p></div>')


# ── Vitruve VBT chart ───────────────────────────────────────────────────────
# Mean propulsive velocity (m/s) dla %1RM — przepisane 1:1 z grafiki Vitruve od
# Filipa (2026-10-18); badanie i protokół przy każdym ćwiczeniu jak na grafice
_VBT_KOL = ["1RM", "95%", "90%", "85%", "80%", "75%", "70%", "65%", "60%", "55%", "50%", "45%", "40%"]
_VBT = [
    ("Bench pull", "Sánchez Medina et al. (2014) — prone lying rowing on bench with Smith machine",
     [0.53, 0.59, 0.65, 0.72, 0.78, 0.85, 0.92, 0.99, 1.06, 1.13, 1.21, 1.28, 1.36]),
    ("Back squat", "Sánchez Medina et al. (2014) — deep squat with Smith machine and pauses",
     [0.32, 0.42, 0.51, 0.59, 0.68, 0.76, 0.84, 0.92, 1.00, 1.07, 1.14, 1.21, 1.28]),
    ("Pull up", "Sánchez Moreno et al. (2017) — prone pull up",
     [0.22, 0.31, 0.39, 0.50, 0.57, 0.65, 0.74, 0.83, 0.91, 1.00, 1.09, None, None]),
    ("Military press", "Muñoz et al. (2014) — military press behind the neck with Smith machine",
     [0.20, 0.27, 0.34, 0.41, 0.49, 0.55, 0.62, 0.69, 0.75, 0.81, 0.86, 0.92, 0.97]),
    ("Bench press", "González Badillo i Sánchez Medina (2010) — bench press with Smith machine and pauses",
     [0.18, 0.25, 0.32, 0.39, 0.47, 0.55, 0.62, 0.70, 0.78, 0.87, 0.95, 1.07, 1.13]),
    ("Deadlift", "Helms et al. (2017) — deadlift, expert powerlifters, 1RM = 237,3 kg",
     [0.14, 0.21, 0.29, 0.37, 0.46, None, None, None, None, None, None, None, None]),
    ("Hip thrust", "Hoyo, Núñez et al. (2017) — predicting loading intensity measuring velocity in barbell hip thrust",
     [0.24, None, 0.36, None, 0.48, None, 0.60, None, 0.72, None, None, None, None]),
]


def _vbt() -> str:
    glowa = "".join(f'<th class="{"rm1" if i == 0 else ""}">{k}</th>' for i, k in enumerate(_VBT_KOL))
    wiersze = []
    for nazwa, zrodlo, v in _VBT:
        kom = "".join(
            f'<td class="v{" rm1" if i == 0 else ""}">{x:.2f}</td>' if x is not None
            else f'<td class="v brak{" rm1" if i == 0 else ""}">–</td>' for i, x in enumerate(v))
        wiersze.append(f'<tr><th class="cw" rowspan="2">{escape(nazwa)}</th>'
                       f'<td class="zr" colspan="{len(_VBT_KOL)}">{escape(zrodlo)}</td></tr><tr>{kom}</tr>')
    return (f'<div class="nz"><h2>Vitruve VBT chart</h2>'
            f'<p class="pod">Mean propulsive velocity (m/s) dla każdego %1RM.</p>'
            f'<div class="ramka waska"><table class="vbt"><thead><tr><th>Ćwiczenie</th>{glowa}</tr></thead>'
            f'<tbody>{"".join(wiersze)}</tbody></table></div>'
            f'<p class="zrodlo">Źródło: grafika Vitruve „Mean propulsive velocity (m/s) for each % of 1RM” '
            f'ze screena od Filipa, przepisana 1:1; badanie przy każdym ćwiczeniu.</p></div>')


# ── Velocity Zones ──────────────────────────────────────────────────────────
# prędkości i nazwy stref 1:1 z grafiki od Filipa (2026-10-18); granice stref
# w %1RM NIE mają liczb na grafice — odczyt z położenia linii (szacunek)
_STREFY = [(0, 24, "Starting strength", ">1,3 m/s"), (24, 43, "Speed / strength", "1,3–1 m/s"),
           (43, 64, "Strength / speed", "1–0,75 m/s"), (64, 88, "Accelerative strength", "0,75–0,5 m/s"),
           (88, 100, "Absolute strength", "<0,5 m/s")]


def _strefy() -> str:
    os_ = "".join(f'<span style="left:{p}%">{p}{"%" if p else ""}</span>' for p in range(0, 101, 10))
    seg = "".join(
        f'<div class="vz-seg" style="left:{a}%;width:{b - a}%">'
        f'{"<small>None</small>" if a == 0 else ""}{escape(n)}</div>' for a, b, n, _ in _STREFY)
    pr = "".join(f'<span style="left:{(a + b) / 2}%">{escape(v)}</span>' for a, b, _, v in _STREFY)
    return (f'<div class="nz"><h2>Velocity Zones</h2>'
            f'<p class="pod">Strefy prędkości wzdłuż %1RM.</p>'
            f'<div class="ramka waska"><div class="vz">'
            f'<div class="vz-os"><b>% 1RM</b>{os_}</div>'
            f'<div class="vz-pas">{seg}</div>'
            f'<div class="vz-pr">{pr}</div></div></div>'
            f'<p class="zrodlo">Źródło: grafika „Velocity Zones” ze screena od Filipa — nazwy stref i zakresy prędkości '
            f'przepisane 1:1; granice stref w %1RM odczytane z położenia linii na grafice (bez liczb w źródle).</p></div>')


# ── Matt Jordan — Loading parameters ────────────────────────────────────────
# przepisane 1:1 z grafiki od Filipa (2026-10-18), kolory komórek jak na grafice;
# objaśnienia gwiazdek i jednostki przerwy na grafice nie widać
_MJ_B1, _MJ_B2, _MJ_G1, _MJ_G2, _MJ_R1, _MJ_R2, _MJ_O = ("#2bb0f2", "#6cc5fa", "#00c97b", "#8df3cd",
                                                        "#f89c9b", "#fbbdbd", "#fdc18d")
_MJ = [  # (metoda, cel, powt., intensywność, serie, tempo E:P:C, przerwa, kolor)
    ("Reactive Strength", "Stretch Shorten Cycle Ability", "6-10", "Body Mass", "3-6", "Short-Long", "1-2", _MJ_B1),
    ("Heavy Power", "Maximal Muscle Power", "3-6", "60-80%", "4-6", "Fast", "1.5-3", _MJ_B2),
    ("Heavy RFD", "Late Rate of Force Development", "3-6", "60-80%", "4-6", "Fast", "1.5-3", _MJ_B1),
    ("Light Power", "Maximal Muscle Power", "5-8", "20-60%", "5-8", "Fast", "1-2.5", _MJ_B2),
    ("Light RFD", "Initial Rate of Force Development", "5-8", "20-60%", "5-8", "Fast", "1-2.5", _MJ_B1),
    ("Eccentric Decel/Braking", "Eccentric Rate of Force Development", "3-5", "Body Mass-60%", "3-5", "X:1-3:1", "1-2.5", _MJ_B2),
    ("Maximal Strength", "Maximal Muscle Strength", "1-5", "90-100% (Very Heavy)", "3-5 ***", "2-4:1-3:X", "2.5-5", _MJ_G1),
    ("Maximal Eccentric Strength", "Maximal Eccentric Muscle Strength", "3-5", "90-110% (Very Heavy)", "3-5 ***", "2-10:0:A", "2.5-5", _MJ_G2),
    ("Max Rep Exhaustive", "Muscle Hypertrophy", "5-12", "70-85% (Heavy)", "3-4 ***", "2-4:1-3:1-3", "2-3", _MJ_R1),
    ("Max Set Exhaustive", "Muscle Hypertrophy", "5-12", "50-70% (Moderate)", "5-10 **", "1-3:1-2:1-3", "1-2", _MJ_R2),
    ("Assistant Strength", "Structural Balance", "8-15", "60-80% (Moderate)", "2-4", "1-3:1-3:1-3", "1-2", _MJ_R1),
    ("Slow Tempo Exhaustive", "Muscle Hypertrophy", "5-8", "60-80% (Moderate)", "3-5", "4-6:1-3:4-6", "1-3", _MJ_R2),
    ("Low Load Exhaustive", "Muscle Hypertrophy/Strength Endurance", "15-30", "30-60% (Light)", "2-4", "1-2:0:1", "2-3", _MJ_R1),
    ("Technical Development", "Movement Competency/Motor Control", "2-8", "Light", "3-10", "NA", "1-2", _MJ_O),
]
# strefy (wiersze od–do, 0-indeksowo) i etykiety TUT na pasku z grafiki
_MJ_STREFY = [(0, 5, "Zone 1", _MJ_B1), (6, 7, "Zone 3", _MJ_G1), (8, 12, "Zone 2", _MJ_R1)]
_MJ_TUT = [("< 10", 3 / 13), ("5-20", 7 / 13), ("20-40", 9 / 13), ("40-60", 11.5 / 13)]


def _jordan() -> str:
    glowa = ('<tr><th class="pion">TUT (s)</th><th class="pion">Strength zone</th><th>Strength Method</th>'
             '<th>Target Strength Ability</th><th>Rep</th><th>Intensity</th><th>Set Range<br>* Sets to</th>'
             '<th>Tempo<br>E:P:C</th><th>Interset Rest</th><th class="pion">Adaptation</th></tr>')
    tut = "".join(f'<span style="top:{y * 100:.1f}%">{escape(t)}</span>' for t, y in _MJ_TUT)
    wiersze = []
    for i, (met, cel, rep, inten, serie, tempo, rest, k) in enumerate(_MJ):
        lewe = ""
        if i == 0:
            lewe += f'<td class="boczny tut" rowspan="13">{tut}</td>'
        elif i == 13:
            lewe += '<td class="puste"></td>'
        st = next((z for z in _MJ_STREFY if z[0] == i), None)
        if st:
            lewe += (f'<td class="strefa" rowspan="{st[1] - st[0] + 1}" style="background:{st[3]}">'
                     f'<span>{st[2]}</span></td>')
        elif i == 13:
            lewe += '<td class="puste"></td>'
        komorki = "".join(f'<td style="background:{k}">{escape(x)}</td>' for x in (met, cel, rep, inten, serie, tempo, rest))
        # dwie komórki zamiast jednej z dwoma napisami — przy niskich wierszach napisy nachodziły
        prawe = ('<td class="adapt neur" rowspan="7"><span>Neural Adaptations</span></td>' if i == 0
                 else '<td class="adapt morf" rowspan="6"><span>Muscle Morphology Adaptation</span></td>' if i == 7
                 else '<td class="puste"></td>' if i == 13 else "")
        wiersze.append(f"<tr>{lewe}{komorki}{prawe}</tr>")
    return (f'<div class="nz"><h2>Matt Jordan · Loading parameters</h2>'
            f'<p class="pod">Metoda siłowa → cel, powtórzenia, intensywność, serie, tempo, przerwa.</p>'
            f'<div class="mj-ramka"><table class="mj"><thead>{glowa}</thead><tbody>{"".join(wiersze)}</tbody></table></div>'
            f'<p class="zrodlo">Źródło: tabela Matta Jordana ze screena od Filipa, przepisana 1:1 (kolory jak na grafice). '
            f'Objaśnienia gwiazdek (*, **, ***) i jednostki przerwy na grafice nie widać.</p></div>')


# ── Matt Jordan — JSCEP Energy System Table ────────────────────────────────
# przepisane 1:1 z grafiki od Filipa (2026-10-18), kolory stref jak na grafice
_ES = [("Zone 1", "Sub Lactate Threshold 1", "", "55-75", "0.8-1.5", "#bde3fd"),
       ("Zone 2", "Lactate Threshold 1", "(Aerobic Threshold - AeT)", "76-85", "1.6-2.9", "#9fd6fb"),
       ("Zone 3", "Lactate Threshold 2", "(Anaerobic Threshold - AnT)", "86-90", "3.0-4.0", "#74c6fa"),
       ("Zone 4", "Critical Power", "", "91-95", "4.1-6.0", "#33b5f8"),
       ("Zone 5", "Maximal Aerobic Power", "", "96-100", "6.1-10.0", "#0aa0ec"),
       ("Zone 6", "Lactate Capacity", "", "Max", "10.1-12.0", "#0688d0"),
       ("Zone 7", "Lactate Power", "", "Max", "> 12.0", "#0670aa")]


def _energia() -> str:
    wiersze = "".join(
        f'<tr><td style="background:{k}">{z}</td>'
        f'<td style="background:{k}">{escape(n)}{f"<small>{escape(d)}</small>" if d else ""}</td>'
        f'<td style="background:{k}">{hr}</td><td style="background:{k}">{escape(la)}</td></tr>'
        for z, n, d, hr, la, k in _ES)
    return (f'<div class="nz"><h2>Matt Jordan · Energy system</h2>'
            f'<p class="pod">JSCEP Energy System Table — strefy, tętno i mleczan.</p>'
            f'<div class="ramka es-ramka" style="border:0;background:transparent"><table class="es"><thead><tr>'
            f'<th>Zone</th><th>Energy System</th><th>Heart Rate (%)</th><th>Blood Lactate (mmol/L)</th>'
            f'</tr></thead><tbody>{wiersze}</tbody></table></div>'
            f'<p class="zrodlo">Źródło: „JSCEP Energy System Table” (@JordanStrength) ze screena od Filipa, przepisana 1:1. '
            f'Koncepcja wg: Seiler S, Tønnessen E. Intervals, Thresholds and Long Slow Distance: the Role of Intensity '
            f'and Duration in Endurance Training. Training [Internet]. 2009;13(13):32–53 (zapis jak na grafice).</p></div>')


_HTML = {"nz-gojenie": _gojenie, "nz-izometria": _izometria, "nz-1rm": _1rm,
         "nz-vbt": _vbt, "nz-strefy": _strefy, "nz-jordan": _jordan, "nz-energia": _energia}


def jest(id_: str) -> bool:
    return id_ in _HTML


def css() -> str:
    """Sam <style> narzędzi — wstrzykiwany osobno: globalna reguła apki chowa
    kontener, w którym jest <style> (app.py, „Kontenery z samym <style>”)."""
    return _CSS


def tresc(id_: str, naglowek: bool = True) -> str:
    """Treść narzędzia bez <style> (do st.html) albo pusty napis.
    naglowek=False: bez <h2> z nazwą — w oknie nazwa stoi w tytule okna."""
    f = _HTML.get(id_)
    if not f:
        return ""
    t = f()
    if not naglowek:
        tytul = next(n["tytul"] for n in NARZEDZIA if n["id"] == id_)
        t = t.replace(f"<h2>{escape(tytul)}</h2>", "", 1)
    return t


def html(id_: str) -> str:
    """Pełny fragment: styl + treść (np. do zapisu/podglądu poza apką)."""
    t = tresc(id_)
    return (_CSS + t) if t else ""
