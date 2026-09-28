"""
Konta trenerów — logowanie własnym hasłem, każde konto w swojej przestrzeni.

Filip 2026-09-28: „każdy ma dostęp do tej samej aplikacji, ale jedna osoba
nie widzi drugiej osoby planów; każdy ma swoje hasło, ale ja mam dostęp jako
admin do wszystkiego".

Konta leżą w magazynie pod WSPÓLNYM kluczem `konta` (bez prefiksu
przestrzeni), więc czyta je każda instancja apki — hasła nie siedzą ani
w kodzie (repo trenera jest publiczne), ani w sekretach Streamlit.
Zamiast hasła: sól + PBKDF2-SHA256.

    {"konta": [{"id": "filip", "name": "Coach Filip", "rola": "admin",
                "workspace": "", "pt": true, "sol": "…", "skrot": "…"}, …]}

- `workspace` — przestrzeń danych konta (store._kv_name dokleja prefiks
  `ws/<nazwa>/`); pusta = przestrzeń Filipa;
- `pt` — czy konto widzi Performance testing (dane VALD);
- `rola: "admin"` — przełącznik podglądu wszystkich kont.

Brak dokumentu `konta` (albo magazynu) = stare zachowanie: brama z jednym
hasłem z sekretu `haslo`, nic się u nikogo nie zmienia.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets

import streamlit as st

KLUCZ = "konta"
_ITER = 200_000

# sesja: kto się zalogował i czyje dane ogląda (admin może podglądać inne)
S_ZALOGOWANY = "_aph_konto_zalogowany"
S_OGLADANE = "_aph_konto_ogladane"
S_WS = "_aph_ws_konto"            # czyta store.workspace()
S_NAZWA = "_aph_konto_nazwa"      # czyta store.coach_name()
S_PT = "_aph_konto_pt"            # czyta store.tylko_plany()


def _skrot(haslo: str, sol: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", (haslo or "").encode("utf-8"),
                               bytes.fromhex(sol), _ITER).hex()


def wszystkie() -> list[dict]:
    """Konta z magazynu. Magazyn niedostępny albo pusty → [] (stara brama)."""
    from . import store
    if not store.enabled():
        return []
    try:
        d = store.kv_get(KLUCZ) or {}
    except (RuntimeError, OSError):
        return []
    return [k for k in (d.get("konta") or [])
            if isinstance(k, dict) and k.get("id")]


def aktywne() -> bool:
    """Logowanie kontami działa, gdy choć jedno konto ma ustawione hasło."""
    return any(k.get("skrot") and k.get("sol") for k in wszystkie())


def _po_id(kid: str) -> dict | None:
    return next((k for k in wszystkie() if k.get("id") == kid), None)


def sprawdz(kid: str, haslo: str) -> dict | None:
    """Konto, gdy hasło pasuje; inaczej None. Porównanie stałoczasowe."""
    k = _po_id(kid)
    if not k or not k.get("skrot") or not k.get("sol"):
        return None
    if hmac.compare_digest(_skrot(haslo, k["sol"]), k["skrot"]):
        return k
    return None


def zapisz(lista: list[dict]) -> None:
    from . import store
    store.kv_put(KLUCZ, {"konta": lista})


def ustaw_haslo(lista: list[dict], kid: str, haslo: str) -> list[dict]:
    """Nowa sól i skrót dla konta `kid` (lista zmieniana w miejscu)."""
    for k in lista:
        if k.get("id") == kid:
            k["sol"] = secrets.token_hex(16)
            k["skrot"] = _skrot(haslo, k["sol"])
    return lista


def _ustaw_widok(k: dict) -> None:
    ss = st.session_state
    ss[S_OGLADANE] = k["id"]
    ss[S_WS] = str(k.get("workspace") or "")
    ss[S_NAZWA] = str(k.get("name") or k["id"])


def wejdz(k: dict) -> None:
    """Po poprawnym haśle: konto zalogowane i jego przestrzeń w sesji."""
    from . import coaches
    ss = st.session_state
    ss[S_ZALOGOWANY] = k["id"]
    ss[S_PT] = bool(k.get("pt"))
    _ustaw_widok(k)
    # stary przełącznik paneli Filip/Kuba działał w jednej przestrzeni —
    # przy kontach każdy ma swoją, więc panel zawsze domyślny
    coaches.set_current(coaches.DEFAULT)


def wyloguj() -> None:
    for s in (S_ZALOGOWANY, S_OGLADANE, S_WS, S_NAZWA, S_PT):
        st.session_state.pop(s, None)


def zalogowane() -> dict | None:
    kid = st.session_state.get(S_ZALOGOWANY)
    return _po_id(kid) if kid else None


def jest_admin() -> bool:
    k = zalogowane()
    return bool(k and k.get("rola") == "admin")


def ogladane_id() -> str:
    return str(st.session_state.get(S_OGLADANE) or "")


def podglad(kid: str) -> bool:
    """Admin przełącza się na dane innego konta. Nie-admin: nic."""
    if not jest_admin():
        return False
    k = _po_id(kid)
    if not k:
        return False
    _ustaw_widok(k)
    return True


def inicjaly(nazwa: str) -> str:
    slowa = [w for w in (nazwa or "").split()
             if w.lower() not in ("coach", "trener")] or (nazwa or "?").split()
    return "".join(w[0] for w in slowa[:2]).upper() or "?"


def do_przelacznika() -> list[dict]:
    """Konta do przełącznika w powłoce — tylko dla admina."""
    if not jest_admin():
        return []
    return [{"id": k["id"], "name": k.get("name") or k["id"],
             "initials": inicjaly(k.get("name") or k["id"])} for k in wszystkie()]
