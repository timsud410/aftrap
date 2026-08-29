#!/usr/bin/env python3
"""Laad komende wedstrijden uit API-Football Pro.

De API-key komt uitsluitend uit de omgeving (`API_FOOTBALL_KEY`). De loader
vraagt per competitie één compact datumvenster op en logt nooit headers of de
sleutel zelf.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta

import db as store
from load_fdcouk import DEFAULT_DB, current_season_start

BASE_URL = "https://v3.football.api-sports.io"
SOURCE = "api_football"
DEFAULT_HORIZON_DAYS = 8

# Alleen bewezen naamverschillen worden handmatig gekoppeld. Alle overige
# namen gaan door een unieke genormaliseerde match; bij twijfel ontstaat een
# nieuw, zichtbaar team in plaats van een stille verkeerde koppeling.
TEAM_NAME_ALIASES: dict[tuple[str, str], str] = {
    ("EPL", "Manchester City"): "Man City",
    ("EPL", "Manchester United"): "Man United",
    ("EPL", "Nottingham Forest"): "Nott'm Forest",
    ("EPL", "Wolverhampton"): "Wolves",
    ("LIG", "Atletico Madrid"): "Ath Madrid",
    ("LIG", "Athletic Club"): "Ath Bilbao",
    ("LIG", "Celta Vigo"): "Celta",
    ("LIG", "Espanyol"): "Espanol",
    ("LIG", "Rayo Vallecano"): "Vallecano",
    ("LIG", "Real Betis"): "Betis",
    ("LIG", "Real Sociedad"): "Sociedad",
    ("SEA", "AC Milan"): "Milan",
    ("SEA", "Hellas Verona"): "Verona",
    ("FR1", "Paris Saint Germain"): "Paris SG",
    ("FR1", "Saint Etienne"): "St Etienne",
    ("BUN", "Bayern München"): "Bayern Munich",
    ("BUN", "Borussia Mönchengladbach"): "M'gladbach",
    ("BUN", "Eintracht Frankfurt"): "Ein Frankfurt",
    ("BUN", "Bayer Leverkusen"): "Leverkusen",
    ("BUN", "Borussia Dortmund"): "Dortmund",
    ("BUN", "1.FC Köln"): "FC Koln",
    ("BUN", "1. FC Köln"): "FC Koln",
    ("BUN", "FSV Mainz 05"): "Mainz",
    ("BUN", "FC St. Pauli"): "St Pauli",
    ("BUN", "1899 Hoffenheim"): "Hoffenheim",
    ("BUN", "1. FC Union Berlin"): "Union Berlin",
    ("ERE", "Fortuna Sittard"): "For Sittard",
    ("ERE", "NEC Nijmegen"): "Nijmegen",
    ("ERE", "FC Utrecht"): "Utrecht",
    ("ERE", "PEC Zwolle"): "Zwolle",
    ("ERE", "RKC Waalwijk"): "Waalwijk",
    ("ERE", "SC Heerenveen"): "Heerenveen",
    ("ERE", "FC Volendam"): "Volendam",
}


def api_get(path: str, params: dict[str, object], api_key: str) -> dict:
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(
        f"{BASE_URL}/{path}?{query}",
        headers={"x-apisports-key": api_key, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=40) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"API-Football verzoek mislukt: {exc}") from exc
    errors = payload.get("errors")
    if errors and errors not in ({}, []):
        raise RuntimeError(f"API-Football gaf een fout: {errors}")
    if not isinstance(payload.get("response"), list):
        raise RuntimeError("API-Football antwoord mist een response-lijst")
    return payload


def _normalise(name: str) -> str:
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    keep = "".join(c.lower() if c.isalnum() else " " for c in text)
    words = [w for w in keep.split() if w not in {"fc", "afc", "cf", "calcio"}]
    return " ".join(words)


def resolve_team(
    conn: sqlite3.Connection,
    league_code: str,
    api_id: int,
    api_name: str,
) -> tuple[int, bool]:
    alias = str(api_id)
    row = conn.execute(
        "SELECT team_id FROM team_aliases WHERE source = ? AND alias = ?",
        (SOURCE, alias),
    ).fetchone()
    if row:
        return int(row["team_id"]), False

    preferred = TEAM_NAME_ALIASES.get((league_code, api_name), api_name)
    row = conn.execute(
        "SELECT id FROM teams WHERE league_code = ? AND name = ?",
        (league_code, preferred),
    ).fetchone()
    if row:
        team_id = int(row["id"])
    else:
        wanted = _normalise(preferred)
        candidates = [
            r for r in conn.execute(
                "SELECT id, name FROM teams WHERE league_code = ?", (league_code,)
            )
            if _normalise(r["name"]) == wanted
        ]
        if len(candidates) == 1:
            team_id = int(candidates[0]["id"])
        else:
            cur = conn.execute(
                "INSERT INTO teams (league_code, name) VALUES (?, ?)",
                (league_code, api_name),
            )
            team_id = int(cur.lastrowid)
            conn.execute(
                "INSERT INTO team_aliases (source, alias, team_id) VALUES (?, ?, ?)",
                (SOURCE, alias, team_id),
            )
            return team_id, True

    conn.execute(
        "INSERT INTO team_aliases (source, alias, team_id) VALUES (?, ?, ?)",
        (SOURCE, alias, team_id),
    )
    return team_id, False


def _local_date_time(value: str) -> tuple[str, str | None]:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.date().isoformat(), parsed.strftime("%H:%M")


def store_fixture(
    conn: sqlite3.Connection, league_code: str, item: dict
) -> tuple[int, bool, list[str]]:
    fixture = item["fixture"]
    league = item["league"]
    teams = item["teams"]
    goals = item.get("goals") or {}
    score = item.get("score") or {}
    halftime = score.get("halftime") or {}
    external_id = str(fixture["id"])
    match_date, kickoff = _local_date_time(fixture["date"])

    home_id, home_new = resolve_team(
        conn, league_code, int(teams["home"]["id"]), teams["home"]["name"]
    )
    away_id, away_new = resolve_team(
        conn, league_code, int(teams["away"]["id"]), teams["away"]["name"]
    )
    new_names = []
    if home_new:
        new_names.append(teams["home"]["name"])
    if away_new:
        new_names.append(teams["away"]["name"])

    mapped = conn.execute(
        "SELECT fixture_id FROM fixture_external_ids WHERE source=? AND external_id=?",
        (SOURCE, external_id),
    ).fetchone()
    fixture_id = int(mapped["fixture_id"]) if mapped else None
    if fixture_id is None:
        existing = conn.execute(
            """SELECT id FROM fixtures
               WHERE league_code=? AND season=? AND match_date=?
                 AND home_team_id=? AND away_team_id=?""",
            (league_code, int(league["season"]), match_date, home_id, away_id),
        ).fetchone()
        fixture_id = int(existing["id"]) if existing else None

    created = fixture_id is None
    if created:
        cur = conn.execute(
            """INSERT INTO fixtures
               (league_code, season, match_date, kickoff, home_team_id, away_team_id,
                home_goals, away_goals, home_goals_ht, away_goals_ht, status)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                league_code, int(league["season"]), match_date, kickoff,
                home_id, away_id, goals.get("home"), goals.get("away"),
                halftime.get("home"), halftime.get("away"),
                fixture["status"]["short"],
            ),
        )
        fixture_id = int(cur.lastrowid)
    else:
        conn.execute(
            """UPDATE fixtures SET season=?, match_date=?, kickoff=?,
                  home_team_id=?, away_team_id=?, home_goals=?, away_goals=?,
                  home_goals_ht=?, away_goals_ht=?, status=?
               WHERE id=?""",
            (
                int(league["season"]), match_date, kickoff, home_id, away_id,
                goals.get("home"), goals.get("away"), halftime.get("home"),
                halftime.get("away"), fixture["status"]["short"], fixture_id,
            ),
        )

    conn.execute(
        """INSERT OR IGNORE INTO fixture_external_ids
           (source, external_id, fixture_id) VALUES (?,?,?)""",
        (SOURCE, external_id, fixture_id),
    )
    return fixture_id, created, new_names


