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
  o długości, jaką wystawia aplikacja — nie dowolnym `?plan=x`.
"""
from __future__ import annotations

import hmac
import time

import streamlit as st

_OK = "_brama_otwarta"
_PROBY = "_brama_proby"
_BLOKADA_DO = "_brama_blokada_do"
_LIMIT = 5          # nieudanych prób, zanim sesja poczeka
_PRZERWA = 30.0     # sekund

# Tyle liczy sobie najkrótszy token udostępnienia (training.find_plan_by_token
# odrzuca krótsze), więc krótszy `?plan=` nie ma prawa omijać hasła.
_MIN_TOKEN = 20


def _haslo() -> str:
    from .store import _secret
    return _secret("haslo")


def sprawdz_haslo() -> bool:
    """True = wpuszczam dalej. False = pokazałem ekran logowania albo odmowę."""
    from .store import workspace
    haslo = _haslo()
    if not haslo:
        if workspace():
            _brak_hasla()
            return False
        return True
    if st.session_state.get(_OK):
        return True
    if len(str(st.query_params.get("plan") or "").strip()) >= _MIN_TOKEN:
        return True
    _ekran()
    return False


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
            # bajty, nie str: compare_digest na tekście z polskim znakiem
            # rzuca TypeError i nikt by nie wszedł. Dalej stałoczasowe.
            if hmac.compare_digest((wpis or "").strip().encode("utf-8"),
                                   _haslo().encode("utf-8")):
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
        if st.session_state.get(_PROBY, 0) >= 3:
            st.caption("Hasło dostajesz od trenera, który zakładał dostęp.")
