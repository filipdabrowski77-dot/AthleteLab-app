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

Brak magazynu (tryb plikowy, Mac bez kluczy) = stare zachowanie: brama
z jednym hasłem z sekretu `haslo`. Magazyn skonfigurowany, a kont z hasłem
brak albo dokument nieczytelny → brama zamknięta (2026-10-03: apka trenera
jest publiczna, patrz brama.sprawdz_haslo).
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
import urllib.parse

import streamlit as st

KLUCZ = "konta"
_ITER = 200_000

# sesja: kto się zalogował i czyje dane ogląda (admin może podglądać inne)
S_ZALOGOWANY = "_aph_konto_zalogowany"
S_OGLADANE = "_aph_konto_ogladane"
S_WS = "_aph_ws_konto"            # czyta store.workspace()
S_NAZWA = "_aph_konto_nazwa"      # czyta store.coach_name()
S_PT = "_aph_konto_pt"            # czyta store.tylko_plany()
S_WYLOGOWANY = "_aph_wylogowany"  # ta karta się wylogowała — bez wejścia z ciasteczka

# Zapamiętane logowanie: F5 i nowa karta wymagały hasła od nowa, a ekran
# lądował na Starcie (audyt 2026-09-28). Ciasteczko to „id.ważność.podpis";
# podpis HMAC zależy od skrótu hasła, więc zmiana hasła je unieważnia,
# a klucz wynika z sekretu magazynu, którego przeglądarka nie zna.
CIASTKO = "aph_sesja"
CIASTKO_DNI = 30
# „Znane urządzenie” (wzorzec OWASP device cookie): przeglądarka, w której
# konto raz weszło poprawnym hasłem, ma przy logowaniu własny licznik prób —
# obcy, który co 30 s zgaduje hasło, nie zabierze jej okienka (przegląd
# 2026-10-03). Wylogowanie go nie kasuje; zmiana hasła unieważnia.
URZADZENIE = "aph_urz"
URZADZENIE_DNI = 365


def _skrot(haslo: str, sol: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", (haslo or "").encode("utf-8"),
                               bytes.fromhex(sol), _ITER).hex()


def stan() -> tuple[list[dict], bool]:
    """(konta, awaria) z JEDNEGO odczytu. awaria = magazyn skonfigurowany,
    a dokumentu kont nie da się przeczytać albo ma zły kształt (awaria
    Supabase, 5xx/429, zerwana sieć). Brama decyduje na tej jednej wartości:
    dwa osobne odczyty (błąd, potem sukces) otwierały wejście (przegląd
    2026-10-03)."""
    from . import store
    if not store.enabled():
        return [], False
    try:
        d = store.kv_get(KLUCZ) or {}
        return [k for k in (d.get("konta") or [])
                if isinstance(k, dict) and k.get("id")], False
    except (RuntimeError, OSError, AttributeError, TypeError, KeyError):
        return [], True


def wszystkie() -> list[dict]:
    """Konta z magazynu. Magazyn niedostępny albo pusty → []."""
    return stan()[0]


def aktywne(lista: "list[dict] | None" = None) -> bool:
    """Logowanie kontami działa, gdy choć jedno konto ma ustawione hasło."""
    return any(k.get("skrot") and k.get("sol")
               for k in (wszystkie() if lista is None else lista))


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
    # cała sesja, nie tylko klucze konta: otwarty profil, plan i edytor
    # poprzedniego konta pokazywały się następnemu w tej samej karcie,
    # także nazwiska z przestrzeni Filipa (audyt 2026-09-28)
    st.session_state.clear()
    st.session_state[S_WYLOGOWANY] = True


def _podpis(kid: str, waznosc: int, skrot: str) -> str:
    from .store import _creds
    c = _creds()
    klucz = hashlib.sha256(b"aph-sesja|" + (c[1] if c else "").encode()).digest()
    return hmac.new(klucz, f"{kid}|{waznosc}|{skrot}".encode(),
                    hashlib.sha256).hexdigest()[:40]


def token_sesji(k: dict) -> str:
    waznosc = int(time.time()) + CIASTKO_DNI * 86400
    return f"{k['id']}.{waznosc}.{_podpis(k['id'], waznosc, k.get('skrot') or '')}"


def _ciastko(nazwa: str = CIASTKO) -> str:
    try:
        return urllib.parse.unquote(st.context.cookies.get(nazwa) or "")
    except Exception:
        return ""


def _podpis_urzadzenia(kid: str, skrot: str) -> str:
    return _podpis(kid, 0, "urz|" + skrot)


def token_urzadzenia(k: dict) -> str:
    return f"{k['id']}.{_podpis_urzadzenia(k['id'], k.get('skrot') or '')}"


def znane_urzadzenie(kid: str) -> bool:
    """Ta przeglądarka weszła już kiedyś poprawnym hasłem na konto `kid`."""
    try:
        kid_c, podpis = _ciastko(URZADZENIE).rsplit(".", 1)
    except ValueError:
        return False
    # isascii: compare_digest na tekście z nie-ASCII rzuca TypeError (traceback
    # dla gościa z podrobionym ciasteczkiem, przegląd 2026-10-03)
    if kid_c != kid or not podpis.isascii():
        return False
    k = _po_id(kid)
    return bool(k and k.get("skrot") and hmac.compare_digest(
        podpis, _podpis_urzadzenia(kid, k["skrot"])))


def z_ciastka() -> dict | None:
    """Wejście bez hasła, gdy przeglądarka ma ważne ciasteczko tego konta."""
    if st.session_state.get(S_WYLOGOWANY):
        return None
    try:
        kid, waznosc, podpis = _ciastko().rsplit(".", 2)
        waznosc = int(waznosc)
    except ValueError:
        return None
    if waznosc < time.time() or not podpis.isascii():
        return None
    k = _po_id(kid)
    if not k or not k.get("skrot") or not hmac.compare_digest(
            podpis, _podpis(kid, waznosc, k["skrot"])):
        return None
    wejdz(k)
    return k


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
