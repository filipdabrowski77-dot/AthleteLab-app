"""
Dyktando planu → dane apki (Filip 2026-09-10).

Trzy rzeczy, które psuły rozpisywanie z głosu:
1. Nazwy ćwiczeń — dyktafon przekręca („rumuński pociąg"), Filip mówi
   synonimami („rumuński martwy ciąg" = Barbell RDL). `dopasuj_nazwe`
   szuka w Bazie po aliasach i podobieństwie; potwierdzone przekręcenia
   zapisuje `dodaj_alias`, więc następnym razem trafiają od razu.
2. Zapis dawek — pięć systemów Filipa, zawsze w tej samej notacji, którą
   edytor (views/plan_panel) czyta do sets_n / reps / intent:
     powtórzenia   2 x 10-15 @ rpe 9
     czas          2 x 30-45 sec
     top set       top set 1 x 3 @ rpe 9 + 2 x 5 @ rpe 7
     cluster       cluster 3 x (2 x 1) / 30 s
     test siły     test 3RM
   Dodatkowo: serie po serii (1 x 5 @ rpe 9 + 2 x 5 @ rpe 8) i AMRAP.
3. Tempo vs uwagi — „3 sec ecc" to tempo (kolumna w Main), „do upadku",
   „na przepalenie" to uwagi.

Format pliku dyktanda (to, co asystent spisuje z tego, co Filip mówi):

    plan: Jan Kowalski | GPP 1 | 2026-09-14 | 4 | folder: Klub
    trening: A
    prep
    - 90/90 | 1x8-10
    - hip airplane | 1x10-12 | uwagi: powoli
    plyo
    - 1a broad jump | 2x3 | 2x4 | 2x5
    main
    - 1a rumuński martwy ciąg => Barbell RDL | top set 1x3 rpe 9 + 2x5 rpe 7 | tempo: 3 sec ecc
    - 1b swiss ball leg curl | 2x10-15 rb 9 | uwagi: do upadku

Kolejne `|` z dawką to kolejne tygodnie (W1, W2, …); pusty tydzień
dziedziczy w apce sam. `=> Nazwa` to jawne wskazanie wpisu z Bazy — zapis
planu utrwala je jako alias. `!` na końcu nazwy = ćwiczenie nowe, wpisz
dosłownie, nie szukaj w Bazie.
"""
from __future__ import annotations

import difflib
import json
import re
from datetime import date

from .library import LIBRARY_DIR

# ---------------------------------------------------------------- liczebniki
_LICZ = {
    "zero": 0, "jeden": 1, "jedna": 1, "jedno": 1, "dwa": 2, "dwie": 2, "trzy": 3,
    "cztery": 4, "pięć": 5, "piec": 5, "sześć": 6, "szesc": 6, "siedem": 7,
    "osiem": 8, "dziewięć": 9, "dziewiec": 9, "dziesięć": 10, "dziesiec": 10,
    "jedenaście": 11, "dwanaście": 12, "trzynaście": 13, "czternaście": 14,
    "piętnaście": 15, "pietnascie": 15, "szesnaście": 16, "siedemnaście": 17,
    "osiemnaście": 18, "dziewiętnaście": 19, "dwadzieścia": 20, "dwadziescia": 20,
    "trzydzieści": 30, "trzydziesci": 30, "czterdzieści": 40, "czterdziesci": 40,
    "pięćdziesiąt": 50, "piecdziesiat": 50, "sześćdziesiąt": 60, "szescdziesiat": 60,
    "siedemdziesiąt": 70, "osiemdziesiąt": 80, "dziewięćdziesiąt": 90, "sto": 100,
    "piątka": 5, "piatka": 5, "trójka": 3, "trojka": 3, "szóstka": 6, "ósemka": 8,
    "dziesiątka": 10, "dwunastka": 12,
}
_LICZ_RE = re.compile(r"\b(" + "|".join(sorted(map(re.escape, _LICZ), key=len,
                                                reverse=True)) + r")\b", re.I)


