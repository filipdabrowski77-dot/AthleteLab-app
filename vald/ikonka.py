"""Ikonka na ekran początkowy telefonu (czarne logo APH) — wspólna dla całej
apki (app.py) i lekkiej apki zawodnika (athlete_app.py, Streamlit Cloud).

Własnego <head> Streamlit nie daje, więc ikonę, nazwę i manifest dopisuję
z ramki komponentu. W Streamlit Cloud apka siedzi w ramce /~/+/ strony-
opakowania (ta sama domena), a iPhone czyta ikonę z dokumentu NAJWYŻSZEGO
— tam dopisanie do dokumentu apki nic nie dawało i telefon brał koronę
Streamlita (Filip 2026-10-01: „własne czarne logo”)."""
from __future__ import annotations

import json


def wstaw(nazwa: str = "APH", manifest: bool = True) -> None:
    import streamlit.components.v1 as components
    components.html("""<script>
    const NAZWA = """ + json.dumps(nazwa) + """, MANIFEST = """ + ("true" if manifest else "false") + """;
    try {
      const app = window.parent;                 // dokument apki: od niego adresy plików
      let w = app;
      try { if (window.top.document) w = window.top; } catch (e) {}
      const d = w.document, u = p => new URL(p, app.location.href).href;
      const ustaw = (tag, sel, at, nadpisz) => {
        let el = d.head.querySelector(sel);
        if (el && !nadpisz) return;
        if (!el) { el = d.createElement(tag); d.head.appendChild(el); }
        Object.entries(at).forEach(([k, v]) => el.setAttribute(k, v));
      };
      ustaw("link", 'link[rel="apple-touch-icon"]', {rel: "apple-touch-icon", href: u("app/static/aph-trener-180.png")}, true);
      if (w === app) {
        // Mac / tunel: apka jest całą stroną — manifest trybu trenera, pełny ekran
        if (MANIFEST) ustaw("link", 'link[rel="manifest"]', {rel: "manifest", href: u("app/static/manifest.json")});
        ustaw("meta", 'meta[name="apple-mobile-web-app-capable"]', {name: "apple-mobile-web-app-capable", content: "yes"});
      } else {
        // Streamlit Cloud: manifest opakowania ma start_url "/" i tryb pełnoekranowy —
        // ikonka z linku planu otwierała goły adres („Brak dostępu”, Filip 2026-10-01),
        // a pełny ekran gubi logowanie Streamlita (przekierowanie przez share.streamlit.io
        // wychodzi poza apkę). Mój manifest: bez start_url (= ten adres, z ?plan=),
        // otwiera się w Safari jak zakładka.
        ustaw("link", 'link[rel="manifest"]', {rel: "manifest", href: u("app/static/manifest-chmura.json")}, true);
        const cap = d.head.querySelector('meta[name="apple-mobile-web-app-capable"]');
        if (cap) cap.remove();
      }
      ustaw("meta", 'meta[name="apple-mobile-web-app-title"]', {name: "apple-mobile-web-app-title", content: NAZWA}, true);
      ustaw("meta", 'meta[name="theme-color"]', {name: "theme-color", content: "#000000"});
    } catch (e) {}
    </script>""", height=0)
