"""
Claude w Dyktafonie: trener mówi (albo pisze) normalnie, Claude oddaje
plan w formacie dyktanda (vald/dyktando.py), apka dopasowuje nazwy do Bazy
i zapisuje jak zwykłe dyktando. Filip 2026-09-29: „zamiast dyktanda po
prostu klikasz i włącza ci się Claude, który już jest w aplikacji".

Klucz API: sekret `anthropic_api_key` (Streamlit secrets albo env
APH_ANTHROPIC_API_KEY). Bez klucza przycisk się nie pokazuje — nic nie pada.
Klucz jest Filipa, koszt idzie na jego konto; nigdy w kodzie ani w repo.
Model: sekret `anthropic_model` (domyślnie MODEL) — zmiana bez wdrożenia.

Claude dostaje w kontekście: reguły rozpisywania (instrukcja_claude.txt),
Bazę ćwiczeń i podopiecznych, a dla zawodnika wymienionego w rozmowie —
jego ostatnie plany w formacie dyktanda. Dzięki temu „daj mu prep taki sam
jak w dniu C” albo „dopisz dzień A do planu 1.0” działa bez przepisywania.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

MODEL = "claude-opus-5"
_INSTRUKCJA = Path(__file__).with_name("instrukcja_claude.txt")
_ILE_PLANOW = 2          # ostatnie plany zawodnika w kontekście
_MAX_ZNAKOW_PLANOW = 12000


def klucz() -> str:
    from .store import _secret
    return _secret("anthropic_api_key")


def model() -> str:
    from .store import _secret
    return _secret("anthropic_model") or MODEL


def dostepny() -> bool:
    return bool(klucz())


def wspomniani(historia: list[dict], zawodnicy: list[str]) -> list[str]:
    """Podopieczni, których nazwisko albo imię+nazwisko pada w rozmowie
    (bez rozróżniania wielkości liter; samo imię nie wystarcza — „Filip”
    to też trener)."""
    tekst = " ".join(m.get("content", "") for m in historia if m.get("role") == "user").lower()
    out = []
    for z in zawodnicy:
        czesci = z.lower().split()
        if not czesci:
            continue
        pelne = z.lower() in tekst
        nazwisko = len(czesci) > 1 and re.search(r"\b" + re.escape(czesci[-1]) + r"\b", tekst)
        if pelne or nazwisko:
            out.append(z)
    return out


def kontekst_planow(historia: list[dict], zawodnicy: list[str]) -> str:
    """Ostatnie plany wspomnianych zawodników w formacie dyktanda."""
    from .dyktando import plan_do_tekstu
    from .training import get_plans
    bloki = []
    for z in wspomniani(historia, zawodnicy):
        for p in get_plans(z)[:_ILE_PLANOW]:
            try:
                bloki.append(plan_do_tekstu(p))
            except Exception:
                continue
    txt = "\n\n".join(bloki)
    return txt[:_MAX_ZNAKOW_PLANOW]


def system(nazwy: list[str], zawodnicy: list[str], historia: list[dict] | None = None) -> str:
    """Instrukcja z pliku + dzisiejsza data + Baza ćwiczeń + podopieczni
    (+ ich ostatnie plany), żeby Claude używał nazw, które apka dopasuje
    bez pytania, i widział, co zawodnik ma teraz."""
    txt = _INSTRUKCJA.read_text(encoding="utf-8")
    plany = kontekst_planow(historia or [], zawodnicy)
    return (txt
            + f"\n\nDziś jest {date.today().isoformat()}. Gdy nie podam daty startu, "
              "przyjmij dzisiejszą.\n"
            + "\nPODOPIECZNI (użyj dokładnie tej pisowni):\n"
            + "\n".join(f"- {z}" for z in zawodnicy)
            + "\n\nBAZA ĆWICZEŃ (użyj dokładnie tych nazw; inne tylko z „!”):\n"
            + "\n".join(f"- {n}" for n in nazwy)
            + ("\n\nOBECNE PLANY ZAWODNIKA (format dyktanda; „dopisz dzień A do planu X” = "
               "oddaj blok z tą samą nazwą planu i tylko nowym treningiem; „prep jak w dniu C” = "
               "przepisz te pozycje dosłownie):\n\n" + plany if plany else ""))


def odpowiedz(historia: list[dict], nazwy: list[str], zawodnicy: list[str]) -> str:
    """Jedna odpowiedź Claude na całą rozmowę (historia = [{role, content}])."""
    import anthropic
    client = anthropic.Anthropic(api_key=klucz())
    msg = client.messages.create(
        model=model(), max_tokens=4000,
        system=system(nazwy, zawodnicy, historia),
        messages=[{"role": m["role"], "content": m["content"]} for m in historia])
    return "".join(getattr(b, "text", "") for b in msg.content).strip()


def wyciagnij_blok(tekst: str) -> str:
    """Blok planu z odpowiedzi (od linii „plan:” do końca, bez ogrodzenia
    ```). Pusty string, gdy Claude jeszcze pyta."""
    t = re.sub(r"```[a-z]*\n?", "", tekst or "")
    m = re.search(r"(?ms)^\s*plan:.*", t)
    return m.group(0).strip() if m else ""