def _slowa_na_liczby(t: str) -> str:
    """„dwadzieścia pięć" → 25, „dwa" → 2. Dziesiątki + jedności sklejamy."""
    def zam(m):
        return str(_LICZ[m.group(1).lower()])
    t = _LICZ_RE.sub(zam, t)
    # „20 5" (z „dwadzieścia pięć") → 25; tylko dziesiątka + jedność
    t = re.sub(r"\b([2-9]0) ([1-9])\b", lambda m: str(int(m.group(1)) + int(m.group(2))), t)
    return t


def _oczysc(t: str) -> str:
    t = (t or "").strip()
    t = _slowa_na_liczby(t)
    t = t.replace("–", "-").replace("—", "-").replace("×", "x")
    t = re.sub(r"\bmyślnik\b|\bmyslnik\b", "-", t, flags=re.I)
    t = re.sub(r"\brazy\b", "x", t, flags=re.I)
    t = re.sub(r"\b(rb|rp|rpe|erpe)\b\.?", "rpe", t, flags=re.I)
    t = re.sub(r"\b(sekund|sekundy|sekundę|sek|s)\b\.?", "sec", t, flags=re.I)
    t = re.sub(r"\b(powtórzeń|powtórzenia|powtórzenie|powt|reps?)\b\.?", "", t, flags=re.I)
    t = re.sub(r"\b(serie|serii|seria)\b", "", t, flags=re.I)
    t = re.sub(r"\s*-\s*", "-", t)            # 10 - 15 → 10-15
    t = re.sub(r"(\d)\s*x\s*(\d)", r"\1 x \2", t, flags=re.I)
    t = re.sub(r"(\d)x", r"\1 x", t)
    t = re.sub(r"\s+", " ", t).strip(" ,.")
    return t


_ZAKRES = r"\d+(?:-\d+)?"
_RPE = rf"rpe\s*({_ZAKRES}(?:/\d+)?)"


def _dawka_prosta(t: str) -> str | None:
    """N x reps [sec] [@ rpe R] — systemy 1 i 2 (powtórzenia / czas)."""
    m = re.match(rf"^({_ZAKRES}) x ({_ZAKRES})\s*(sec)?\s*(?:(?:@\s*)?{_RPE}|@\s*(.+))?$",
                 t, flags=re.I)
    if not m:
        return None
    serie, reps, sec, rpe, inny = m.groups()
    out = f"{serie} x {reps}" + (" sec" if sec else "")
    if rpe:
        out += f" @ rpe {rpe}"
    elif inny:
        out += f" @ {inny.strip()}"
    return out


