import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AccountUiTests(unittest.TestCase):
    def setUp(self):
        self.template = (ROOT / "dashboard_template.html").read_text(encoding="utf-8")
        self.account_js = (ROOT / "assets" / "aftrap-account.js").read_text(encoding="utf-8")
        self.app_js = (ROOT / "assets" / "aftrap-app.js").read_text(encoding="utf-8")
        self.account_css = (ROOT / "assets" / "aftrap-account.css").read_text(encoding="utf-8")
        self.public_assets = self.template + self.app_js + self.account_js + self.account_css

    def test_account_interface_is_wired(self):
        for marker in (
            'id="auth-gate"',
            'id="auth-password"',
            'data-view="bets"',
            'id="bets-view"',
            'id="bet-form"',
            'id="scenario-bankroll"',
            'src="aftrap-account.js?v=20260829-4"',
            'href="aftrap-account.css"',
            'src="aftrap-app.js?v=20260829-4"',
            'id="match-dialog"',
        ):
            self.assertIn(marker, self.template)

    def test_private_allowlist_is_not_published(self):
        self.assertNotIn("tim-zuiderent@hotmail.com", self.public_assets.lower())
        self.assertNotIn("danielvanhelden7@hotmail.com", self.public_assets.lower())

    def test_frontend_contains_no_privileged_key(self):
        self.assertNotIn("service_role", self.public_assets.lower())
        self.assertNotIn("sb_secret_", self.public_assets.lower())
        self.assertIn("sb_publishable_", self.account_js)

    def test_login_uses_password_without_publishing_it(self):
        self.assertIn("signInWithPassword", self.account_js)
        self.assertNotIn("signInWithOtp", self.account_js)
        self.assertNotIn("const PASSWORD", self.public_assets)

    def test_bets_use_authenticated_owner(self):
        self.assertIn("user_id: user.id", self.account_js)
        self.assertIn('from("aftrap_bets")', self.account_js)

    def test_team_bankroll_uses_shared_record(self):
        self.assertIn('team_id: "aftrap"', self.account_js)
        self.assertIn('updated_by: user.id', self.account_js)
        self.assertIn('{ onConflict: "team_id" }', self.account_js)
        self.assertIn("Onze bets", self.template)

    def test_app_logo_and_home_screen_manifest_are_wired(self):
        self.assertIn('rel="manifest" href="manifest.webmanifest"', self.template)
        self.assertIn('rel="apple-touch-icon"', self.template)
        self.assertIn('src="aftrap-icon-192.png"', self.template)
        for asset in (
            "aftrap-icon-192.png",
            "aftrap-icon-512.png",
            "apple-touch-icon.png",
            "favicon-32.png",
            "manifest.webmanifest",
        ):
            self.assertTrue((ROOT / "assets" / asset).is_file(), asset)

    def test_bookmaker_filter_and_odds_value_are_wired(self):
        self.assertIn('id="bookmaker-select"', self.template)
        self.assertIn("Beste beschikbare odd", self.template)
        self.assertIn("selectedOdd", self.template)
        self.assertIn("Break-even", self.template)
        self.assertIn("fixture.odds", self.template)
        self.assertIn("odd.s===key", self.template)

    def test_minimum_odd_ranking_is_wired(self):
        self.assertIn('id="minimum-odd"', self.template)
        self.assertIn('id="chance-ranking"', self.template)
        self.assertIn("minimumOdd: 1.30", self.app_js)
        self.assertIn("rankedSelections", self.app_js)
        self.assertIn("b.probability - a.probability", self.app_js)
        self.assertIn("Number(odd.o) < state.minimumOdd", self.app_js)

    def test_value_bet_and_auto_settlement_are_wired(self):
        self.assertIn("fairMarketProbability", self.app_js)
        self.assertIn("data-add-bet", self.app_js)
        self.assertIn("openFromTip", self.account_js)
        self.assertIn("autoSettleBets", self.account_js)
        self.assertIn("clv_percent", self.account_js)
        self.assertIn("AFTRAP_SETTLEMENTS", self.template)

    def test_account_module_uses_explicit_shared_data(self):
        self.assertIn("window.AFTRAP_DATA", self.account_js)
        self.assertIn("const esc =", self.account_js)
        self.assertNotIn("DATA.map", self.account_js)
        self.assertNotIn("teamName(fixture", self.account_js)


if __name__ == "__main__":
    unittest.main()
