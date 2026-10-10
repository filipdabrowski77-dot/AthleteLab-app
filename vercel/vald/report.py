"""
Generator raportu PDF zawodnika — czyste RYSOWANIE (matplotlib, A4).

Dane przychodzą z app.py jako gotowe serie (per dzień) — ten moduł nie zna
parquetu ani logiki agregacji. Styl: Slate (spójny z dashboardem), zero
ozdobnych dopisków — tytuł, wykresy, stopka.

Struktura wejścia (build_report_pdf):
    sections = [
        {
            "test": "CMJ",
            "accent": "#2F6BD8",
            "charts": [
                {"kind": "line", "title": "Jump Height", "unit": "cm",
                 "series": pd.Series(idx=Timestamp, val=float)},
                {"kind": "line2", "title": "Peak Force", "unit": "N",
                 "series_l": pd.Series, "series_r": pd.Series},      # RSAIP/RSKIP
                {"kind": "asym", "title": "Concentric Impulse",
                 "series": pd.Series(signed % — dodatnie=R, ujemne=L)},
            ],
        },
    ]
"""
from __future__ import annotations

import io
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import pandas as pd

# ── Tokeny Slate (jak w app.py / viz.py) ────────────────────────────────────
INK = "#0F1722"
DIM = "#54606F"
MUTE = "#90A0B0"
LINE = "#E3E8EF"          # ~rgba(15,23,42,.10) na bieli
ACCENT = "#2F6BD8"
SIDE_L = "#3B6FB0"        # lewa kończyna — steel blue
SIDE_R = "#E08A2B"        # prawa kończyna — amber
AMBER = "#E0A52B"
RED = "#D8553F"

_A4 = (8.27, 11.69)       # cale, portrait
_CHARTS_PER_PAGE = 3      # 1 kolumna — pełna szerokość: czytelna oś czasu,
                          # etykiety % asymetrii mają miejsce (nie nachodzą)


def _style_axes(ax) -> None:
    """Recessive osie/grid — dane na pierwszym planie."""
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(LINE)
    ax.grid(axis="y", color=LINE, linestyle=(0, (3, 3)), linewidth=0.7)
    ax.set_axisbelow(True)
    ax.tick_params(colors=DIM, labelsize=7.5, length=0)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=4, maxticks=9))


def _pad_single_day_xlim(ax, x) -> None:
    """Przy 1 punkcie AutoDateLocator wariuje (oś Jan–Jul) — zwężamy do ±4 dni."""
    if len(x) == 1:
        d = pd.Timestamp(x[0])
        ax.set_xlim(d - pd.Timedelta(days=4), d + pd.Timedelta(days=4))


def _fmt_pl(v: float, dec: int) -> str:
    return f"{v:.{dec}f}".replace(".", ",")


def _dec_for(values) -> int:
    m = max((abs(float(v)) for v in values if pd.notna(v)), default=0)
    return 1 if m >= 10 else 2


def _draw_line(ax, chart: dict) -> None:
    s = chart["series"].dropna().sort_index()
    unit = chart.get("unit", "")
    if s.empty:
        ax.text(0.5, 0.5, "brak danych", transform=ax.transAxes,
                ha="center", va="center", color=MUTE, fontsize=9)
        ax.set_axis_off()
        return
    x = list(s.index)
    y = [float(v) for v in s.values]
    dec = _dec_for(y)

    ax.plot(x, y, color=ACCENT, linewidth=2.2, zorder=3,
            marker="o", markersize=4.5, markerfacecolor="white",
            markeredgecolor=ACCENT, markeredgewidth=1.6)
    # Ostatni punkt: pełny marker + selektywna etykieta wartości
    ax.plot([x[-1]], [y[-1]], marker="o", markersize=7,
            markerfacecolor=ACCENT, markeredgecolor="white",
            markeredgewidth=1.4, zorder=4)
    ax.annotate(
        f"{_fmt_pl(y[-1], dec)} {unit}".strip(),
        (x[-1], y[-1]), textcoords="offset points", xytext=(0, 9),
        ha="right", fontsize=8.5, fontweight="bold", color=INK, zorder=5,
    )
    # Zakres Y z oddechem (nie od zera — trend ma być czytelny)
    lo, hi = min(y), max(y)
    span = (hi - lo) or (abs(hi) or 1.0)
    ax.set_ylim(lo - span * 0.25, hi + span * 0.30)
    _style_axes(ax)
    _pad_single_day_xlim(ax, x)
    if unit:
        ax.set_ylabel(unit, color=DIM, fontsize=8)
    ax.set_title(chart["title"], loc="left", color=INK,
                 fontsize=10.5, fontweight="bold", pad=8)


