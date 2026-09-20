# AthleteLab — aplikacja do planów treningowych

Kod aplikacji (Streamlit) do układania planów treningowych i prowadzenia
bazy ćwiczeń. To repozytorium zawiera **wyłącznie kod** — żadnych danych
zawodników ani wyników testów.

Dane (plany, baza ćwiczeń) żyją w zewnętrznym magazynie; adres i klucz
podaje się przez sekrety Streamlita, nie przez repo:

```toml
[supabase]
url = "…"
key = "…"
workspace = "nazwa"      # osobna przestrzeń danych dla tej instancji
tylko_plany = "1"        # bez modułu Performance testing
coach_name = "Coach …"   # podpis w aplikacji
```

Uruchomienie lokalne: `streamlit run app.py`
