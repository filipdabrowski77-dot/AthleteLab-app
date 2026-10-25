"""
Raport „Testy” w stylu PDF-ów zaakceptowanych przez Filipa (24.10.2026,
skill testy-pdf) — wspólne
rysowanie dla przycisku „Drukuj PDF” w Performance testing i dla kafelków
na stronie, żeby wydruk i ekran wyglądały tak samo.

Tylko rysowanie (HTML + inline SVG), bez logiki danych: wołający podaje
serie dzień → wartość (pandas Series z indeksem dat). Reguły stylu:
bez imienia na stronie i bez stopek, krzywa monotoniczna z miękkim
wypełnieniem, wartość przy punkcie, Δ % do poprzedniego testu (▲ zielony,
▼ czerwony, metryki bez kierunku szare), asymetria w słupkach — w górę
niebieski = lewa, w dół pomarańczowy = prawa, zielona strefa ±10 %,
wspólna skala dla wszystkich asymetrii.

PDF: Playwright/Chromium, jeśli jest (lokalnie). Na Streamlit Cloud go nie
ma — wtedy `render_pdf` zwraca None i apka drukuje ten sam HTML z przeglądarki.
"""
from __future__ import annotations

import html as _html
import secrets

import pandas as pd

L_COLOR, R_COLOR, ZONE_COLOR = "#3B6FB0", "#E08A2B", "#3BA776"   # jak vald/viz.py

RSI_MOD_DESC = ("Wskaźnik „atletyczności” skoku — im wyższy, tym lepiej. "
                "Bierze pod uwagę, jak wysoko i jak szybko skoczyłeś.")


# ── formatowanie ──────────────────────────────────────────────────────────────
def num(x: float, dec: int) -> str:
    return f"{x:.{dec}f}".replace(".", ",").replace("-", "−")


def pct(new: float, old: float) -> str:
    if not old:
        return "—"
    # (nowa − stara) / |stara|: przy ujemnych metrykach (CM Depth, Ecc. Peak
    # Velocity) znak zgodny z kafelkami apki (przegląd 2026-10-25)
    p = (new - old) / abs(old) * 100
    return ("+" if p >= 0 else "−") + num(abs(p), 1) + " %"


def dm(d) -> str:
    return pd.Timestamp(d).strftime("%d.%m")


def dmy(d) -> str:
    return pd.Timestamp(d).strftime("%d.%m.%Y")


def side(v: float, long: bool = False) -> str:
    if long:
        return "lewa" if v < 0 else "prawa"
    return "L" if v < 0 else "P"


def auto_dec(vals) -> int:
    """Miejsca po przecinku jak w PDF-ach: RSI 2, cm 1, ms 0."""
    m = max((abs(v) for v in vals), default=0)
    if m >= 100:
        return 0
    if m >= 5:
        return 1
    return 2


class _Ids:
    """Unikalne id gradientów na jedno wywołanie — kilka wstawek SVG w tym
    samym DOM (strona apki) nie może współdzielić `g1`."""

    def __init__(self) -> None:
        self.pre = "t" + secrets.token_hex(3)
        self.n = 0

    def __call__(self) -> str:
        self.n += 1
        return f"{self.pre}{self.n}"


# ── wykresy ───────────────────────────────────────────────────────────────────
def smooth_path(xs: list[float], ys: list[float]) -> str:
    """Krzywa monotoniczna (Fritsch-Carlson): nie wychodzi ponad/pod sąsiednie
    punkty, więc nie dorysowuje wartości, których nie było."""
    n = len(xs)
    if n < 3:
        return "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    hs = [xs[i + 1] - xs[i] for i in range(n - 1)]
    ds = [(ys[i + 1] - ys[i]) / hs[i] for i in range(n - 1)]

    def sgn(v: float) -> int:
        return int(v > 0) - int(v < 0)

    m = [0.0] * n
    for i in range(1, n - 1):
        pp = (ds[i - 1] * hs[i] + ds[i] * hs[i - 1]) / (hs[i - 1] + hs[i])
        m[i] = (sgn(ds[i - 1]) + sgn(ds[i])) * min(abs(ds[i - 1]), abs(ds[i]), 0.5 * abs(pp)) or 0.0
    m[0] = (3 * ds[0] - m[1]) / 2 if sgn(3 * ds[0] - m[1]) == sgn(ds[0]) else 0.0
    m[-1] = (3 * ds[-1] - m[-2]) / 2 if sgn(3 * ds[-1] - m[-2]) == sgn(ds[-1]) else 0.0
    out = [f"M{xs[0]:.1f},{ys[0]:.1f}"]
    for i in range(n - 1):
        dx = hs[i] / 3
        out.append(f"C{xs[i] + dx:.1f},{ys[i] + m[i] * dx:.1f} {xs[i + 1] - dx:.1f},"
                   f"{ys[i + 1] - m[i + 1] * dx:.1f} {xs[i + 1]:.1f},{ys[i + 1]:.1f}")
    return " ".join(out)


