import unittest

from tips import Signal, SignalPerformance, build_tips


class TipSelectionTests(unittest.TestCase):
    def test_binary_outcome_below_baseline_is_not_a_tip(self):
        signal = Signal(
            "first_half_tempo", "first_half", "fh_over_1.5", 1.0, {}, "tempo"
        )
        performance = {"first_half_tempo": SignalPerformance(0.58, 1000)}
        self.assertEqual(
            build_tips({"fh_over_1.5": 0.35}, [signal], 1.0, performance),
            [],
        )

    def test_negative_strength_supports_encoded_under_direction(self):
        signal = Signal(
            "combined_xg", "over_under", "under_2.5", -1.0, {}, "laag totaal"
        )
        performance = {"combined_xg": SignalPerformance(0.60, 1000)}
        tips = build_tips({"under_2.5": 0.70}, [signal], 1.0, performance)
        self.assertEqual([tip.selection for tip in tips], ["under_2.5"])

    def test_three_way_result_uses_one_third_baseline(self):
        signal = Signal(
            "form_vs_underlying", "match_result", "away", -0.9, {}, "uit sterker"
        )
        performance = {
            "form_vs_underlying": SignalPerformance(0.55, 1000, baseline=1 / 3)
        }
        tips = build_tips({"away": 0.55}, [signal], 1.0, performance)
        self.assertEqual([tip.selection for tip in tips], ["away"])


if __name__ == "__main__":
    unittest.main()
