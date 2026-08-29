import unittest

from backtest import _devig, metrics


class BacktestMetricTests(unittest.TestCase):
    def test_devig_probabilities_sum_to_one(self):
        probs = _devig([2.0, 3.5, 4.0])
        self.assertAlmostEqual(sum(probs), 1.0)

    def test_metrics_include_calibration_and_market_return(self):
        rows = [
            {
                "outcome": 1,
                "model_probability": 0.60,
                "baseline": 0.50,
                "closing_odds": 2.0,
                "profit_at_close": 1.0,
                "market_edge": 0.10,
            },
            {
                "outcome": 0,
                "model_probability": 0.60,
                "baseline": 0.50,
                "closing_odds": 2.0,
                "profit_at_close": -1.0,
                "market_edge": 0.10,
            },
        ]
        result = metrics(rows)
        self.assertEqual(result["hit_rate"], 0.5)
        self.assertEqual(result["roi_at_close"], 0.0)
        self.assertAlmostEqual(result["calibration_gap"], -0.1)


if __name__ == "__main__":
    unittest.main()
