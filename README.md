# Trumf-scraper

Et lite Python-prosjekt som viser hvordan du kan skrape ukestilbud fra
Trumf-partnere og lagre resultatet lokalt i en CSV-fil. Scriptet laster
inn både PDF-baserte kundeaviser (Meny) og HTML-baserte butikksider
(Spar, Kiwi, Joker, Norli og Mester Grønn).

## Kom i gang

1. Opprett et virtuelt miljø (anbefalt) og installer avhengigheter:

   ```bash
   python -m venv .venv
   source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
   pip install -r requirements.txt
   ```

2. Kjør scrapteren fra prosjektroten:

   ```bash
   python -m src.trumf_scraper
   ```

   Programmet lagrer en fil som heter `data/trumf-tilbud-YYYYMMDD-HHMMSS.csv`
   med kolonnene `butikk`, `tittel`, `pris` og `ekstrainfo`.

## Struktur

- `src/trumf_scraper.py` – hovedscriptet som inneholder alt av
  skrapelogikk.
- `requirements.txt` – Python-avhengigheter.
- `data/` – mappe hvor CSV-filene legges (opprettes automatisk når
  skriptet kjøres).

## Videre arbeid

Tilbudssidene endrer seg ofte. Dersom strukturen på nettsidene endres,
kan du oppdatere de respektive `scrape_*`-funksjonene i
`src/trumf_scraper.py`. Det kan også være nyttig å legge inn flere
valideringer, logging eller eksport til andre formater (for eksempel
Excel eller en lokal database).
