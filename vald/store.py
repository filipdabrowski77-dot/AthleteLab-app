"""
Wspólny magazyn danych (plany + baza ćwiczeń) — jeden „mózg" dla Maca
Filipa i zawsze-włączonej apki w chmurze (Streamlit Cloud).

Backend wybierany automatycznie:
- są klucze Supabase (st.secrets["supabase"] albo env SUPABASE_URL/SUPABASE_KEY)
  → czytamy/piszemy do Supabase (tabela `kv`: key text PK, value jsonb).
  Mac i chmura współdzielą TE SAME dane → korekta trenera widoczna u
  zawodnika od razu, bez zależności od tego, czy Mac jest włączony.
- brak kluczy → None; wołający używa swojego zapisu do plików JSON
  (lokalny dev, testy i tryb offline działają DOKŁADNIE jak dotąd).

Bez nowych zależności — czysty urllib (stdlib), więc requirements i
Streamlit Cloud bez zmian.

Tabela w Supabase (SQL Editor, raz):
    create table if not exists kv (
        key text primary key,
        value jsonb not null,
        updated_at timestamptz not null default now()
    );
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

_TABLE = "kv"
# s — własne zapisy odświeżają cache od razu (kv_put), więc TTL dotyczy
# wyłącznie zmian z INNEGO urządzenia: drugiego trenera albo telefonu
# zawodnika. 1.5 s oznaczało, że każde kliknięcie szło po sieci na nowo
# (8 kluczy × 100-800 ms = ponad sekunda na akcję).
_TTL = 15.0
_cache: dict[str, tuple[float, dict]] = {}


def _creds() -> tuple[str, str] | None:
    """(url, key) z sekretów Streamlit albo env; None gdy brak konfiguracji.

    PUŁAPKA (2026-09-20): skrypt odpalony z katalogu repo widzi
    .streamlit/secrets.toml i pisze do PRODUKCYJNEGO Supabase, nawet gdy env
    wskazuje mocka — tak trafiły tam dwa śmieciowe plany. APH_STORE_OFF=1
    wyłącza magazyn twardo, niezależnie od sekretów.
    """
    if (os.environ.get("APH_STORE_OFF") or "").strip() in ("1", "true", "tak"):
        return None
    url = key = ""
    try:  # st.secrets rzuca, gdy nie ma secrets.toml — łapiemy
        import streamlit as st
        sec = st.secrets.get("supabase", {})
        url = (sec.get("url") or "").strip()
        key = (sec.get("key") or "").strip()
    except Exception:
        pass
    if not (url and key):
        url = (os.environ.get("SUPABASE_URL") or "").strip()
        key = (os.environ.get("SUPABASE_KEY") or "").strip()
    if url and key:
        return url.rstrip("/"), key
    return None


def enabled() -> bool:
    """Czy używamy wspólnego magazynu (są klucze)."""
    return _creds() is not None


def _secret(name: str) -> str:
    """Wartość z st.secrets ([supabase] albo top-level) lub env APH_<NAME>."""
    try:
        import streamlit as st
        sec = st.secrets.get("supabase", {})
        v = (sec.get(name) if hasattr(sec, "get") else None)
        if not v:
            v = st.secrets.get(name)
        if v:
            return str(v).strip()
    except Exception:
        pass
    return (os.environ.get("APH_" + name.upper()) or "").strip()


_WS_KEY = "_aph_workspace"
_WS_OVERRIDE: str | None = None


def _czysta_ws(w: str) -> str:
    return "".join(c for c in (w or "") if c.isalnum() or c in "-_").lower()


def set_workspace(name: str) -> None:
    """Przełącz przestrzeń w trakcie działania (apka zawodnika bierze ją
    z linku ?ws=…). Sekrety wygrywają z env, więc APH_WORKSPACE tego nie
    zrobi. Trzymam to w session_state, bo jeden proces obsługuje wielu
    zawodników — globalna zmienna przełączyłaby magazyn wszystkim.
    Cache jest kluczowany prefiksem przestrzeni, więc nie czyszczę go."""
    nowa = _czysta_ws(name)
    try:
        import streamlit as st
        st.session_state[_WS_KEY] = nowa
        return
    except Exception:
        pass
    global _WS_OVERRIDE
    _WS_OVERRIDE = nowa or None


def workspace() -> str:
    """Przestrzeń robocza drugiego trenera na tym samym Supabase: sekret
    `workspace` albo env APH_WORKSPACE. Pusty = przestrzeń domyślna."""
    try:
        import streamlit as st
        w = st.session_state.get(_WS_KEY)
        if w:
            return str(w)
    except Exception:
        pass
    if _WS_OVERRIDE:
        return _WS_OVERRIDE
    return _czysta_ws(_secret("workspace"))


def coach_name() -> str:
    """Nazwa trenera w instancji gościa (sekret `coach_name`). Pusta = apka
    wyliczy ją z nazwy przestrzeni — bez tego drugi trener widział w stopce
    „Coach Filip" jako siebie."""
    return _secret("coach_name")


def share_base() -> str:
    """Adres apki do linków dla zawodnika (sekret `share_base_url`)."""
    return _secret("share_base_url").rstrip("/")


