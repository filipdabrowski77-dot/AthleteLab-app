"""
Atrapa Streamlita dla funkcji na Vercelu.

vald/ui_training.py importuje `streamlit` na górze pliku (dialogi), a
vald/store.py zagląda do `st.secrets` i `st.session_state`. Funkcja na
Vercelu nie ma Streamlita (i nie ma go mieć — to 200 MB zależności), więc
ten pakiet podstawia minimum, którego te moduły dotykają przy imporcie
i w ścieżce zawodnika: dialog → dekorator bez efektu, secrets → pusto
(klucze idą z env SUPABASE_URL/SUPABASE_KEY), session_state → słownik.
Katalog `vercel/` jest na początku sys.path (api/*.py), więc lokalnie
też wygrywa z prawdziwym Streamlitem w .venv.
"""
from __future__ import annotations

secrets: dict = {}
session_state: dict = {}
query_params: dict = {}


def dialog(*_a, **_k):
    return lambda f: f


def cache_data(*a, **_k):
    if a and callable(a[0]):
        return a[0]
    return lambda f: f


cache_resource = cache_data


def _nic(*_a, **_k):
    return None


markdown = info = warning = error = caption = write = rerun = _nic
