import unittest
from datetime import date

import numpy as np

from model import market_probabilities, score_matrix, time_weights


class ModelInvariantTests(unittest.TestCase):
    def test_score_matrix_is_a_probability_distribution(self):
        matrix = score_matrix(1.7, 1.1)
        self.assertAlmostEqual(float(matrix.sum()), 1.0, places=12)
        self.assertTrue((matrix >= 0).all())

    def test_markets_from_one_matrix_are_coherent(self):
        probabilities = market_probabilities(score_matrix(1.7, 1.1))
        self.assertAlmostEqual(
            probabilities["home"] + probabilities["draw"] + probabilities["away"],
            1.0,
        )
        self.assertAlmostEqual(
            probabilities["over_2.5"] + probabilities["under_2.5"], 1.0
        )

    def test_future_observation_is_rejected(self):
        with self.assertRaises(ValueError):
            time_weights([date(2025, 1, 2)], date(2025, 1, 1))


if __name__ == "__main__":
    unittest.main()
