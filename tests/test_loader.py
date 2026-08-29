import tempfile
import unittest
from pathlib import Path

import db as store
from load_fdcouk import add_xg_proxy, store_season


class CausalProxyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = store.connect(Path(self.tmp.name) / "test.sqlite")

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def add_fixture(self, day, home, away, goals, shots):
        home_id = store.team_id(self.conn, "EPL", home)
        away_id = store.team_id(self.conn, "EPL", away)
        cur = self.conn.execute(
            """INSERT INTO fixtures
               (league_code, season, match_date, home_team_id, away_team_id,
                home_goals, away_goals, status)
               VALUES ('EPL', 2020, ?, ?, ?, ?, ?, 'finished')""",
            (day, home_id, away_id, goals[0], goals[1]),
        )
        fixture_id = cur.lastrowid
        self.conn.executemany(
            """INSERT INTO fixture_stats
               (fixture_id, team_id, is_home, shots_on_target)
               VALUES (?, ?, ?, ?)""",
            [
                (fixture_id, home_id, 1, shots[0]),
                (fixture_id, away_id, 0, shots[1]),
            ],
        )
        return fixture_id

    def test_fixture_and_same_day_results_never_set_their_own_scale(self):
        first = self.add_fixture("2020-08-01", "A", "B", (1, 1), (5, 5))
        second = self.add_fixture("2020-08-08", "C", "D", (5, 0), (5, 5))
        third = self.add_fixture("2020-08-08", "E", "F", (0, 5), (5, 5))
        add_xg_proxy(self.conn, "EPL", 2020)

        def values(fixture_id):
            return [
                row["xg"]
                for row in self.conn.execute(
                    "SELECT xg FROM fixture_xg WHERE fixture_id=? ORDER BY team_id",
                    (fixture_id,),
                )
            ]

        self.assertEqual(values(first), [1.5, 1.5])  # vaste prior 0.30
        self.assertEqual(values(second), [1.0, 1.0])  # alleen datum 1: 2/10
        self.assertEqual(values(third), [1.0, 1.0])   # kent datumgenoot niet

    def test_finished_snapshot_enriches_existing_api_fixture(self):
        home_id = store.team_id(self.conn, "EPL", "A")
        away_id = store.team_id(self.conn, "EPL", "B")
        cur = self.conn.execute(
            """INSERT INTO fixtures
               (league_code,season,match_date,kickoff,home_team_id,away_team_id,status)
               VALUES ('EPL',2020,'2020-08-01','15:00',?,?,'NS')""",
            (home_id, away_id),
        )
        fixture_id = int(cur.lastrowid)
        self.conn.execute(
            """INSERT INTO fixture_external_ids(source,external_id,fixture_id)
               VALUES ('api_football','123',?)""",
            (fixture_id,),
        )
        row = {
            "date": "2020-08-01", "kickoff": "15:00", "home": "A", "away": "B",
            "home_goals": 2, "away_goals": 1, "home_goals_ht": 1,
            "away_goals_ht": 0, "referee": "Ref", "home_shots": 12,
            "away_shots": 8, "home_sot": 5, "away_sot": 3,
            "home_corners": 6, "away_corners": 2, "home_fouls": 9,
            "away_fouls": 11, "home_yellow": 1, "away_yellow": 2,
            "home_red": 0, "away_red": 0, "odds_home": 1.8,
            "odds_draw": 3.5, "odds_away": 4.6, "odds_over25": 1.9,
            "odds_under25": 1.95, "bookmaker": "market_avg_closing",
        }

        inserted, updated = store_season(self.conn, "EPL", 2020, [row])
        add_xg_proxy(self.conn, "EPL", 2020)

        self.assertEqual((inserted, updated), (0, 1))
        fixture = self.conn.execute(
            "SELECT home_goals,away_goals,status FROM fixtures WHERE id=?",
            (fixture_id,),
        ).fetchone()
        self.assertEqual(tuple(fixture), (2, 1, "finished"))
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) n FROM fixture_stats WHERE fixture_id=?", (fixture_id,)).fetchone()["n"],
            2,
        )
        self.assertIsNotNone(self.conn.execute("SELECT 1 FROM closing_odds WHERE fixture_id=?", (fixture_id,)).fetchone())
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) n FROM fixture_xg WHERE fixture_id=?", (fixture_id,)).fetchone()["n"],
            2,
        )


if __name__ == "__main__":
    unittest.main()
