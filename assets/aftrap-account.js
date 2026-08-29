(() => {
  "use strict";

  const PROJECT_URL = "https://gvqjigdvfvjasvixgghe.supabase.co";
  const PUBLISHABLE_KEY = "sb_publishable_P_GfkNQxT878kt2etxYn9w_y4fCHSWl";
  const db = window.supabase.createClient(PROJECT_URL, PUBLISHABLE_KEY, {
    auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true },
  });
  const money = new Intl.NumberFormat("nl-NL", { style: "currency", currency: "EUR" });
  const number = new Intl.NumberFormat("nl-NL", { maximumFractionDigits: 1 });
  const statusLabels = { open: "Open", won: "Gewonnen", lost: "Verloren", void: "Void", cashed_out: "Cash-out" };
  let user = null;
  let member = null;
  let bets = [];
  let betFilter = "all";
  let startingBankroll = 0;
  const settlements = window.AFTRAP_SETTLEMENTS || [];

  const el = id => document.getElementById(id);
  const esc = input => String(input ?? "").replace(/[&<>"']/g, character => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  })[character]);
  const value = id => el(id).value.trim();
  const setMessage = (id, text, error = false) => {
    const node = el(id);
    node.textContent = text;
    node.classList.toggle("error", error);
  };
  const setBusy = (button, busy, label) => {
    button.disabled = busy;
    if (!button.dataset.label) button.dataset.label = button.textContent;
    button.textContent = busy ? label : button.dataset.label;
  };
  const parseFiniteAmount = raw => {
    const normalized = String(raw ?? "").trim().replace(",", ".");
    if (!normalized) return null;
    const parsed = Number(normalized);
    return Number.isFinite(parsed) ? parsed : null;
  };
  const parseAmount = raw => parseFiniteAmount(raw) ?? 0;
  const isoToday = () => {
    const now = new Date();
    const offset = now.getTimezoneOffset() * 60000;
    return new Date(now.getTime() - offset).toISOString().slice(0, 10);
  };
  const displayDate = raw => raw ? new Intl.DateTimeFormat("nl-NL", { day: "numeric", month: "short", year: "numeric" }).format(new Date(`${raw}T12:00:00`)) : "Geen datum";

  const fixtureDescription = fixture => `${fixture.home} – ${fixture.away}`;
  const normalizedText = raw => String(raw ?? "")
    .normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase()
    .replace(/[\u2010-\u2015−]/g, "-").replace(/(\d),(\d)/g, "$1.$2").replace(/\s+/g, " ").trim();

  function accountMarketGroup(key) {
    if (["home", "draw", "away", "home_or_draw", "away_or_draw", "home_or_away"].includes(key)) return "Fulltime";
    if (key.startsWith("fh_")) return "Eerste helft";
    if (key.startsWith("btts_")) return "BTTS";
    if (key.startsWith("home_") || key.startsWith("away_")) return "Team goals";
    return "Totaal goals";
  }

  function accountSelectionLabel(key, fixture) {
    const fixed = {
      home: `${fixture.home} wint`, draw: "Gelijkspel", away: `${fixture.away} wint`,
      home_or_draw: `${fixture.home} of gelijk`, away_or_draw: `${fixture.away} of gelijk`,
      home_or_away: "Geen gelijkspel", btts_yes: "Beide teams scoren", btts_no: "Niet beide teams scoren",
      fh_home: `${fixture.home} wint 1e helft`, fh_draw: "Gelijk 1e helft", fh_away: `${fixture.away} wint 1e helft`,
    };
    if (fixed[key]) return fixed[key];
    let match = key.match(/^(over|under)_([0-9.]+)$/);
    if (match) return `${match[1] === "over" ? "Over" : "Under"} ${match[2]} goals`;
    match = key.match(/^fh_(over|under)_([0-9.]+)$/);
    if (match) return `1e helft ${match[1]} ${match[2]}`;
    match = key.match(/^(home|away)_(over|under)_([0-9.]+)$/);
    if (match) return `${match[1] === "home" ? fixture.home : fixture.away} ${match[2]} ${match[3]}`;
    return key.replaceAll("_", " ");
  }

  function selectionAliases(key, fixture) {
    const aliases = [key, accountSelectionLabel(key, fixture)];
    if (key === "home") aliases.push("1", "thuis", "thuis wint");
    if (key === "draw") aliases.push("x", "gelijk");
    if (key === "away") aliases.push("2", "uit", "uit wint");
    if (key === "btts_yes") aliases.push("ja", "btts ja");
    if (key === "btts_no") aliases.push("nee", "btts nee");
    const total = key.match(/^(?:fh_)?(?:home_|away_)?(over|under)_([0-9.]+)$/);
    if (total) aliases.push(`${total[1]} ${total[2]}`, `${total[1]} ${total[2].replace(".", ",")}`);
    return aliases.map(normalizedText);
  }

  function fixtureFromDescription(description) {
    const wanted = normalizedText(description);
    return (window.AFTRAP_DATA || []).find(fixture => normalizedText(fixtureDescription(fixture)) === wanted) || null;
  }

  function resolveSelectionKey(fixture, selection) {
    const wanted = normalizedText(selection);
    if (!wanted) return null;
    return Object.keys(fixture.probs || {}).filter(key => !key.endsWith("clean_sheet"))
      .find(key => selectionAliases(key, fixture).includes(wanted)) || null;
  }

  function populateSelectionOptions(fixture) {
    let list = el("bet-selection-options");
    if (!list) {
      list = document.createElement("datalist");
      list.id = "bet-selection-options";
      document.body.appendChild(list);
      el("bet-selection").setAttribute("list", list.id);
    }
    list.innerHTML = fixture ? Object.keys(fixture.probs || {}).filter(key => !key.endsWith("clean_sheet"))
      .map(key => `<option value="${esc(accountSelectionLabel(key, fixture))}" label="${esc(accountMarketGroup(key))}"></option>`).join("") : "";
  }

  function rememberBetContext() {
    const form = el("bet-form");
    form.dataset.originalFixtureId = value("bet-fixture-id");
    form.dataset.originalSelectionKey = value("bet-selection-key");
    form.dataset.originalKind = value("bet-kind");
    form.dataset.originalDescription = value("bet-description");
    form.dataset.originalMarket = value("bet-market");
    form.dataset.originalSelection = value("bet-selection");
  }

  function betContextIsUnchanged() {
    const form = el("bet-form");
    return value("bet-kind") === (form.dataset.originalKind || "")
      && value("bet-description") === (form.dataset.originalDescription || "")
      && value("bet-market") === (form.dataset.originalMarket || "")
      && value("bet-selection") === (form.dataset.originalSelection || "");
  }

  function syncManualBetContext({ preserveExisting = false } = {}) {
    if (value("bet-kind") !== "single") {
      el("bet-fixture-id").value = "";
      el("bet-selection-key").value = "";
      populateSelectionOptions(null);
      return;
    }
    const contextUnchanged = preserveExisting && betContextIsUnchanged();
    const originalFixtureStillSelected = preserveExisting
      && value("bet-kind") === (el("bet-form").dataset.originalKind || "")
      && value("bet-description") === (el("bet-form").dataset.originalDescription || "")
      && Boolean(el("bet-form").dataset.originalFixtureId);
    const matched = fixtureFromDescription(value("bet-description"));
    const existing = originalFixtureStillSelected ? (window.AFTRAP_DATA || []).find(fixture => String(fixture.id) === el("bet-form").dataset.originalFixtureId) : null;
    const fixture = matched || existing || null;
    if (!fixture) {
      el("bet-fixture-id").value = "";
      el("bet-selection-key").value = "";
      populateSelectionOptions(null);
      return;
    }
    el("bet-fixture-id").value = String(fixture.id);
    if (fixture.date && (matched || !value("bet-event-date"))) el("bet-event-date").value = fixture.date;
    populateSelectionOptions(fixture);
    const selectionKey = resolveSelectionKey(fixture, value("bet-selection"));
    if (selectionKey) {
      el("bet-selection-key").value = selectionKey;
      if (!value("bet-market")) el("bet-market").value = accountMarketGroup(selectionKey);
    } else if (contextUnchanged && el("bet-form").dataset.originalSelectionKey) {
      el("bet-selection-key").value = el("bet-form").dataset.originalSelectionKey;
    } else {
      el("bet-selection-key").value = "";
    }
  }

  function setAppChromeAccessible(accessible) {
    [document.querySelector(".topbar"), document.querySelector(".shell")].forEach(node => {
      if (!node) return;
      node.inert = !accessible;
      if (accessible) node.removeAttribute("aria-hidden");
      else node.setAttribute("aria-hidden", "true");
    });
  }

  function showLogin() {
    document.body.classList.add("auth-pending");
    setAppChromeAccessible(false);
    el("auth-gate").classList.remove("hidden");
    el("account-button").classList.add("hidden");
  }

  function showApp() {
    el("auth-gate").classList.add("hidden");
    document.body.classList.remove("auth-pending");
    setAppChromeAccessible(true);
    el("account-button").classList.remove("hidden");
    el("account-name").textContent = member.display_name;
  }

  async function authorizeSession() {
    const { data: userData, error: userError } = await db.auth.getUser();
    if (userError || !userData.user) {
      showLogin();
      return false;
    }
    user = userData.user;
    const { data, error } = await db.from("aftrap_members").select("email,display_name").maybeSingle();
    if (error || !data) {
      await db.auth.signOut();
      user = null;
      showLogin();
      setMessage("auth-status", "Dit e-mailadres heeft geen toegang tot Aftrap.", true);
      return false;
    }
    member = data;
    showApp();
    await Promise.all([loadSettings(), loadBets()]);
    return true;
  }

  async function loginWithPassword(event) {
    event.preventDefault();
    const button = el("login-button");
    const email = value("auth-email").toLowerCase();
    const password = value("auth-password");
    if (!email || !password) return;
    setBusy(button, true, "Inloggen…");
    setMessage("auth-status", "");
    const { error } = await db.auth.signInWithPassword({ email, password });
    setBusy(button, false, "");
    if (error) {
      setMessage("auth-status", "E-mailadres of wachtwoord klopt niet.", true);
      return;
    }
    await authorizeSession();
  }

  async function loadSettings() {
    const { data } = await db.from("aftrap_settings").select("starting_bankroll").eq("team_id", "aftrap").maybeSingle();
    startingBankroll = Number(data?.starting_bankroll || 0);
    el("bankroll-input").value = startingBankroll || "";
    el("scenario-bankroll").value = currentBankroll().toFixed(2);
    renderBetSummary();
    calculateScenarios();
  }

  async function saveSettings() {
    const amount = parseAmount(value("bankroll-input"));
    if (amount < 0) return;
    const button = el("save-bankroll");
    setBusy(button, true, "Opslaan…");
    const { error } = await db.from("aftrap_settings").upsert({
      team_id: "aftrap",
      updated_by: user.id,
      starting_bankroll: amount,
      updated_at: new Date().toISOString(),
    }, { onConflict: "team_id" });
    setBusy(button, false, "");
    if (error) {
      setMessage("bankroll-message", "Bankroll kon niet worden opgeslagen.", true);
      return;
    }
    startingBankroll = amount;
    el("scenario-bankroll").value = currentBankroll().toFixed(2);
    setMessage("bankroll-message", "Bankroll opgeslagen.");
    renderBetSummary();
    calculateScenarios();
  }

  async function loadBets(allowAutoSettle = true) {
    el("bet-list").innerHTML = '<div class="loading-block">Bets laden…</div>';
    const { data, error } = await db.from("aftrap_bets").select("*").order("placed_at", { ascending: false }).order("created_at", { ascending: false });
    if (error) {
      el("bet-list").innerHTML = '<div class="empty">De bets konden niet worden geladen.</div>';
      return;
    }
    bets = data || [];
    if (allowAutoSettle && await autoSettleBets()) return loadBets(false);
    renderBets();
    renderBetSummary();
    renderPerformance();
    el("scenario-bankroll").value = currentBankroll().toFixed(2);
    calculateScenarios();
  }

  function settledProfit() {
    return bets.filter(bet => bet.status !== "open").reduce((sum, bet) => sum + Number(bet.payout || 0) - Number(bet.stake), 0);
  }

  function openStake() {
    return bets.filter(bet => bet.status === "open").reduce((sum, bet) => sum + Number(bet.stake), 0);
  }

  function currentBankroll() {
    return startingBankroll + settledProfit() - openStake();
  }

  function renderBetSummary() {
    const settled = bets.filter(bet => ["won", "lost", "void", "cashed_out"].includes(bet.status));
    const decisive = bets.filter(bet => ["won", "lost"].includes(bet.status));
    const profit = settledProfit();
    const stake = settled.reduce((sum, bet) => sum + Number(bet.stake), 0);
    const roi = stake ? profit / stake : 0;
    const wins = decisive.filter(bet => bet.status === "won").length;
    el("bets-summary").innerHTML = `
      <div class="bet-kpi primary"><span>Beschikbare bankroll</span><strong>${startingBankroll ? money.format(currentBankroll()) : "Nog instellen"}</strong><small>${money.format(openStake())} staat open</small></div>
      <div class="bet-kpi"><span>Totale winst</span><strong>${money.format(profit)}</strong><small>${settled.length} afgewikkelde bets</small></div>
      <div class="bet-kpi"><span>ROI</span><strong>${number.format(roi * 100)}%</strong><small>op ${money.format(stake)} inzet</small></div>
      <div class="bet-kpi"><span>Hit rate</span><strong>${decisive.length ? `${Math.round(wins / decisive.length * 100)}%` : "—"}</strong><small>${wins} van ${decisive.length} beslist</small></div>`;
  }

  function renderPerformance() {
    const target = el("bet-performance");
    const settled = bets.filter(bet => ["won", "lost", "void", "cashed_out"].includes(bet.status));
    if (!settled.length) {
      target.innerHTML = '<div class="detail-empty">Na de eerste afgewikkelde bets verschijnt hier jullie rendement per markt.</div>';
      return;
    }
    const groups = {};
    for (const bet of settled) {
      const key = bet.market || "Overig";
      const group = groups[key] ||= { n: 0, stake: 0, profit: 0, clv: [] };
      group.n += 1;
      group.stake += Number(bet.stake);
      group.profit += Number(bet.payout || 0) - Number(bet.stake);
      if (bet.clv_percent != null) group.clv.push(Number(bet.clv_percent));
    }
    target.innerHTML = `<div class="performance-table">${Object.entries(groups).sort((a, b) => b[1].n - a[1].n).map(([name, group]) => {
      const roi = group.stake ? group.profit / group.stake * 100 : 0;
      const avgClv = group.clv.length ? group.clv.reduce((sum, value) => sum + value, 0) / group.clv.length : null;
      return `<div class="performance-row"><span>${esc(name)} · ${group.n}</span><b>${roi >= 0 ? "+" : ""}${number.format(roi)}% ROI</b><b>${group.profit >= 0 ? "+" : ""}${money.format(group.profit)}</b><b>${avgClv == null ? "CLV —" : `${avgClv >= 0 ? "+" : ""}${number.format(avgClv)}% CLV`}</b></div>`;
    }).join("")}</div>`;
  }

  function betProfit(bet) {
    return bet.status === "open" ? null : Number(bet.payout || 0) - Number(bet.stake);
  }

  function renderBets() {
    const visible = bets.filter(bet => betFilter === "all" || (betFilter === "open" ? bet.status === "open" : bet.status !== "open"));
    document.querySelectorAll(".bet-filter").forEach(button => button.classList.toggle("active", button.dataset.betFilter === betFilter));
    if (!visible.length) {
      el("bet-list").innerHTML = '<div class="empty">Nog geen bets in deze weergave.</div>';
      return;
    }
    el("bet-list").innerHTML = visible.map(bet => {
      const profit = betProfit(bet);
      const possible = Number(bet.stake) * Number(bet.odds);
      const expectedValue = bet.model_probability == null ? null : Number(bet.model_probability) * Number(bet.odds) - 1;
      return `<article class="bet-item">
        <div><div class="bet-title">${esc(bet.description)}</div><div class="bet-copy">${esc(bet.kind === "combi" ? "Combinatie" : (bet.market || "Single"))}${bet.selection ? ` · ${esc(bet.selection)}` : ""}<br>${esc(displayDate(bet.event_date || bet.placed_at))}${bet.bookmaker ? ` · ${esc(bet.bookmaker)}` : ""}${bet.result_score ? ` · ${esc(bet.result_score)}` : ""}</div><div class="bet-value-line">${expectedValue == null ? "" : `<span class="${expectedValue > 0 ? "positive" : ""}">${expectedValue > 0 ? "+" : ""}${number.format(expectedValue * 100)}% EV bij plaatsing</span>`}${bet.edge_pp != null ? `<span>${Number(bet.edge_pp) > 0 ? "+" : ""}${number.format(Number(bet.edge_pp))} pp versus markt</span>` : ""}${bet.clv_percent != null ? `<span class="${Number(bet.clv_percent) > 0 ? "positive" : ""}">${Number(bet.clv_percent) > 0 ? "+" : ""}${number.format(Number(bet.clv_percent))}% CLV</span>` : ""}${bet.auto_settled ? `<span>automatisch afgewikkeld</span>` : ""}</div><div class="bet-status ${esc(bet.status)}">${esc(statusLabels[bet.status] || bet.status)}</div></div>
        <div class="bet-numbers"><div class="bet-number"><span>Inzet</span><b>${money.format(Number(bet.stake))}</b></div><div class="bet-number"><span>Quote</span><b>${number.format(Number(bet.odds))}</b></div><div class="bet-number"><span>${profit === null ? "Mogelijk" : "Resultaat"}</span><b>${profit === null ? money.format(possible) : `${profit >= 0 ? "+" : ""}${money.format(profit)}`}</b></div></div>
        <div class="bet-actions">${bet.status === "open" ? `<button class="bet-action good" data-settle="won" data-id="${bet.id}">Gewonnen</button><button class="bet-action bad" data-settle="lost" data-id="${bet.id}">Verloren</button><button class="bet-action" data-settle="void" data-id="${bet.id}">Void</button><button class="bet-action" data-settle="cashed_out" data-id="${bet.id}">Cash-out</button>` : ""}<button class="bet-action" data-edit-bet="${bet.id}">Bewerken</button><button class="bet-action bad" data-delete-bet="${bet.id}">Verwijderen</button></div>
      </article>`;
    }).join("");
  }

  function openBetDialog(bet = null) {
    el("bet-form").reset();
    const amountsLocked = Boolean(bet && bet.status !== "open");
    el("bet-id").value = bet?.id || "";
    el("bet-fixture-id").value = bet?.fixture_external_id || "";
    el("bet-selection-key").value = bet?.selection_key || "";
    el("bet-model-probability").value = bet?.model_probability || "";
    el("bet-fair-market-probability").value = bet?.fair_market_probability || "";
    el("bet-edge-pp").value = bet?.edge_pp || "";
    el("bet-dialog-title").textContent = bet ? "Bet bewerken" : "Nieuwe bet";
    el("bet-kind").value = bet?.kind || "single";
    el("bet-description").value = bet?.description || "";
    el("bet-market").value = bet?.market || "";
    el("bet-selection").value = bet?.selection || "";
    el("bet-bookmaker").value = bet?.bookmaker || "";
    el("bet-stake").value = bet?.stake || "";
    el("bet-odds").value = bet?.odds || "";
    [el("bet-stake"), el("bet-odds")].forEach(input => {
      input.disabled = amountsLocked;
      input.title = amountsLocked ? "Inzet en quotering staan vast nadat een bet is afgewikkeld." : "";
    });
    el("bet-placed-at").value = bet?.placed_at || isoToday();
    el("bet-event-date").value = bet?.event_date || "";
    el("bet-notes").value = bet?.notes || "";
    el("bet-legs").value = Array.isArray(bet?.legs) ? bet.legs.map(leg => leg.label || "").filter(Boolean).join("\n") : "";
    rememberBetContext();
    populateSelectionOptions((window.AFTRAP_DATA || []).find(fixture => String(fixture.id) === value("bet-fixture-id")) || null);
    renderBetContext();
    toggleLegs();
    setMessage("bet-form-message", amountsLocked ? "Deze bet is al afgewikkeld. Inzet en quotering kunnen daarom niet meer worden gewijzigd." : "");
    el("bet-dialog").showModal();
  }

  function renderBetContext() {
    const model = parseAmount(value("bet-model-probability"));
    const odds = parseAmount(value("bet-odds"));
    const breakEven = odds >= 1.01 ? 1 / odds : null;
    const expectedValue = model && odds >= 1.01 ? model * odds - 1 : null;
    const box = el("bet-model-context");
    box.classList.toggle("hidden", !model);
    box.innerHTML = model ? `<span>Modelkans<b>${number.format(model * 100)}%</b></span><span>Break-even<b>${breakEven ? `${number.format(breakEven * 100)}%` : "—"}</b></span><span>Verwachte waarde<b>${expectedValue == null ? "—" : `${expectedValue > 0 ? "+" : ""}${number.format(expectedValue * 100)}% EV`}</b></span>` : "";
  }

  function openFromTip(tip) {
    openBetDialog();
    el("bet-kind").value = "single";
    el("bet-fixture-id").value = tip.fixtureId;
    el("bet-selection-key").value = tip.selectionKey;
    el("bet-description").value = tip.description;
    el("bet-market").value = tip.market;
    el("bet-selection").value = tip.selection;
    el("bet-bookmaker").value = tip.bookmaker;
    el("bet-odds").value = tip.odds.toFixed(2);
    el("bet-event-date").value = tip.eventDate;
    el("bet-model-probability").value = tip.modelProbability;
    el("bet-fair-market-probability").value = tip.fairMarketProbability ?? "";
    el("bet-edge-pp").value = tip.edgePp ?? "";
    renderBetContext();
    rememberBetContext();
    populateSelectionOptions((window.AFTRAP_DATA || []).find(fixture => String(fixture.id) === value("bet-fixture-id")) || null);
    el("bet-stake").focus();
  }

  function toggleLegs() {
    el("bet-legs-wrap").classList.toggle("hidden", el("bet-kind").value !== "combi");
  }

  async function saveBet(event) {
    event.preventDefault();
    const id = value("bet-id");
    syncManualBetContext({ preserveExisting: true });
    const button = el("save-bet");
    const payload = {
      user_id: user.id,
      placed_at: value("bet-placed-at") || isoToday(),
      event_date: value("bet-event-date") || null,
      kind: value("bet-kind"),
      description: value("bet-description"),
      market: value("bet-market") || null,
      selection: value("bet-selection") || null,
      bookmaker: value("bet-bookmaker") || null,
      stake: parseAmount(value("bet-stake")),
      odds: parseAmount(value("bet-odds")),
      legs: value("bet-legs").split("\n").map(label => label.trim()).filter(Boolean).map(label => ({ label })),
      notes: value("bet-notes") || null,
      fixture_external_id: value("bet-fixture-id") || null,
      selection_key: value("bet-selection-key") || null,
      model_probability: parseAmount(value("bet-model-probability")) || null,
      fair_market_probability: parseAmount(value("bet-fair-market-probability")) || null,
      edge_pp: value("bet-edge-pp") === "" ? null : Number(value("bet-edge-pp")),
      updated_at: new Date().toISOString(),
    };
    const existingBet = id ? bets.find(bet => String(bet.id) === String(id)) : null;
    if (existingBet && existingBet.status !== "open") {
      payload.stake = Number(existingBet.stake);
      payload.odds = Number(existingBet.odds);
    }
    if (!payload.description || payload.stake <= 0 || payload.odds < 1.01) {
      setMessage("bet-form-message", "Vul minimaal een omschrijving, inzet en quotering van 1,01 of hoger in.", true);
      return;
    }
    if (payload.kind === "single" && payload.fixture_external_id && !payload.selection_key) {
      setMessage("bet-form-message", "Kies bij deze wedstrijd een selectie uit de suggesties, zodat Aftrap de bet automatisch kan afwikkelen.", true);
      return;
    }
    setBusy(button, true, "Opslaan…");
    const query = id ? db.from("aftrap_bets").update(payload).eq("id", id) : db.from("aftrap_bets").insert(payload);
    const { error } = await query;
    setBusy(button, false, "");
    if (error) {
      setMessage("bet-form-message", "De bet kon niet worden opgeslagen.", true);
      return;
    }
    el("bet-dialog").close();
    await loadBets();
  }

  async function settleBet(id, status) {
    const bet = bets.find(item => item.id === id);
    if (!bet) return;
    let payout = null;
    if (status === "won") payout = Number(bet.stake) * Number(bet.odds);
    if (status === "lost") payout = 0;
    if (status === "void") payout = Number(bet.stake);
    if (status === "cashed_out") {
      const raw = window.prompt("Welk bedrag heb je uitgecasht?", Number(bet.stake).toFixed(2));
      if (raw === null) return;
      payout = parseFiniteAmount(raw);
      if (payout === null || payout < 0) {
        window.alert("Vul een geldig cash-outbedrag van € 0,00 of hoger in.");
        return;
      }
    }
    const { error } = await db.from("aftrap_bets").update({ status, payout, auto_settled: false, settled_at: new Date().toISOString(), updated_at: new Date().toISOString() }).eq("id", id);
    if (!error) await loadBets();
  }

  function settleSelection(key, result) {
    const { hg, ag, hh, ah } = result;
    if (key.startsWith("fh_")) {
      if (hh == null || ah == null) return null;
      const rest = key.slice(3), total = hh + ah;
      if (rest.startsWith("over_")) return total > Number(rest.slice(5));
      if (rest.startsWith("under_")) return total < Number(rest.slice(6));
      if (rest === "home") return hh > ah;
      if (rest === "draw") return hh === ah;
      if (rest === "away") return ah > hh;
      return null;
    }
    const total = hg + ag;
    if (key.startsWith("over_")) return total > Number(key.slice(5));
    if (key.startsWith("under_")) return total < Number(key.slice(6));
    if (key === "home") return hg > ag;
    if (key === "draw") return hg === ag;
    if (key === "away") return ag > hg;
    if (key === "home_or_draw") return hg >= ag;
    if (key === "away_or_draw") return ag >= hg;
    if (key === "home_or_away") return hg !== ag;
    if (key === "btts_yes") return hg > 0 && ag > 0;
    if (key === "btts_no") return hg === 0 || ag === 0;
    for (const [prefix, goals] of [["home_", hg], ["away_", ag]]) {
      if (!key.startsWith(prefix)) continue;
      const rest = key.slice(prefix.length);
      if (rest.startsWith("over_")) return goals > Number(rest.slice(5));
      if (rest.startsWith("under_")) return goals < Number(rest.slice(6));
    }
    return null;
  }

  async function autoSettleBets() {
    const candidates = bets.filter(bet => bet.status === "open" && bet.kind === "single" && bet.fixture_external_id && bet.selection_key);
    let changed = false;
    for (const bet of candidates) {
      const result = settlements.find(item => String(item.id) === String(bet.fixture_external_id));
      if (!result) continue;
      const won = settleSelection(bet.selection_key, result);
      if (won == null) continue;
      const close = (result.closing || []).find(item => item.s === bet.selection_key && item.b === bet.bookmaker) || (result.closing || []).find(item => item.s === bet.selection_key);
      const closingOdd = close ? Number(close.o) : null;
      const clv = closingOdd ? (Number(bet.odds) / closingOdd - 1) * 100 : null;
      const payload = {
        status: won ? "won" : "lost", payout: won ? Number(bet.stake) * Number(bet.odds) : 0,
        closing_odd: closingOdd, clv_percent: clv, result_score: `${result.hg}-${result.ag}`,
        auto_settled: true, settled_at: new Date().toISOString(), updated_at: new Date().toISOString(),
      };
      const { error } = await db.from("aftrap_bets").update(payload).eq("id", bet.id).eq("status", "open");
      if (!error) changed = true;
    }
    return changed;
  }

  async function deleteBet(id) {
    if (!window.confirm("Deze bet definitief verwijderen?")) return;
    const { error } = await db.from("aftrap_bets").delete().eq("id", id);
    if (!error) await loadBets();
  }

  function scenarioNumber(input, minimum, maximum = Infinity) {
    const raw = parseFiniteAmount(input.value);
    const bounded = Math.min(maximum, Math.max(minimum, raw ?? minimum));
    const valid = raw !== null && raw >= minimum && raw <= maximum;
    input.setAttribute("aria-invalid", valid ? "false" : "true");
    return { value: bounded, valid, provided: raw !== null };
  }

  function clampScenarioInput(input) {
    const minimum = parseFiniteAmount(input.min) ?? -Infinity;
    const maximum = parseFiniteAmount(input.max) ?? Infinity;
    const raw = parseFiniteAmount(input.value);
    if (raw === null) return;
    const bounded = Math.min(maximum, Math.max(minimum, raw));
    if (bounded !== raw) input.value = String(bounded);
  }

  function calculateScenarios() {
    const bankrollField = scenarioNumber(el("scenario-bankroll"), 0);
    const bankroll = bankrollField.value;
    document.querySelectorAll(".scenario-card").forEach(card => {
      const stakeField = scenarioNumber(card.querySelector("[data-scenario-stake]"), 0);
      const oddsField = scenarioNumber(card.querySelector("[data-scenario-odds]"), 1.01);
      const chanceField = scenarioNumber(card.querySelector("[data-scenario-chance]"), 0, 100);
      const stake = stakeField.value;
      const odds = oddsField.value;
      const chance = chanceField.value / 100;
      const valid = stakeField.valid && oddsField.valid;
      const payout = valid ? stake * odds : 0;
      const winBankroll = bankroll - stake + payout;
      const lossBankroll = bankroll - stake;
      const breakEven = oddsField.valid ? 1 / odds : 0;
      const ev = chanceField.provided && valid ? stake * (chance * odds - 1) : null;
      const kelly = chanceField.provided && oddsField.valid ? Math.max(0, (chance * odds - 1) / (odds - 1)) : null;
      card.querySelector("[data-scenario-output]").innerHTML = `
        <div class="scenario-metric"><span>Uitbetaling</span><b>${money.format(payout)}</b></div>
        <div class="scenario-metric"><span>Break-even</span><b>${number.format(breakEven * 100)}%</b></div>
        <div class="scenario-metric"><span>Bankroll bij winst</span><b>${money.format(winBankroll)}</b></div>
        <div class="scenario-metric"><span>Bankroll bij verlies</span><b>${money.format(lossBankroll)}</b></div>
        <div class="scenario-metric"><span>Verwachte waarde</span><b>${ev === null ? "Vul kans in" : money.format(ev)}</b></div>
        <div class="scenario-metric"><span>¼ Kelly-inzet</span><b>${kelly === null ? "—" : money.format(bankroll * kelly * .25)}</b></div>`;
    });
  }

  function populateFixtureOptions() {
    const fixtures = window.AFTRAP_DATA || [];
    el("fixture-options").innerHTML = fixtures.map(fixture => `<option value="${esc(`${fixture.home} – ${fixture.away}`)}"></option>`).join("");
  }

  document.addEventListener("DOMContentLoaded", async () => {
    setAppChromeAccessible(false);
    populateFixtureOptions();
    el("email-form").addEventListener("submit", loginWithPassword);
    el("account-button").addEventListener("click", async () => { await db.auth.signOut(); location.reload(); });
    el("new-bet").addEventListener("click", () => openBetDialog());
    el("bet-form").addEventListener("submit", saveBet);
    el("bet-kind").addEventListener("change", () => { toggleLegs(); syncManualBetContext(); });
    el("bet-description").addEventListener("input", () => syncManualBetContext());
    ["bet-market", "bet-selection"].forEach(id => el(id).addEventListener("input", () => syncManualBetContext({ preserveExisting: true })));
    el("bet-odds").addEventListener("input", renderBetContext);
    el("close-bet-dialog").addEventListener("click", () => el("bet-dialog").close());
    el("cancel-bet").addEventListener("click", () => el("bet-dialog").close());
    el("save-bankroll").addEventListener("click", saveSettings);
    el("scenario-bankroll").addEventListener("input", calculateScenarios);
    el("scenario-bankroll").addEventListener("blur", event => { clampScenarioInput(event.target); calculateScenarios(); });
    document.querySelectorAll(".scenario-card input").forEach(input => {
      input.addEventListener("input", calculateScenarios);
      input.addEventListener("blur", event => { clampScenarioInput(event.target); calculateScenarios(); });
    });
    document.addEventListener("click", event => {
      const filter = event.target.closest("[data-bet-filter]");
      if (filter) { betFilter = filter.dataset.betFilter; renderBets(); }
      const settle = event.target.closest("[data-settle]");
      if (settle) settleBet(settle.dataset.id, settle.dataset.settle);
      const edit = event.target.closest("[data-edit-bet]");
      if (edit) openBetDialog(bets.find(bet => bet.id === edit.dataset.editBet));
      const remove = event.target.closest("[data-delete-bet]");
      if (remove) deleteBet(remove.dataset.deleteBet);
    });
    calculateScenarios();
    const { data: { session } } = await db.auth.getSession();
    if (session) await authorizeSession(); else showLogin();
  });

  window.AftrapAccount = { refresh: loadBets, openFromTip };
})();
