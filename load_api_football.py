#!/usr/bin/env python3
"""Laad komende wedstrijden uit API-Football Pro.

De API-key komt uitsluitend uit de omgeving (`API_FOOTBALL_KEY`). De loader
vraagt per competitie één compact datumvenster op en logt nooit headers of de
sleutel zelf.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

import db as store
from load_fdcouk import DEFAULT_DB, current_season_start

BASE_URL = "https://v3.football.api-sports.io"
SOURCE = "api_football"
DEFAULT_HORIZON_DAYS = 8
PLAYER_FORM_APPEARANCES = 5
PLAYER_FORM_FIXTURES = 8
PLAYER_FIXTURE_BATCH = 20

# Alleen bewezen naamverschillen worden handmatig gekoppeld. Alle overige
# namen gaan door een unieke genormaliseerde match; bij twijfel ontstaat een
# nieuw, zichtbaar team in plaats van een stille verkeerde koppeling.
TEAM_NAME_ALIASES: dict[tuple[str, str], str] = {
    ("EPL", "Manchester City"): "Man City",
    ("EPL", "Manchester United"): "Man United",
    ("EPL", "Nottingham Forest"): "Nott'm Forest",
    ("EPL", "Wolverhampton"): "Wolves",
    ("EPL", "Hull City"): "Hull",
    ("LIG", "Atletico Madrid"): "Ath Madrid",
    ("LIG", "Athletic Club"): "Ath Bilbao",
    ("LIG", "Celta Vigo"): "Celta",
    ("LIG", "Espanyol"): "Espanol",
    ("LIG", "Rayo Vallecano"): "Vallecano",
    ("LIG", "Real Betis"): "Betis",
    ("LIG", "Real Sociedad"): "Sociedad",
    ("LIG", "Deportivo La Coruna"): "La Coruna",
    ("LIG", "Racing Santander"): "Santander",
    ("SEA", "AC Milan"): "Milan",
    ("SEA", "Hellas Verona"): "Verona",
    ("SEA", "AS Roma"): "Roma",
    ("FR1", "Paris Saint Germain"): "Paris SG",
    ("FR1", "Saint Etienne"): "St Etienne",
    ("FR1", "Estac Troyes"): "Troyes",
    ("FR1", "Stade Brestois 29"): "Brest",
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
    ("BUN", "Hamburger SV"): "Hamburg",
    ("BUN", "SC Freiburg"): "Freiburg",
    ("BUN", "SC Paderborn 07"): "Paderborn",
    ("BUN", "VfB Stuttgart"): "Stuttgart",
    ("ERE", "Fortuna Sittard"): "For Sittard",
    ("ERE", "NEC Nijmegen"): "Nijmegen",
    ("ERE", "FC Utrecht"): "Utrecht",
    ("ERE", "PEC Zwolle"): "Zwolle",
    ("ERE", "RKC Waalwijk"): "Waalwijk",
    ("ERE", "SC Heerenveen"): "Heerenveen",
    ("ERE", "FC Volendam"): "Volendam",
    ("ERE", "ADO Den Haag"): "Den Haag",
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


def canonical_odd_selection(bet_name: str, outcome_name: str) -> str | None:
    """Vertaal gangbare pre-match API-markten naar onze modelselecties."""
    bet = _normalise(bet_name)
    outcome = _normalise(outcome_name)
    first_half = "first half" in bet or "1st half" in bet

    if "both teams" in bet and ("score" in bet or "to score" in bet):
        if outcome in {"yes", "no"}:
            return f"btts_{outcome}"

    if "winner" in bet or bet in {"match result", "1x2"}:
        result = {"home": "home", "draw": "draw", "away": "away"}.get(outcome)
        if result:
            return f"fh_{result}" if first_half else result

    if "double chance" in bet:
        compact = outcome.replace(" ", "")
        if compact in {"homedraw", "1x", "homeordraw"}:
            return "home_or_draw"
        if compact in {"drawaway", "x2", "awayordraw"}:
            return "away_or_draw"

    if "over under" in bet or "total goals" in bet:
        match = re.match(r"\s*(over|under)\s+([0-9]+(?:[.,][0-9]+)?)", outcome_name.lower())
        if match:
            kind, raw_line = match.groups()
            line = str(float(raw_line.replace(",", "."))).rstrip("0").rstrip(".")
            key = f"{kind}_{line}"
            if "home" in bet or "team 1" in bet:
                return f"home_{key}"
            if "away" in bet or "team 2" in bet:
                return f"away_{key}"
            return f"fh_{key}" if first_half else key
    return None


def _upcoming_api_fixtures(
    conn: sqlite3.Connection,
    start: date,
    horizon_days: int,
) -> list[sqlite3.Row]:
    end = start + timedelta(days=horizon_days)
    return conn.execute(
        """SELECT f.id fixture_id, x.external_id
           FROM fixtures f
           JOIN fixture_external_ids x ON x.fixture_id=f.id
             AND x.source='api_football'
           WHERE f.match_date BETWEEN ? AND ?
             AND f.home_goals IS NULL AND f.away_goals IS NULL
             AND f.status IN ('NS', 'TBD')
           ORDER BY f.match_date, f.kickoff""",
        (start.isoformat(), end.isoformat()),
    ).fetchall()


def _store_fixture_odds(
    conn: sqlite3.Connection,
    fixture_id: int,
    responses: list[dict],
) -> tuple[int, set[str]]:
    """Vervang één complete odds-snapshot nadat alle pagina's zijn ontvangen."""
    fetched_at = datetime.now().astimezone().isoformat(timespec="seconds")
    best_rows: dict[tuple[int, str], tuple] = {}
    bookmakers: set[str] = set()
    for response in responses:
        updated = response.get("update")
        for bookmaker in response.get("bookmakers") or []:
            bookmaker_id = bookmaker.get("id")
            bookmaker_name = str(bookmaker.get("name") or "").strip()
            if bookmaker_id is None or not bookmaker_name:
                continue
            bookmakers.add(bookmaker_name)
            for bet in bookmaker.get("bets") or []:
                bet_id = bet.get("id")
                bet_name = str(bet.get("name") or "").strip()
                if bet_id is None or not bet_name:
                    continue
                for value in bet.get("values") or []:
                    outcome = str(value.get("value") or "").strip()
                    try:
                        odd = float(value.get("odd"))
                    except (TypeError, ValueError):
                        continue
                    if not outcome or odd <= 1:
                        continue
                    selection = canonical_odd_selection(bet_name, outcome)
                    if selection is None:
                        continue
                    row = (
                        fixture_id, int(bookmaker_id), bookmaker_name, int(bet_id),
                        bet_name, outcome, selection, odd,
                        updated, fetched_at,
                    )
                    key = (int(bookmaker_id), selection)
                    if key not in best_rows or odd > best_rows[key][7]:
                        best_rows[key] = row

    rows = list(best_rows.values())

    conn.execute("DELETE FROM fixture_odds WHERE fixture_id=?", (fixture_id,))
    conn.executemany(
        """INSERT INTO fixture_odds
           (fixture_id, bookmaker_id, bookmaker_name, bet_id, bet_name,
            outcome_name, selection_key, odd, source_updated, fetched_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        rows,
    )
    conn.executemany(
        """INSERT INTO fixture_odds_history
           (fixture_id, bookmaker_id, bookmaker_name, selection_key, odd,
            source_updated, fetched_at)
           VALUES (?,?,?,?,?,?,?)
           ON CONFLICT(fixture_id, bookmaker_id, selection_key, source_updated)
           DO UPDATE SET odd=excluded.odd, fetched_at=excluded.fetched_at""",
        [
            (row[0], row[1], row[2], row[6], row[7], row[8] or fetched_at, fetched_at)
            for row in rows
        ],
    )
    return len(rows), bookmakers


def _availability_fixtures(
    conn: sqlite3.Connection,
    start: date,
    horizon_days: int,
) -> list[sqlite3.Row]:
    end = start + timedelta(days=horizon_days)
    return conn.execute(
        """SELECT f.id fixture_id, x.external_id, f.match_date, f.kickoff
           FROM fixtures f
           JOIN fixture_external_ids x ON x.fixture_id=f.id
             AND x.source='api_football'
           WHERE f.match_date BETWEEN ? AND ?
             AND f.home_goals IS NULL AND f.away_goals IS NULL
             AND f.status IN ('NS','TBD')
           ORDER BY f.match_date,f.kickoff""",
        (start.isoformat(), end.isoformat()),
    ).fetchall()


def _store_availability(
    conn: sqlite3.Connection,
    fixture_id: int,
    kind: str,
    payload: list[dict],
) -> None:
    fetched_at = datetime.now().astimezone().isoformat(timespec="seconds")
    conn.execute(
        """INSERT INTO fixture_availability
           (fixture_id,kind,payload_json,source_updated,fetched_at)
           VALUES (?,?,?,?,?)
           ON CONFLICT(fixture_id,kind) DO UPDATE SET
             payload_json=excluded.payload_json,
             source_updated=excluded.source_updated,
             fetched_at=excluded.fetched_at""",
        (fixture_id, kind, json.dumps(payload, ensure_ascii=False), fetched_at, fetched_at),
    )


def load_fixture_availability(
    conn: sqlite3.Connection,
    api_key: str,
    start: date | None = None,
) -> dict:
    """Laad blessures voor drie dagen en opstellingen vlak voor de aftrap."""
    start = start or date.today()
    injury_fixtures = _availability_fixtures(conn, start, 3)
    now = datetime.now()
    lineup_fixtures = []
    for fixture in _availability_fixtures(conn, start, 1):
        if not fixture["kickoff"]:
            continue
        kickoff = datetime.fromisoformat(f'{fixture["match_date"]}T{fixture["kickoff"]}:00')
        if timedelta(minutes=-30) <= kickoff - now <= timedelta(hours=3):
            lineup_fixtures.append(fixture)

    calls = failures = injury_rows = lineup_rows = 0
    for fixture in injury_fixtures:
        try:
            payload = api_get("injuries", {"fixture": fixture["external_id"]}, api_key)
            calls += 1
            _store_availability(conn, int(fixture["fixture_id"]), "injuries", payload["response"])
            injury_rows += len(payload["response"])
        except RuntimeError:
            failures += 1
    for fixture in lineup_fixtures:
        try:
            payload = api_get("fixtures/lineups", {"fixture": fixture["external_id"]}, api_key)
            calls += 1
            if payload["response"]:
                _store_availability(conn, int(fixture["fixture_id"]), "lineups", payload["response"])
                lineup_rows += len(payload["response"])
        except RuntimeError:
            failures += 1
    conn.commit()
    return {
        "calls": calls, "failures": failures,
        "injuries": injury_rows, "lineups": lineup_rows,
    }


def load_pre_match_odds(
    conn: sqlite3.Connection,
    api_key: str,
    start: date | None = None,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
) -> dict:
    """Laad alle pagina's met pre-match odds voor komende fixtures."""
    start = start or date.today()
    fixtures = _upcoming_api_fixtures(conn, start, horizon_days)
    rows = calls = failures = with_odds = 0
    bookmakers: set[str] = set()
    for fixture in fixtures:
        responses: list[dict] = []
        page = 1
        try:
            while True:
                payload = api_get(
                    "odds",
                    {"fixture": fixture["external_id"], "page": page},
                    api_key,
                )
                calls += 1
                responses.extend(payload["response"])
                paging = payload.get("paging") or {}
                if page >= int(paging.get("total") or 1):
                    break
                page += 1
        except RuntimeError:
            failures += 1
            continue
        stored, names = _store_fixture_odds(
            conn, int(fixture["fixture_id"]), responses
        )
        rows += stored
        bookmakers.update(names)
        with_odds += int(stored > 0)
    conn.commit()
    return {
        "fixtures": len(fixtures), "with_odds": with_odds, "rows": rows,
        "bookmakers": len(bookmakers), "calls": calls, "failures": failures,
    }


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
    query_start = start - timedelta(days=2)
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
                "from": query_start.isoformat(),
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
        "from": query_start.isoformat(),
        "to": end.isoformat(),
    }


