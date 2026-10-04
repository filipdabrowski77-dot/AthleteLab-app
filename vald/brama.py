"""
Ekran z hasłem przed wejściem do aplikacji.

Instancja drugiego trenera stoi pod publicznym adresem — Streamlit
Community Cloud daje jedną apkę z repo prywatnego na konto, a tę Filip ma
zajętą. Bez tej bramy każdy, kto zna adres, wszedłby do Bazy ćwiczeń
i planów (Filip 2026-09-20).

Zasady:
- u Filipa (brak `workspace`) brama jest nieaktywna, dopóki nie ustawi `haslo`;
- w instancji z `workspace` brak hasła ZAMYKA wejście zamiast je otwierać —
  inaczej zapomniany sekret cicho wystawiłby publiczną apkę bez ochrony;
- link zawodnika (?plan=<token>) przechodzi bez hasła, ale tylko z tokenem
  o długości, jaką wystawia aplikacja — nie dowolnym `?plan=x`;
- 2026-10-03 apka trenera jest publiczna: przy skonfigurowanym magazynie
  brama nigdy nie wpuszcza bez konta ani hasła — ani przy awarii bazy, ani
  przy braku dokumentu kont (sesja zalogowana wcześniej zostaje);
- nieudane próby liczone też na konto, wspólnie dla wszystkich sesji.
"""
from __future__ import annotations

import hmac
import threading
import time

import streamlit as st

_OK = "_brama_otwarta"
_PROBY = "_brama_proby"
_BLOKADA_DO = "_brama_blokada_do"
_DO_CIASTKA = "_brama_do_ciastka"
_DO_URZADZENIA = "_brama_do_urzadzenia"
_LIMIT = 5          # nieudanych prób, zanim sesja poczeka
_PRZERWA = 30.0     # sekund
# Licznik w session_state zeruje się w nowej karcie, więc przy publicznym
# adresie zgadywanie haseł nie miało realnego limitu (audyt 2026-10-03).
# Drugi licznik jest wspólny dla wszystkich sesji procesu (zwykły słownik
# modułu — st.cache_resource kasuje anonimowe „clear cache”): po _LIMIT_KONTA
# nieudanych próbach w oknie konto dostaje jedną próbę na _ODSTEP_KONTA.
# Dławienie zamiast blokady: obcy nie odetnie właściciela na kwadrans,
# a telefon z zapamiętanym logowaniem wchodzi przed formularzem.
_LIMIT_KONTA = 10
_OKNO_KONTA = 15 * 60.0   # sekund
_ODSTEP_KONTA = 30.0      # sekund
_NIEUDANE: dict = {}      # (konto, id, znane) / "haslo" → czasy prób (monotonic)
_ZAMEK = threading.Lock()

# Tyle liczy sobie najkrótszy token udostępnienia (training.find_plan_by_token
# odrzuca krótsze), więc krótszy `?plan=` nie ma prawa omijać hasła.
_MIN_TOKEN = 20


def _haslo() -> str:
    from .store import _secret
    return _secret("haslo")


def _konto_rezerwuj(klucz) -> float:
    """0 = próba przydzielona i od razu zapisana (przed liczeniem hasła —
    równoległe sesje nie przeskoczą limitu); > 0 = ile sekund poczekać."""
    with _ZAMEK:
        teraz = time.monotonic()
        proby = [t for t in _NIEUDANE.get(klucz, []) if teraz - t < _OKNO_KONTA]
        if len(proby) >= _LIMIT_KONTA and teraz - proby[-1] < _ODSTEP_KONTA:
            _NIEUDANE[klucz] = proby
            return proby[-1] + _ODSTEP_KONTA - teraz
        _NIEUDANE[klucz] = (proby + [teraz])[-_LIMIT_KONTA:]
        return 0.0


def _konto_udane(klucz) -> None:
    with _ZAMEK:
        _NIEUDANE.pop(klucz, None)


def _czeka_komunikat(zostalo: float) -> None:
    st.warning(f"Za dużo nieudanych prób. Spróbuj za {int(zostalo) + 1} s.")


