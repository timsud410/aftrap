import unittest

from run_tips import matchday_label, settle


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


if __name__ == "__main__":
    unittest.main()
