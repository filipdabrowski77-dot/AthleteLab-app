"""
PUBLICZNA mini-apka dla ZAWODNIKA — tylko widok planu z sekretnego linku
(?plan=<token>). Deploy na Streamlit Cloud jako OSOBNA, publiczna apka
(główny dashboard z danymi VALD zostaje prywatny).

Nie importuje app.py — zero danych VALD (parquet), lekki cold start.
Dane planów/bazy ćwiczeń: wspólny magazyn Supabase (vald/store.py) —
korekty trenera z Maca widoczne tu od razu.
"""
import streamlit as st

st.set_page_config(
    page_title="Twój plan — AthleteLab",
    page_icon="🏋️",
    layout="centered",
    initial_sidebar_state="collapsed",
)

from vald.ui_training import _render_athlete_mode  # noqa: E402

_token = (st.query_params.get("plan") or "").strip()
# ?ws=… — plan wystawiony przez drugiego trenera leży w jego przestrzeni
_ws = "".join(c for c in (st.query_params.get("ws") or "")
              if c.isalnum() or c in "-_").lower()
if _ws:
    from vald import store as _store
    _store.set_workspace(_ws)

if _token:
    try:
        _render_athlete_mode(_token)
    except RuntimeError as e:
        # zawodnik na telefonie ma zobaczyć zdanie, nie traceback
        st.error("Nie mogę teraz wczytać planu — spróbuj za chwilę.")
        st.caption(str(e))
else:
    st.markdown(
        "<div style='max-width:420px;margin:80px auto;text-align:center;"
        "color:#54606F;'>"
        "<div style='font-size:40px;'>🔒</div>"
        "<div style='font-size:17px;font-weight:700;color:#0F1722;"
        "margin:8px 0 4px;'>Brak dostępu</div>"
        "Otwórz link do planu, który dostałeś od trenera.</div>",
        unsafe_allow_html=True,
    )
