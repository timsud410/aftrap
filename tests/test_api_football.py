import copy
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import db as store
from load_api_football import (
    TEAM_NAME_ALIASES,
    _store_player_fixture,
    canonical_odd_selection,
    load_pre_match_odds,
    load_recent_player_stats,
    resolve_team,
    store_fixture,
)
from run_tips import _fixture_odds, pick_upcoming_dates, player_shot_form


FIXTURE = {
    "fixture": {
        "id": 123456,
        "date": "2026-09-05T16:30:00+02:00",
        "status": {"short": "NS"},
    },
    "league": {"id": 39, "season": 2026},
    "teams": {
        "home": {"id": 50, "name": "Manchester City"},
        "away": {"id": 33, "name": "Manchester United"},
    },
    "goals": {"home": None, "away": None},
    "score": {"halftime": {"home": None, "away": None}},
}


class ApiFootballStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = store.connect(Path(self.tmp.name) / "test.sqlite")
        store.team_id(self.conn, "EPL", "Man City")
        store.team_id(self.conn, "EPL", "Man United")
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_known_api_names_map_to_historical_teams(self):
        fixture_id, created, new_names = store_fixture(self.conn, "EPL", FIXTURE)
        self.assertTrue(created)
        self.assertEqual(new_names, [])
        row = self.conn.execute(
            """SELECT th.name home, ta.name away
               FROM fixtures f JOIN teams th ON th.id=f.home_team_id
               JOIN teams ta ON ta.id=f.away_team_id WHERE f.id=?""",
            (fixture_id,),
        ).fetchone()
        self.assertEqual((row["home"], row["away"]), ("Man City", "Man United"))

    def test_every_declared_name_alias_resolves_to_history(self):
        for (league, _), historical_name in TEAM_NAME_ALIASES.items():
            store.team_id(self.conn, league, historical_name)
        self.conn.commit()

        for api_id, ((league, api_name), historical_name) in enumerate(
            TEAM_NAME_ALIASES.items(), start=1000
        ):
            team_id, created = resolve_team(
                self.conn, league, api_id, api_name
            )
            row = self.conn.execute(
                "SELECT name FROM teams WHERE id=?", (team_id,)
            ).fetchone()
            self.assertFalse(created, f"{league}: {api_name}")
            self.assertEqual(row["name"], historical_name)

    def test_external_id_updates_postponed_fixture_in_place(self):
        fixture_id, _, _ = store_fixture(self.conn, "EPL", FIXTURE)
        moved = copy.deepcopy(FIXTURE)
        moved["fixture"]["date"] = "2026-09-06T18:00:00+02:00"
        moved["fixture"]["status"]["short"] = "PST"
        updated_id, created, _ = store_fixture(self.conn, "EPL", moved)
        self.assertEqual(updated_id, fixture_id)
        self.assertFalse(created)
        row = self.conn.execute(
            "SELECT match_date, kickoff, status FROM fixtures WHERE id=?",
            (fixture_id,),
        ).fetchone()
        self.assertEqual((row["match_date"], row["kickoff"], row["status"]),
                         ("2026-09-06", "18:00", "PST"))

    def test_upcoming_window_only_contains_playable_api_fixtures(self):
        store_fixture(self.conn, "EPL", FIXTURE)
        self.conn.commit()
        self.assertEqual(
            pick_upcoming_dates(self.conn, date(2026, 9, 1), horizon_days=7),
            ["2026-09-05"],
        )

        postponed = copy.deepcopy(FIXTURE)
        postponed["fixture"]["status"]["short"] = "PST"
        store_fixture(self.conn, "EPL", postponed)
        self.conn.commit()
        self.assertEqual(
            pick_upcoming_dates(self.conn, date(2026, 9, 1), horizon_days=7),
            [],
        )

    def test_api_markets_map_to_model_selections(self):
        self.assertEqual(canonical_odd_selection("Match Winner", "Home"), "home")
        self.assertEqual(canonical_odd_selection("Both Teams Score", "Yes"), "btts_yes")
        self.assertEqual(canonical_odd_selection("Double Chance", "Home/Draw"), "home_or_draw")
        self.assertEqual(canonical_odd_selection("Goals Over/Under", "Over 2.5"), "over_2.5")
        self.assertEqual(
            canonical_odd_selection("Goals Over/Under - First Half", "Under 1.5"),
            "fh_under_1.5",
        )
        self.assertEqual(
            canonical_odd_selection("Home Team Goals", "Over", "1.5"),
            "home_over_1.5",
        )
        self.assertIsNone(canonical_odd_selection("Second Half Winner", "Home"))
        self.assertIsNone(canonical_odd_selection("Corners Winner", "Home"))
        self.assertIsNone(
            canonical_odd_selection("Both Teams Score - First Half", "Yes")
        )
        self.assertIsNone(
            canonical_odd_selection("Goals Over/Under - Second Half", "Over 1.5")
        )

    def test_odds_loader_stores_bookmakers_and_replaces_snapshot(self):
        fixture_id, _, _ = store_fixture(self.conn, "EPL", FIXTURE)
        self.conn.commit()
        response = {
            "response": [{
                "fixture": {"id": 123456},
                "update": "2026-09-01T08:00:00+00:00",
                "bookmakers": [{
                    "id": 8, "name": "TestBet", "bets": [{
                        "id": 1, "name": "Match Winner", "values": [
                            {"value": "Home", "odd": "1.95"},
                            {"value": "Draw", "odd": "3.40"},
                            {"value": "Away", "odd": "4.10"},
                        ],
                    }, {
                        "id": 3, "name": "Second Half Winner", "values": [
                            {"value": "Home", "odd": "9.00"},
                            {"value": "Draw", "odd": "8.00"},
                            {"value": "Away", "odd": "7.00"},
                        ],
                    }],
                }],
            }],
            "paging": {"current": 1, "total": 1},
        }
        with patch("load_api_football.api_get", return_value=response) as api:
            result = load_pre_match_odds(
                self.conn, "secret", date(2026, 9, 1), horizon_days=7
            )
        self.assertEqual(api.call_count, 1)
        self.assertEqual(result["with_odds"], 1)
        self.assertEqual(result["bookmakers"], 1)
        self.assertEqual(result["rows"], 3)
        self.assertTrue(result["mapping_reset"])
        row = self.conn.execute(
            """SELECT bookmaker_name, selection_key, odd FROM fixture_odds
               WHERE fixture_id=? AND selection_key='home'""",
            (fixture_id,),
        ).fetchone()
        self.assertEqual((row["bookmaker_name"], row["selection_key"], row["odd"]),
                         ("TestBet", "home", 1.95))
        current, movement = _fixture_odds(self.conn, fixture_id)
        self.assertAlmostEqual(sum(item["f"] for item in current), 1.0, places=3)
        self.assertEqual(len(movement), 3)
        self.assertTrue(all(item["n"] == 1 for item in movement))
        self.assertTrue(all(item["a"] == item["c"] for item in movement))

        empty = {"response": [], "paging": {"current": 1, "total": 1}}
        with patch("load_api_football.api_get", return_value=empty):
            result = load_pre_match_odds(
                self.conn, "secret", date(2026, 9, 1), horizon_days=7
            )
        self.assertEqual(result["rows"], 0)
        self.assertFalse(result["mapping_reset"])
        count = self.conn.execute(
            "SELECT COUNT(*) n FROM fixture_odds WHERE fixture_id=?", (fixture_id,)
        ).fetchone()["n"]
        self.assertEqual(count, 0)
        history_count = self.conn.execute(
            "SELECT COUNT(*) n FROM fixture_odds_history WHERE fixture_id=?", (fixture_id,)
        ).fetchone()["n"]
        self.assertEqual(history_count, 3)

    def test_player_shots_are_stored_and_summarised_over_last_five_appearances(self):
        store_fixture(self.conn, "EPL", FIXTURE)
        team_id = self.conn.execute(
            "SELECT id FROM teams WHERE league_code='EPL' AND name='Man City'"
        ).fetchone()["id"]
        for index, shots_on in enumerate((0, 1, 2, 1, 3, 4), start=1):
            item = {
                "fixture": {
                    "id": 900000 + index,
                    "date": f"2026-08-{20 + index:02d}T15:00:00+02:00",
                },
                "players": [{
                    "team": {"id": 50, "name": "Manchester City"},
                    "players": [{
                        "player": {"id": 777, "name": "Test Spits", "photo": None},
                        "statistics": [{
                            "games": {"minutes": 80},
                            "shots": {"total": shots_on + 2, "on": shots_on},
                        }],
                    }],
                }],
            }
            self.assertEqual(_store_player_fixture(self.conn, item), 1)
        one_match_outlier = {
            "fixture": {"id": 900099, "date": "2026-08-27T15:00:00+02:00"},
            "players": [{
                "team": {"id": 50, "name": "Manchester City"},
                "players": [{
                    "player": {"id": 779, "name": "Eenmalige Uitschieter"},
                    "statistics": [{
                        "games": {"minutes": 15},
                        "shots": {"total": 9, "on": 9},
                    }],
                }],
            }],
        }
        self.assertEqual(_store_player_fixture(self.conn, one_match_outlier), 1)
        self.conn.commit()

        form = player_shot_form(
            self.conn, int(team_id), "2026-08-29", appearances=5
        )
        self.assertEqual(len(form), 2)
        self.assertEqual(form[0]["name"], "Test Spits")
        self.assertEqual(form[0]["n"], 5)
        self.assertEqual(form[0]["sot_avg"], 2.2)
        self.assertEqual(form[0]["sot_hits"], 5)
        self.assertEqual(form[0]["sot_hit_rate"], 1.0)

    def test_recent_player_loader_batches_and_reuses_finished_fixture_cache(self):
        store_fixture(self.conn, "EPL", FIXTURE)
        self.conn.commit()
        recent = {
            "fixture": {"id": 888001, "date": "2026-08-30T15:00:00+02:00"},
            "players": [],
        }
        detailed = copy.deepcopy(recent)
        detailed["players"] = [
            {
                "team": {"id": 50, "name": "Manchester City"},
                "players": [{
                    "player": {"id": 778, "name": "Cache Spits"},
                    "statistics": [{
                        "games": {"minutes": 90},
                        "shots": {"total": 4, "on": 2},
                    }],
                }],
            },
            {
                "team": {"id": 33, "name": "Manchester United"},
                "players": [],
            },
        ]

        def fake_get(path, params, _key):
            if path == "fixtures" and "team" in params:
                return {"response": [recent]}
            if path == "fixtures" and "ids" in params:
                return {"response": [detailed]}
            self.fail(f"Onverwachte API-call: {path} {params}")

        cache = Path(self.tmp.name) / "player-cache"
        with patch("load_api_football.api_get", side_effect=fake_get) as api:
            first = load_recent_player_stats(
                self.conn, "secret", date(2026, 9, 1), cache_dir=cache
            )
            self.assertEqual(first["fetched"], 1)
            self.assertEqual(first["cached"], 0)
            self.assertEqual(first["player_rows"], 1)
            self.assertEqual(api.call_count, 3)  # twee teams + één bulkrequest

        with patch("load_api_football.api_get", side_effect=fake_get) as api:
            second = load_recent_player_stats(
                self.conn, "secret", date(2026, 9, 1), cache_dir=cache
            )
            self.assertEqual(second["cached"], 1)
            self.assertEqual(second["fetched"], 0)
            self.assertEqual(api.call_count, 2)  # alleen recente fixturelijsten


if __name__ == "__main__":
    unittest.main()
