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
            'src="aftrap-account.js?v=20260830-1"',
            'href="aftrap-account.css?v=20260831-7"',
            'src="aftrap-app.js?v=20260831-7"',
            'src="aftrap-data.js?v=20260831-7"',
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
        self.assertIn('bookmaker: "auto"', self.app_js)
        self.assertIn('=== "bet365"', self.app_js)
        self.assertIn('select.value = state.bookmaker', self.app_js)

    def test_programme_opens_on_all_matchdays(self):
        self.assertIn('date: "all"', self.app_js)
        self.assertNotIn("defaultProgrammeDate", self.app_js)
        self.assertIn('state.date === day ? "active"', self.app_js)

    def test_daily_shortlist_uses_conservative_distinct_singles_and_combo(self):
        self.assertIn('id="daily-picks"', self.template)
        self.assertIn('id="official-history"', self.template)
        self.assertIn("OFFICIAL_HISTORY", self.app_js)
        self.assertIn("officialSelections", self.app_js)
        self.assertIn("Conservatieve kans", self.app_js)
        self.assertIn("Officiële EV", self.app_js)
        self.assertIn("data-model-probability", self.app_js)
        self.assertIn("currentDailyCombo", self.app_js)
        self.assertIn("data-add-daily-combo", self.app_js)
        self.assertIn("openFromCombo", self.account_js)
        self.assertIn("combinatie handmatig afwikkelen", self.account_js)
        self.assertIn("Break-even = 1 ÷ odd", self.template)

    def test_official_dates_and_result_archives_are_interactive(self):
        self.assertIn('id="official-date-nav"', self.template)
        self.assertIn('id="archive-dialog"', self.template)
        self.assertIn("renderOfficialDateNav", self.app_js)
        self.assertIn("data-official-date", self.app_js)
        self.assertIn("data-open-top10-archive", self.app_js)
        self.assertIn("openTop10Archive", self.app_js)
        self.assertIn("openOfficialArchive", self.app_js)
        self.assertIn("Goed", self.app_js)
        self.assertIn("Fout", self.app_js)

    def test_daily_top10_history_and_compact_score_feed_are_wired(self):
        self.assertIn('id="top10-results"', self.template)
        self.assertIn('id="score-feed"', self.template)
        self.assertIn("RECOMMENDATION_HISTORY", self.app_js)
        self.assertIn("historicalDailyTop10", self.app_js)
        self.assertIn("Number(item.o) < state.minimumOdd", self.app_js)
        self.assertIn(".slice(0, 10)", self.app_js)
        self.assertIn("Flat-stake ROI", self.app_js)
        self.assertIn("quickFixtureTips", self.app_js)
        self.assertIn("score-feed-row", self.app_js)
        self.assertIn("top10-panel", self.template)

    def test_generated_data_uses_external_script_before_app(self):
        data_script = 'src="aftrap-data.js?v=20260831-7"'
        app_script = 'src="aftrap-app.js?v=20260831-7"'
        self.assertLess(self.template.index(data_script), self.template.index(app_script))
        self.assertNotIn("window.AFTRAP_DATA=/*__DATA__*/[]", self.template)

    def test_minimum_odd_ranking_is_wired(self):
        self.assertIn('id="minimum-odd"', self.template)
        self.assertIn('id="chance-ranking"', self.template)
        self.assertIn("minimumOdd: 1.30", self.app_js)
        self.assertIn("rankedSelections", self.app_js)
        self.assertIn("b.probability - a.probability", self.app_js)
        self.assertIn("Number(odd.o) < state.minimumOdd", self.app_js)
        self.assertIn("filter(isPreMatch)", self.app_js)

    def test_chance_ranking_odds_are_visible_on_light_rows(self):
        self.assertIn(".chance-row .odd-pill", self.template)
        self.assertIn("background: #f3faea; color: #29410f", self.template)

    def test_chance_ranking_explains_every_model_percentage(self):
        self.assertIn("modelReason", self.app_js)
        self.assertIn("expectationOrigin", self.app_js)
        self.assertIn("Herleiding:", self.app_js)
        self.assertIn("defensiecorrectie", self.app_js)
        self.assertIn("effectieve duels", self.app_js)
        self.assertIn("Herleiding doelverwachting", self.app_js)
        self.assertIn("chance-reason", self.app_js)
        self.assertIn("Thuiswinst ${pct1(fixture.p_home)} + gelijk", self.app_js)
        self.assertIn("verwacht het model ${goalText(expected)} goals", self.app_js)

    def test_match_detail_exposes_causal_season_and_comeback_context(self):
        self.assertIn("contextBlock", self.app_js)
        self.assertIn("Seizoen & wedstrijdverloop", self.app_js)
        self.assertIn("Achter bij rust", self.app_js)
        self.assertIn("Teruggekomen", self.app_js)
        self.assertIn("Voorsprong weg", self.app_js)
        self.assertIn("Historie in dit stadion", self.app_js)
        self.assertIn("walk-forwardtest", self.app_js)
        self.assertIn(".context-grid", self.template)

    def test_mobile_dashboard_has_app_layout_and_live_statistics(self):
        self.assertIn("viewport-fit=cover", self.template)
        self.assertIn("overflow-x: clip", self.template)
        self.assertIn("overscroll-behavior-x: none", self.template)
        self.assertIn("touch-action: pan-y", self.template)
        self.assertIn('id="dashboard-stats"', self.template)
        self.assertIn("renderDashboardStats", self.app_js)
        self.assertIn('label: "Winnaar value"', self.app_js)
        self.assertIn('label: "Goals value"', self.app_js)
        self.assertIn('label: "BTTS value"', self.app_js)
        self.assertIn('data-open-market="${esc(card.action.key)}"', self.app_js)
        self.assertIn("expectedValue: probability * Number(odd.o) - 1", self.app_js)
        self.assertIn("const breakEven = 1 / Number(odd.o)", self.app_js)
        self.assertIn("aria-label=\"Model ${pct1(card.model)}, break-even", self.app_js)
        self.assertIn("grid-template-columns: repeat(4,minmax(0,1fr))", self.template)
        self.assertNotIn('{ label: "Wedstrijden"', self.app_js)
        self.assertNotIn('{ label: "Beschikbare kansen"', self.app_js)
        self.assertNotIn('{ label: "Bookmakers"', self.app_js)
        self.assertNotIn('{ label: "Odds bijgewerkt"', self.app_js)
        self.assertIn('.dashboard-stat .dashboard-stat-selection,.dashboard-stat .dashboard-stat-selection em { color: #fff; font-weight: 800; }', self.template)

    def test_mobile_safe_area_and_dialog_state_are_stable(self):
        self.assertIn(".topbar { position: fixed; right: 0; left: 0; }", self.template)
        self.assertIn("calc(75px + env(safe-area-inset-top))", self.template)
        self.assertIn("shouldResetScroll", self.app_js)
        self.assertIn("dialog.scrollTop = 0", self.app_js)
        self.assertNotIn("Zie direct waar het model wél iets ziet.</h1>", self.template)
        self.assertNotIn('class="trust-strip"', self.template)

    def test_selected_bookmaker_is_preserved_when_adding_a_bet(self):
        self.assertIn('data-bookmaker="${esc(found.b)}"', self.app_js)
        self.assertIn("button.dataset.bookmaker || state.bookmaker", self.app_js)

    def test_ranking_has_market_and_sort_controls(self):
        self.assertIn('id="market-select"', self.template)
        self.assertIn('id="sort-select"', self.template)
        self.assertIn('market: "all"', self.app_js)
        self.assertIn('sort: "probability"', self.app_js)
        self.assertIn('state.market !== "all"', self.app_js)
        self.assertIn('state.sort === "edge"', self.app_js)
        self.assertIn('state.sort === "odds"', self.app_js)

    def test_ranking_excludes_thin_data_and_value_uses_executable_ev(self):
        self.assertIn("RANKING_MIN_QUALITY = 0.45", self.app_js)
        self.assertIn("DASHBOARD_MIN_QUALITY = 0.62", self.app_js)
        self.assertIn("DASHBOARD_MIN_EFFECTIVE_MATCHES = 10", self.app_js)
        self.assertIn("item.expectedValue >= DASHBOARD_MIN_EV", self.app_js)
        self.assertIn("item.expectedValue <= DASHBOARD_MAX_EV", self.app_js)
        self.assertIn("item.marketDifference <= DASHBOARD_MAX_MARKET_GAP", self.app_js)
        self.assertIn('minProbability: 0.50, maxOdd: 2.50', self.app_js)
        self.assertIn('minProbability: 0.50, maxOdd: 2.50', self.app_js)
        self.assertIn('minProbability: 0.48, maxOdd: 2.50', self.app_js)
        self.assertIn('expectedValue > 0 ? "value"', self.app_js)
        self.assertIn("model-warning", self.app_js)

    def test_odds_expire_and_long_rankings_are_paginated(self):
        self.assertIn("Number.POSITIVE_INFINITY", self.app_js)
        self.assertIn("window.setInterval(renderAll, 5 * 60 * 1000)", self.app_js)
        self.assertIn('document.addEventListener("visibilitychange"', self.app_js)
        self.assertIn("state.visibleCount += PAGE_SIZE", self.app_js)
        self.assertNotIn("state.expanded = true", self.app_js)

    def test_tabs_dialogs_and_auth_gate_are_accessible(self):
        self.assertIn('role="tablist"', self.template)
        self.assertIn('role="tabpanel"', self.template)
        self.assertIn('aria-labelledby="match-dialog-title"', self.template)
        self.assertIn('<header class="topbar" inert aria-hidden="true">', self.template)

    def test_value_bet_and_auto_settlement_are_wired(self):
        self.assertIn("fairMarketProbability", self.app_js)
        self.assertIn("data-add-bet", self.app_js)
        self.assertIn("openFromTip", self.account_js)
        self.assertIn("autoSettleBets", self.account_js)
        self.assertIn("clv_percent", self.account_js)
        self.assertIn("AFTRAP_SETTLEMENTS", self.account_js)

    def test_account_module_uses_explicit_shared_data(self):
        self.assertIn("window.AFTRAP_DATA", self.account_js)
        self.assertIn("const esc =", self.account_js)
        self.assertNotIn("DATA.map", self.account_js)
        self.assertNotIn("teamName(fixture", self.account_js)

    def test_manual_fixture_bet_gets_auto_settlement_keys(self):
        self.assertIn("fixtureFromDescription", self.account_js)
        self.assertIn("resolveSelectionKey", self.account_js)
        self.assertIn("syncManualBetContext", self.account_js)
        self.assertIn('el("bet-fixture-id").value = String(fixture.id)', self.account_js)
        self.assertIn('el("bet-selection-key").value = selectionKey', self.account_js)
        self.assertIn('payload.fixture_external_id && !payload.selection_key', self.account_js)
        self.assertIn("betContextIsUnchanged", self.account_js)
        self.assertIn('el("bet-selection-key").value = ""', self.account_js)

    def test_settled_bet_amounts_cannot_be_changed(self):
        self.assertIn('const amountsLocked = Boolean(bet && bet.status !== "open")', self.account_js)
        self.assertIn("input.disabled = amountsLocked", self.account_js)
        self.assertIn('existingBet.status !== "open"', self.account_js)
        self.assertIn("payload.stake = Number(existingBet.stake)", self.account_js)
        self.assertIn("payload.odds = Number(existingBet.odds)", self.account_js)

    def test_scenario_and_cashout_values_are_bounded(self):
        self.assertIn("function scenarioNumber(input, minimum, maximum = Infinity)", self.account_js)
        self.assertIn("Math.min(maximum, Math.max(minimum", self.account_js)
        self.assertIn('scenarioNumber(card.querySelector("[data-scenario-stake]"), 0)', self.account_js)
        self.assertIn('scenarioNumber(card.querySelector("[data-scenario-odds]"), 1.01)', self.account_js)
        self.assertIn('scenarioNumber(card.querySelector("[data-scenario-chance]"), 0, 100)', self.account_js)
        self.assertIn("payout === null || payout < 0", self.account_js)

    def test_local_today_and_locked_auth_chrome_are_wired(self):
        self.assertIn("now.getTimezoneOffset() * 60000", self.account_js)
        self.assertIn("function setAppChromeAccessible(accessible)", self.account_js)
        self.assertIn("node.inert = !accessible", self.account_js)
        self.assertIn('node.setAttribute("aria-hidden", "true")', self.account_js)
        self.assertIn('node.removeAttribute("aria-hidden")', self.account_js)


if __name__ == "__main__":
    unittest.main()
