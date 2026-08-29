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

import os
import shutil
import sys
import traceback
from datetime import date
from pathlib import Path

import db as store

HERE = Path(__file__).resolve().parent
SITE = HERE / "site"
SOCIAL_CARD = HERE / "assets" / "aftrap-og.png"
ACCOUNT_JS = HERE / "assets" / "aftrap-account.js"
ACCOUNT_CSS = HERE / "assets" / "aftrap-account.css"
APP_ASSETS = (
    HERE / "assets" / "aftrap-icon-192.png",
    HERE / "assets" / "aftrap-icon-512.png",
    HERE / "assets" / "apple-touch-icon.png",
    HERE / "assets" / "favicon-32.png",
    HERE / "assets" / "manifest.webmanifest",
)

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
        import load_api_football
        import run_tips
    except ImportError as e:
        print(f"Kan de modules niet laden: {e}")
        return 1

    this_year = load_fdcouk.current_season_start(date.today())

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
        if SOCIAL_CARD.exists():
            shutil.copy2(SOCIAL_CARD, SITE / "aftrap-og.png")
        shutil.copy2(ACCOUNT_JS, SITE / ACCOUNT_JS.name)
        shutil.copy2(ACCOUNT_CSS, SITE / ACCOUNT_CSS.name)
        for asset in APP_ASSETS:
            shutil.copy2(asset, SITE / asset.name)

    def load_upcoming() -> None:
        api_key = os.environ.get("API_FOOTBALL_KEY", "").strip()
        if not api_key:
            print("  API_FOOTBALL_KEY ontbreekt; lokale terugkijkmodus blijft actief.")
            return
        conn = store.connect(load_fdcouk.DEFAULT_DB)
        try:
            result = load_api_football.load_upcoming(conn, api_key)
            odds_result = load_api_football.load_pre_match_odds(conn, api_key)
            player_result = load_api_football.load_recent_player_stats(conn, api_key)
        finally:
            conn.close()
        print(
            f"\n  {result['fetched']} komende fixtures gelezen, "
            f"{result['created']} nieuw."
        )
        if result["new_teams"]:
            print("  Nieuwe teams zonder historische naamkoppeling:")
            for name in result["new_teams"]:
                print(f"    - {name}")
        print(
            f"  Spelersvorm: {player_result['teams']} teams, "
            f"{player_result['fixtures']} recente duels, "
            f"{player_result['player_rows']} spelerregels "
            f"({player_result['cached']} uit cache)."
        )
        print(
            f"  Odds: {odds_result['with_odds']}/{odds_result['fixtures']} wedstrijden, "
            f"{odds_result['bookmakers']} bookmakers, {odds_result['rows']} quoteringen "
            f"({odds_result['calls']} API-calls)."
        )
        if odds_result["failures"]:
            print(f"  Let op: odds ophalen mislukte voor {odds_result['failures']} wedstrijden.")
        if player_result["team_failures"] or player_result["fixture_failures"]:
            print(
                "  Let op: spelersdata ontbrak voor "
                f"{player_result['team_failures']} teams en "
                f"{player_result['fixture_failures']} duels."
            )

    try:
        step("Data ophalen", load)
        step("Komende wedstrijden ophalen", load_upcoming)
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