def _draw_line_lr(ax, chart: dict) -> None:
    """Dwie serie L/R (testy unilateralne) — kolor przypisany kończynie."""
    sl = chart.get("series_l", pd.Series(dtype=float)).dropna().sort_index()
    sr = chart.get("series_r", pd.Series(dtype=float)).dropna().sort_index()
    unit = chart.get("unit", "")
    if sl.empty and sr.empty:
        ax.text(0.5, 0.5, "brak danych", transform=ax.transAxes,
                ha="center", va="center", color=MUTE, fontsize=9)
        ax.set_axis_off()
        return
    all_y: list[float] = []
    all_x: list = []
    single = max(len(sl), len(sr)) <= 1
    for s, color, lbl in ((sl, SIDE_L, "L"), (sr, SIDE_R, "R")):
        if s.empty:
            continue
        y = [float(v) for v in s.values]
        all_y += y
        all_x += list(s.index)
        ax.plot(list(s.index), y, color=color, linewidth=2.0, zorder=3,
                marker="o",
                markersize=7 if single else 4,
                markerfacecolor=color if single else "white",
                markeredgecolor="white" if single else color,
                markeredgewidth=1.4, label=lbl)
        if single and y:
            dec = _dec_for(y)
            ax.annotate(f"{_fmt_pl(y[-1], dec)}", (s.index[-1], y[-1]),
                        textcoords="offset points", xytext=(8, 0),
                        ha="left", va="center", fontsize=8,
                        fontweight="bold", color=INK)
    lo, hi = min(all_y), max(all_y)
    span = (hi - lo) or (abs(hi) or 1.0)
    ax.set_ylim(lo - span * 0.25, hi + span * 0.30)
    _style_axes(ax)
    _pad_single_day_xlim(ax, sorted(set(all_x)))
    if unit:
        ax.set_ylabel(unit, color=DIM, fontsize=8)
    ax.set_title(chart["title"], loc="left", color=INK,
                 fontsize=10.5, fontweight="bold", pad=8)
    leg = ax.legend(loc="upper left", frameon=False, fontsize=8,
                    handlelength=1.2, borderaxespad=0.2)
    for t in leg.get_texts():
        t.set_color(DIM)