def _upcoming_api_teams(
    conn: sqlite3.Connection,
    start: date,
    horizon_days: int,
) -> list[sqlite3.Row]:
    """API-team-ID's die daadwerkelijk in de komende periode voorkomen."""
    end = start + timedelta(days=horizon_days)
    return conn.execute(
        """SELECT DISTINCT t.id team_id, t.name, a.alias api_team_id
           FROM (
             SELECT home_team_id team_id FROM fixtures
              WHERE match_date BETWEEN ? AND ? AND home_goals IS NULL
                AND status IN ('NS', 'TBD')
             UNION
             SELECT away_team_id team_id FROM fixtures
              WHERE match_date BETWEEN ? AND ? AND away_goals IS NULL
                AND status IN ('NS', 'TBD')
           ) upcoming
           JOIN teams t ON t.id = upcoming.team_id
           JOIN team_aliases a ON a.team_id = t.id
             AND a.source = 'api_football'
           ORDER BY t.name""",
        (start.isoformat(), end.isoformat(), start.isoformat(), end.isoformat()),
    ).fetchall()


def _store_player_fixture(conn: sqlite3.Connection, item: dict) -> int:
    """Bewaar individuele schotcijfers uit één afgeronde API-fixture."""
    fixture = item.get("fixture") or {}
    external_fixture_id = str(fixture.get("id") or "")
    fixture_date = str(fixture.get("date") or "")[:10]
    if not external_fixture_id or len(fixture_date) != 10:
        return 0

    stored = 0
    for team_block in item.get("players") or []:
        api_team = team_block.get("team") or {}
        mapping = conn.execute(
            """SELECT team_id FROM team_aliases
               WHERE source = 'api_football' AND alias = ?""",
            (str(api_team.get("id") or ""),),
        ).fetchone()
        if not mapping:
            continue
        team_id = int(mapping["team_id"])
        for entry in team_block.get("players") or []:
            player = entry.get("player") or {}
            external_player_id = str(player.get("id") or "")
            name = str(player.get("name") or "").strip()
            stats = (entry.get("statistics") or [{}])[0] or {}
            if not external_player_id or not name:
                continue
            conn.execute(
                """INSERT INTO players (source, external_id, name, photo)
                   VALUES ('api_football', ?, ?, ?)
                   ON CONFLICT(source, external_id) DO UPDATE SET
                     name=excluded.name, photo=excluded.photo""",
                (external_player_id, name, player.get("photo")),
            )
            player_row = conn.execute(
                """SELECT id FROM players
                   WHERE source='api_football' AND external_id=?""",
                (external_player_id,),
            ).fetchone()
            games = stats.get("games") or {}
            shots = stats.get("shots") or {}
            conn.execute(
                """INSERT INTO player_match_stats
                   (source, external_fixture_id, match_date, team_id, player_id,
                    minutes, shots, shots_on_target)
                   VALUES ('api_football', ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(source, external_fixture_id, player_id) DO UPDATE SET
                     match_date=excluded.match_date,
                     team_id=excluded.team_id,
                     minutes=excluded.minutes,
                     shots=excluded.shots,
                     shots_on_target=excluded.shots_on_target""",
                (
                    external_fixture_id,
                    fixture_date,
                    team_id,
                    int(player_row["id"]),
                    games.get("minutes"),
                    shots.get("total"),
                    shots.get("on"),
                ),
            )
            stored += 1
    return stored


