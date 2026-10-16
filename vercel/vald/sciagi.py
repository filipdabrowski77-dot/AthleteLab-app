"""Ściągi trenera — obrazy pod ręką przy rozpisywaniu planu (Filip 2026-10-16:
„panel po lewej, w którym po kliknięciu znajdę przydatne rzeczy” — tabele %1RM,
izometria, tissue healing timelines).

Magazyn jak reszta apki: Supabase kv (klucz `sciagi` = lista, `sciagi/<id>` =
obraz w base64), bez magazynu pliki w <ValdLibrary>/sciagi/. Lista osobno od
obrazów: panel pokazuje tytuły od razu, obraz pobiera dopiero po kliknięciu.
Obrazy nie trafiają do repo (publiczne AthleteLab-app dostaje sam kod).
"""
from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime

from . import store
from .library import LIBRARY_DIR

KLUCZ = "sciagi"
TYPY = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif"}
MAX_BAJTOW = 4 * 1024 * 1024      # kv to jsonb — base64 rośnie o 1/3
_KATALOG = LIBRARY_DIR / "sciagi"


def _czytaj(nazwa: str) -> dict | None:
    if store.enabled():
        return store.kv_get(nazwa)
    p = _KATALOG / f"{nazwa.replace('/', '__')}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def _zapisz(nazwa: str, wartosc: dict) -> None:
    if store.enabled():
        store.kv_put(nazwa, wartosc)
        return
    _KATALOG.mkdir(parents=True, exist_ok=True)
    p = _KATALOG / f"{nazwa.replace('/', '__')}.json"
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(wartosc, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


def lista() -> list[dict]:
    """[{id, tytul, mime, dodano}] w kolejności dodania."""
    dane = _czytaj(KLUCZ) or {}
    return [x for x in (dane.get("items") or []) if isinstance(x, dict) and x.get("id")]


def obraz(id_: str) -> tuple[bytes, str] | None:
    """(bajty, mime) albo None, gdy nie ma / usunięta."""
    if not any(x["id"] == id_ for x in lista()):
        return None
    d = _czytaj(f"{KLUCZ}/{id_}") or {}
    if not d.get("b64"):
        return None
    return base64.b64decode(d["b64"]), str(d.get("mime") or "image/png")


def dodaj(tytul: str, dane: bytes, mime: str) -> dict:
    """Nowa ściąga na końcu listy. ValueError przy złym typie / za dużym pliku."""
    tytul = (tytul or "").strip()[:120]
    if not tytul:
        raise ValueError("Wpisz tytuł")
    if mime not in TYPY:
        raise ValueError("Obsługiwane obrazy: PNG, JPG, WEBP, GIF")
    if not dane:
        raise ValueError("Pusty plik")
    if len(dane) > MAX_BAJTOW:
        raise ValueError(f"Plik za duży (najwyżej {MAX_BAJTOW // (1024 * 1024)} MB)")
    wpis = {"id": uuid.uuid4().hex[:12], "tytul": tytul, "mime": mime,
            "dodano": datetime.now().isoformat(timespec="seconds")}
    # najpierw obraz, potem lista — przerwany zapis nie zostawi pozycji bez obrazu
    _zapisz(f"{KLUCZ}/{wpis['id']}", {"mime": mime, "b64": base64.b64encode(dane).decode("ascii")})
    _zapisz(KLUCZ, {"items": lista() + [wpis]})
    return wpis


def zmien_tytul(id_: str, tytul: str) -> bool:
    tytul = (tytul or "").strip()[:120]
    items = lista()
    if not tytul or not any(x["id"] == id_ for x in items):
        return False
    _zapisz(KLUCZ, {"items": [dict(x, tytul=tytul) if x["id"] == id_ else x for x in items]})
    return True


def usun(id_: str) -> bool:
    """Ściąga znika z listy, obraz zostaje wyczyszczony (kv nie ma kasowania)."""
    items = lista()
    if not any(x["id"] == id_ for x in items):
        return False
    _zapisz(KLUCZ, {"items": [x for x in items if x["id"] != id_]})
    _zapisz(f"{KLUCZ}/{id_}", {"usunieta": True})
    return True