def normalizuj_dawke(tekst: str) -> str:
    """Jedna notacja dawki dla edytora i PDF. Nierozpoznane → tekst po
    oczyszczeniu (liczby, x, rpe), żeby nic nie ginęło."""
    t = _oczysc(tekst)
    if not t:
        return ""
    low = t.lower()

    # 5. test siły: „dojście do 3RM", „test 3 RM", „3RM"
    m = re.search(r"(?:dojście do|dojscie do|test)?\s*(\d+)\s*rm\b", low)
    if m and ("rm" in low) and not re.search(r"\bx\b", low):
        # RPE przy teście zostaje („test 5RM @ rpe 9" — Filip 2026-09-16
        # dyktuje próg bezpieczeństwa razem z testem)
        r = re.search(_RPE, low)
        return f"test {m.group(1)}RM" + (f" @ rpe {r.group(1)}" if r else "")

    # 4. cluster — w edytorze to jedno pole opisowe („3 x (3 x 1) / 20 s"),
    #    więc zapis „3x(2x1)/30s" ujednolicamy, a dyktowany opis („3 serie
    #    2 powt 30 sec przerwy") zostaje słowami, tylko z liczbami i sec
    if low.startswith("cluster"):
        m = re.match(r"^cluster\s*(\d+)\s*x\s*\(\s*(\d+)\s*x\s*(\d+)\s*\)\s*/\s*(\d+)\s*(?:sec|s)?$",
                     low)
        if m:
            return "cluster {} x ({} x {}) / {} s".format(*m.groups())
        opis = _slowa_na_liczby(tekst.strip())
        opis = re.sub(r"\b(sekund|sekundy|sekundę|sek)\b\.?", "sec", opis, flags=re.I)
        opis = re.sub(r"\b(powtórzeń|powtórzenia|powtórzenie)\b", "powt", opis, flags=re.I)
        opis = re.sub(r"^cluster[:\s]*", "", opis, flags=re.I)
        return "cluster " + " ".join(opis.split())

    # 3. top set + back-off
    if low.startswith("top set") or low.startswith("topset"):
        reszta = re.sub(r"^top\s*set\s*", "", t, flags=re.I)
        czesci = re.split(r"\s*(?:\+|,|back[- ]?off|back set|backoff)\s*", reszta, flags=re.I)
        czesci = [c for c in czesci if c.strip()]
        znorm = [_dawka_prosta(c.strip()) or c.strip() for c in czesci]
        return "top set " + " + ".join(znorm)

    # AMRAP
    if low.startswith("amrap"):
        return "AMRAP " + t[5:].strip()

    # serie po serii: „1 x 5 rpe 9 + 2 x 5 rpe 8", „ciężka 5 rpe 9"
    low2 = re.sub(r"^(ciężka|ciezka|ciężkie|ciezkie)\s+(\d+)", r"1 x \2", low)
    if low2 != low:
        t, low = _oczysc(low2), low2
    czesci = [c.strip() for c in re.split(r"\s*\+\s*", t) if c.strip()]
    if len(czesci) > 1:
        znorm = [_dawka_prosta(c) for c in czesci]
        if all(znorm):
            return " + ".join(znorm)

    # 1 i 2: powtórzenia / czas
    d = _dawka_prosta(t)
    if d:
        return d
    # „30 sec" bez serii → 1 x 30 sec; „5 rpe 8" → 1 x 5 @ rpe 8
    m = re.match(rf"^({_ZAKRES})\s*(sec)?\s*(?:{_RPE})?$", t, flags=re.I)
    if m:
        reps, sec, rpe = m.groups()
        return f"1 x {reps}" + (" sec" if sec else "") + (f" @ rpe {rpe}" if rpe else "")
    return t


# ---------------------------------------------------------------- tempo / uwagi
_TEMPO_RE = re.compile(r"^\s*(\d+)\s*(sec|s|sek)?\s*(ecc|exc|ekscentr\w*|iso|conc|konc\w*|pauz\w*|pause)\b",
                       re.I)


def tempo_czy_uwaga(tekst: str) -> tuple[str, str]:
    """(tempo, uwaga): „3 sec ecc" → tempo; „do upadku" → uwaga."""
    t = _oczysc(tekst)
    if not t:
        return "", ""
    m = _TEMPO_RE.match(t)
    if m:
        return t, ""
    return "", tekst.strip()


