"""
Tryb trenera na telefonie — lista ćwiczeń z wpisywaniem serii
(Streamlit custom component, bez Node i bez buildu).

Cały interfejs rysuje `trener_panel/index.html`; Python podaje dane
(vald/ui_training.py → _trk_dane) i odbiera operacje (_trk_konsumuj →
_trk_zastosuj). Komponent istnieje, bo przez API Streamlita 1.50 nie da się
dać polom klawiatury numerycznej (inputmode) ani celów dotyku 44 px.

Kontrakt — argumenty (każdy klucz na najwyższym poziomie `args`):

    ctx        {"plan_id", "sess_id", "wk"}
    sekcje     [{"key", "tytul", "acc", "tint", "zwinieta"}]   w kolejności
    karty      [{"i",            indeks pozycji w sesji — adres zapisu
                 "exercise", "section",
                 "slot",         treść kółka (P1… w Prep, 1a/1b w Main)
                 "dawka",        „3 × 7"
                 "intent",       „rpe 7"
                 "det",          „Rest 2-3 min · Tempo … · uwaga"
                 "n_plan",       ile wierszy serii z rozpiski (min. 1)
                 "reps_plan",    [powt. per seria do jednego stuknięcia ✓; "" = nie wstawiaj]
                 "reps_hint",    rozpiska powtórzeń do placeholdera („8-12")
                 "ostatnio",     „W1: 70×7 · 80×7 · 85×6" (bez słowa „Ostatnio")
                 "kg_hint",      kg pierwszej serii z „ostatnio" — tylko placeholder
                 "serie",        [{"kg","reps","rpe","stan": "ok"|"skip"|""}]
                 "notatka"}]
    status     {"stan": "Zaplanowany"|"W toku"|"Zapisany", "data": „27.09"|""}
    ack        [id operacji zapisanych albo już wcześniej zapisanych]
    odrzucone  [{"id", "powod"}]
    blad       tekst błędu zapisu ("" = brak)

Wartość zwracana (setComponentValue):

    {"seq": "IID-n", "iid": "IID", "ops": [...wszystkie niepotwierdzone...]}
    {"id", "typ": "cwiczenie", "t", "plan_id", "sess_id", "wk", "i", "exercise",
     "serie": [{"kg","reps","rpe","stan"}], "notatka": str|null}
    {"id", "typ": "koniec", "t", "plan_id", "sess_id", "wk"}

W danych nie ma adresów URL — tryb trenera to prosty widok bez filmów.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

import streamlit as st
import streamlit.components.v1 as components

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trener_panel")
_component = None


def trener_panel(
    dane: Dict[str, Any],
    *,
    key: str = "trk_panel",
    height: int = 900,
) -> Optional[Dict[str, Any]]:
    """Rysuje komponent. Deklaracja leniwa: bez index.html (interfejs jeszcze
    nie wgrany) apka pokazuje komunikat zamiast wywracać się przy imporcie."""
    global _component
    if not os.path.isfile(os.path.join(_DIR, "index.html")):
        st.warning("Brak interfejsu trybu trenera (views/trener_panel/index.html).")
        return None
    if _component is None:
        _component = components.declare_component("trener_panel", path=_DIR)
    return _component(**dane, default=None, height=height, key=key)
