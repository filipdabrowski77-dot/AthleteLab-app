"""
Claude w dyktandzie: trener mówi (albo pisze) normalnie, Claude oddaje
plan w formacie dyktanda (vald/dyktando.py), apka dopasowuje nazwy do Bazy
i zapisuje jak zwykłe dyktando. Filip 2026-09-29: „zamiast dyktanda po
prostu klikasz i włącza ci się Claude, który już jest w aplikacji".

Klucz API: sekret `anthropic_api_key` (Streamlit secrets albo env
APH_ANTHROPIC_API_KEY). Bez klucza przycisk się nie pokazuje — nic nie pada.
Klucz jest Filipa, koszt idzie na jego konto; nigdy w kodzie ani w repo.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

MODEL = "claude-opus-5"
_INSTRUKCJA = Path(__file__).with_name("instrukcja_claude.txt")


def klucz() -> str:
    from .store import _secret
    return _secret("anthropic_api_key")


def dostepny() -> bool:
    return bool(klucz())


def system(nazwy: list[str], zawodnicy: list[str]) -> str:
    """Instrukcja z pliku + dzisiejsza data + Baza ćwiczeń + podopieczni,
    żeby Claude używał nazw, które apka dopasuje bez pytania."""
    txt = _INSTRUKCJA.read_text(encoding="utf-8")
    return (txt
            + f"\n\nDziś jest {date.today().isoformat()}. Gdy nie podam daty startu, "
              "przyjmij najbliższy poniedziałek.\n"
            + "Odpowiadasz krótko, po polsku. Gdy masz wszystko, oddaj SAM blok "
              "planu (bez komentarza przed i po). Gdy czegoś brakuje albo coś "
              "jest niejasne, zadaj jedno krótkie pytanie.\n"
            + "\nPODOPIECZNI (użyj dokładnie tej pisowni):\n"
            + "\n".join(f"- {z}" for z in zawodnicy)
            + "\n\nBAZA ĆWICZEŃ (użyj dokładnie tych nazw; inne tylko z „!”):\n"
            + "\n".join(f"- {n}" for n in nazwy))


def odpowiedz(historia: list[dict], nazwy: list[str], zawodnicy: list[str]) -> str:
    """Jedna odpowiedź Claude na całą rozmowę (historia = [{role, content}])."""
    import anthropic
    client = anthropic.Anthropic(api_key=klucz())
    msg = client.messages.create(
        model=MODEL, max_tokens=2500,
        system=system(nazwy, zawodnicy),
        messages=[{"role": m["role"], "content": m["content"]} for m in historia])
    return "".join(getattr(b, "text", "") for b in msg.content).strip()


def wyciagnij_blok(tekst: str) -> str:
    """Blok planu z odpowiedzi (od linii „plan:” do końca, bez ogrodzenia
    ```). Pusty string, gdy Claude jeszcze pyta."""
    t = re.sub(r"```[a-z]*\n?", "", tekst or "")
    m = re.search(r"(?ms)^\s*plan:.*", t)
    return m.group(0).strip() if m else ""