# ---------------------------------------------------------------- nazwy
# synonimy z dyktanda → tokeny, jakimi posługuje się Baza
_SYNONIMY = {
    "martwy ciąg": "dl", "martwyciąg": "dl", "martwe ciągi": "dl",
    "rumuński": "rdl", "rumunski": "rdl", "romanian": "rdl",
    "jednonóż": "sl", "jednonoz": "sl", "single leg": "sl", "na jednej nodze": "sl",
    "wykrok": "lunge", "przysiad": "squat", "hantle": "db", "hantla": "db",
    "sztanga": "barbell", "kettel": "kettlebell", "kettla": "kettlebell",
    "guma": "band", "gumą": "band", "z gumą": "band", "medball": "medball",
    "piłka lekarska": "medball", "overhead press": "ohp", "wyciskanie nad głowę": "ohp",
    "podciąganie": "pull up", "pompka": "push up", "pompki": "push up",
    "deska": "plank", "plank bokiem": "side plank", "łydki": "calf", "łydka": "calf",
    "wspięcia": "calf raise", "hip lift off": "hip flexor lift off",
    "half kneeling": "half kneeling", "klęk": "kneeling",
    "bułgarski": "bulgarian split squat", "bulgarski": "bulgarian split squat",
    "przysiad bułgarski": "bulgarian split squat", "wykrok tylny": "reverse lunge",
    "wykrok w tył": "reverse lunge", "wykrok boczny": "lateral lunge",
    "mostek": "bridge", "mostek biodrowy": "hip thrust", "brzuszki": "sit-up",
    "kołyska": "deadbug", "wyskok": "jump", "skok w dal": "broad jump",
    "przysiad ze sztangą": "back squat", "przysiad przedni": "front squat",
    # kierunki — Filip dyktuje po polsku, Baza ma angielskie (2026-09-16)
    "do tyłu": "backward", "w tył": "backward", "tyłem": "backward",
    "do przodu": "forward", "w przód": "forward", "przód": "forward",
    "w bok": "lateral", "na boki": "lateral", "boczny": "lateral",
    "boczne": "lateral", "w miejscu": "in place",
}
_STOP = {"na", "z", "w", "do", "i", "the", "with", "of", "&", "+", "-"}


def _tokeny(nazwa: str) -> list[str]:
    t = (nazwa or "").lower()
    t = t.replace("'", "").replace("’", "")
    for a, b in sorted(_SYNONIMY.items(), key=lambda kv: -len(kv[0])):
        t = re.sub(rf"\b{re.escape(a)}\b", b, t)
    t = re.sub(r"[()/,.:;]", " ", t)
    return [x for x in t.split() if x and x not in _STOP]


def _podobienstwo(a: str, b: str) -> float:
    ta, tb = _tokeny(a), _tokeny(b)
    if not ta or not tb:
        return 0.0
    sa, sb = set(ta), set(tb)
    jacc = len(sa & sb) / len(sa | sb)
    seq = difflib.SequenceMatcher(None, " ".join(ta), " ".join(tb)).ratio()
    zlepek = difflib.SequenceMatcher(None, "".join(ta), "".join(tb)).ratio()
    # tokeny podobne literowo (przekręcenie dyktafonu) liczą się połowicznie
    blisko = sum(1 for x in sa if x not in sb and
                 any(difflib.SequenceMatcher(None, x, y).ratio() >= 0.8 for y in sb))
    jacc2 = (len(sa & sb) + 0.5 * blisko) / len(sa | sb)
    wynik = max(jacc, jacc2) * 0.6 + seq * 0.4
    if zlepek >= 0.7:                 # „hiberplane" ↔ „hipairplane" = 0.76
        wynik = max(wynik, zlepek * 0.8)
    return wynik


def dopasuj_nazwe(tekst: str, nazwy: list[str], aliasy: dict | None = None,
                  ile: int = 3) -> dict:
    """{'nazwa': str, 'pewnosc': float, 'kandydaci': [(nazwa, pewnosc), …],
    'zrodlo': 'baza'|'alias'|'podobne'|'brak'}. Pewność 1.0 tylko przy
    trafieniu dosłownym albo przez alias."""
    t = " ".join((tekst or "").split())
    low = t.lower()
    aliasy = aliasy or {}
    po_nazwie = {n.lower(): n for n in nazwy}
    if low in po_nazwie:
        return {"nazwa": po_nazwie[low], "pewnosc": 1.0, "kandydaci": [], "zrodlo": "baza"}
    if low in aliasy and aliasy[low].lower() in po_nazwie:
        return {"nazwa": po_nazwie[aliasy[low].lower()], "pewnosc": 1.0,
                "kandydaci": [], "zrodlo": "alias"}
    oceny = sorted(((n, _podobienstwo(t, n)) for n in nazwy), key=lambda x: -x[1])[:ile]
    oceny = [(n, round(s, 2)) for n, s in oceny if s > 0.3]
    if not oceny:
        return {"nazwa": t, "pewnosc": 0.0, "kandydaci": [], "zrodlo": "brak"}
    return {"nazwa": oceny[0][0], "pewnosc": oceny[0][1], "kandydaci": oceny,
            "zrodlo": "podobne"}


