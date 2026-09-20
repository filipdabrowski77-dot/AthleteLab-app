"""
Athletic Performance Hub — app shell jako Streamlit custom component.

Rysuje: Start, Training Plans (Plany / Nowy plan), Plan zawodnika,
Baza ćwiczeń (Wszystkie / Bez filmu / Bez kategorii), Performance testing
oraz modal „Ćwiczenie". Wygląd 1:1 z zatwierdzonym designem — cały UI jest
w `app_shell/index.html`, Python podaje tylko dane i obsługuje akcje.

Użycie:

    from views.app_shell import app_shell

    ev = app_shell(screen="start", data=build_data())
    if ev:
        if ev["action"] == "open_plan":
            st.session_state.plan_id = ev["id"];  st.rerun()
        if ev["action"] == "open_workout":
            open_workout_dialog(ev["plan_id"], ev["letter"])
        ...

Struktura katalogów (index.html MUSI leżeć w podfolderze o tej nazwie):

    views/
      app_shell.py
      app_shell/
        index.html
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

import streamlit.components.v1 as components

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app_shell")
_component = components.declare_component("aph_app_shell", path=_DIR)


def app_shell(
    screen: str = "start",
    data: Optional[Dict[str, Any]] = None,
    *,
    height: int = 900,
    key: str = "app_shell",
    **extra: Any,
) -> Optional[Dict[str, Any]]:
    """
    screen: "start" | "plans" | "plan" | "exercises" | "testing"
    data:   słownik jak w sekcji `let D = {...}` w index.html (kontrakt niżej)

    Zwraca None (brak interakcji) albo {"action": ..., "screen": ..., ...}:
      navigate      {to}
      open_plan     {id}
      open_workout  {plan_id, letter}
      queue_add     {item:{name, plan, date}}
      queue_open    {item}
      queue_del     {index}
      create_plan   {form:{athlete, new_athlete, name, start, weeks}}
      pdf           {plan_id}
      copy_link     {url}
      add_workout   {plan_id}
      edit_exercise {name}
      save_exercise {form:{name, cat, intensity, film}}
      save_film     {name, url}
      save_cat      {name, cat, intensity}
    """
    return _component(screen=screen, data=data or {}, default=None, height=height, key=key, **extra)


# ---------------------------------------------------------------- kontrakt danych
#
# data = {
#   "user":   {"name": str, "initials": str},
#   "stats":  {"plans": int, "plans_active": int, "athletes": int, "no_film": int},
#   "queue":  [{"date": "03.09", "name": str, "plan": str}],
#   "recent": [{"initials": "AM", "plan": str, "meta": str, "id": str}],
#   "athletes_list": [str],
#   "plans":  [{"date": "02.09.2026", "name": str, "athlete": str,
#               "status": "Trwa"|"Szkic"|"Zamknięty", "id": str}],
#   "plan":   {"id": str, "name": str, "athlete": str, "status": str, "range": str,
#              "weeks": int, "share_url": str,
#              "workouts": [{"letter": "A", "name": str, "count": int, "no_film": int}]},
#   "exercises": [{"name": str, "cat": "Movement Prep"|"Plyometrics"|"Strength"|"Nieprzypisane",
#                  "intensity": "—"|"easy"|"medium"|"high / max", "has_film": bool}],
#   "exercises_total": int,
#   "no_film":  [{"name": str, "plans": str}],  "no_film_total": int,
#   "no_cat":   [{"name": str}],                "no_cat_total": int,
#   "testing":  [{"name": str, "date": str, "cmj": str, "asym": str,
#                 "asym_level": "ok"|"warn"|"bad"}],
# }
#
# Każdy klucz jest opcjonalny — brakujące pola zostają na danych demo z index.html,
# więc komponent nigdy nie renderuje pustej strony podczas wdrażania.


if __name__ == "__main__":
    import streamlit as st

    st.set_page_config(layout="wide", page_title="APH — app shell")
    st.markdown(
        "<style>section.main > div{padding:0!important} "
        "div[data-testid='stAppViewBlockContainer']{padding:0!important;max-width:100%!important}"
        "header[data-testid='stHeader']{display:none}</style>",
        unsafe_allow_html=True,
    )
    st.session_state.setdefault("screen", "start")
    ev = app_shell(screen=st.session_state.screen, height=980)
    if ev:
        if ev["action"] == "navigate":
            st.session_state.screen = ev["to"]
        elif ev["action"] in ("open_plan", "queue_open"):
            st.session_state.screen = "plan"
            st.rerun()
        else:
            st.toast(str(ev))
