"""Wykresy plotly do panelu Vald ForceDecks."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .metrics import ASYM_GREEN, ASYM_YELLOW, MetricDef, asymmetry_flag

FLAG_COLORS = {
    "green": "#3BA776",
    "orange": "#E0A52B",
    "red": "#D8553F",
    "gray": "#54606F",
}

# Stała paleta — żeby ten sam zawodnik miał ten sam kolor we wszystkich wykresach
ATHLETE_PALETTE = [
    "#22c55e", "#3b82f6", "#a855f7", "#f59e0b", "#06b6d4",
    "#ec4899", "#84cc16", "#f97316", "#14b8a6", "#eab308",
]


def athlete_color(athlete: str, all_athletes: list[str]) -> str:
    """Stabilny kolor dla zawodnika w obrębie sesji."""
    try:
        idx = all_athletes.index(athlete)
    except ValueError:
        idx = 0
    return ATHLETE_PALETTE[idx % len(ATHLETE_PALETTE)]


SIDE_L_COLOR = "#3B6FB0"   # steel blue (lewa noga) — Slate
SIDE_R_COLOR = "#E08A2B"   # amber (prawa noga) — Slate
SIDE_NONE_COLOR = "#90a0b0"  # mute (brak dominującej strony)


def asymmetry_overview_bar(
    flagged: list[tuple[MetricDef, str, float, str | None]]
) -> go.Figure:
    """Horizontal bar — wszystkie asymetrie z progami 10% i 15%.
    Kolor per bar wg dominującej strony: L=blue, R=amber, brak=gray.

    flagged: lista (MetricDef, kolumna_csv, magnitude, side)
    """
    data = sorted(
        [(m.label, mag, side) for m, _, mag, side in flagged if not pd.isna(mag)],
        key=lambda t: t[1],
    )
    # Label z prostym oznaczeniem strony: L (lewa) lub P (prawa).
    # Format mockup-style: "L ← {metric}" / "{metric} → P" / "{metric}"
    def _label_with_side(lab: str, side: str | None) -> str:
        if side == "L":
            return f"L  ←  {lab}"
        if side == "R":
            return f"{lab}  →  P"
        return lab

    labels = [_label_with_side(lab, side) for lab, _, side in data]
    values = [v for _, v, _ in data]
    sides = [side for _, _, side in data]
    colors = [
        SIDE_L_COLOR if s == "L"
        else SIDE_R_COLOR if s == "R"
        else SIDE_NONE_COLOR
        for s in sides
    ]
    # Tekst na końcu baru: "5.5% L" / "5.5% P" z kolorem strony
    bar_text = []
    for v, s in zip(values, sides):
        if s == "L":
            bar_text.append(
                f"<b>{v:.1f}%</b>  <b style='color:{SIDE_L_COLOR}'>L</b>"
            )
        elif s == "R":
            bar_text.append(
                f"<b>{v:.1f}%</b>  <b style='color:{SIDE_R_COLOR}'>P</b>"
            )
        else:
            bar_text.append(f"<b>{v:.1f}%</b>")
    # Customdata dla hover (side w czytelnej formie)
    customdata = [[s or "brak danych"] for s in sides]

    max_v = max(values + [ASYM_YELLOW + 5]) if values else ASYM_YELLOW + 5
    upper = max(max_v * 1.25, ASYM_YELLOW + 5)

    fig = go.Figure(
        go.Bar(
            x=values, y=labels, orientation="h",
            marker=dict(color=colors, line=dict(width=0)),
            text=bar_text, textposition="outside",
            textfont=dict(size=11, family="Archivo, sans-serif", color="#0E0E10"),
            customdata=customdata,
            hovertemplate=(
                "<b>%{y}</b><br>"
                "Asymetria: <b>%{x:.1f}%</b><br>"
                "Strona dominująca: <b>%{customdata[0]}</b>"
                "<extra></extra>"
            ),
        )
    )
    # Strefy mocniejsze — Filip raportował że jasne (0.07 alpha) były niewidoczne,
    # szczególnie zielony zlewał się z bone bg. Podbicie do 0.20 daje wyraźny
    # gradient strefowy bez przykrycia barów.
    fig.add_vrect(x0=0, x1=ASYM_GREEN, fillcolor=FLAG_COLORS["green"], opacity=0.20, line_width=0)
    fig.add_vrect(x0=ASYM_GREEN, x1=ASYM_YELLOW, fillcolor=FLAG_COLORS["orange"], opacity=0.20, line_width=0)
    fig.add_vrect(x0=ASYM_YELLOW, x1=upper, fillcolor=FLAG_COLORS["red"], opacity=0.20, line_width=0)
    fig.add_vline(x=ASYM_GREEN, line_dash="dot", line_color=FLAG_COLORS["green"], opacity=0.7, line_width=1.5)
    fig.add_vline(x=ASYM_YELLOW, line_dash="dot", line_color=FLAG_COLORS["red"], opacity=0.7, line_width=1.5)
    fig.update_layout(
        height=max(280, 28 * len(values) + 90),
        margin=dict(l=10, r=40, t=10, b=20),
        xaxis=dict(
            title=dict(text="Asymetria (%)", font=dict(size=11, family="Archivo, sans-serif", color="#5E5E64")),
            range=[0, upper],
            gridcolor="rgba(14,14,16,0.06)",
            tickfont=dict(size=10, family="Archivo, sans-serif", color="#5E5E64"),
        ),
        yaxis=dict(
            automargin=True,
            tickfont=dict(size=10, family="Archivo, sans-serif", color="#0E0E10"),
        ),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
    )
    return fig


def asymmetry_bipolar_trend(
    per_day_signed: pd.Series, *, height: int = 110,
) -> go.Figure:
    """Bipolar bar trend per dzień — kolumny w górę (R, amber) lub w dół
    (L, blue) wg signed mean asymetrii. Strefy referencyjne (zielona ±10%,
    pomarańczowa ±10-15%, czerwona >±15%) + solid linia bazowa na 0.

    per_day_signed: Series indexed by date, mean signed % asymetrii per dzień
    (NIE abs — żeby widać direction L/R)."""
    if per_day_signed is None or per_day_signed.dropna().empty:
        return _empty_fig("brak danych")

    s = per_day_signed.dropna()
    _PL_MONTHS = {
        1: "sty", 2: "lut", 3: "mar", 4: "kwi", 5: "maj", 6: "cze",
        7: "lip", 8: "sie", 9: "wrz", 10: "paź", 11: "lis", 12: "gru",
    }

    def _fmt_date(d) -> str:
        try:
            ts = pd.Timestamp(d)
            return f"{ts.day} {_PL_MONTHS[ts.month]}"
        except Exception:
            return str(d)
    dates = [_fmt_date(d) for d in s.index]
    full_dates = [pd.Timestamp(d).strftime("%Y-%m-%d") for d in s.index]
    values = [float(v) for v in s.values]

    # Color per bar wg sign
    colors = [
        SIDE_L_COLOR if v < 0 else SIDE_R_COLOR if v > 0 else SIDE_NONE_COLOR
        for v in values
    ]

    abs_max = max(abs(v) for v in values) if values else 0
    y_top = max(abs_max * 1.20, ASYM_YELLOW + 5)

    # Bar text (magnitude wartość bezwzględna w pillu)
    text_vals = [f"{abs(v):.1f}%" for v in values]

    fig = go.Figure(
        go.Bar(
            x=dates, y=values, orientation="v",
            marker=dict(color=colors, line=dict(width=0)),
            text=text_vals,
            textposition="outside",
            textfont=dict(size=10, family="Archivo, sans-serif", color="#0E0E10"),
            hovertemplate=(
                "%{customdata[2]}<br>"
                "Asym: <b>%{customdata[0]:.1f}%</b><br>"
                "Strona: <b>%{customdata[1]}</b>"
                "<extra></extra>"
            ),
            customdata=[
                [abs(v), ("L" if v < 0 else "P" if v > 0 else "—"), fd]
                for v, fd in zip(values, full_dates)
            ],
        )
    )

    # Strefy symetryczne wokół 0 (mocniejsza opacity zgodnie z preferencją Filipa)
    fig.add_hrect(y0=-ASYM_GREEN, y1=ASYM_GREEN, fillcolor=FLAG_COLORS["green"], opacity=0.22, line_width=0)
    fig.add_hrect(y0=ASYM_GREEN, y1=ASYM_YELLOW, fillcolor=FLAG_COLORS["orange"], opacity=0.22, line_width=0)
    fig.add_hrect(y0=-ASYM_YELLOW, y1=-ASYM_GREEN, fillcolor=FLAG_COLORS["orange"], opacity=0.22, line_width=0)
    fig.add_hrect(y0=ASYM_YELLOW, y1=y_top, fillcolor=FLAG_COLORS["red"], opacity=0.22, line_width=0)
    fig.add_hrect(y0=-y_top, y1=-ASYM_YELLOW, fillcolor=FLAG_COLORS["red"], opacity=0.22, line_width=0)
    fig.add_hline(y=ASYM_GREEN, line_dash="dot", line_color=FLAG_COLORS["green"], opacity=0.6, line_width=1)
    fig.add_hline(y=-ASYM_GREEN, line_dash="dot", line_color=FLAG_COLORS["green"], opacity=0.6, line_width=1)
    fig.add_hline(y=ASYM_YELLOW, line_dash="dot", line_color=FLAG_COLORS["red"], opacity=0.6, line_width=1)
    fig.add_hline(y=-ASYM_YELLOW, line_dash="dot", line_color=FLAG_COLORS["red"], opacity=0.6, line_width=1)
    fig.add_hline(y=0, line_color="rgba(14,14,16,0.55)", line_width=1.2)

    fig.update_layout(
        height=height,
        margin=dict(l=12, r=12, t=24, b=32),
        xaxis=dict(
            showgrid=False,
            tickfont=dict(size=11, family="Archivo, sans-serif", color="#5E5E64"),
        ),
        yaxis=dict(
            range=[-y_top, y_top],
            showgrid=False,
            zeroline=False,
            visible=False,
            fixedrange=True,
        ),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
        bargap=0.05,
        barcornerradius=2,
    )
    fig.update_xaxes(type="category")
    # Specjalny przypadek: 1 dzień testowy → bar by zajął całą szerokość wykresu,
    # co wygląda jak słup obok wykresu, nie bar. Padding x-axis = 4 unity po każdej
    # stronie sprawia że bar (na pozycji 0) zajmuje ~1/9 szerokości — lekko szerszy
    # niż text "% pod nim".
    if len(values) == 1:
        fig.update_xaxes(range=[-4, 4])
    return fig


def asymmetry_vertical_column(
    magnitude: float, side: str | None, *, height: int = 100,
) -> go.Figure:
    """Mini vertical column z bipolarną osią — pokazuje pojedynczą asymetrię
    z aktualnej sesji. Kolumna w GÓRĘ = R (prawa), w DÓŁ = L (lewa).
    5 stref: zielona po środku (±10%), 2 pomarańczowe (±10-15%), 2 czerwone (>±15%).

    Używany w sekcji Asymmetry per kafelek metryki (zamiast linii trendu).
    """
    if pd.isna(magnitude):
        return _empty_fig("brak danych")

    mag = abs(float(magnitude))
    signed = -mag if side == "L" else mag
    color = (
        SIDE_L_COLOR if side == "L"
        else SIDE_R_COLOR if side == "R"
        else SIDE_NONE_COLOR
    )

    y_top = max(mag * 1.25, ASYM_YELLOW + 5)

    # Bar text z literą strony w kolorze (np. "13% P" gdzie P jest amber).
    side_letter = "L" if side == "L" else "P" if side == "R" else ""
    if side_letter:
        bar_text = [
            f"<b>{mag:.1f}%</b> <b style='color:{color}'>{side_letter}</b>"
        ]
    else:
        bar_text = [f"<b>{mag:.1f}%</b>"]

    fig = go.Figure(
        go.Bar(
            x=[""], y=[signed], orientation="v",
            marker=dict(color=color, line=dict(width=0)),
            text=bar_text,
            textposition="outside",
            textfont=dict(size=12, family="Archivo Black, sans-serif", color="#0E0E10"),
            hovertemplate=(
                f"Asymetria: <b>{mag:.1f}%</b><br>"
                f"Strona: <b>{side or '—'}</b>"
                "<extra></extra>"
            ),
            width=0.45,
        )
    )

    # Strefy symetryczne wokół 0: green pośrodku, 2× orange, 2× red
    fig.add_hrect(y0=-ASYM_GREEN, y1=ASYM_GREEN, fillcolor=FLAG_COLORS["green"], opacity=0.22, line_width=0)
    fig.add_hrect(y0=ASYM_GREEN, y1=ASYM_YELLOW, fillcolor=FLAG_COLORS["orange"], opacity=0.22, line_width=0)
    fig.add_hrect(y0=-ASYM_YELLOW, y1=-ASYM_GREEN, fillcolor=FLAG_COLORS["orange"], opacity=0.22, line_width=0)
    fig.add_hrect(y0=ASYM_YELLOW, y1=y_top, fillcolor=FLAG_COLORS["red"], opacity=0.22, line_width=0)
    fig.add_hrect(y0=-y_top, y1=-ASYM_YELLOW, fillcolor=FLAG_COLORS["red"], opacity=0.22, line_width=0)
    fig.add_hline(y=ASYM_GREEN, line_dash="dot", line_color=FLAG_COLORS["green"], opacity=0.5, line_width=1)
    fig.add_hline(y=-ASYM_GREEN, line_dash="dot", line_color=FLAG_COLORS["green"], opacity=0.5, line_width=1)
    fig.add_hline(y=ASYM_YELLOW, line_dash="dot", line_color=FLAG_COLORS["red"], opacity=0.5, line_width=1)
    fig.add_hline(y=-ASYM_YELLOW, line_dash="dot", line_color=FLAG_COLORS["red"], opacity=0.5, line_width=1)
    fig.add_hline(y=0, line_color="rgba(14,14,16,0.5)", line_width=1.2)

    # L / P labels po bokach osi 0 (P = prawa, Polish)
    fig.add_annotation(
        xref="paper", yref="y", x=0.02, y=y_top * 0.88,
        text=f"<b style='color:{SIDE_R_COLOR};'>P ▲</b>",
        showarrow=False, font=dict(size=10, family="JetBrains Mono, monospace"),
    )
    fig.add_annotation(
        xref="paper", yref="y", x=0.02, y=-y_top * 0.88,
        text=f"<b style='color:{SIDE_L_COLOR};'>L ▼</b>",
        showarrow=False, font=dict(size=10, family="JetBrains Mono, monospace"),
    )

    fig.update_layout(
        height=height,
        margin=dict(l=8, r=8, t=20, b=8),
        xaxis=dict(
            visible=False,
            fixedrange=True,
        ),
        yaxis=dict(
            visible=False,
            range=[-y_top, y_top],
            fixedrange=True,
            zeroline=False,
        ),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
        bargap=0.6,
    )
    return fig


def metric_trend_chart(
    sub: pd.DataFrame,
    metric_def: MetricDef,
    metric_col: str,
    athlete_col: str,
    date_col: str,
    side_col: str | None = None,
    all_athletes: list[str] | None = None,
    *,
    height: int = 230,
) -> go.Figure:
    """Mini wykres trendu pojedynczej metryki w czasie. Linia per zawodnik.

    Dla asymetrii: wartość bezwzględna + strefy 🟢🟡🔴 i progi 10/15%.
    Strona dominująca (L/R) w tooltipie.
    """
    cols = [athlete_col, date_col, metric_col]
    if side_col and side_col in sub.columns:
        cols.append(side_col)
    d = sub[cols].copy()
    d[metric_col] = pd.to_numeric(d[metric_col], errors="coerce")
    if metric_def.asymmetry:
        d[metric_col] = d[metric_col].abs()
    d = d.dropna(subset=[date_col, metric_col]).sort_values(date_col)

    if d.empty:
        return _empty_fig("brak danych")

    all_athletes = all_athletes or sorted(d[athlete_col].dropna().astype(str).unique().tolist())

    fig = go.Figure()
    for athlete, g in d.groupby(athlete_col):
        color = athlete_color(str(athlete), all_athletes)
        customdata = (
            g[side_col].fillna("—").astype(str).tolist()
            if side_col and side_col in g.columns
            else None
        )
        hovertemplate = (
            f"<b>{athlete}</b><br>"
            f"%{{x|%d %b %Y}}: <b>%{{y:.2f}}</b> {metric_def.unit}"
            + (f"<br>strona: %{{customdata}}" if customdata else "")
            + "<extra></extra>"
        )
        fig.add_trace(
            go.Scatter(
                x=g[date_col],
                y=g[metric_col],
                customdata=customdata,
                mode="lines+markers",
                name=str(athlete),
                line=dict(width=2.5, color=color),
                marker=dict(
                    size=9, color=color,
                    line=dict(width=2, color="#FAF8F2"),
                ),
                hovertemplate=hovertemplate,
            )
        )

    if metric_def.asymmetry:
        max_v = max(d[metric_col].max(), ASYM_YELLOW + 3)
        upper = max(max_v * 1.15, ASYM_YELLOW + 5)
        fig.add_hrect(y0=0, y1=ASYM_GREEN, fillcolor=FLAG_COLORS["green"], opacity=0.08, line_width=0)
        fig.add_hrect(y0=ASYM_GREEN, y1=ASYM_YELLOW, fillcolor=FLAG_COLORS["orange"], opacity=0.08, line_width=0)
        fig.add_hrect(y0=ASYM_YELLOW, y1=upper, fillcolor=FLAG_COLORS["red"], opacity=0.08, line_width=0)
        fig.add_hline(y=ASYM_GREEN, line_dash="dot", line_color=FLAG_COLORS["green"], opacity=0.5)
        fig.add_hline(y=ASYM_YELLOW, line_dash="dot", line_color=FLAG_COLORS["red"], opacity=0.5)
        fig.update_yaxes(range=[0, upper])

    fig.update_layout(
        template="plotly_white",
        height=height,
        margin=dict(l=10, r=10, t=10, b=10),
        showlegend=False,
        font=dict(family="Roboto, Archivo, sans-serif"),
        xaxis=dict(
            title="",
            showgrid=True,
            gridcolor="rgba(14,14,16,0.07)",
            tickfont=dict(size=11, color="#5E5E64"),
            tickformat="%d %b",
            showspikes=True,
            spikemode="across",
            spikecolor="rgba(14,14,16,0.25)",
            spikethickness=1,
            spikedash="dot",
        ),
        yaxis=dict(
            title=dict(
                text=metric_def.unit,
                font=dict(size=11, color="#5E5E64"),
            ),
            showgrid=True,
            gridcolor="rgba(14,14,16,0.07)",
            tickfont=dict(size=11, color="#5E5E64"),
            zeroline=False,
        ),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        hovermode="closest",
        hoverlabel=dict(
            bgcolor="#FFFFFF",
            bordercolor="rgba(14,14,16,0.15)",
            font=dict(size=12, family="Roboto, Archivo, sans-serif", color="#0E0E10"),
        ),
    )
    return fig


def key_metrics_timeline_chart(
    series_per_metric: dict,  # label -> pd.Series (indexed by datetime)
    metric_defs: dict,        # label -> MetricDef
) -> go.Figure:
    """Small-multiples grid kluczowych metryk w czasie.

    Każda metryka ma własny subplot z PRAWDZIWYMI wartościami (w jednostkach
    metryki), nie znormalizowane. Wcześniejsza wersja skalowała wszystko do
    własnego min-max 0–100% — wzmacniała szum, mieszała jednostki i była
    niewiarygodna. Tu każdy mini-wykres ma osobną oś Y dopasowaną do swojej
    metryki, tytuł z jednostką i hover z konkretną wartością.
    """
    # Filtruj puste serie
    items = [(label, series.dropna()) for label, series in series_per_metric.items()]
    items = [(lab, s) for lab, s in items if not s.empty]
    n = len(items)
    if n == 0:
        return _empty_fig("Brak danych do wykresu")

    # Layout: max 3 kolumny, dynamiczna liczba rzędów
    n_cols = min(3, n)
    n_rows = (n + n_cols - 1) // n_cols

    # Ciepłe kolory = MAX/Performance, chłodne = AVG/Strategy
    palette_max = ["#22c55e", "#facc15", "#f97316"]
    palette_avg = ["#06b6d4", "#a855f7", "#3b82f6", "#ec4899"]
    max_idx = 0
    avg_idx = 0

    # Tytuły subplotów: "Label (unit)"
    titles = []
    for label, _ in items:
        m = metric_defs[label]
        unit = f" [{m.unit}]" if m.unit else ""
        # Usuń wszystkie suffix-y agregacji — bardziej zwięźle
        clean_label = (label
                       .replace(" (peak/day)", "")
                       .replace(" (avg/day)", "")
                       .replace(" (max)", "")
                       .replace(" (avg)", ""))
        titles.append(f"{clean_label}{unit}")

    fig = make_subplots(
        rows=n_rows, cols=n_cols,
        subplot_titles=titles,
        horizontal_spacing=0.08,
        vertical_spacing=0.22,
    )

    for i, (label, s) in enumerate(items):
        row = i // n_cols + 1
        col = i % n_cols + 1
        m = metric_defs[label]
        # Kolor po sekcji metryki — performance ciepłe, strategy/asym chłodne
        is_perf = m.section == "performance"
        if is_perf:
            color = palette_max[max_idx % len(palette_max)]
            max_idx += 1
        else:
            color = palette_avg[avg_idx % len(palette_avg)]
            avg_idx += 1

        unit = m.unit or ""
        x_vals = list(s.index)
        y_vals = s.tolist()
        n_pts = len(y_vals)
        last_val = float(y_vals[-1])
        prev_val = float(y_vals[-2]) if n_pts > 1 else last_val

        # Procentowa zmiana: OSTATNIA sesja vs POPRZEDNIA (day-over-day),
        # nie vs pierwsza sesja. Inaczej wczesny warmup-test wykrzywia % na zawsze.
        if prev_val != 0 and n_pts > 1:
            delta_pct = (last_val - prev_val) / abs(prev_val) * 100.0
        else:
            delta_pct = 0.0

        # Kierunek "lepiej": dla higher_better wzrost = good, dla niżej_lepiej spadek = good.
        # Dla metryk strategy (neutral_direction=True) nie kolorujemy good/bad —
        # zmiana ma sens ale nie da się jednoznacznie nazwać "lepiej/gorzej".
        if abs(delta_pct) < 0.5:
            accent_color = "#94a3b8"
            arrow = "→"
        elif getattr(m, "neutral_direction", False):
            accent_color = "#94a3b8"     # szary — neutralna zmiana strategy
            arrow = "↑" if delta_pct > 0 else "↓"
        else:
            is_good = (delta_pct > 0) == m.higher_better
            accent_color = "#22c55e" if is_good else "#ef4444"
            arrow = "↑" if delta_pct > 0 else "↓"

        # Per-point delta % vs POPRZEDNI punkt (day-over-day) do hovera.
        # Pierwszy punkt: brak referencji → 0% (label "pierwsza sesja" w hoverze).
        # UWAGA: używam `j` nie `i` — outer enumerate ma `i` jako subplot index!
        deltas = [0.0]
        for j in range(1, n_pts):
            ref = float(y_vals[j - 1])
            if ref == 0:
                deltas.append(0.0)
            else:
                deltas.append((float(y_vals[j]) - ref) / abs(ref) * 100.0)
        customdata = [[unit, d] for d in deltas]

        # Główna linia z markerami — wszystkie punkty w kolorze metryki
        fig.add_trace(
            go.Scatter(
                x=x_vals, y=y_vals,
                mode="lines+markers",
                line=dict(color=color, width=2.5),
                marker=dict(
                    size=8, color=color,
                    line=dict(width=1.5, color="#FAF8F2"),
                ),
                customdata=customdata,
                showlegend=False,
                hovertemplate=(
                    "%{x|%d %b %Y %H:%M}<br>"
                    "<b>%{y:.2f}</b> %{customdata[0]}<br>"
                    "<span style='color:#94a3b8'>vs poprz. sesja: %{customdata[1]:+.1f}%</span>"
                    "<extra></extra>"
                ),
            ),
            row=row, col=col,
        )

        # Ostatni marker — wyróżniony, w kolorze trendu
        if n_pts > 1:
            fig.add_trace(
                go.Scatter(
                    x=[x_vals[-1]], y=[last_val],
                    mode="markers",
                    marker=dict(
                        size=14, color=accent_color,
                        line=dict(width=2, color="#FAF8F2"),
                    ),
                    showlegend=False, hoverinfo="skip",
                ),
                row=row, col=col,
            )

            # Linia bazowa: poziom POPRZEDNIEJ sesji (dashed) — wzrokowe odniesienie
            # do delta % nad ostatnim markerem.
            fig.add_hline(
                y=prev_val,
                line_dash="dot",
                line_color="rgba(14,14,16,0.25)",
                line_width=1,
                row=row, col=col,
            )

            # Annotation % vs POPRZEDNIA sesja — w PRAWYM GÓRNYM rogu subplot'u
            # (paper coords subplot), żeby nie zasłaniała wykresu. Wcześniej
            # była nad ostatnim markerem co przy gęstych liniach przykrywało dane.
            sign = "+" if delta_pct > 0 else ""
            if accent_color == "#22c55e":
                bg_tint = "rgba(34, 197, 94, 0.16)"
            elif accent_color == "#ef4444":
                bg_tint = "rgba(239, 68, 68, 0.14)"
            else:
                bg_tint = "rgba(255, 255, 255, 0.92)"
            axis_n = i + 1  # 1-indexed subplot index → xref/yref domain
            xref = "x domain" if axis_n == 1 else f"x{axis_n} domain"
            yref = "y domain" if axis_n == 1 else f"y{axis_n} domain"
            fig.add_annotation(
                x=0.98, y=0.96,
                xref=xref, yref=yref,
                text=f"<b>{arrow} {sign}{delta_pct:.1f}%</b>",
                showarrow=False,
                font=dict(size=11, color=accent_color, family="Archivo, sans-serif"),
                xanchor="right", yanchor="top",
                bgcolor=bg_tint,
                bordercolor=accent_color,
                borderwidth=1,
                borderpad=4,
            )

        # Y-axis: lekki margin nad/pod żeby linia nie kleiła się do krawędzi
        # (więcej padding górnego niż dolnego — miejsce na annotation)
        vmin, vmax = float(s.min()), float(s.max())
        if vmin == vmax:
            pad = abs(vmin) * 0.1 if vmin != 0 else 1.0
            yrange = [vmin - pad, vmax + pad]
        else:
            spread = vmax - vmin
            yrange = [vmin - spread * 0.15, vmax + spread * 0.30]
        fig.update_yaxes(
            range=yrange,
            row=row, col=col,
            showgrid=True,
            gridcolor="rgba(14,14,16,0.07)",
            tickfont=dict(size=10.5, color="#5E5E64"),
            zeroline=False,
        )
        fig.update_xaxes(
            row=row, col=col,
            showgrid=True,
            gridcolor="rgba(14,14,16,0.05)",
            tickfont=dict(size=10, color="#7A7A80"),
            tickformat="%d %b",
            nticks=4,
        )

    # Zmniejsz fonty tytułów subplotów, podsuń je trochę
    for ann in fig.layout.annotations:
        ann.font = dict(size=12, color="#1A1A1E")

    fig.update_layout(
        template="plotly_white",
        height=200 * n_rows + 40,
        margin=dict(l=30, r=20, t=40, b=20),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        hovermode="closest",
        font=dict(family="Roboto, Archivo, sans-serif"),
        hoverlabel=dict(
            bgcolor="#FFFFFF",
            bordercolor="rgba(14,14,16,0.15)",
            font=dict(size=12, family="Roboto, Archivo, sans-serif", color="#0E0E10"),
        ),
    )
    return fig


def metric_sparkline(
    per_day_series: pd.Series,
    metric_def: MetricDef,
    *,
    height: int = 70,
) -> go.Figure:
    """Mini wykres trendu pod kafelkiem metryki. Bez osi, bez tytułu —
    czysto linia + ostatni marker w kolorze trendu vs pierwsza sesja.

    per_day_series: index = datetime (jeden punkt per dzień), values = już zaagregowane
    (max dla performance, mean dla strategy/asymmetry — odpowiedzialność wyżej).
    """
    s = per_day_series.dropna() if per_day_series is not None else pd.Series(dtype=float)
    if s.empty or len(s) < 2:
        # Pojedynczy punkt lub brak — komunikat zamiast wykresu
        msg = "—" if s.empty else "1 sesja"
        fig = go.Figure()
        fig.update_layout(
            height=height,
            margin=dict(l=0, r=0, t=0, b=0),
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            xaxis=dict(visible=False),
            yaxis=dict(visible=False),
            annotations=[dict(
                text=f"<span style='color:#475569; font-size:10px;'>{msg}</span>",
                x=0.5, y=0.5, xref="paper", yref="paper",
                showarrow=False,
            )],
        )
        return fig

    x_vals = list(s.index)
    y_vals = s.tolist()
    last_val = float(y_vals[-1])
    prev_val = float(y_vals[-2]) if len(y_vals) > 1 else last_val

    # Delta % vs POPRZEDNIA sesja (day-over-day) — nie vs pierwsza, żeby
    # warmup-test sprzed roku nie wykrzywiał ostatniego trendu.
    if prev_val != 0 and len(y_vals) > 1:
        delta_pct = (last_val - prev_val) / abs(prev_val) * 100.0
    else:
        delta_pct = 0.0

    # Kolor trendu — analogicznie do key_metrics_timeline_chart
    if abs(delta_pct) < 0.5:
        accent = "#94a3b8"
    elif getattr(metric_def, "neutral_direction", False):
        accent = "#94a3b8"
    else:
        is_good = (delta_pct > 0) == metric_def.higher_better
        accent = "#22c55e" if is_good else "#ef4444"

    base_color = "rgba(148, 163, 184, 0.7)"  # szara linia tła
    unit = metric_def.unit or ""

    fig = go.Figure()

    # Strefy referencyjne dla ASYMETRII — green/orange/red horizontal bands.
    # Analogicznie do zbiorczego wykresu asymetrii (asymmetry_overview_bar).
    # Pomaga wzrokowo zobaczyć w którym zakresie jest aktualna asymetria
    # i czy zmienia się w czasie między strefami.
    if metric_def.asymmetry:
        # Y range musi obejmować pełny zakres stref żeby były widoczne nawet
        # przy niskich wartościach (np. wszystkie sesje <8% → bez tego red zone niewidoczny)
        vmin, vmax = float(s.min()), float(s.max())
        zone_max = max(vmax * 1.15, ASYM_YELLOW + 3)
        # Pomarańczowa nieco mocniejsza (#fbbf24 amber-400 = jaśniejsza wersja)
        # + wyższa opacity bo bazowy #f59e0b w 0.10 zlewał się z tłem.
        fig.add_hrect(y0=0, y1=ASYM_GREEN, fillcolor=FLAG_COLORS["green"],
                      opacity=0.20, line_width=0)
        fig.add_hrect(y0=ASYM_GREEN, y1=ASYM_YELLOW, fillcolor="#fbbf24",
                      opacity=0.22, line_width=0)
        fig.add_hrect(y0=ASYM_YELLOW, y1=zone_max, fillcolor=FLAG_COLORS["red"],
                      opacity=0.20, line_width=0)
        fig.add_hline(y=ASYM_GREEN, line_dash="dot",
                      line_color=FLAG_COLORS["green"], opacity=0.6, line_width=1.2)
        fig.add_hline(y=ASYM_YELLOW, line_dash="dot",
                      line_color=FLAG_COLORS["red"], opacity=0.6, line_width=1.2)

    # Linia bazowa = poprzednia sesja (referencja do delta na hoverze ostatniego marker'a).
    # Pomijamy dla asymetrii — strefy zielona/pomarańczowa/czerwona + ich linie graniczne
    # już dają punkt odniesienia, dodatkowa szara linia mogłaby wyglądać jak 4ta strefa.
    if not metric_def.asymmetry:
        fig.add_hline(
            y=prev_val, line_dash="dot",
            line_color="rgba(14,14,16,0.18)", line_width=1,
        )
    # Główna linia
    fig.add_trace(go.Scatter(
        x=x_vals, y=y_vals,
        mode="lines+markers",
        line=dict(color=base_color, width=1.8),
        marker=dict(size=4, color=base_color),
        hovertemplate=(
            "%{x|%Y-%m-%d}<br><b>%{y:.2f}</b> " + unit + "<extra></extra>"
        ),
    ))
    # Ostatni marker — duży, w kolorze trendu
    fig.add_trace(go.Scatter(
        x=[x_vals[-1]], y=[last_val],
        mode="markers",
        marker=dict(size=8, color=accent, line=dict(width=1.5, color="#FAF8F2")),
        hoverinfo="skip", showlegend=False,
    ))

    # Padding y-axis — dla asymetrii zakres rozszerzony żeby zmieścić wszystkie strefy
    vmin, vmax = float(s.min()), float(s.max())
    if metric_def.asymmetry:
        # Range: 0 do max(value, ASYM_YELLOW+3) — żeby widzieć przejście do czerwonej strefy
        ymax_asym = max(vmax * 1.15, ASYM_YELLOW + 3)
        yrange = [0, ymax_asym]
    elif vmin == vmax:
        pad = abs(vmin) * 0.1 if vmin != 0 else 1.0
        yrange = [vmin - pad, vmax + pad]
    else:
        spread = vmax - vmin
        yrange = [vmin - spread * 0.2, vmax + spread * 0.2]

    fig.update_layout(
        height=height,
        margin=dict(l=0, r=0, t=0, b=0),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
        xaxis=dict(visible=False, fixedrange=True),
        yaxis=dict(visible=False, fixedrange=True, range=yrange),
        hovermode="closest",
    )
    return fig


def _empty_fig(message: str) -> go.Figure:
    fig = go.Figure()
    fig.update_layout(
        template="plotly_white",
        height=230,
        annotations=[dict(text=message, showarrow=False, x=0.5, y=0.5, xref="paper", yref="paper")],
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        margin=dict(l=10, r=10, t=10, b=10),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig
