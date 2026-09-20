"""
Profile trenerów — dwa panele na tych samych planach i bazie ćwiczeń.

Filip 2026-09-02: „Coach Filip i Coach Kuba jako dwa różne panele. Baza
planów wspólna, baza ćwiczeń wspólna, ale zawodnicy i kolejka osobno".

Wybór siedzi w `st.session_state["coach"]`; dane sprzed podziału (profile
i zadania bez znacznika) należą do Filipa.
"""
from __future__ import annotations

import streamlit as st

COACHES: list[dict] = [
    {"id": "filip", "name": "Coach Filip", "initials": "F"},
    {"id": "kuba", "name": "Coach Kuba", "initials": "K"},
]
DEFAULT = "filip"

_BY_ID = {c["id"]: c for c in COACHES}


def current() -> str:
    """Id aktywnego trenera."""
    c = str(st.session_state.get("coach") or "").strip().lower()
    return c if c in _BY_ID else DEFAULT


def set_current(coach_id: str) -> None:
    c = str(coach_id or "").strip().lower()
    if c in _BY_ID:
        st.session_state["coach"] = c


def info(coach_id: str = "") -> dict:
    return _BY_ID.get((coach_id or current()).strip().lower(), _BY_ID[DEFAULT])


def name(coach_id: str = "") -> str:
    return info(coach_id)["name"]


def as_data() -> list[dict]:
    """Lista do przełącznika w powłoce."""
    return [dict(c) for c in COACHES]
