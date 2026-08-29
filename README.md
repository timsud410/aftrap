# Aftrap

Dagelijkse voetbalprognoses uit een eigen statistiekmodel. Met een API-Football
sleutel toont de pagina de nog te spelen wedstrijden van de komende acht dagen.
Zonder sleutel valt de lokale build terug op de laatste gespeelde wedstrijddag.

Voor teams in die vooruitblik haalt de build ook individuele schotdata op. Per
uitgelichte wedstrijd toont het dashboard maximaal twee spelers per team met
hun gemiddelde schoten op doel, gemiddelde totale schoten en het aandeel van
hun laatste maximaal vijf optredens waarin zij minimaal één schot op doel
hadden. Deze spelersvorm is beschrijvend en wordt niet als backtest-signaal
gepresenteerd.

## Betrouwbaarheidsregels

- De schoten-op-doelproxy voor een wedstrijd gebruikt alleen de historische
  omzettingsfactor die vóór die wedstrijddag bekend was.
- Signaalgewichten komen uit een chronologische walk-forward backtest; er staan
  geen handmatig verzonnen trefpercentages meer in de applicatie.
- Gewichten zijn richting-specifiek. `btts_yes` en `btts_no` worden bijvoorbeeld
  afzonderlijk beoordeeld.
- Training, validatie en test liggen chronologisch na elkaar.
- Waar exacte slotkoersen beschikbaar zijn, moet ook de ondergrens van het
  95%-interval van het rendement positief zijn. Zonder marktkoers heet een
  signaal alleen voorspellend, niet rendabel.

## Installeren en testen

Python 3.9 of nieuwer is vereist.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -v
```

## Data en dashboard bouwen

```bash
.venv/bin/python build_site.py
```

Dit haalt historische CSV-bestanden op, ververst het lopende seizoen en schrijft
`site/index.html`. Een echte downloadfout laat de build mislukken; een competitie
waarvan het nieuwe seizoen nog niet beschikbaar is geldt niet als fout.

Voor de vooruitblik zet je de API-Football sleutel alleen als omgevingsvariabele:

```bash
API_FOOTBALL_KEY="..." .venv/bin/python build_site.py
```

In GitHub Actions heet het repository-secret eveneens `API_FOOTBALL_KEY`. De
sleutel komt niet in de broncode of in de gebouwde webpagina terecht.
Afgeronde spelerstatistieken worden in `data/api_football` gecachet, zodat een
dagelijkse build dezelfde duels niet opnieuw van de API hoeft te halen.

## Walk-forward backtest

```bash
.venv/bin/python backtest.py \
  --from-season 2011 \
  --to-season 2025 \
  --validation-start 2022 \
  --test-start 2024
```

Uitvoer:

- `reports/backtest_records.csv`: één regel per signaal en wedstrijd;
- `reports/backtest_summary.json`: kalibratie, Brier score, log loss,
  trefpercentages, onzekerheidsintervallen en marktresultaten;
- `signal_weights.json`: uitsluitend de goedgekeurde richting-specifieke
  gewichten die het dashboard mag gebruiken.

De meegeleverde gewichten zijn getraind tot en met seizoen 2023/24 en één keer
getoetst op 2024/25 en 2025/26. Nieuwe seizoenen vormen de volgende echte
productie-holdout.
