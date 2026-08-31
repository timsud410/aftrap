import math
import sqlite3
import unittest
from datetime import datetime

import db as store
from model import TeamRatings
from run_tips import (
    daily_recommendation_history,
    expectation_breakdown,
    head_to_head_profile,
    matchday_label,
    model_history_summary,
    official_category,
    official_recommendation_history,
    select_official_recommendations,
    settle,
    store_daily_recommendations,
    store_official_recommendations,
    team_season_profile,
    validate_dashboard_data,
)


class SettlementTests(unittest.TestCase):
    def test_first_half_totals_are_eligible_for_official_goal_selection(self):
        self.assertEqual(official_category("fh_under_1.5"), ("Goals", 0.52))
        self.assertEqual(official_category("fh_over_0.5"), ("Goals", 0.52))
        now = datetime.now().astimezone()
        fixture = {
            "id": "weekend-1", "date": "2026-09-05", "quality": 0.71,
            "effective_matches": {"home": 36.0, "away": 36.0},
            "probs": {"fh_under_1.5": 0.738},
            "tips": [{"raw": "fh_under_1.5", "b": "medium", "r": "getoetst tempo-signaal"}],
            "odds": [{"s": "fh_under_1.5", "b": "Bet365", "o": 1.44,
                      "f": 0.6453, "u": now.isoformat()}],
        }
        picks = select_official_recommendations([fixture], now=now)
        self.assertEqual(len(picks), 1)
        self.assertGreaterEqual(picks[0]["ev"], 0.015)

    def test_expectation_breakdown_multiplies_back_to_goal_expectation(self):
        ratings = TeamRatings(
            attack={"Thuis": 0.12, "Uit": -0.08},
            defence={"Thuis": 0.05, "Uit": -0.11},
            intercept=0.30,
            home_advantage=0.16,
            rho=0.0,
        )
        breakdown = expectation_breakdown(ratings, "Thuis", "Uit")
        expected_home, expected_away = ratings.expected_goals("Thuis", "Uit")
        home_product = math.prod(breakdown["home"].values())
        away_product = math.prod(breakdown["away"].values())
        self.assertAlmostEqual(home_product, expected_home)
        self.assertAlmostEqual(away_product, expected_away)
        self.assertEqual(breakdown["away"]["venue"], 1.0)

    def test_first_half_totals_are_settled(self):
        self.assertTrue(settle("fh_over_1.5", 3, 1, 1, 1))
        self.assertFalse(settle("fh_over_1.5", 3, 1, 1, 0))
        self.assertTrue(settle("fh_under_1.5", 3, 1, 1, 0))

    def test_first_half_result_is_settled(self):
        self.assertTrue(settle("fh_home", 2, 1, 1, 0))
        self.assertTrue(settle("fh_draw", 2, 1, 0, 0))
        self.assertIsNone(settle("fh_draw", 2, 1))

    def test_matchday_label_is_human_readable(self):
        self.assertEqual(
            matchday_label(["2026-08-29", "2026-09-06"]),
            "29 aug – 6 sep",
        )

    def test_dashboard_integrity_guard_accepts_coherent_markets(self):
        result = validate_dashboard_data([{
            "id": "fixture-1",
            "probs": {
                "home": 0.5, "draw": 0.3, "away": 0.2,
                "home_or_draw": 0.8, "away_or_draw": 0.5,
                "home_or_away": 0.7, "btts_yes": 0.55, "btts_no": 0.45,
                "over_2.5": 0.6, "under_2.5": 0.4,
            },
            "odds": [
                {"b": "Book", "s": "home", "o": 1.9, "f": 0.5, "u": "2026-08-29T12:00:00+02:00"},
                {"b": "Book", "s": "draw", "o": 3.3, "f": 0.3, "u": "2026-08-29T12:00:00+02:00"},
                {"b": "Book", "s": "away", "o": 5.0, "f": 0.2, "u": "2026-08-29T12:00:00+02:00"},
            ],
        }])
        self.assertEqual(result, {"probabilities": 10, "odds": 3, "market_groups": 1})

    def test_dashboard_integrity_guard_rejects_contradictory_probabilities(self):
        with self.assertRaises(ValueError):
            validate_dashboard_data([{
                "id": "fixture-bad",
                "probs": {"home": 0.7, "draw": 0.3, "away": 0.2},
                "odds": [],
            }])

    def test_model_history_summary_counts_only_complete_past_model_matches(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript(
            """
            CREATE TABLE fixtures (
                id INTEGER PRIMARY KEY, match_date TEXT,
                home_team_id INTEGER, away_team_id INTEGER,
                home_goals INTEGER, away_goals INTEGER
            );
            CREATE TABLE fixture_xg (
                fixture_id INTEGER, team_id INTEGER, source TEXT, xg REAL
            );
            INSERT INTO fixtures VALUES
                (1, '2020-08-01', 10, 11, 2, 1),
                (2, '2020-08-02', 10, 11, 1, 0),
                (3, '2030-08-03', 10, 11, 0, 0);
            INSERT INTO fixture_xg VALUES
                (1, 10, 'proxy', 1.5), (1, 11, 'proxy', 0.8),
                (2, 10, 'proxy', 1.2),
                (3, 10, 'proxy', 0.4), (3, 11, 'proxy', 0.4);
            """
        )

        self.assertEqual(
            model_history_summary(conn, "2026-08-29"),
            {"matches": 1, "first_date": "2020-08-01"},
        )

    def test_season_and_comeback_context_is_causal(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript(
            """
            CREATE TABLE fixtures (
                id INTEGER PRIMARY KEY, league_code TEXT, season INTEGER,
                match_date TEXT, home_team_id INTEGER, away_team_id INTEGER,
                home_goals INTEGER, away_goals INTEGER,
                home_goals_ht INTEGER, away_goals_ht INTEGER
            );
            INSERT INTO fixtures VALUES
                (1,'EPL',2026,'2026-08-01',1,3,2,1,0,1),
                (2,'EPL',2026,'2026-08-10',1,3,1,1,1,0),
                (3,'EPL',2025,'2026-05-01',1,2,1,0,0,0),
                (4,'EPL',2026,'2026-08-30',1,2,9,0,5,0);
            """
        )
        profile = team_season_profile(conn, 1, "EPL", 2026, "2026-08-30")
        self.assertEqual(profile["n"], 2)
        self.assertEqual(profile["ppg"], 2.0)
        self.assertEqual(profile["behind_ht_rate"], 0.5)
        self.assertEqual(profile["comeback_rate"], 1.0)
        self.assertEqual(profile["lead_drop_rate"], 1.0)
        self.assertEqual(head_to_head_profile(conn, 1, 2, "2026-08-30")["n"], 1)

    def test_daily_recommendations_are_frozen_and_settled(self):
        conn = store.connect(":memory:")
        conn.execute("INSERT INTO teams (league_code,name) VALUES ('EPL','Alpha')")
        conn.execute("INSERT INTO teams (league_code,name) VALUES ('EPL','Beta')")
        home_id = int(conn.execute("SELECT id FROM teams WHERE name='Alpha'").fetchone()["id"])
        away_id = int(conn.execute("SELECT id FROM teams WHERE name='Beta'").fetchone()["id"])
        conn.execute(
            """INSERT INTO fixtures
               (league_code,season,match_date,kickoff,home_team_id,away_team_id,status)
               VALUES ('EPL',2026,'2026-08-30','15:00',?,?,'NS')""",
            (home_id, away_id),
        )
        fixture_id = int(conn.execute("SELECT id FROM fixtures").fetchone()["id"])
        conn.execute(
            "INSERT INTO fixture_external_ids VALUES ('api_football','fx-1',?)",
            (fixture_id,),
        )
        fixture = {
            "id": "fx-1", "date": "2026-08-30", "quality": 0.8,
            "effective_matches": {"home": 30, "away": 30},
            "probs": {"home": 0.58, "draw": 0.2},
            "tips": [{"raw": "home", "b": "medium", "r": "getoetst signaal"}],
            "odds": [
                {"s": "home", "b": "Bet365", "o": 2.0, "f": 0.5,
                 "u": datetime.now().astimezone().isoformat()},
                {"s": "draw", "b": "Andere", "o": 4.0},
            ],
        }
        self.assertEqual(store_daily_recommendations(conn, [fixture]), 1)
        official = select_official_recommendations([fixture])
        self.assertEqual(len(official), 1)
        self.assertEqual(official[0]["category"], "Winnaar")
        self.assertGreater(official[0]["adjusted_p"], 0.5)
        self.assertEqual(store_official_recommendations(conn, official), 1)
        official[0]["odd"]["o"] = 2.2
        official[0]["p"] = 0.61
        self.assertEqual(store_official_recommendations(conn, official), 0)
        frozen = conn.execute(
            "SELECT odd,model_probability FROM official_recommendations"
        ).fetchone()
        self.assertEqual(float(frozen["odd"]), 2.0)
        self.assertEqual(float(frozen["model_probability"]), 0.58)
        conn.execute(
            "UPDATE fixtures SET home_goals=1,away_goals=0,home_goals_ht=0,away_goals_ht=0,status='FT' WHERE id=?",
            (fixture_id,),
        )
        history = daily_recommendation_history(conn)
        self.assertEqual(len(history), 1)
        self.assertTrue(history[0]["hit"])
        self.assertEqual(history[0]["o"], 2.0)
        official_history = official_recommendation_history(conn)
        self.assertEqual(len(official_history), 1)
        self.assertTrue(official_history[0]["hit"])
        self.assertEqual(official_history[0]["phase"], "paper_trade")


if __name__ == "__main__":
    unittest.main()
