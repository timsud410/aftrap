import sqlite3
import unittest

from run_tips import (
    matchday_label,
    model_history_summary,
    settle,
    validate_dashboard_data,
)


class SettlementTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