# ---------------------------------------------------------------- aliasy
_ALIAS_KEY = "exercise_aliases"
ALIAS_PATH = LIBRARY_DIR / "exercise_aliases.json"


def aliasy() -> dict:
    from . import store
    if store.enabled():
        d = store.kv_get(_ALIAS_KEY) or {}
    else:
        try:
            d = json.load(open(ALIAS_PATH, encoding="utf-8"))
        except Exception:
            d = {}
    return {str(k).lower(): str(v) for k, v in (d.get("aliasy") or {}).items()}


def dodaj_alias(alias: str, nazwa: str) -> None:
    from . import store
    alias = " ".join((alias or "").split()).lower()
    nazwa = " ".join((nazwa or "").split())
    if not alias or not nazwa or alias == nazwa.lower():
        return
    d = aliasy()
    d[alias] = nazwa
    if store.enabled():
        store.kv_put(_ALIAS_KEY, {"aliasy": d})
    else:
        ALIAS_PATH.parent.mkdir(parents=True, exist_ok=True)
        json.dump({"aliasy": d}, open(ALIAS_PATH, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)


# ---------------------------------------------------------------- parser pliku
_SEKCJE = {"prep": "Prep", "movement prep": "Prep", "rozgrzewka": "Prep",
           "plyo": "Plyo & Power", "plyo & power": "Plyo & Power", "plyo and power": "Plyo & Power",
           "power": "Plyo & Power", "main": "Main", "część główna": "Main", "glowna": "Main",
           "główna": "Main", "conditioning": "Conditioning", "kondycja": "Conditioning",
           "akcesoria": "Main"}


def parsuj_dyktando(tekst: str) -> dict:
    """Plik dyktanda → {'plan': {...}, 'treningi': [{'title', 'items': [...]}]}.
    Pozycja: {'section','slot','tekst','wskazana','nowe','dawki':[…],'tempo','note'}."""
    plan = {"athlete": "", "name": "", "start": "", "weeks": 4, "group": ""}
    treningi: list[dict] = []
    sekcja = "Main"
    for nr, linia in enumerate(tekst.splitlines(), 1):
        l = linia.strip()
        if not l or l.startswith("#"):
            continue
        low = l.lower()
        if low.startswith("plan:"):
            pola = [p.strip() for p in l[5:].split("|")]
            for i, p in enumerate(pola):
                if p.lower().startswith("folder:"):
                    plan["group"] = p.split(":", 1)[1].strip()
                elif i == 0:
                    plan["athlete"] = p
                elif i == 1:
                    plan["name"] = p
                elif re.match(r"^\d{4}-\d{2}-\d{2}$", p):
                    plan["start"] = p
                elif re.match(r"^\d+(\s*(tyg|tygodnie|tygodni|weeks?))?$", p, re.I):
                    plan["weeks"] = int(re.match(r"\d+", p).group())
            continue
        if low.startswith("trening:"):
            treningi.append({"title": l.split(":", 1)[1].strip(), "items": []})
            sekcja = "Prep"
            continue
        if low in _SEKCJE:
            sekcja = _SEKCJE[low]
            continue
        if l.startswith("-"):
            if not treningi:
                treningi.append({"title": "", "items": []})
            pola = [p.strip() for p in l[1:].split("|")]
            glowa = pola[0]
            m = re.match(r"^(\d+[a-hA-H]?)\s+(.+)$", glowa)
            slot, nazwa = (m.group(1), m.group(2)) if m else ("", glowa)
            wskazana = ""
            if "=>" in nazwa:
                nazwa, wskazana = [x.strip() for x in nazwa.split("=>", 1)]
            nowe = nazwa.endswith("!")
            nazwa = nazwa.rstrip("!").strip()
            it = {"section": sekcja, "slot": slot, "tekst": nazwa, "wskazana": wskazana,
                  "nowe": nowe, "dawki": [], "tempo": "", "note": "", "linia": nr}
            for p in pola[1:]:
                pl = p.lower()
                if pl.startswith("tempo:"):
                    it["tempo"] = p.split(":", 1)[1].strip()
                elif pl.startswith("uwagi:") or pl.startswith("uwaga:"):
                    it["note"] = p.split(":", 1)[1].strip()
                elif pl.startswith("w") and re.match(r"^w\d+\s*:", pl):
                    # jawny tydzień: „w3: 3 x 5"
                    nr_t = int(re.match(r"^w(\d+)", pl).group(1))
                    while len(it["dawki"]) < nr_t:
                        it["dawki"].append("")
                    it["dawki"][nr_t - 1] = p.split(":", 1)[1].strip()
                else:
                    it["dawki"].append(p)
            treningi[-1]["items"].append(it)
            continue
        raise ValueError(f"linia {nr}: nie rozumiem: {linia!r}")
    return {"plan": plan, "treningi": treningi}


# ---------------------------------------------------------------- budowa planu
def rozstrzygnij(pozycje: list[dict], nazwy: list[str], aliasy_: dict) -> list[dict]:
    """Dopisuje do każdej pozycji 'nazwa', 'pewnosc', 'kandydaci', 'zrodlo'."""
    po_nazwie = {n.lower(): n for n in nazwy}
    for it in pozycje:
        if it.get("nowe"):
            it.update({"nazwa": it["tekst"], "pewnosc": 1.0, "kandydaci": [], "zrodlo": "nowe"})
        elif it.get("wskazana"):
            w = it["wskazana"]
            if w.lower() not in po_nazwie:
                it.update({"nazwa": w, "pewnosc": 0.0, "kandydaci": [],
                           "zrodlo": "wskazana-brak"})
            else:
                it.update({"nazwa": po_nazwie[w.lower()], "pewnosc": 1.0,
                           "kandydaci": [], "zrodlo": "wskazana"})
        else:
            it.update(dopasuj_nazwe(it["tekst"], nazwy, aliasy_))
        it["dawki_norm"] = [normalizuj_dawke(d) if d else "" for d in it["dawki"]]
        if not it.get("tempo") and it.get("note"):
            tmp, uw = tempo_czy_uwaga(it["note"])
            if tmp:
                it["tempo"], it["note"] = tmp, uw
    return pozycje


def _dawka_na_tydzien(d: str) -> dict:
    """Ten sam podział, co textToDose w edytorze: „N x reps @ intent"."""
    m = re.match(r"^(\d+(?:-\d+)?)\s*x\s*([^@]*?)\s*(?:@\s*(.+))?$", d)
    if m:
        return {"sets_n": m.group(1), "reps": m.group(2).strip(),
                "intent": (m.group(3) or "").strip(), "rest": ""}
    return {"sets_n": "", "reps": d, "intent": "", "rest": ""}


def zbuduj_items(pozycje: list[dict]) -> list[dict]:
    from .training import normalize_slots
    items = []
    for it in pozycje:
        weeks = {}
        for i, d in enumerate(it["dawki_norm"], 1):
            if d:
                weeks[str(i)] = _dawka_na_tydzien(d)
        items.append({"section": it["section"], "slot": it.get("slot", ""),
                      "exercise": it["nazwa"], "note": it.get("note", ""),
                      "tempo": it.get("tempo", ""), "weeks": weeks})
    return normalize_slots(items)


def zapisz_plan(dane: dict, prog: float = 0.999) -> dict:
    """Tworzy plan w bazie apki. Rzuca ValueError, gdy któraś nazwa nie jest
    rozstrzygnięta (pewność < prog) — najpierw popraw plik (`=> Nazwa` albo `!`)."""
    from . import exlib
    from .training import create_plan, new_id, upsert_plan
    nazwy = [e["name"] for e in exlib.exercises()]
    al = aliasy()
    p = dane["plan"]
    if not (p["athlete"] and p["name"]):
        raise ValueError("nagłówek 'plan:' musi mieć zawodnika i nazwę planu")
    niepewne = []
    for tr in dane["treningi"]:
        rozstrzygnij(tr["items"], nazwy, al)
        niepewne += [it for it in tr["items"] if it["pewnosc"] < prog]
    if niepewne:
        raise ValueError("nierozstrzygnięte nazwy: " + ", ".join(
            f"{it['tekst']!r} (linia {it['linia']})" for it in niepewne))
    start = date.fromisoformat(p["start"]) if p["start"] else date.today()
    plan = create_plan(p["athlete"], p["name"], start, int(p["weeks"] or 4),
                       group=p.get("group", ""))
    import datetime as _dt
    plan["created"] = _dt.datetime.now().isoformat(timespec="seconds")
    plan["in_base"] = None
    plan["sessions"] = []
    for i, tr in enumerate(dane["treningi"]):
        plan["sessions"].append({
            "id": new_id(), "title": tr["title"] or f"Trening {chr(65 + i)}",
            "items": zbuduj_items(tr["items"]), "done_date": "", "plan_date": ""})
    upsert_plan(plan)
    # profil zawodnika — bez niego plan nie pokazuje się w Podopiecznych ani
    # w profilu, do którego zawodnik odklikuje treningi (2026-09-18:
    # plany z dyktanda były niewidoczne na liście podopiecznych)
    from .shell import _przypisz_zawodnika
    _przypisz_zawodnika(plan["athlete"])
    # utrwal potwierdzone dopasowania: „=> Nazwa" i aliasy z dyktanda
    for tr in dane["treningi"]:
        for it in tr["items"]:
            if it["zrodlo"] == "wskazana" and it["tekst"].lower() != it["nazwa"].lower():
                dodaj_alias(it["tekst"], it["nazwa"])
    return plan


def raport(dane: dict) -> str:
    """Tabela do potwierdzenia: co usłyszałem → co wybrałem → pewność → dawki."""
    from . import exlib
    nazwy = [e["name"] for e in exlib.exercises()]
    al = aliasy()
    linie = []
    p = dane["plan"]
    linie.append(f"PLAN: {p['athlete']} | {p['name']} | start {p['start'] or 'dziś'} | "
                 f"{p['weeks']} tyg." + (f" | folder {p['group']}" if p['group'] else ""))
    for tr in dane["treningi"]:
        rozstrzygnij(tr["items"], nazwy, al)
        linie.append(f"\nTRENING {tr['title'] or '?'}")
        sek = None
        for it in tr["items"]:
            if it["section"] != sek:
                sek = it["section"]
                linie.append(f"  [{sek}]")
            znak = {"baza": "=", "alias": "≈", "wskazana": "→", "nowe": "+",
                    "podobne": "?", "brak": "✗", "wskazana-brak": "✗"}[it["zrodlo"]]
            kand = ""
            if it["zrodlo"] == "podobne":
                kand = "   kandydaci: " + ", ".join(f"{n} ({s})" for n, s in it["kandydaci"])
            dawki = " | ".join(d or "·" for d in it["dawki_norm"]) or "—"
            extra = (f"   tempo: {it['tempo']}" if it["tempo"] else "") + \
                    (f"   uwagi: {it['note']}" if it["note"] else "")
            linie.append(f"  {it.get('slot') or ' ':>3} {znak} {it['tekst']:<38} → "
                         f"{it['nazwa']:<38} {it['pewnosc']:.2f}   {dawki}{extra}{kand}")
    linie.append("\nznaki: = w Bazie, ≈ alias, → wskazane, + nowe, ? podobne (potwierdź), ✗ brak")
    return "\n".join(linie)
