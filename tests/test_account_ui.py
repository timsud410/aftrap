import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AccountUiTests(unittest.TestCase):
    def setUp(self):
        self.template = (ROOT / "dashboard_template.html").read_text(encoding="utf-8")
        self.account_js = (ROOT / "assets" / "aftrap-account.js").read_text(encoding="utf-8")
        self.account_css = (ROOT / "assets" / "aftrap-account.css").read_text(encoding="utf-8")
        self.public_assets = self.template + self.account_js + self.account_css

    def test_account_interface_is_wired(self):
        for marker in (
            'id="auth-gate"',
            'data-view="bets"',
            'id="bets-view"',
            'id="bet-form"',
            'id="scenario-bankroll"',
            'src="aftrap-account.js"',
            'href="aftrap-account.css"',
        ):
            self.assertIn(marker, self.template)

    def test_private_allowlist_is_not_published(self):
        self.assertNotIn("tim-zuiderent@hotmail.com", self.public_assets.lower())
        self.assertNotIn("danielvanhelden7@hotmail.com", self.public_assets.lower())

    def test_frontend_contains_no_privileged_key(self):
        self.assertNotIn("service_role", self.public_assets.lower())
        self.assertNotIn("sb_secret_", self.public_assets.lower())
        self.assertIn("sb_publishable_", self.account_js)

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


if __name__ == "__main__":
    unittest.main()
