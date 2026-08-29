#!/usr/bin/env python3
"""
Eén knop: data ophalen, model draaien, pagina wegschrijven.

Dit is wat GitHub elke ochtend uitvoert. Het roept dezelfde loader en
dezelfde runner aan die je ook lokaal zou gebruiken, zodat er geen tweede
versie van de logica ontstaat die stilletjes uit de pas gaat lopen.

Faalt een onderdeel, dan stopt het script met een foutcode. Liever geen
pagina dan een pagina met tips van vorige week zonder dat je dat ziet.
"""

from __future__ import annotations

import sys
import traceback
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
SITE = HERE / "site"

# Hoeveel seizoenen we inladen. Meer is beter voor het toetsen van signalen;
# vanaf ongeveer 2010 is de dekking van schoten en corners in de meeste
# competities compleet.
FROM_SEASON = 2010


def step(name: str, fn) -> None:
    print(f"\n{'=' * 66}\n  {name}\n{'=' * 66}", flush=True)
    fn()


def main() -> int:
    try:
        import load_fdcouk
        import run_tips
    except ImportError as e:
        print(f"Kan de modules niet laden: {e}")
        return 1

    this_year = date.today().year

    def load() -> None:
        rc = load_fdcouk.main_with_args(
            from_season=FROM_SEASON, to_season=this_year, leagues=None, refresh=False
        )
        if rc != 0:
            raise RuntimeError("inladen mislukt")

    def build() -> None:
        SITE.mkdir(parents=True, exist_ok=True)
        rc = run_tips.main_with_args(out=str(SITE / "index.html"))
        if rc != 0:
            raise RuntimeError("tips genereren mislukt")

    try:
        step("Data ophalen", load)
        step("Tips genereren", build)
    except Exception:
        traceback.print_exc()
        return 1

    index = SITE / "index.html"
    if not index.exists() or index.stat().st_size < 2000:
        print("De pagina is niet of nauwelijks geschreven; dat klopt niet.")
        return 1

    print(f"\n  Klaar. {index} is {index.stat().st_size // 1024} kB.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