def sprawdz_haslo() -> bool:
    """True = wpuszczam dalej. False = pokazałem ekran logowania albo odmowę."""
    from . import konta, store
    from .store import workspace
    lista, awaria = konta.stan()
    link = len(str(st.query_params.get("plan") or "").strip()) >= _MIN_TOKEN
    if konta.aktywne(lista):
        # konta trenerów (vald/konta.py) zastępują jedno wspólne hasło
        if konta.zalogowane():
            return True
        if link:
            return True
        k = konta.z_ciastka()
        if k:
            # Safari przycina ciasteczka zapisane z JS do 7 dni — wejście
            # z ciasteczka zapisuje je od nowa, okno się przesuwa (audyt 2026-10-04)
            st.session_state[_DO_CIASTKA] = konta.token_sesji(k)
            st.session_state[_DO_URZADZENIA] = konta.token_urzadzenia(k)
            return True
        _ekran_kont()
        return False
    haslo = _haslo()
    if awaria:
        # baza chwilowo nieczytelna: sesja zalogowana wcześniej zostaje (trener
        # w trakcie treningu, telefon ponawia kolejkę), link zawodnika sam pokaże
        # brak połączenia; nowa sesja czeka, chyba że jest hasło z sekretu
        if st.session_state.get(konta.S_ZALOGOWANY) or link:
            return True
        if not haslo:
            _brak_polaczenia()
            return False
    if not haslo:
        if workspace() or (store.enabled() and not link):
            _brak_hasla()
            return False
        return True
    if st.session_state.get(_OK):
        return True
    if len(str(st.query_params.get("plan") or "").strip()) >= _MIN_TOKEN:
        return True
    _ekran()
    return False


def _brak_polaczenia() -> None:
    st.warning("Nie mogę połączyć się z bazą danych. Spróbuj za chwilę.")
    if st.button("Spróbuj ponownie", key="brama_ponow"):
        st.rerun()


def _brak_hasla() -> None:
    st.error("Ta instancja nie ma ustawionego hasła (sekret `haslo`), "
             "więc nie wpuszczam nikogo. Uzupełnij sekrety w panelu "
             "Streamlit Cloud: Settings → Secrets.")


def _ekran() -> None:
    st.markdown(
        "<div style='max-width:380px;margin:14vh auto 0;text-align:center;'>"
        "<div style='font-size:34px;'>🔒</div>"
        "<div style='font-size:19px;font-weight:700;margin:10px 0 2px;'>"
        "Athletic Performance Hub</div>"
        "<div style='color:#54606F;font-size:14px;'>Podaj hasło, żeby wejść."
        "</div></div>",
        unsafe_allow_html=True,
    )
    _, srodek, _ = st.columns([1, 2, 1])
    with srodek:
        zostalo = st.session_state.get(_BLOKADA_DO, 0.0) - time.monotonic()
        if zostalo > 0:
            st.warning(f"Za dużo prób. Spróbuj za {int(zostalo) + 1} s.")
            return
        wpis = st.text_input("Hasło", type="password", key="brama_wpis",
                             label_visibility="collapsed", placeholder="hasło")
        if st.button("Wejdź", type="primary", use_container_width=True,
                     key="brama_wejdz"):
            czeka = _konto_rezerwuj("haslo")
            if czeka > 0:
                _czeka_komunikat(czeka)
                return
            # bajty, nie str: compare_digest na tekście z polskim znakiem
            # rzuca TypeError i nikt by nie wszedł. Dalej stałoczasowe.
            if hmac.compare_digest((wpis or "").strip().encode("utf-8"),
                                   _haslo().encode("utf-8")):
                _konto_udane("haslo")
                st.session_state[_OK] = True
                for k in (_PROBY, _BLOKADA_DO):
                    st.session_state.pop(k, None)
                st.rerun()
            else:
                proby = st.session_state.get(_PROBY, 0) + 1
                st.session_state[_PROBY] = proby
                if proby >= _LIMIT:
                    st.session_state[_BLOKADA_DO] = time.monotonic() + _PRZERWA
                    st.session_state[_PROBY] = 0
                    st.rerun()          # od razu pokaż odliczanie, nie błąd
                st.error("Nie to hasło.")