def tylko_plany() -> bool:
    """Instancja bez Performance testing: sekret `tylko_plany` albo env
    APH_TYLKO_PLANY. Drugi trener układa plany i uzupełnia Bazę ćwiczeń,
    wyników z płyt nie ogląda (Filip 2026-09-18)."""
    return _secret("tylko_plany").lower() in ("1", "true", "tak", "yes", "on")


# Baza ćwiczeń jest WSPÓLNA do ODCZYTU: drugi trener widzi całą bibliotekę
# Filipa i każdy jego nowy wpis (Filip 2026-09-18). Od 2026-09-20 jego własne
# dodatki i poprawki idą do prefiksowanej nakładki `exercise_library_own`
# (vald/exlib.py) — wspólnej Bazy instancja gościa nie rusza. Plany, profile
# i roster zostają osobne: to dane podopiecznych.
_WSPOLNE_KEYS = {"exercise_library"}


def _kv_name(name: str) -> str:
    w = workspace()
    if name in _WSPOLNE_KEYS:
        return name
    return f"ws/{w}/{name}" if w else name


# zrywy sieci/TLS: SSLError i ConnectionError to OSError, ale NIE URLError —
# bez tego traceback leciał na ekran zamiast komunikatu (Filip 2026-09-20)
_SIEC = (urllib.error.URLError, TimeoutError, ValueError, OSError)


def _z_ponowieniem(op, opis: str):
    """Jedna próba ponowienia — zerwane TLS zwykle działa za drugim razem."""
    for ostatnia in (False, True):
        try:
            return op()
        except _SIEC as e:
            if ostatnia:
                raise RuntimeError(f"Magazyn Supabase nieosiągalny {opis}: {e}") from e
            time.sleep(0.4)


def _headers(key: str, extra: dict | None = None) -> dict:
    h = {"apikey": key, "Authorization": f"Bearer {key}",
         "Content-Type": "application/json"}
    if extra:
        h.update(extra)
    return h


def kv_get(name: str) -> dict | None:
    """Wartość spod klucza (dict) albo None, gdy brak wpisu / brak magazynu.
    Rzuca RuntimeError, gdy magazyn skonfigurowany, ale nieosiągalny —
    lepiej głośno niż po cichu pokazać/utrwalić pustkę."""
    creds = _creds()
    if creds is None:
        return None
    name = _kv_name(name)
    hit = _cache.get(name)
    if hit and (time.monotonic() - hit[0]) < _TTL:
        return hit[1]
    url, key = creds

    def _fetch(k: str):
        def _raz():
            req = urllib.request.Request(
                f"{url}/rest/v1/{_TABLE}?key=eq.{k}&select=value",
                headers=_headers(key), method="GET")
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.loads(r.read().decode("utf-8"))
        rows = _z_ponowieniem(_raz, f"przy odczycie '{k}'")
        return rows[0]["value"] if rows else None

    val = _fetch(name)
    if val is not None:
        _cache[name] = (time.monotonic(), val)
    return val


def kv_get_many(names: "list[str]") -> dict:
    """Pobierz wiele kluczy JEDNYM zapytaniem (Supabase: key=in.(...)).
    Osiem osobnych round-tripów kosztowało ponad sekundę na każdą akcję —
    tyle samo danych w jednym locie schodzi do jednego opóźnienia sieci.
    Zwraca {nazwa: wartość} tylko dla znalezionych; resztę czyta wołający."""
    creds = _creds()
    if creds is None:
        return {}
    swieze = time.monotonic()
    braki = [n for n in names
             if not (_cache.get(_kv_name(n))
                     and (swieze - _cache[_kv_name(n)][0]) < _TTL)]
    if not braki:
        return {n: _cache[_kv_name(n)][1] for n in names
                if _kv_name(n) in _cache}
    url, key = creds
    pelne = [_kv_name(n) for n in braki]
    lista = ",".join(urllib.parse.quote(k, safe="") for k in pelne)
    req = urllib.request.Request(
        f"{url}/rest/v1/{_TABLE}?key=in.({lista})&select=key,value",
        headers=_headers(key), method="GET")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            wiersze = json.loads(r.read().decode("utf-8"))
    except _SIEC:
        return {}          # cicho — wołający pobierze klucze pojedynczo
    teraz = time.monotonic()
    for w in wiersze:
        _cache[w["key"]] = (teraz, w["value"])
    return {n: _cache[_kv_name(n)][1] for n in names
            if _kv_name(n) in _cache}


def kv_put(name: str, value: dict) -> None:
    """Zapisz (upsert) wartość pod kluczem. No-op, gdy brak magazynu."""
    creds = _creds()
    if creds is None:
        return
    url, key = creds
    name = _kv_name(name)
    body = json.dumps([{"key": name, "value": value}]).encode("utf-8")
    req = urllib.request.Request(
        f"{url}/rest/v1/{_TABLE}?on_conflict=key",
        data=body, method="POST",
        headers=_headers(key, {"Prefer": "resolution=merge-duplicates"}))
    def _raz():
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.read()
    _z_ponowieniem(_raz, f"przy zapisie '{name}'")
    _cache[name] = (time.monotonic(), value)


def invalidate(name: str | None = None) -> None:
    """Wyrzuć cache (po zapisie z innego procesu / test)."""
    if name is None:
        _cache.clear()
    else:
        _cache.pop(_kv_name(name), None)
