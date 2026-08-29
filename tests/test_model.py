import math
import unittest
from datetime import date

import numpy as np

from model import (
    TeamRatings,
    first_half_probabilities,
    initialise_promoted,
    market_probabilities,
    score_matrix,
    time_weights,
)


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

        self.assertTrue(all(0.0 <= value <= 1.0 for value in probabilities.values()))
        self.assertAlmostEqual(
            probabilities["home_or_draw"], probabilities["home"] + probabilities["draw"]
        )
        self.assertAlmostEqual(
            probabilities["away_or_draw"], probabilities["away"] + probabilities["draw"]
        )
        self.assertAlmostEqual(
            probabilities["home_or_away"], probabilities["home"] + probabilities["away"]
        )
        for prefix in ("", "home_", "away_"):
            for line in (1.5, 2.5, 3.5) if not prefix else (0.5, 1.5, 2.5):
                self.assertAlmostEqual(
                    probabilities[f"{prefix}over_{line}"] + probabilities[f"{prefix}under_{line}"],
                    1.0,
                )
        self.assertAlmostEqual(probabilities["btts_yes"] + probabilities["btts_no"], 1.0)

    def test_first_half_markets_are_complete_probability_groups(self):
        probabilities = first_half_probabilities(1.7, 1.1)
        self.assertTrue(all(0.0 <= value <= 1.0 for value in probabilities.values()))
        self.assertAlmostEqual(
            probabilities["fh_home"] + probabilities["fh_draw"] + probabilities["fh_away"],
            1.0,
        )
        for line in (0.5, 1.5):
            self.assertAlmostEqual(
                probabilities[f"fh_over_{line}"] + probabilities[f"fh_under_{line}"],
                1.0,
            )

    def test_future_observation_is_rejected(self):
        with self.assertRaises(ValueError):
            time_weights([date(2025, 1, 2)], date(2025, 1, 1))

    def test_promoted_prior_is_partially_pooled_until_ten_effective_matches(self):
        ratings = TeamRatings(
            attack={"Promovendus": 0.35, "Gevestigd": 0.12},
            defence={"Promovendus": -0.25, "Gevestigd": 0.08},
            intercept=0.2,
            home_advantage=0.1,
            rho=-0.074,
            effective_matches={"Promovendus": 4.0, "Gevestigd": 12.0},
            dispersion=1.3,
        )

        pooled = initialise_promoted(
            ratings, ["Promovendus", "Gevestigd", "Nieuw"]
        )

        weight = 4.0 / 10.0
        self.assertAlmostEqual(
            pooled.attack["Promovendus"],
            weight * 0.35 + (1.0 - weight) * math.log(0.79),
        )
        self.assertAlmostEqual(
            pooled.defence["Promovendus"],
            weight * -0.25 + (1.0 - weight) * math.log(0.845),
        )
        self.assertEqual(pooled.attack["Gevestigd"], 0.12)
        self.assertEqual(pooled.defence["Gevestigd"], 0.08)
        self.assertAlmostEqual(pooled.attack["Nieuw"], math.log(0.79))
        self.assertAlmostEqual(pooled.defence["Nieuw"], math.log(0.845))
        self.assertEqual(pooled.effective_matches["Nieuw"], 0.0)

    def test_promoted_prior_does_not_mutate_original_ratings(self):
        ratings = TeamRatings(
            attack={"Promovendus": 0.35},
            defence={"Promovendus": -0.25},
            intercept=0.2,
            home_advantage=0.1,
            rho=-0.074,
            effective_matches={"Promovendus": 4.0},
        )
        original_attack = dict(ratings.attack)
        original_defence = dict(ratings.defence)
        original_effective = dict(ratings.effective_matches)

        pooled = initialise_promoted(ratings, ["Promovendus", "Nieuw"])

        self.assertIsNot(pooled, ratings)
        self.assertIsNot(pooled.attack, ratings.attack)
        self.assertIsNot(pooled.defence, ratings.defence)
        self.assertIsNot(pooled.effective_matches, ratings.effective_matches)
        self.assertEqual(ratings.attack, original_attack)
        self.assertEqual(ratings.defence, original_defence)
        self.assertEqual(ratings.effective_matches, original_effective)


if __name__ == "__main__":
    unittest.main()
