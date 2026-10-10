"""
Lista „Do rozpisania" na stronie startowej — proste zadania trenera:
komu rozpisać plan, do kiedy, z odliczaniem dni i odhaczaniem.

Plik: ~/Documents/ValdLibrary/plan_todos.json
Wpis: {id, text, due: "YYYY-MM-DD"|"", done: bool, created}
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import date

from .library import LIBRARY_DIR, daily_backup

TODOS_PATH = LIBRARY_DIR / "plan_todos.json"
_STORE_KEY = "plan_todos"


def _load() -> dict:
    from . import store
    if store.enabled():
        data = store.kv_get(_STORE_KEY) or {"todos": []}
        if not (isinstance(data, dict) and isinstance(data.get("todos"), list)):
            return {"todos": []}
        return data
    if not TODOS_PATH.exists():
        return {"todos": []}
    try:
        with open(TODOS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"{TODOS_PATH.name} jest uszkodzony — przywróć kopię z "
            f"{TODOS_PATH.parent / 'backups'}/") from e
    if not (isinstance(data, dict) and isinstance(data.get("todos"), list)):
        return {"todos": []}
    return data


def _save(data: dict) -> None:
    from . import store
    if store.enabled():
        store.kv_put(_STORE_KEY, data)
        return
    daily_backup(TODOS_PATH)
    TODOS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = TODOS_PATH.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, TODOS_PATH)


def list_todos(include_done: bool = False, coach: str = "") -> list[dict]:
    """Zadania posortowane: najpierw z terminem (najbliższe), potem bez.
    `coach` filtruje kolejkę do jednego panelu (puste = Coach Filip)."""
    todos = _load()["todos"]
    if not include_done:
        todos = [t for t in todos if not t.get("done")]
    if coach:
        c = coach.strip().lower()
        todos = [t for t in todos
                 if (t.get("coach") or "").strip().lower() == c
                 or (not t.get("coach") and c == "filip")]
    return sorted(todos, key=lambda t: (t.get("due") or "9999-99-99",
                                        t.get("created") or ""))


def add_todo(text: str = "", due: str = "", osoba: str = "",
             plan: str = "", coach: str = "") -> dict | None:
    """Wpis: kto, jaki plan, do kiedy (Filip 2026-08-29). Stare wpisy
    trzymają samo `text` — zostaje jako fallback przy wyświetlaniu."""
    osoba = " ".join((osoba or "").split())
    plan = " ".join((plan or "").split())
    text = " ".join((text or "").split())
    if not text:
        text = " — ".join(x for x in (osoba, plan) if x)
    if not text:
        return None
    t = {"id": uuid.uuid4().hex[:10], "text": text,
         "osoba": osoba, "plan": plan, "coach": (coach or "").strip().lower(),
         "due": (due or "").strip(), "done": False,
         "created": date.today().isoformat()}
    data = _load()
    data["todos"].append(t)
    _save(data)
    return t


def set_done(todo_id: str, done: bool = True) -> None:
    data = _load()
    for t in data["todos"]:
        if t.get("id") == todo_id:
            t["done"] = bool(done)
    _save(data)


def delete_todo(todo_id: str) -> None:
    data = _load()
    data["todos"] = [t for t in data["todos"] if t.get("id") != todo_id]
    _save(data)


def dni_do(due: str) -> int | None:
    """Ile dni do terminu (ujemne = po terminie); None gdy brak/zły format."""
    try:
        return (date.fromisoformat(due) - date.today()).days
    except Exception:
        return None


def konczace_sie_plany(dni: int = 7) -> list[dict]:
    """Aktualne plany, które kończą się w ciągu N dni —
    [{athlete, name, end, dni_zostalo}]."""
    from .training import get_all_plans, is_current, plan_end
    out = []
    for p in get_all_plans():
        end = plan_end(p)
        if not end or not is_current(p):
            continue
        zostalo = (end - date.today()).days
        if 0 <= zostalo <= dni:
            out.append({"athlete": p.get("athlete", ""),
                        "name": p.get("name", ""),
                        "end": end.isoformat(), "dni_zostalo": zostalo})
    return sorted(out, key=lambda x: x["dni_zostalo"])
