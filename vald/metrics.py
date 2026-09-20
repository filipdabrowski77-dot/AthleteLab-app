"""
Definicje metryk per typ testu — pogrupowane w sekcje:
  • performance — co zawodnik osiąga (output)
  • strategy    — jak to osiąga (technika, strategia ruchu)
  • asymmetry   — równowaga L/R

Każda metryka pasowana do kolumny CSV przez słowa kluczowe (substring,
case-insensitive). To pozwala obsłużyć różne warianty eksportu ForceDecks
(z jednostkami, z dodatkowymi spacjami itd.).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd


@dataclass
class MetricDef:
    name: str
    keywords: list[str]
    unit: str = ""
    higher_better: bool = True
    asymmetry: bool = False
    section: str = "performance"  # "performance" | "strategy" | "asymmetry"
    # Dla metryk gdzie kierunku zmiany nie da się jednoznacznie sklasyfikować
    # jako "lepiej/gorzej" (np. głębokość zejścia, czas trwania fazy).
    # Delta pokazywana neutralnie szarym kolorem.
    neutral_direction: bool = False
    pl_label: str = ""
    desc: str = ""

    @property
    def label(self) -> str:
        return self.pl_label or self.name


# Progi flagowania asymetrii L/R (%)
ASYM_GREEN = 10.0
ASYM_YELLOW = 15.0


# ─────────────────────────────────────────────────────────────────────────────
# CMJ — Counter Movement Jump (19 metryk z formatu Trial Summary ForceDecks)
# ─────────────────────────────────────────────────────────────────────────────

CMJ_PERFORMANCE: list[MetricDef] = [
    MetricDef(
        name="Jump Height",
        keywords=["jump height (imp-mom)", "jump height"],
        unit="cm",
        section="performance",
        pl_label="Jump Height",
        desc="Wysokość skoku liczona metodą impulse-momentum (z impulsu siły).",
    ),
    MetricDef(
        name="mRSI",
        # UWAGA: biblioteka ma DWIE kolumny zaczynające się od „RSI-modified":
        #   „RSI-modified (Imp-Mom)"        = Jump Height (Imp-Mom) / Contraction Time
        #   „RSI-modified (Imp-Mom) [m/s] " = liczone z wysokości z czasu lotu
        # Mimo etykiety „(Imp-Mom)" ta druga daje wartości wyższe średnio o 9,1%
        # (do +22% na pojedynczej próbie, 517 prób CMJ). Bez tego pierwszego
        # keyworda dopasowanie po prefiksie brało wariant „[m/s]" — kafelki,
        # trendy i PB pokazywały zawyżony RSI-mod (Filip 2026-09-04).
        keywords=["rsi-modified (imp-mom)", "rsi-modified", "rsi modified", "mrsi"],
        unit="m/s",
        section="performance",
        pl_label="RSI-mod",
        desc="Modified Reactive Strength Index — wysokość skoku / czas skurczu. "
             "Wskaźnik łączący wynik i tempo wykonania.",
    ),
    MetricDef(
        name="Peak Power / BM",
        keywords=["peak power / bm"],
        unit="W/kg",
        section="performance",
        pl_label="Peak Power / BM",
        desc="Moc szczytowa w fazie koncentrycznej znormalizowana do masy ciała.",
    ),
    MetricDef(
        name="Concentric Mean Force / BW",
        keywords=["concentric mean force / bw"],
        unit="× BW",
        section="performance",
        pl_label="Conc. Mean Force / BW",
        desc="Średnia siła w fazie koncentrycznej w jednostkach masy ciała.",
    ),
    MetricDef(
        name="Force at Zero Velocity / BM",
        keywords=["force at zero velocity"],
        unit="N/kg",
        section="performance",
        pl_label="Force @ V=0",
        desc="Siła w punkcie zwrotnym (najniższa pozycja, prędkość = 0) — "
             "moment przejścia z ekscentryki w koncentrykę.",
    ),
    MetricDef(
        name="Eccentric Deceleration RFD / BM",
        keywords=["eccentric deceleration rfd / bm"],
        unit="N/s/kg",
        section="performance",
        pl_label="Ecc. Decel RFD / BM",
        desc="Tempo narastania siły w fazie hamowania zejścia — agresywność "
             "powstrzymywania ruchu countermovement. Wskaźnik mocy generowanej "
             "w fazie ekscentrycznej.",
    ),
]

CMJ_STRATEGY: list[MetricDef] = [
    MetricDef(
        name="Eccentric Peak Velocity",
        keywords=["eccentric peak velocity"],
        unit="m/s",
        higher_better=False,
        neutral_direction=True,
        section="strategy",
        pl_label="Ecc. Peak Velocity",
        desc="Maksymalna prędkość zejścia (ujemna). Strategia ruchu — nie ma "
             "jednoznacznego 'lepiej/gorzej'.",
    ),
    MetricDef(
        name="Countermovement Depth",
        keywords=["countermovement depth"],
        unit="cm",
        higher_better=False,
        neutral_direction=True,
        section="strategy",
        pl_label="CM Depth",
        desc="Głębokość zejścia przed odbiciem (ujemna). Strategia ruchu — "
             "zbyt płytkie i zbyt głębokie obniża efektywność.",
    ),
    MetricDef(
        name="Eccentric Duration",
        keywords=["eccentric duration"],
        unit="ms",
        higher_better=False,
        neutral_direction=True,
        section="strategy",
        pl_label="Ecc. Duration",
        desc="Czas trwania fazy ekscentrycznej. Strategia ruchu — krócej zwykle "
             "= reaktywniej, ale zależy od profilu zawodnika.",
    ),
    MetricDef(
        name="Contraction Time",
        keywords=["contraction time"],
        unit="ms",
        higher_better=False,
        neutral_direction=True,
        section="strategy",
        pl_label="Contraction Time",
        desc="Całkowity czas skurczu. Strategia ruchu — krótszy zwykle "
             "= eksplozywniej, ale to nie zawsze 'lepiej'.",
    ),
]

CMJ_ASYMMETRY: list[MetricDef] = [
    MetricDef(
        name="Eccentric Mean Force Asymmetry",
        keywords=["eccentric mean force % (asym)"],
        unit="%",
        higher_better=False,
        asymmetry=True,
        section="asymmetry",
        pl_label="Ecc. Mean Force",
        desc="Asymetria średniej siły ekscentrycznej (faza zejścia).",
    ),
    MetricDef(
        name="Eccentric Braking Impulse Asymmetry",
        keywords=["eccentric braking impulse % (asym)"],
        unit="%",
        higher_better=False,
        asymmetry=True,
        section="asymmetry",
        pl_label="Ecc. Braking Impulse",
        desc="Asymetria impulsu w fazie hamowania (od max prędkości zejścia do zwrotu).",
    ),
    MetricDef(
        name="Eccentric Deceleration Impulse Asymmetry",
        keywords=["eccentric deceleration impulse % (asym)"],
        unit="%",
        higher_better=False,
        asymmetry=True,
        section="asymmetry",
        pl_label="Ecc. Decel Impulse",
        desc="Asymetria impulsu deceleracji.",
    ),
    MetricDef(
        name="Eccentric Deceleration RFD Asymmetry",
        keywords=["eccentric deceleration rfd % (asym)"],
        unit="%",
        higher_better=False,
        asymmetry=True,
        section="asymmetry",
        pl_label="Ecc. Decel RFD",
        desc="Asymetria szybkości narastania siły w hamowaniu.",
    ),
    MetricDef(
        name="Force at Zero Velocity Asymmetry",
        keywords=["force at zero velocity % (asym)"],
        unit="%",
        higher_better=False,
        asymmetry=True,
        section="asymmetry",
        pl_label="F@V=0 Asym",
        desc="Asymetria siły w punkcie zerowej prędkości (przejście ekscentryka→koncentryka). "
             "Klasyfikowana w fazie eccentric, bo to moment kończący hamowanie zejścia.",
    ),
    MetricDef(
        name="Concentric Impulse Asymmetry",
        keywords=["concentric impulse % (asym)"],
        unit="%",
        higher_better=False,
        asymmetry=True,
        section="asymmetry",
        pl_label="Concentric Impulse",
        desc="Kluczowa asymetria — impuls w fazie odbicia. Bezpośrednio przekłada "
             "się na różnicę siły wkładanej przez nogi w skok.",
    ),
    MetricDef(
        name="Concentric Impulse-100ms Asymmetry",
        keywords=["concentric impulse-100ms % (asym)"],
        unit="%",
        higher_better=False,
        asymmetry=True,
        section="asymmetry",
        pl_label="Conc. Impulse-100ms",
        desc="Asymetria impulsu w pierwszych 100 ms fazy koncentrycznej "
             "— szybkość generowania siły.",
    ),
    MetricDef(
        name="P1 Concentric Impulse Asymmetry",
        keywords=["p1 concentric impulse % (asym)"],
        unit="%",
        higher_better=False,
        asymmetry=True,
        section="asymmetry",
        pl_label="P1 Conc. Impulse",
        desc="Asymetria pierwszej połowy fazy koncentrycznej (inicjacja odbicia).",
    ),
    MetricDef(
        name="P2 Concentric Impulse Asymmetry",
        keywords=["p2 concentric impulse % (asym)"],
        unit="%",
        higher_better=False,
        asymmetry=True,
        section="asymmetry",
        pl_label="P2 Conc. Impulse",
        desc="Asymetria drugiej połowy fazy koncentrycznej (przed oderwaniem).",
    ),
    MetricDef(
        name="Peak Landing Force Asymmetry",
        keywords=["peak landing force % (asym)"],
        unit="%",
        higher_better=False,
        asymmetry=True,
        section="asymmetry",
        pl_label="Peak Landing Force",
        desc="Asymetria szczytowej siły lądowania — kluczowe dla ryzyka kontuzji "
             "po wylądowaniu.",
    ),
]

CMJ_METRICS: list[MetricDef] = CMJ_PERFORMANCE + CMJ_STRATEGY + CMJ_ASYMMETRY


# ─────────────────────────────────────────────────────────────────────────────
# Pozostałe testy — placeholdery, doszlifujemy gdy dostaniemy realne CSV
# ─────────────────────────────────────────────────────────────────────────────

# Vald ForceDecks SJ (Squat Jump) — z założenia BEZ FAZY EKSCENTRYCZNEJ
# (atleta startuje z półprzysiadu, nie schodzi w dół). Stąd:
# - PERFORMANCE: 4 metryki (Jump Height + 3 concentric — Power/Force/RFD)
# - STRATEGY: nie dotyczy tego testu (placeholder w UI)
# - ASYMMETRY: 4 metryki asymetrii concentrycznych + landing force
SJ_PERFORMANCE: list[MetricDef] = [
    MetricDef(
        name="Jump Height",
        keywords=["jump height (imp-mom)", "jump height"],
        unit="cm",
        section="performance",
        pl_label="Jump Height",
        desc="Wysokość skoku liczona metodą impulse-momentum.",
    ),
    MetricDef(
        name="Concentric Peak Power / BM",
        # VALD ForceDecks dla SJ nie eksportuje 'Concentric Peak Power / BM'
        # jako pure value (0/25 rows). Używa 'Peak Power / BM [W/kg]' (25/25 OK).
        # Fallback keyword "peak power / bm" trafia tę kolumnę.
        keywords=["peak power / bm", "concentric peak power / bm"],
        unit="W/kg",
        section="performance",
        pl_label="Concentric Peak Power / BM",
        desc="Moc szczytowa w fazie koncentrycznej znormalizowana do masy ciała.",
    ),
    MetricDef(
        name="Concentric Peak Force",
        # 'Concentric Peak Force' (pure N, 25/25 OK dla SJ).
        # Match_column z guardami (asym/side/ratio) trafia pure value.
        keywords=["concentric peak force"],
        unit="N",
        section="performance",
        pl_label="Concentric Peak Force",
        desc="Szczytowa siła w fazie koncentrycznej (odbicia).",
    ),
    MetricDef(
        name="Concentric RFD 100",
        # VALD eksportuje 'Concentric RFD - 100ms' (25/25 OK dla SJ).
        # Główny keyword z myślnikiem żeby trafić tę kolumnę. Fallback bez
        # myślnika dla compatibility z innymi nazewnictwami.
        keywords=["concentric rfd - 100ms", "concentric rfd 100ms", "concentric rfd 100"],
        unit="N/s",
        section="performance",
        pl_label="Concentric RFD 100",
        desc="Rate of Force Development w pierwszych 100 ms fazy koncentrycznej.",
    ),
]

# Strategy: BRAK metryk dla SJ (z założenia testu — bez fazy ekscentrycznej).
# Pusta lista — UI pokaże placeholder "Nie dotyczy tego testu".
SJ_STRATEGY: list[MetricDef] = []

SJ_ASYMMETRY: list[MetricDef] = [
    MetricDef(
        name="Concentric Impulse Asymmetry",
        keywords=["concentric impulse % (asym)"],
        unit="%",
        higher_better=False,
        asymmetry=True,
        section="asymmetry",
        pl_label="Concentric Impulse",
        desc="Kluczowa asymetria — impuls w fazie odbicia. Bezpośrednio przekłada "
             "się na różnicę siły wkładanej przez nogi.",
    ),
    MetricDef(
        name="Concentric Peak Force Asymmetry",
        keywords=["concentric peak force % (asym)"],
        unit="%",
        higher_better=False,
        asymmetry=True,
        section="asymmetry",
        pl_label="Concentric Peak Force",
        desc="Asymetria peak force w fazie koncentrycznej — który bok produkuje "
             "więcej siły szczytowej.",
    ),
    MetricDef(
        name="P1 Concentric Impulse Asymmetry",
        keywords=["p1 concentric impulse % (asym)"],
        unit="%",
        higher_better=False,
        asymmetry=True,
        section="asymmetry",
        pl_label="P1 Conc. Impulse",
        desc="Asymetria pierwszej połowy fazy koncentrycznej (inicjacja odbicia).",
    ),
    MetricDef(
        name="P2 Concentric Impulse Asymmetry",
        keywords=["p2 concentric impulse % (asym)"],
        unit="%",
        higher_better=False,
        asymmetry=True,
        section="asymmetry",
        pl_label="P2 Conc. Impulse",
        desc="Asymetria drugiej połowy fazy koncentrycznej (przed oderwaniem).",
    ),
    MetricDef(
        name="Peak Landing Force Asymmetry",
        keywords=["peak landing force % (asym)"],
        unit="%",
        higher_better=False,
        asymmetry=True,
        section="asymmetry",
        pl_label="Peak Landing Force",
        desc="Asymetria szczytowej siły lądowania — kluczowe dla ryzyka kontuzji "
             "po wylądowaniu.",
    ),
]

SJ_METRICS: list[MetricDef] = SJ_PERFORMANCE + SJ_STRATEGY + SJ_ASYMMETRY

# IMTP — Isometric Mid-Thigh Pull. Test izometryczny (brak fazy eccentric/concentric).
# - PERFORMANCE: 4 metryki (Peak Force abs + relative + force@100/200ms relative)
# - STRATEGY: nie dotyczy (test izometryczny, brak fazy ruchu)
# - ASYMMETRY: 5 metryk (Peak + 50/100/150/200ms L/R %)
IMTP_PERFORMANCE: list[MetricDef] = [
    MetricDef(
        name="Peak Force",
        keywords=["peak vertical force"],
        unit="N",
        section="performance",
        pl_label="Peak Force",
        desc="Szczytowa siła wertykalna w pull'u — gold standard IMTP (Comfort 2019, Beckham 2018).",
    ),
    MetricDef(
        name="Peak Force / BM",
        keywords=["peak vertical force / bm"],
        unit="N/kg",
        section="performance",
        pl_label="Peak Force / BM",
        desc="Peak Force znormalizowana do masy ciała. Strefy: <22 słabo, 22-30 średnio, "
             "30-35 dobrze, >35 elite.",
    ),
    MetricDef(
        name="Force at 100ms / BM",
        keywords=["force at 100ms / bm"],
        unit="N/kg",
        section="performance",
        pl_label="Force @ 100ms / BM",
        desc="Siła wyprodukowana w pierwszych 100 ms — wskaźnik eksplozywności startowej.",
    ),
    MetricDef(
        name="Force at 200ms / BM",
        keywords=["force at 200ms / bm"],
        unit="N/kg",
        section="performance",
        pl_label="Force @ 200ms / BM",
        desc="Siła w 200 ms — wskaźnik szybkości rozwoju siły w przedziale "
             "istotnym dla sprintu/skoku (Haff 2015).",
    ),
]

IMTP_STRATEGY: list[MetricDef] = []

IMTP_ASYMMETRY: list[MetricDef] = [
    MetricDef(
        name="Peak Force Asymmetry",
        keywords=["peak vertical force % (asym)"],
        unit="%",
        higher_better=False,
        asymmetry=True,
        section="asymmetry",
        pl_label="Peak Force",
        desc="Asymetria szczytowej siły między nogami — kluczowy wskaźnik kontuzjowy "
             "i RTS-ready (Bishop 2018).",
    ),
    MetricDef(
        name="Force at 50ms Asymmetry",
        keywords=["force at 50ms % (asym)"],
        unit="%",
        higher_better=False,
        asymmetry=True,
        section="asymmetry",
        pl_label="Force @ 50ms",
        desc="Asymetria F50 — UWAGA: niższa reliability niż F100/F150/F200 "
             "(Dos'Santos 2018). Traktować jako uzupełnienie, nie main flag.",
    ),
    MetricDef(
        name="Force at 100ms Asymmetry",
        keywords=["force at 100ms % (asym)"],
        unit="%",
        higher_better=False,
        asymmetry=True,
        section="asymmetry",
        pl_label="Force @ 100ms",
        desc="Asymetria siły w 100 ms — eksplozywność startowa, kluczowa dla sprintu/akceleracji.",
    ),
    MetricDef(
        name="Force at 150ms Asymmetry",
        keywords=["force at 150ms % (asym)"],
        unit="%",
        higher_better=False,
        asymmetry=True,
        section="asymmetry",
        pl_label="Force @ 150ms",
        desc="Asymetria siły w 150 ms — środkowa faza rozwoju siły.",
    ),
    MetricDef(
        name="Force at 200ms Asymmetry",
        keywords=["force at 200ms % (asym)"],
        unit="%",
        higher_better=False,
        asymmetry=True,
        section="asymmetry",
        pl_label="Force @ 200ms",
        desc="Asymetria siły w 200 ms — istotna dla skoku/sprintu w przedziale "
             "rzeczywistego czasu kontaktu z podłożem.",
    ),
]

IMTP_METRICS: list[MetricDef] = IMTP_PERFORMANCE + IMTP_STRATEGY + IMTP_ASYMMETRY

HOP_METRICS: list[MetricDef] = [
    MetricDef(
        name="Best RSI",
        keywords=["best rsi"],
        unit="",
        section="performance",
        pl_label="Best RSI",
        desc="Najwyższy Reactive Strength Index (Flight/Contact Time) z testu. "
             "Wskaźnik reaktywności — jak szybko zawodnik konwertuje kontakt "
             "z podłożem na czas lotu.",
    ),
    MetricDef(
        name="Mean RSI",
        keywords=["mean rsi"],
        unit="",
        section="performance",
        pl_label="Mean RSI",
        desc="Średni RSI ze wszystkich repów — typowa reaktywność z całego "
             "testu, nie tylko best.",
    ),
    MetricDef(
        name="Best Jump Height",
        keywords=["best jump height"],
        unit="cm",
        section="performance",
        pl_label="Best Jump Height",
        desc="Najwyższy wyskok z testu (mierzony z czasu lotu).",
    ),
    MetricDef(
        name="Best Contact Time",
        keywords=["best contact time"],
        unit="ms",
        higher_better=False,
        section="strategy",
        pl_label="Best Contact Time",
        desc="Najkrótszy czas kontaktu z podłożem — strategia/technika "
             "reaktywności w najlepszym repie.",
    ),
    MetricDef(
        name="Mean Contact Time",
        keywords=["mean contact time"],
        unit="ms",
        higher_better=False,
        section="strategy",
        pl_label="Mean Contact Time",
        desc="Średni czas kontaktu z podłożem — typowa technika z całego testu.",
    ),
]

# DJ (Drop Jump) — kafelki Best/Mean RSI obliczane bezpośrednio z per-rep RSI
# (Flight Time/Contact Time) w `_render_dj_special_key_tiles`. Brak standardowych
# MetricDef'ów — VALD nie eksportuje agregatów typu "Best RSI" w CSV dla DJ
# (każdy wiersz = pojedyncze powtórzenie). Rendering specjalny analogiczny do HOP.
DJ_METRICS: list[MetricDef] = []

# RSAIP (Run Specific Ankle Iso Push) — analog IMTP per noga.
# Rendering custom: każda metryka pokazywana jednocześnie dla L i R obok siebie
# w jednym kafelku (TrialLimb=Left/Right rozróżnia repy tego samego testu).
RSAIP_METRICS: list[MetricDef] = []

# RSKIP (Run Specific Knee Iso Push) — analog RSAIP, te same metryki + ten sam
# rendering (L|R obok siebie). Różni się tylko biomechaniką testu (kolano vs kostka).
RSKIP_METRICS: list[MetricDef] = []

METRICS_BY_TEST: dict[str, list[MetricDef]] = {
    "CMJ": CMJ_METRICS,
    "SJ": SJ_METRICS,
    "IMTP": IMTP_METRICS,
    "HOP": HOP_METRICS,
    "DJ": DJ_METRICS,
    "RSAIP": RSAIP_METRICS,
    "RSKIP": RSKIP_METRICS,
}


# ─────────────────────────────────────────────────────────────────────────────
# Helpery
# ─────────────────────────────────────────────────────────────────────────────

def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s).strip()).lower()


def match_column(df: pd.DataFrame, metric: MetricDef) -> str | None:
    """Znajdź pierwszą kolumnę pasującą do metryki przez słowa kluczowe.

    Defensywny guard:
    1) Jeśli metryka NIE jest asymetrią, pomija kolumny z "(asym)" (i odwrotnie).
       Bez tego np. "force at zero velocity" mogłoby dopasować
       "Force at Zero Velocity % (Asym)" jeśli pojawi się wcześniej w CSV.
    2) Pomija RATIO columns (zawierają ":" w nazwie, np.
       "Braking Phase Duration:Contraction Time", "Flight Time:Contraction Time",
       "Contraction Time:Eccentric Duration"). Bug 2026-05-20: substring
       "contraction time" trafiał ratio column PRZED prawdziwym
       "Contraction Time [ms]", pokazując zawodnikowi ~42ms zamiast ~725ms.

    Priorytety dopasowania:
    a) Exact match (normalized full equality)
    b) Starts-with + non-alphanumeric boundary (typowy VALD pattern:
       "Contraction Time [ms]", "Jump Height (Imp-Mom)" — keyword + unit suffix)
    c) Substring fallback
    """
    def _allowed(col_name: str) -> bool:
        lower = col_name.lower().rstrip()
        has_asym = "asym" in lower
        if has_asym != bool(metric.asymmetry):
            return False
        # Ratio columns (zawierają ":") nigdy nie są pure metric values.
        if ":" in col_name:
            return False
        # Side variants "(L)" / "(R)" — używane explicitnie w side analysis
        # (asymmetry tiles z label "L"/"R"), nie traktujemy ich jako pure value.
        # Bug 2026-05-20: keyword "force at zero velocity" trafiał "Force at
        # Zero Velocity (L)" zamiast "Force at Zero Velocity / BM [N/kg]".
        if lower.endswith("(l)") or lower.endswith("(r)"):
            return False
        return True

    norm_cols = {_norm(c): c for c in df.columns if _allowed(c)}
    for kw in metric.keywords:
        kw_n = _norm(kw)
        # 1. Exact match
        for nc, original in norm_cols.items():
            if kw_n == nc:
                return original
        # 2. Starts-with + non-alphanumeric boundary
        #    ("contraction time" matches "contraction time [ms]" but NOT
        #    "contraction time efficiency"). Wymaga że po keywordzie jest
        #    znak nieliterowy/cyfra (typically space, "[", "(", end of string).
        for nc, original in norm_cols.items():
            if nc.startswith(kw_n):
                next_idx = len(kw_n)
                if next_idx == len(nc) or not nc[next_idx].isalnum():
                    return original
        # 3. Substring fallback (loose match)
        for nc, original in norm_cols.items():
            if kw_n in nc:
                return original
    return None


def resolve_metrics(
    df: pd.DataFrame, test_type: str, section: str | None = None
) -> list[tuple[MetricDef, str]]:
    """Dopasuj kanoniczne metryki do kolumn CSV. Filtruj po sekcji jeśli podana."""
    metrics = METRICS_BY_TEST.get(test_type, [])
    if section:
        metrics = [m for m in metrics if m.section == section]
    resolved: list[tuple[MetricDef, str]] = []
    seen: set[str] = set()
    for m in metrics:
        col = match_column(df, m)
        if col and col not in seen:
            resolved.append((m, col))
            seen.add(col)
    return resolved


def asymmetry_flag(value: float) -> str:
    """Zwróć kolor flagi dla wartości asymetrii (%): green / orange / red / gray."""
    if pd.isna(value):
        return "gray"
    v = abs(float(value))
    if v < ASYM_GREEN:
        return "green"
    if v < ASYM_YELLOW:
        return "orange"
    return "red"