def _draw_asym(ax, chart: dict) -> None:
    """Diverging bars: dodatnie = przesunięcie na PRAWĄ (pomarańcz, w górę),
    ujemne = LEWA (niebieski, w dół). Neutralne zero + progi 10/15%."""
    s = chart["series"].dropna().sort_index()
    if s.empty:
        ax.text(0.5, 0.5, "brak danych", transform=ax.transAxes,
                ha="center", va="center", color=MUTE, fontsize=9)
        ax.set_axis_off()
        return
    x = mdates.date2num(list(s.index))
    y = [float(v) for v in s.values]
    # Szerokość słupka: 60% mediany odstępu (gap między słupkami)
    if len(x) > 1:
        diffs = sorted(b - a for a, b in zip(x[:-1], x[1:]))
        width = max(diffs[len(diffs) // 2] * 0.6, 0.8)
    else:
        width = 3.0
    colors = [SIDE_R if v >= 0 else SIDE_L for v in y]
    ax.bar(x, y, width=width, color=colors, zorder=3,
           edgecolor="white", linewidth=0.6)

    top = max(max((abs(v) for v in y)), 18.0) * 1.25
    ax.set_ylim(-top, top)
    ax.axhline(0, color=INK, linewidth=1.0, zorder=4)
    for thr, c in ((10, AMBER), (15, RED)):
        for sgn in (1, -1):
            ax.axhline(sgn * thr, color=c, linewidth=0.7,
                       linestyle=(0, (4, 4)), alpha=0.55, zorder=2)
    # Selektywne etykiety % z krokiem — przy gęstych słupkach etykiety
    # nachodziły na siebie ('14,8''15,1' zlane). Cel: max ~9 etykiet,
    # zawsze z ostatnią.
    n_pts = len(y)
    step = max(1, -(-n_pts // 9))
    label_idx = sorted({*range(0, n_pts, step), n_pts - 1})
    for i in label_idx:
        va = "bottom" if y[i] >= 0 else "top"
        off = 1.5 if y[i] >= 0 else -1.5
        ax.annotate(_fmt_pl(abs(y[i]), 1), (x[i], y[i] + off),
                    ha="center", va=va, fontsize=7, color=DIM)
    _style_axes(ax)
    _pad_single_day_xlim(ax, list(s.index))
    ax.set_ylabel("% asym", color=DIM, fontsize=8)
    ax.set_title(chart["title"], loc="left", color=INK,
                 fontsize=10.5, fontweight="bold", pad=8)
    # Legenda stron: kolor identyfikuje kończynę
    handles = [
        plt.Rectangle((0, 0), 1, 1, color=SIDE_R, label="prawa ▲"),
        plt.Rectangle((0, 0), 1, 1, color=SIDE_L, label="lewa ▼"),
    ]
    leg = ax.legend(handles=handles, loc="upper left", frameon=False,
                    fontsize=7.5, handlelength=1.0, borderaxespad=0.2)
    for t in leg.get_texts():
        t.set_color(DIM)


_DRAW = {"line": _draw_line, "line2": _draw_line_lr, "asym": _draw_asym}


def _title_page(pdf: PdfPages, name: str, meta: dict) -> None:
    fig = plt.figure(figsize=_A4)
    fig.patch.set_facecolor("white")
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_axis_off()

    ax.text(0.08, 0.90, "RAPORT TESTÓW", fontsize=13, color=DIM,
            fontweight="bold", ha="left")
    ax.add_patch(plt.Rectangle((0.08, 0.885), 0.055, 0.004,
                               color=ACCENT, transform=ax.transAxes))
    ax.text(0.08, 0.83, name, fontsize=30, color=INK,
            fontweight="bold", ha="left")

    rows = []
    if meta.get("sport"):
        rows.append(("Dyscyplina", meta["sport"]))
    if meta.get("span"):
        rows.append(("Okres", meta["span"]))
    if meta.get("n_days") is not None:
        rows.append(("Dni testowe", str(meta["n_days"])))
    if meta.get("tests"):
        rows.append(("Testy", meta["tests"]))
    y0 = 0.755
    for i, (k, v) in enumerate(rows):
        ax.text(0.08, y0 - i * 0.034, k.upper(), fontsize=8.5,
                color=MUTE, ha="left")
        ax.text(0.26, y0 - i * 0.034, v, fontsize=10.5,
                color=INK, ha="left", fontweight="bold")

    ax.text(0.08, 0.045,
            f"Athletic Performance Hub · {datetime.now():%d.%m.%Y}",
            fontsize=8, color=MUTE, ha="left")
    pdf.savefig(fig)
    plt.close(fig)


def _section_pages(pdf: PdfPages, section: dict) -> None:
    charts = section.get("charts", [])
    if not charts:
        return
    accent = section.get("accent", ACCENT)
    for start in range(0, len(charts), _CHARTS_PER_PAGE):
        batch = charts[start:start + _CHARTS_PER_PAGE]
        fig = plt.figure(figsize=_A4)
        fig.patch.set_facecolor("white")

        # Nagłówek sekcji: kolorowy pasek + nazwa testu
        fig.text(0.07, 0.955, section["test"], fontsize=15,
                 color=INK, fontweight="bold", ha="left")
        fig.patches.append(plt.Rectangle(
            (0.07, 0.943), 0.05, 0.0035, transform=fig.transFigure,
            color=accent, clip_on=False,
        ))

        gs = fig.add_gridspec(
            3, 1, left=0.10, right=0.94, top=0.905, bottom=0.06,
            hspace=0.62,
        )
        for i, chart in enumerate(batch):
            ax = fig.add_subplot(gs[i, 0])
            _DRAW.get(chart.get("kind", "line"), _draw_line)(ax, chart)

        fig.text(0.95, 0.02, f"{section['test']}", fontsize=7,
                 color=MUTE, ha="right")
        pdf.savefig(fig)
        plt.close(fig)


def build_report_pdf(name: str, meta: dict, sections: list[dict]) -> bytes:
    """Zbuduj PDF; zwraca bytes (do st.download_button)."""
    buf = io.BytesIO()
    with PdfPages(buf) as pdf:
        _title_page(pdf, name, meta)
        for section in sections:
            _section_pages(pdf, section)
    return buf.getvalue()