def load_upcoming(
    conn: sqlite3.Connection,
    api_key: str,
    start: date | None = None,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
) -> dict:
    start = start or date.today()
    end = start + timedelta(days=horizon_days)
    season = current_season_start(start)
    leagues = conn.execute(
        """SELECT code, name, api_football_id FROM leagues
           WHERE api_football_id IS NOT NULL ORDER BY name"""
    ).fetchall()

    fetched = created = 0
    new_teams: list[str] = []
    for league in leagues:
        payload = api_get(
            "fixtures",
            {
                "league": league["api_football_id"],
                "season": season,
                "from": start.isoformat(),
                "to": end.isoformat(),
                "timezone": "Europe/Amsterdam",
            },
            api_key,
        )
        items = payload["response"]
        for item in items:
            _, was_created, names = store_fixture(conn, league["code"], item)
            fetched += 1
            created += int(was_created)
            new_teams.extend(f"{league['code']}: {name}" for name in names)
        print(f"  {league['name']:<16}{len(items):>3} wedstrijden")
    conn.commit()
    return {
        "fetched": fetched,
        "created": created,
        "new_teams": sorted(set(new_teams)),
        "from": start.isoformat(),
        "to": end.isoformat(),
    }


def main() -> int:
    api_key = os.environ.get("API_FOOTBALL_KEY", "").strip()
    if not api_key:
        print("API_FOOTBALL_KEY ontbreekt.")
        return 1
    conn = store.connect(DEFAULT_DB)
    try:
        result = load_upcoming(conn, api_key)
    except Exception as exc:
        print(f"API-Football laden mislukt: {exc}")
        return 1
    print(
        f"\n{result['fetched']} fixtures gelezen, {result['created']} nieuw "
        f"({result['from']} t/m {result['to']})."
    )
    if result["new_teams"]:
        print("Nieuwe teams zonder historische koppeling:")
        for name in result["new_teams"]:
            print(f"  - {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