def load_recent_player_stats(
    conn: sqlite3.Connection,
    api_key: str,
    start: date | None = None,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
    recent_fixtures: int = PLAYER_FORM_FIXTURES,
    cache_dir: str | Path | None = None,
) -> dict:
    """Laad recente individuele schotcijfers voor teams in de vooruitblik.

    Afgeronde fixture-details worden op schijf gecachet: die veranderen niet
    meer en kosten daardoor na de eerste run geen nieuwe API-call.
    """
    start = start or date.today()
    cache = Path(cache_dir) if cache_dir else Path(DEFAULT_DB).parent / "api_football" / "players"
    cache.mkdir(parents=True, exist_ok=True)
    teams = _upcoming_api_teams(conn, start, horizon_days)
    fixtures: dict[str, dict] = {}
    team_failures = 0
    for team in teams:
        try:
            payload = api_get(
                "fixtures",
                {
                    "team": team["api_team_id"],
                    "last": recent_fixtures,
                    "status": "FT-AET-PEN",
                    "timezone": "Europe/Amsterdam",
                },
                api_key,
            )
        except RuntimeError:
            team_failures += 1
            continue
        for item in payload["response"]:
            fixture = item.get("fixture") or {}
            if fixture.get("id") and str(fixture.get("date") or "")[:10] < start.isoformat():
                fixtures[str(fixture["id"])] = item

    cached = fetched = fixture_failures = player_rows = 0
    missing: list[str] = []
    for fixture_id in sorted(fixtures, key=int):
        path = cache / f"{fixture_id}.json"
        if path.exists():
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
                player_rows += _store_player_fixture(conn, item)
                cached += 1
                continue
            except (OSError, json.JSONDecodeError, TypeError):
                pass
        missing.append(fixture_id)

    for offset in range(0, len(missing), PLAYER_FIXTURE_BATCH):
        batch = missing[offset:offset + PLAYER_FIXTURE_BATCH]
        try:
            payload = api_get("fixtures", {"ids": "-".join(batch)}, api_key)
            returned = {
                str((item.get("fixture") or {}).get("id")): item
                for item in payload["response"]
            }
        except RuntimeError:
            returned = {}
        for fixture_id in batch:
            item = returned.get(fixture_id) or fixtures[fixture_id]
            if not item.get("players"):
                try:
                    player_payload = api_get(
                        "fixtures/players", {"fixture": fixture_id}, api_key
                    )
                    item = dict(item)
                    item["players"] = player_payload["response"]
                except RuntimeError:
                    fixture_failures += 1
                    continue
            try:
                (cache / f"{fixture_id}.json").write_text(
                    json.dumps(item, ensure_ascii=False, separators=(",", ":")),
                    encoding="utf-8",
                )
                player_rows += _store_player_fixture(conn, item)
                fetched += 1
            except (OSError, TypeError):
                fixture_failures += 1

    conn.commit()
    return {
        "teams": len(teams),
        "fixtures": len(fixtures),
        "cached": cached,
        "fetched": fetched,
        "player_rows": player_rows,
        "team_failures": team_failures,
        "fixture_failures": fixture_failures,
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