def label_pos(vals: list[float], i: int, x: float, y: float) -> tuple[float, float]:
    """Etykieta po stronie, której nie zajmuje linia."""
    n = len(vals)
    v = vals[i]
    prev = vals[i - 1] if i > 0 else None
    nxt = vals[i + 1] if i < n - 1 else None
    if prev is not None and nxt is not None:
        return (x, y - 10) if v >= (prev + nxt) / 2 else (x, y + 19)
    nb = nxt if prev is None else prev
    if nb is not None and nb > v:
        return x, y + 19
    return x, y - 10


def _rzadkie(n: int, limit: int) -> set[int]:
    """Co k-ty punkt + ostatni; gdy ostatni wypada tuż za poprzednim
    podpisanym, zastępuje go (inaczej dwie daty nachodziły na siebie)."""
    if n <= limit:
        return set(range(n))
    krok = -(-n // limit)
    idx = list(range(0, n, krok))
    if idx[-1] != n - 1:
        if (n - 1) - idx[-1] < krok:
            idx[-1] = n - 1
        else:
            idx.append(n - 1)
    return set(idx)


def _ktore(n: int, vals: list[float], limit: int | None) -> set[int]:
    """Przy wielu punktach podpisuję tylko pierwszy, ostatni, max i min —
    inaczej etykiety nachodzą na siebie (strona apki, 20+ sesji)."""
    if limit is None or n <= limit:
        return set(range(n))
    return {0, n - 1, vals.index(max(vals)), vals.index(min(vals))}


def chart(days, vals, dec, ids: _Ids, *, w=330, h=150, pad_top=26, pad_bot=58,
          pad_x=26, neutral=False, delta_row=True, label_limit=None, date_limit=None) -> str:
    n = len(vals)
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or abs(hi) * 0.1 or 1
    lo, hi = lo - span * 0.12, hi + span * 0.18
    xs = [pad_x + (w - 2 * pad_x) * (i / (n - 1) if n > 1 else 0.5) for i in range(n)]

    def Y(v: float) -> float:
        return pad_top + (h - pad_top - pad_bot) * (1 - (v - lo) / (hi - lo))

    ys = [Y(v) for v in vals]
    base_y = h - pad_bot + 8
    gid = ids()
    path = smooth_path(xs, ys)
    parts = [f'<svg viewBox="0 0 {w} {h}" width="100%" class="chart">',
             f'<line x1="{pad_x - 12}" y1="{base_y}" x2="{w - pad_x + 12}" y2="{base_y}" class="axis"/>',
             f'<defs><linearGradient id="{gid}" x1="0" y1="0" x2="0" y2="1">'
             f'<stop offset="0" stop-color="#2a78d6" stop-opacity="0.18"/>'
             f'<stop offset="1" stop-color="#2a78d6" stop-opacity="0"/></linearGradient></defs>',
             f'<path d="{path} L{xs[-1]:.1f},{base_y} L{xs[0]:.1f},{base_y} Z" fill="url(#{gid})"/>',
             f'<path d="{path}" class="line"/>']
    podpisy = _ktore(n, vals, label_limit)
    daty = _rzadkie(n, date_limit) if date_limit else set(range(n))
    date_y = h - 28 if delta_row else h - 8
    for i, (x, y, v, d) in enumerate(zip(xs, ys, vals, days)):
        last = " last" if i == n - 1 else ""
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.5" class="dot{last}"/>')
        if i in podpisy:
            tx, ty = label_pos(vals, i, x, y)
            parts.append(f'<text x="{tx:.1f}" y="{ty:.1f}" text-anchor="middle" class="val{last}">{num(v, dec)}</text>')
        if i in daty:
            parts.append(f'<text x="{x:.1f}" y="{date_y}" class="date">{dm(d)}</text>')
        if delta_row and i > 0 and vals[i - 1]:
            p = (v - vals[i - 1]) / abs(vals[i - 1]) * 100
            cls, arrow = ("up", "▲") if p >= 0 else ("down", "▼")
            cls = "" if neutral else cls
            parts.append(f'<text x="{x:.1f}" y="{h - 12}" class="chg {cls}">{arrow} {num(abs(p), 1)} %</text>')
    if delta_row:
        parts.append(f'<text x="{xs[0]:.1f}" y="{h - 12}" class="chg">Δ %</text>')
    parts.append("</svg>")
    return "".join(parts)


def bars(days, vals, ylim, *, w=330, h=230, pad_top=18, pad_bot=26, pad_x=14,
         side_right=False, hi: int | None = None, max_dat: int = 12,
         tylko_poza: bool = False) -> str:
    """Słupek w górę = lewa noga generuje więcej (VALD: wartość ujemna), w dół = prawa."""
    n = len(vals)

    def Y(v: float) -> float:
        return pad_top + (h - pad_top - pad_bot) * (1 - (v + ylim) / (2 * ylim))

    slot = (w - 2 * pad_x) / max(n, 1)
    bw = min(slot * 0.62, 26)
    y0 = Y(0)
    parts = [f'<svg viewBox="0 0 {w} {h}" width="100%" class="chart">',
             f'<rect x="{pad_x}" y="{Y(10):.1f}" width="{w - 2 * pad_x}" height="{Y(-10) - Y(10):.1f}" '
             f'fill="{ZONE_COLOR}" fill-opacity="0.22"/>']
    for z in (10, -10):
        parts.append(f'<line x1="{pad_x}" y1="{Y(z):.1f}" x2="{w - pad_x}" y2="{Y(z):.1f}" stroke="{ZONE_COLOR}" '
                     f'stroke-opacity="0.7" stroke-width="1" stroke-dasharray="1.5 2.5"/>')
    # oznaczenia L/P po prawej na stronie apki (Filip 2026-10-25), w PDF po lewej
    sx, anc = (w - pad_x, "end") if side_right else (pad_x, "start")
    parts.append(f'<text x="{sx}" y="{pad_top - 6}" text-anchor="{anc}" class="side">L ↑</text>')
    parts.append(f'<text x="{sx}" y="{h - pad_bot + 1}" text-anchor="{anc}" class="side">P ↓</text>')
    daty = _rzadkie(n, max_dat)             # przy wielu sesjach co któraś data
    for i, (v, d) in enumerate(zip(vals, days)):
        b = -v
        cx = pad_x + slot * (i + 0.5)
        x = cx - bw / 2
        yt = Y(max(-ylim, min(ylim, b)))
        hgt = abs(yt - y0)
        r = min(2.5, hgt)
        col = L_COLOR if b > 0 else R_COLOR
        if b >= 0:
            path = (f"M{x:.1f},{y0:.1f} L{x:.1f},{yt + r:.1f} Q{x:.1f},{yt:.1f} {x + r:.1f},{yt:.1f} "
                    f"L{x + bw - r:.1f},{yt:.1f} Q{x + bw:.1f},{yt:.1f} {x + bw:.1f},{yt + r:.1f} L{x + bw:.1f},{y0:.1f} Z")
            ly = yt - 4
        else:
            path = (f"M{x:.1f},{y0:.1f} L{x:.1f},{yt - r:.1f} Q{x:.1f},{yt:.1f} {x + r:.1f},{yt:.1f} "
                    f"L{x + bw - r:.1f},{yt:.1f} Q{x + bw:.1f},{yt:.1f} {x + bw:.1f},{yt - r:.1f} L{x + bw:.1f},{y0:.1f} Z")
            ly = yt + 11
        # podświetlony dzień (wybrany w pickerze) pełnym kolorem, reszta blado
        op = "" if hi is None or i == hi else ' fill-opacity="0.38"'
        parts.append(f'<path d="{path}" fill="{col}"{op}/>')
        # na stronie (tylko_poza) podpis tylko poza strefą ±10 % i przy wybranym
        # dniu — w wąskich kartach wszystkie podpisy były nieczytelne
        pokaz = (abs(v) > 10 or i == hi) if tylko_poza else (n <= 12 or i in (0, n - 1) or i == hi)
        if pokaz:
            parts.append(f'<text x="{cx:.1f}" y="{ly:.1f}" class="bval">{num(abs(v), 1)}%</text>')
        if i in daty or i == hi:
            parts.append(f'<text x="{cx:.1f}" y="{h - 6}" class="date">{dm(d)}</text>')
    parts.append(f'<line x1="{pad_x}" y1="{y0:.1f}" x2="{w - pad_x}" y2="{y0:.1f}" '
                 f'stroke="rgba(14,14,16,0.55)" stroke-width="1.2"/>')
    parts.append("</svg>")
    return "".join(parts)


def chart_lr(days, lv, rv, dec, *, w=330, h=220, pad_top=26, pad_bot=30, pad_x=26) -> str:
    """Dwie serie: lewa (niebieska) i prawa (pomarańczowa) noga."""
    n = len(days)
    lo, hi = min(min(lv), min(rv)), max(max(lv), max(rv))
    span = (hi - lo) or abs(hi) * 0.1 or 1
    lo, hi = lo - span * 0.25, hi + span * 0.25
    xs = [pad_x + (w - 2 * pad_x) * (i / (n - 1) if n > 1 else 0.5) for i in range(n)]

    def Y(v: float) -> float:
        return pad_top + (h - pad_top - pad_bot) * (1 - (v - lo) / (hi - lo))

    base_y = h - pad_bot + 6
    parts = [f'<svg viewBox="0 0 {w} {h}" width="100%" class="chart">',
             f'<line x1="{pad_x - 12}" y1="{base_y}" x2="{w - pad_x + 12}" y2="{base_y}" class="axis"/>']
    for vals, col in ((lv, L_COLOR), (rv, R_COLOR)):
        parts.append(f'<path d="{smooth_path(xs, [Y(v) for v in vals])}" fill="none" stroke="{col}" '
                     f'stroke-width="2.5" stroke-linecap="round"/>')
    for i, x in enumerate(xs):
        for vals, other, col in ((lv, rv, L_COLOR), (rv, lv, R_COLOR)):
            v = vals[i]
            y = Y(v)
            ty = y - 10 if v >= other[i] else y + 19
            last = " last" if i == n - 1 else ""
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.5" fill="{col}" stroke="#fff" stroke-width="2"/>')
            parts.append(f'<text x="{x:.1f}" y="{ty:.1f}" text-anchor="middle" class="val{last}">{num(v, dec)}</text>')
        parts.append(f'<text x="{x:.1f}" y="{h - 7}" class="date">{dm(days[i])}</text>')
    parts.append("</svg>")
    return "".join(parts)


# ── karty ─────────────────────────────────────────────────────────────────────
def _esc(s: str) -> str:
    return _html.escape(s or "")


def card_line(title, desc, s: pd.Series, unit, ids: _Ids, *, dec=None, neutral=False,
              w=215, h=215, limit: int = 7) -> str:
    days, vals = list(s.index), [float(v) for v in s.values]
    dec = auto_dec(vals) if dec is None else dec
    opis = f'<div class="cdesc">{_esc(desc)}</div>' if desc else '<div class="cdesc"></div>'
    if len(vals) == 1:
        return f"""
    <div class="card tile">
      <div class="ctitle">{_esc(title)}</div>{opis}
      <div class="hero"><span class="big">{num(vals[0], dec)}</span><span class="unit">{_esc(unit)}</span></div>
      <div class="delta">{dmy(days[0])} · pierwszy test</div>
    </div>"""
    return f"""
    <div class="card">
      <div class="ctitle">{_esc(title)}</div>{opis}
      <div class="hero"><span class="big">{num(vals[-1], dec)}</span><span class="unit">{_esc(unit)}</span></div>
      <div class="delta">{dmy(days[-1])} · od {dm(days[0])}: <b>{pct(vals[-1], vals[0])}</b></div>
      {chart(days, vals, dec, ids, w=w, h=h, neutral=neutral, delta_row=len(vals) <= limit,
             label_limit=limit, date_limit=limit)}
    </div>"""


def card_lr(title, sl: pd.Series, sr: pd.Series, unit, *, dec=None) -> str:
    both = pd.concat({"L": sl, "R": sr}, axis=1).dropna()
    if both.empty:
        return ""
    days, lv, rv = list(both.index), list(both["L"]), list(both["R"])
    dec = auto_dec(lv + rv) if dec is None else dec
    od = (f' · od {dm(days[0])}: lewa <b>{pct(lv[-1], lv[0])}</b> · prawa <b>{pct(rv[-1], rv[0])}</b>'
          if len(days) > 1 else " · pierwszy test")
    return f"""
    <div class="card">
      <div class="ctitle">{_esc(title)}</div>
      <div class="hero"><span class="big">{num(lv[-1], dec)}</span><span class="unit">{_esc(unit)} lewa</span>
        <span class="big" style="margin-left:6mm">{num(rv[-1], dec)}</span><span class="unit">{_esc(unit)} prawa</span></div>
      <div class="delta">{dmy(days[-1])}{od}</div>
      {chart_lr(days, lv, rv, dec)}
    </div>"""


def card_asym(title, sub, s: pd.Series, ylim, *, w=330, h=250) -> str:
    days, vals = list(s.index), [float(v) for v in s.values]
    csub = f'<span class="csub">{_esc(sub)}</span>' if sub else ""
    return f"""
    <div class="card">
      <div class="ctitle">{_esc(title)}{csub}</div>
      <div class="hero"><span class="big">{num(abs(vals[-1]), 1)} %</span><span class="unit">{side(vals[-1], True)}</span></div>
      {bars(days, vals, ylim, w=w, h=h)}
    </div>"""


def legend(strefa: bool = True, proste: bool = False) -> str:
    """proste=True: same „lewa / prawa” (SL CMJ — przy czasach większa
    wartość nie znaczy „generuje więcej”)."""
    zona = (f'<span><i style="background:{ZONE_COLOR}; opacity:.45"></i>strefa ±10 %</span>'
            if strefa else "")
    l_txt, p_txt = ("lewa", "prawa") if proste else ("lewa noga generuje więcej", "prawa noga generuje więcej")
    return (f'<div class="legend"><span><i style="background:{L_COLOR}"></i>{l_txt}</span>'
            f'<span><i style="background:{R_COLOR}"></i>{p_txt}</span>{zona}</div>')


def shared_ylim(series: list[pd.Series]) -> float:
    """Wspólna skala asymetrii (min. ±20 %), żeby słupki dało się porównać."""
    m = max((float(s.abs().max()) for s in series if len(s)), default=0.0)
    return max(m * 1.12, 20.0)


# ── wydruk A4 ─────────────────────────────────────────────────────────────────
_CSS_PRINT = """
@page { size: A4; margin: 0; }
* { box-sizing: border-box; }
body { margin: 0; font-family: "Helvetica Neue", Helvetica, Arial, "Liberation Sans", sans-serif; color: #0b0b0b;
       background: #fff; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
.page { width: 210mm; height: 297mm; padding: 14mm 14mm 10mm; position: relative; overflow: hidden; }
.page + .page { page-break-before: always; }
.head { border-bottom: 1.5px solid #0b0b0b; padding-bottom: 2.5mm; margin-bottom: 6mm; }
.period { font-size: 9pt; color: #52514e; }
h2 { font-size: 13pt; margin: 0 0 3mm; font-weight: 700; }
h2 span { font-weight: 400; color: #52514e; font-size: 10pt; margin-left: 2mm; }
.grid1 { display: grid; grid-template-columns: 1fr; gap: 4mm; margin-bottom: 6mm; }
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 4mm; margin-bottom: 6mm; }
.grid3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 4mm; margin-bottom: 6mm; }
.card { border: 1px solid #e1e0d9; border-radius: 8px; padding: 3.5mm 4mm 1.5mm; }
.card.tile { padding-bottom: 3mm; }
.ctitle { font-size: 10.5pt; font-weight: 700; }
.csub { font-weight: 400; color: #898781; font-size: 8pt; margin-left: 1.5mm; }
.cdesc { font-size: 7.8pt; color: #898781; margin-top: 0.8mm; line-height: 1.35; }
.grid3 .cdesc { min-height: 3.2em; }
.grid3 .tile .cdesc { min-height: 0; }
.grid1 .cdesc:empty, .grid2 .cdesc:empty { display: none; }
.hero { margin-top: 1.5mm; }
.big { font-size: 22pt; font-weight: 700; letter-spacing: -0.5px; }
.grid1 .big { font-size: 24pt; }
.unit { font-size: 10pt; color: #52514e; margin-left: 1.5mm; }
.delta { font-size: 8.3pt; color: #52514e; margin: 0.5mm 0 1mm; }
.delta b { color: #0b0b0b; }
.chart { display: block; overflow: visible; }
.chart .axis { stroke: #e1e0d9; stroke-width: 1; }
.chart .side { font-size: 9.5px; fill: #898781; font-weight: 700; }
.chart .line { fill: none; stroke: #2a78d6; stroke-width: 2.5; stroke-linejoin: round; stroke-linecap: round; }
.chart .dot { fill: #2a78d6; stroke: #fff; stroke-width: 2; }
.chart .dot.last { fill: #104281; }
.chart .val { font-size: 10px; fill: #52514e; font-weight: 600; }
.chart .val.last { fill: #0b0b0b; font-weight: 700; }
.chart .date { font-size: 9px; fill: #898781; text-anchor: middle; }
.chart .chg { font-size: 9.5px; fill: #898781; text-anchor: middle; font-weight: 600; }
.chart .chg.up { fill: #006300; }
.chart .chg.down { fill: #c0392b; }
.chart .bval { font-size: 9px; fill: #0E0E10; text-anchor: middle; font-weight: 600; }
.legend { font-size: 9pt; color: #52514e; margin: -1mm 0 4mm; display: flex; gap: 6mm; }
.legend i { display: inline-block; width: 3.2mm; height: 3.2mm; border-radius: 1px; margin-right: 1.5mm; vertical-align: -0.4mm; }
"""

# wysokości bloków na stronie A4 (mm) — strona ma 297 − 24 marginesu − 12 nagłówka
_STRONA_MM = 259
_H2_MM, _LEG_MM = 10, 8
_GRID1_MM, _GRID3_MM, _GRID2_MM, _TILE_MM = 112, 96, 88, 40


def _bloki_sekcji(sec: dict, ids: _Ids, ylim: float) -> list[list[tuple[float, str]]]:
    """Sekcja testu → paczki bloków (wykresy / L-P / asymetrie), każdy blok
    = (wysokość mm, html). Nagłówek h2 przyklejony do pierwszego bloku, żeby
    nie zostawał sam na dole strony; paczka trzyma się razem, jeśli zmieści
    się na jednej stronie (asymetrie na osobnej stronie jak w PDF-ach)."""
    out: list[tuple[float, str]] = []
    lines = [x for x in sec.get("lines", []) if len(x["s"])]
    lrs = [x for x in sec.get("lr", []) if len(x["l"]) and len(x["r"])]
    asyms = [x for x in sec.get("asyms", []) if len(x["s"])]
    h2 = f'<h2>{_esc(sec["title"])}<span>{_esc(sec.get("sub", ""))}</span></h2>'
    if lines:
        if len(lines) <= 2:
            rows = [[x] for x in lines]
            for i, row in enumerate(rows):
                x = row[0]
                body = card_line(x["title"], x.get("desc", ""), x["s"], x.get("unit", ""), ids,
                                 dec=x.get("dec"), neutral=x.get("neutral", False), w=700, h=300,
                                 limit=14)
                wys = _TILE_MM if len(x["s"]) == 1 else _GRID1_MM
                out.append((wys + (_H2_MM if i == 0 else 0),
                            (h2 if i == 0 else "") + f'<div class="grid1">{body}</div>'))
        else:
            for i in range(0, len(lines), 3):
                body = "".join(card_line(x["title"], x.get("desc", ""), x["s"], x.get("unit", ""), ids,
                                         dec=x.get("dec"), neutral=x.get("neutral", False), limit=6)
                               for x in lines[i:i + 3])
                # rząd samych kafelków z jedną sesją jest niski (bez wykresu)
                wys = _TILE_MM if all(len(x["s"]) == 1 for x in lines[i:i + 3]) else _GRID3_MM
                out.append((wys + (_H2_MM if i == 0 else 0),
                            (h2 if i == 0 else "") + f'<div class="grid3">{body}</div>'))
    paczki = [out] if out else []
    out = []
    for i in range(0, len(lrs), 2):
        body = "".join(card_lr(x["title"], x["l"], x["r"], x.get("unit", ""), dec=x.get("dec"))
                       for x in lrs[i:i + 2])
        pierwszy = not paczki and not out
        out.append((_GRID2_MM + (_H2_MM if pierwszy else 0),
                    (h2 if pierwszy else "") + f'<div class="grid2">{body}</div>'))
    if out:
        paczki.append(out)
    out = []
    if asyms:
        h2a = (f'<h2>Asymetria · {_esc(sec["title"])}<span>{_esc(sec.get("asym_sub", "średnia ze skoków dnia"))}'
               f'</span></h2>')
        for i in range(0, len(asyms), 2):
            body = "".join(card_asym(x["title"], x.get("sub", ""), x["s"], ylim) for x in asyms[i:i + 2])
            naglowek = (h2a + legend()) if i == 0 else ""
            out.append((_GRID2_MM + (_H2_MM + _LEG_MM if i == 0 else 0),
                        naglowek + f'<div class="grid2">{body}</div>'))
    if out:
        paczki.append(out)
    return paczki


def build_report_html(period: str, sections: list[dict], header: str = "") -> str:
    """Cały wydruk: sekcje testów → strony A4.

    sections: [{"title", "sub", "lines": [{"title","desc","unit","dec","s","neutral"}],
                "lr": [{"title","unit","dec","l","r"}],
                "asyms": [{"title","sub","s"}], "asym_sub"}]
    Asymetrie wszystkich sekcji mają wspólną skalę (jak w PDF-ach)."""
    ids = _Ids()
    ylim = shared_ylim([a["s"] for sec in sections for a in sec.get("asyms", [])])
    naglowek = " · ".join(x for x in ("ForceDecks", header, period) if x)
    head = f'<div class="head"><div class="period">{_esc(naglowek)}</div></div>'
    pages: list[list[str]] = [[]]
    wolne = _STRONA_MM
    for sec in sections:
        for paczka in _bloki_sekcji(sec, ids, ylim):
            razem = sum(h for h, _b in paczka)
            if razem > wolne and razem <= _STRONA_MM and pages[-1]:
                pages.append([])
                wolne = _STRONA_MM
            for h, block in paczka:
                if h > wolne and pages[-1]:
                    pages.append([])
                    wolne = _STRONA_MM
                pages[-1].append(block)
                wolne -= h
    body = "".join(f'<section class="page">{head}{"".join(p)}</section>' for p in pages if p)
    return (f'<!doctype html><html lang="pl"><head><meta charset="utf-8"><title>Testy</title>'
            f'<style>{_CSS_PRINT}</style></head><body>{body}</body></html>')


def render_pdf(html: str) -> bytes | None:
    """HTML → PDF przez Chromium. None, gdy Playwright/Chromium niedostępny
    (Streamlit Cloud) — wtedy apka drukuje z przeglądarki."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return None
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            try:
                pg = b.new_page()
                pg.set_content(html, wait_until="load")
                return pg.pdf(format="A4", print_background=True,
                              margin={"top": "0", "bottom": "0", "left": "0", "right": "0"})
            finally:
                b.close()
    except Exception:
        return None


def print_page(html: str) -> str:
    """Ten sam HTML z przyciskiem „Drukuj” i automatycznym oknem druku —
    do wstawienia w iframe (components.html), gdy nie ma Chromium."""
    pasek = ('<div class="noprint" style="position:sticky;top:0;z-index:9;background:#fff;'
             'padding:8px 12px;border-bottom:1px solid #e1e0d9;font-family:Helvetica,Arial,sans-serif">'
             '<button onclick="window.print()" style="font:600 14px Helvetica,Arial,sans-serif;'
             'padding:8px 18px;border-radius:8px;border:1px solid #0b0b0b;background:#0b0b0b;color:#fff;'
             'cursor:pointer">Drukuj / zapisz jako PDF</button></div>')
    skrypt = ("<style>@media print{.noprint{display:none!important}}"
              "@media screen{body{background:#f4f3ef}.page{background:#fff;margin:12px auto;"
              "box-shadow:0 1px 6px rgba(0,0,0,.12)}}</style>"
              "<script>window.addEventListener('load',function(){setTimeout(function(){"
              "try{window.print()}catch(e){}},400)});</script>")
    return html.replace("<body>", "<body>" + pasek, 1).replace("</head>", skrypt + "</head>", 1)


# ── ekran (strona apki) ───────────────────────────────────────────────────────
SCREEN_CSS = """
<style>
.stApp .tpdf { font-family: var(--aph-text, "Helvetica Neue", Helvetica, Arial, sans-serif); }
.stApp .tpdf .tgrid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; margin: 0 0 10px; }
.stApp .tpdf .tgrid.two { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.stApp .tpdf .tgrid.c4 { grid-template-columns: repeat(4, minmax(0, 1fr)); }
.stApp .tpdf .card { background: var(--aph-card, #fff); border: 1px solid #e1e0d9; border-radius: 12px;
  padding: 10px 12px 6px; min-width: 0; }
.stApp .tpdf .card.small { padding: 9px 12px 4px; }
.stApp .tpdf .ctitle { font-size: 13px; font-weight: 700; color: #0b0b0b !important; }
.stApp .tpdf .csub { font-weight: 400; color: #898781 !important; font-size: 11.5px; margin-left: 6px; }
.stApp .tpdf .hero { margin-top: 6px; display: flex; align-items: baseline; gap: 6px; flex-wrap: wrap; }
.stApp .tpdf .big { font-size: 26px; font-weight: 700; letter-spacing: -0.5px; line-height: 1.05; color: #0b0b0b !important; }
.stApp .tpdf .card.small .big { font-size: 20px; }
.stApp .tpdf .unit { font-size: 13px; color: #52514e !important; }
.stApp .tpdf .delta { font-size: 12px; color: #52514e !important; margin: 4px 0 2px; display: flex; gap: 8px;
  align-items: center; flex-wrap: wrap; }
.stApp .tpdf .pill { font-weight: 700; font-size: 12px; padding: 1px 8px; border-radius: 99px;
  background: #f1f0eb; color: #52514e !important; }
.stApp .tpdf .pill.up { background: #e3f1e6; color: #006300 !important; }
.stApp .tpdf .pill.down { background: #f8e3df; color: #c0392b !important; }
.stApp .tpdf .chart { display: block; overflow: visible; }
.stApp .tpdf .chart .axis { stroke: #e1e0d9; stroke-width: 1; }
.stApp .tpdf .chart .side { font-size: 9.5px; fill: #898781; font-weight: 700; }
.stApp .tpdf .chart .line { fill: none; stroke: #2a78d6; stroke-width: 2.5; stroke-linejoin: round; stroke-linecap: round; }
.stApp .tpdf .chart .dot { fill: #2a78d6; stroke: #fff; stroke-width: 2; }
.stApp .tpdf .chart .dot.last { fill: #104281; }
.stApp .tpdf .chart .val { font-size: 10px; fill: #52514e; font-weight: 600; }
.stApp .tpdf .chart .val.last { fill: #0b0b0b; font-weight: 700; }
.stApp .tpdf .chart .date { font-size: 9px; fill: #898781; text-anchor: middle; }
.stApp .tpdf .chart .chg { font-size: 9.5px; fill: #898781; text-anchor: middle; font-weight: 600; }
.stApp .tpdf .chart .bval { font-size: 9px; fill: #0E0E10; text-anchor: middle; font-weight: 600; }
.stApp .tpdf .card.asym .big { font-size: 18px; }
.stApp .tpdf .sL { color: #3B6FB0 !important; }
.stApp .tpdf .sP { color: #E08A2B !important; }
.stApp .tpdf .unit.sL, .stApp .tpdf .unit.sP { font-weight: 700; }
.stApp .tpdf .xhead { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; margin: 6px 0 2px; }
.stApp .tpdf .xhead .ctitle { font-size: 15px; margin-right: 6px; }
.stApp .tpdf .xhead .big { font-size: 26px; }
.stApp .tpdf .xnarrow { display: none; }
@media (max-width: 640px) { .stApp .tpdf .xwide { display: none; } .stApp .tpdf .xnarrow { display: block; } }
.stApp .tpdf .nodata { height: 60px; display: grid; place-items: center; font-size: 11px; color: #898781 !important; }
.stApp .tpdf .legend { font-size: 12px; color: #52514e !important; margin: 0 0 10px; display: flex; gap: 16px; flex-wrap: wrap; }
.stApp .tpdf .legend i { display: inline-block; width: 11px; height: 11px; border-radius: 2px; margin-right: 6px; vertical-align: -1px; }
.stApp .tpdf .legend span { color: #52514e !important; }
@media (max-width: 900px) { .stApp .tpdf .tgrid, .stApp .tpdf .tgrid.c4 { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 640px) { .stApp .tpdf .tgrid, .stApp .tpdf .tgrid.two, .stApp .tpdf .tgrid.c4 { grid-template-columns: minmax(0, 1fr); } }
</style>
"""


def screen_tile(title: str, value_text: str, unit: str, delta_text: str, tone: str,
                s: pd.Series, ids: _Ids, *, small: bool = False, dec: int | None = None,
                last_label: str = "") -> str:
    """Kafelek na stronę: wartość, Δ % do poprzedniej sesji (pigułka) i krzywa
    w stylu PDF. Przy wielu sesjach podpisane tylko skrajne punkty."""
    vals = [float(v) for v in s.values] if len(s) else []
    days = list(s.index)
    if len(vals) >= 2:
        d = auto_dec(vals) if dec is None else dec
        # dół wykresu z zapasem: etykieta pod najniższym punktem nie może
        # wchodzić na daty (podgląd 25.10 — CM Depth, Ecc. Duration)
        # mniejsze kafelki (Filip 2026-10-25: zajmowały za dużo miejsca)
        if small:
            wykres = chart(days, vals, d, ids, w=330, h=104, pad_top=20, pad_bot=34, delta_row=False,
                           label_limit=4, date_limit=5)
        else:
            wykres = chart(days, vals, d, ids, w=330, h=140, pad_top=24, pad_bot=36, delta_row=False,
                           label_limit=6, date_limit=6)
    else:
        wykres = f'<div class="nodata">{"1 sesja" if vals else "—"}</div>'
    pill = f'<span class="pill {tone}">{_esc(delta_text)}</span>' if delta_text else ""
    lab = f"<span>{_esc(last_label)}</span>" if last_label else ""
    cls = "card small" if small else "card"
    return (f'<div class="{cls}"><div class="ctitle">{_esc(title)}</div>'
            f'<div class="hero"><span class="big">{_esc(value_text)}</span><span class="unit">{_esc(unit)}</span></div>'
            f'<div class="delta">{pill}{lab}</div>{wykres}</div>')


def screen_asym_card(title: str, s: pd.Series, ylim: float, ref_day=None) -> str:
    """Asymetria na stronę: wartość z dnia wybranego w pickerze (słupek tego
    dnia pełnym kolorem, reszta blado), kolor = noga (lewa niebieska, prawa
    pomarańczowa), L/P po prawej. Bez pomiaru w tym dniu — „—”."""
    if not len(s):
        return ""
    days, vals = list(s.index), [float(v) for v in s.values]
    hi = None
    if ref_day is not None:
        dni = [pd.Timestamp(d).date() for d in days]
        hi = dni.index(ref_day) if ref_day in dni else -1
    if hi == -1:
        hero = '<span class="big" style="color:#898781">—</span><span class="unit">brak w tym dniu</span>'
        hi = None
    else:
        v = vals[-1] if hi is None else vals[hi]
        noga = "L" if v < 0 else "P"
        strona = side(v, True)
        if abs(v) < 0.05:               # równo — bez strony i koloru nogi
            noga, strona = "", "równo"
        # klasy, bo Streamlit wycina atrybut style z markdownu
        hero = (f'<span class="big s{noga}">{num(abs(v), 1)} %</span>'
                f'<span class="unit s{noga}">{strona}</span>')
    return f"""
    <div class="card asym">
      <div class="ctitle">{_esc(title)}</div>
      <div class="hero">{hero}</div>
      {bars(days, vals, ylim, w=330, h=150, pad_top=16, pad_bot=22, side_right=True, hi=hi,
            max_dat=6, tylko_poza=True)}
    </div>"""


def lr_pair_card(title: str, lv, rv, unit: str, dec: int | None = None,
                 kierunek: bool = True) -> str:
    """Single leg: lewa i prawa obok siebie z jednego dnia + asymetria liczona
    jak w VALD: (P − L) / max × 100, minus = lewa (na modułach — prędkość
    i głębokość zejścia są ujemne). Kolor = noga: lewa niebieska, prawa
    pomarańczowa."""
    def ok(v):
        return v is not None and not pd.isna(v)
    vals = [abs(float(v)) for v in (lv, rv) if ok(v)]
    if not vals or max(vals) == 0:      # same zera = VALD nie policzył metryki
        return ""
    dec = auto_dec(vals) if dec is None else dec
    if ok(lv) and ok(rv) and max(abs(lv), abs(rv)) > 0:
        a = (abs(rv) - abs(lv)) / max(abs(lv), abs(rv)) * 100
        if abs(a) < 0.05:               # równo — bez strony i koloru nogi
            hero = '<span class="big">0,0 %</span><span class="unit">równo</span>'
        elif not kierunek:
            # czasy, głębokość, prędkość zejścia: większa wartość ≠ „noga
            # generuje więcej” (przegląd 2026-10-25) — sama różnica, bez koloru
            hero = f'<span class="big">{num(abs(a), 1)} %</span><span class="unit">różnica</span>'
        else:
            noga = "L" if a < 0 else "P"
            hero = (f'<span class="big s{noga}">{num(abs(a), 1)} %</span>'
                    f'<span class="unit s{noga}">{side(a, True)}</span>')
    else:
        hero = '<span class="big" style="color:#898781">—</span><span class="unit">jedna noga</span>'
    w, h, base = 330, 112, 88
    top = max(vals) * 1.18
    parts = [f'<svg viewBox="0 0 {w} {h}" width="100%" class="chart">',
             f'<line x1="40" y1="{base}" x2="{w - 40}" y2="{base}" class="axis"/>']
    for v, cx, col, lit in ((lv, 120, L_COLOR, "L"), (rv, 210, R_COLOR, "P")):
        if ok(v):
            hb = (abs(float(v)) / top) * (base - 22)
            parts.append(f'<rect x="{cx - 30}" y="{base - hb:.1f}" width="60" height="{hb:.1f}" rx="3" fill="{col}"/>')
            parts.append(f'<text x="{cx}" y="{base - hb - 6:.1f}" text-anchor="middle" class="val last">'
                         f'{num(float(v), dec)}</text>')
        parts.append(f'<text x="{cx}" y="{h - 10}" text-anchor="middle" class="side">{lit}</text>')
    parts.append("</svg>")
    return (f'<div class="card asym"><div class="ctitle">{_esc(title)}'
            f'<span class="csub">{_esc(unit)}</span></div>'
            f'<div class="hero">{hero}</div>{"".join(parts)}</div>')