def _ciastko_js(wartosc: str, sekundy: int, nazwa: str = "") -> None:
    """Zapis/usunięcie ciasteczka sesji w dokumencie apki (ramka
    components.html ma ten sam origin)."""
    import json
    import streamlit.components.v1 as components
    from .konta import CIASTKO
    nazwa = nazwa or CIASTKO
    components.html(f"""<script>
    try {{
      const w = window.parent, bezp = w.location.protocol === "https:" ? "; Secure" : "";
      w.document.cookie = "{nazwa}=" + encodeURIComponent({json.dumps(wartosc)})
        + "; Max-Age={sekundy}; Path=/; SameSite=Lax" + bezp;
    }} catch (e) {{}}
    </script>""", height=0)


def zapamietaj_logowanie() -> None:
    """Po wejściu hasłem: ciasteczko, żeby F5 i nowa karta nie pytały
    o hasło (woła app.py za bramą, raz po zalogowaniu)."""
    from .konta import CIASTKO_DNI, URZADZENIE, URZADZENIE_DNI
    tok = st.session_state.pop(_DO_CIASTKA, None)
    if tok:
        _ciastko_js(tok, CIASTKO_DNI * 86400)
    urz = st.session_state.pop(_DO_URZADZENIA, None)
    if urz:
        _ciastko_js(urz, URZADZENIE_DNI * 86400, URZADZENIE)


def _ekran_kont() -> None:
    """Logowanie: wybór konta + hasło. Te same limity prób co przy haśle."""
    from . import konta
    if st.session_state.get(konta.S_WYLOGOWANY) and konta._ciastko():
        _ciastko_js("", 0)        # Wyloguj: nowa karta też ma pytać o hasło
    lista = [k for k in konta.wszystkie() if k.get("skrot")]
    st.markdown(
        "<div style='max-width:380px;margin:14vh auto 0;text-align:center;'>"
        "<div style='font-size:34px;'>🔒</div>"
        "<div style='font-size:19px;font-weight:700;margin:10px 0 2px;'>"
        "Athletic Performance Hub</div>"
        "<div style='color:#54606F;font-size:14px;'>Wybierz konto i podaj hasło."
        "</div></div>",
        unsafe_allow_html=True,
    )
    _, srodek, _ = st.columns([1, 2, 1])
    with srodek:
        zostalo = st.session_state.get(_BLOKADA_DO, 0.0) - time.monotonic()
        if zostalo > 0:
            st.warning(f"Za dużo prób. Spróbuj za {int(zostalo) + 1} s.")
            return
        kid = st.selectbox("Konto", [k["id"] for k in lista], key="brama_konto",
                           format_func=lambda i: next(
                               ((k.get("name") or i) for k in lista if k["id"] == i), i),
                           label_visibility="collapsed")
        wpis = st.text_input("Hasło", type="password", key="brama_wpis",
                             label_visibility="collapsed", placeholder="hasło")
        if st.button("Wejdź", type="primary", use_container_width=True,
                     key="brama_wejdz"):
            # id spoza listy (podrobiony selectbox) nie zakłada licznika
            if kid not in {k_["id"] for k_ in lista}:
                st.error("Nie to hasło.")
                return
            # znane urządzenie ma własny licznik — obcy go nie wyczerpie
            klucz = ("konto", kid, konta.znane_urzadzenie(kid))
            czeka = _konto_rezerwuj(klucz)
            if czeka > 0:
                _czeka_komunikat(czeka)
                return
            k = konta.sprawdz(kid, (wpis or "").strip())
            if k:
                _konto_udane(klucz)
                konta.wejdz(k)
                for s_ in (_PROBY, _BLOKADA_DO, konta.S_WYLOGOWANY):
                    st.session_state.pop(s_, None)
                st.session_state[_DO_CIASTKA] = konta.token_sesji(k)
                st.session_state[_DO_URZADZENIA] = konta.token_urzadzenia(k)
                st.rerun()
            else:
                proby = st.session_state.get(_PROBY, 0) + 1
                st.session_state[_PROBY] = proby
                if proby >= _LIMIT:
                    st.session_state[_BLOKADA_DO] = time.monotonic() + _PRZERWA
                    st.session_state[_PROBY] = 0
                    st.rerun()
                st.error("Nie to hasło.")

