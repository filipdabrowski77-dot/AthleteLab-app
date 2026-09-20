"""
Panel rozpisywania planu treningowego — Streamlit custom component (bez Node, bez buildu).

Wygląd 1:1 z zatwierdzonym prototypem: cały panel rysuje `plan_panel/index.html`,
Python tylko podaje dane i odbiera zmieniony plan.

Użycie:

    from views.plan_panel import plan_panel

    @st.dialog("Plan treningowy", width="large")
    def workout_dialog(plan, workout):
        result = plan_panel(plan, workout)          # dict albo None
        if result:
            workout.update(result["workout"])       # zawsze aktualny stan planu
            if result.get("action") == "save":
                save_workout(plan, workout)         # <- Twoja funkcja zapisu JSON
                st.toast("Plan zapisany")
            if result.get("action") == "library":
                open_exercise_library(result["section"])   # <- Twój dialog Bazy ćwiczeń

Struktura katalogów (ważne — index.html musi leżeć w podfolderze):

    views/
      plan_panel.py
      plan_panel/
        index.html
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

import streamlit as st
import streamlit.components.v1 as components

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plan_panel")

_component = components.declare_component("plan_panel", path=_DIR)


def plan_panel(
    plan: Dict[str, Any],
    workout: Dict[str, Any],
    *,
    height: int = 1400,
    key: str = "plan_panel",
    **extra: Any,
) -> Optional[Dict[str, Any]]:
    """
    plan:    {"athlete": "Jan Kowalski", "name": "Blok 1"}
    workout: {"name", "date", "weeks", "exercises": [...]}  — model bez zmian:
             {"section": "Prep"|"Plyo & Power"|"Main", "slot", "exercise", "note",
              "tempo", "film", "weeks": {"1": {"sets_n","reps","intent","rest"}}}

    Zwraca None (brak interakcji) albo:
             {"workout": {...}, "action": "save"|"library"|None, "section": str}
    Panel sam liczy dziedziczenie dawek (pusty tydzień = ostatni wypełniony wcześniejszy),
    kopiowanie tygodni, dodawanie/usuwanie tygodni (2–8) i kolumnę Tempo (Main Strength).
    """
    return _component(plan=plan, workout=workout, default=None, height=height,
                      key=key, **extra)


# ---------------------------------------------------------------- demo / test
if __name__ == "__main__":
    st.set_page_config(layout="wide")
    demo_plan = {"athlete": "Jan Kowalski", "name": "Blok 1"}
    if "demo_workout" not in st.session_state:
        st.session_state.demo_workout = {
            "name": "Trening A", "date": "2026-07-20", "weeks": 4,
            "exercises": [
                {"section": "Prep", "slot": "", "exercise": "TH medball CARs", "note": "",
                 "tempo": "", "film": "https://youtu.be/x",
                 "weeks": {"1": {"sets_n": "1", "reps": "6", "intent": ""}}},
                {"section": "Prep", "slot": "", "exercise": "Pigeon on bench", "note": "",
                 "tempo": "", "film": "",
                 "weeks": {"1": {"sets_n": "1", "reps": "12-15", "intent": ""}}},
                {"section": "Plyo & Power", "slot": "", "exercise": "SL box jump", "note": "",
                 "tempo": "", "film": "https://youtu.be/y",
                 "weeks": {"1": {"sets_n": "2", "reps": "3", "intent": ""},
                           "2": {"sets_n": "2", "reps": "4", "intent": ""}}},
                {"section": "Main", "slot": "1a", "exercise": "Zercher reverse lunge",
                 "note": "przednia noga wstaje", "tempo": "", "film": "https://youtu.be/z",
                 "weeks": {"1": {"sets_n": "3", "reps": "8", "intent": "rpe 7"},
                           "3": {"sets_n": "3", "reps": "7", "intent": "rpe 8"}}},
                {"section": "Main", "slot": "1b", "exercise": "Swiss ball leg curl",
                 "note": "", "tempo": "3 sec ecc", "film": "https://youtu.be/q",
                 "weeks": {"1": {"sets_n": "2", "reps": "10-15", "intent": "rpe 8"}}},
            ],
        }

    res = plan_panel(demo_plan, st.session_state.demo_workout)
    if res:
        st.session_state.demo_workout.update(res["workout"])
        if res.get("action") == "save":
            st.toast("Plan zapisany (demo)")
        if res.get("action") == "library":
            st.toast(f"Baza ćwiczeń: {res.get('section')}")
