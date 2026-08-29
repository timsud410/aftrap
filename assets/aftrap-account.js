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

  const el = id => document.getElementById(id);
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
  const parseAmount = raw => Number(String(raw).replace(",", ".")) || 0;
  const isoToday = () => new Date().toISOString().slice(0, 10);
  const displayDate = raw => raw ? new Intl.DateTimeFormat("nl-NL", { day: "numeric", month: "short", year: "numeric" }).format(new Date(`${raw}T12:00:00`)) : "Geen datum";

  function showLogin() {
    document.body.classList.add("auth-pending");
    el("auth-gate").classList.remove("hidden");
    el("account-button").classList.add("hidden");
  }

  function showApp() {
    el("auth-gate").classList.add("hidden");
    document.body.classList.remove("auth-pending");
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

  async function requestOtp(event) {
    event.preventDefault();
    const button = el("request-code");
    const email = value("auth-email").toLowerCase();
    if (!email) return;
    setBusy(button, true, "Versturen…");
    setMessage("auth-status", "");
    const { error } = await db.auth.signInWithOtp({
      email,
      options: { shouldCreateUser: true, emailRedirectTo: `${location.origin}${location.pathname}` },
    });
    setBusy(button, false, "");
    if (error) {
      setMessage("auth-status", "De inlogmail kon niet worden verstuurd. Probeer het over een minuut opnieuw.", true);
      return;
    }
    sessionStorage.setItem("aftrap_pending_email", email);
    el("otp-email-copy").textContent = email;
    el("email-form").classList.add("hidden");
    el("otp-form").classList.remove("hidden");
    el("auth-code").focus();
    setMessage("auth-status", "Controleer je inbox. Gebruik de zescijferige code of open de inloglink.");
  }

  async function verifyOtp(event) {
    event.preventDefault();
    const button = el("verify-code");
    const email = sessionStorage.getItem("aftrap_pending_email") || value("auth-email").toLowerCase();
    const token = value("auth-code").replace(/\s/g, "");
    if (!/^\d{6}$/.test(token)) {
      setMessage("auth-status", "Vul de zescijferige code uit de e-mail in.", true);
      return;
    }
    setBusy(button, true, "Controleren…");
    const { error } = await db.auth.verifyOtp({ email, token, type: "email" });
    setBusy(button, false, "");
    if (error) {
      setMessage("auth-status", "Deze code is ongeldig of verlopen. Vraag eventueel een nieuwe aan.", true);
      return;
    }
    sessionStorage.removeItem("aftrap_pending_email");
    await authorizeSession();
  }

  function resetOtp() {
    el("otp-form").classList.add("hidden");
    el("email-form").classList.remove("hidden");
    el("auth-code").value = "";
    setMessage("auth-status", "");
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

  async function loadBets() {
    el("bet-list").innerHTML = '<div class="loading-block">Bets laden…</div>';
    const { data, error } = await db.from("aftrap_bets").select("*").order("placed_at", { ascending: false }).order("created_at", { ascending: false });
    if (error) {
      el("bet-list").innerHTML = '<div class="empty">De bets konden niet worden geladen.</div>';
      return;
    }
    bets = data || [];
    renderBets();
    renderBetSummary();
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
      return `<article class="bet-item">
        <div><div class="bet-title">${esc(bet.description)}</div><div class="bet-copy">${esc(bet.kind === "combi" ? "Combinatie" : (bet.market || "Single"))}${bet.selection ? ` · ${esc(bet.selection)}` : ""}<br>${esc(displayDate(bet.event_date || bet.placed_at))}${bet.bookmaker ? ` · ${esc(bet.bookmaker)}` : ""}</div><div class="bet-status ${esc(bet.status)}">${esc(statusLabels[bet.status] || bet.status)}</div></div>
        <div class="bet-numbers"><div class="bet-number"><span>Inzet</span><b>${money.format(Number(bet.stake))}</b></div><div class="bet-number"><span>Quote</span><b>${number.format(Number(bet.odds))}</b></div><div class="bet-number"><span>${profit === null ? "Mogelijk" : "Resultaat"}</span><b>${profit === null ? money.format(possible) : `${profit >= 0 ? "+" : ""}${money.format(profit)}`}</b></div></div>
        <div class="bet-actions">${bet.status === "open" ? `<button class="bet-action good" data-settle="won" data-id="${bet.id}">Gewonnen</button><button class="bet-action bad" data-settle="lost" data-id="${bet.id}">Verloren</button><button class="bet-action" data-settle="void" data-id="${bet.id}">Void</button><button class="bet-action" data-settle="cashed_out" data-id="${bet.id}">Cash-out</button>` : ""}<button class="bet-action" data-edit-bet="${bet.id}">Bewerken</button><button class="bet-action bad" data-delete-bet="${bet.id}">Verwijderen</button></div>
      </article>`;
    }).join("");
  }

  function openBetDialog(bet = null) {
    el("bet-form").reset();
    el("bet-id").value = bet?.id || "";
    el("bet-dialog-title").textContent = bet ? "Bet bewerken" : "Nieuwe bet";
    el("bet-kind").value = bet?.kind || "single";
    el("bet-description").value = bet?.description || "";
    el("bet-market").value = bet?.market || "";
    el("bet-selection").value = bet?.selection || "";
    el("bet-bookmaker").value = bet?.bookmaker || "";
    el("bet-stake").value = bet?.stake || "";
    el("bet-odds").value = bet?.odds || "";
    el("bet-placed-at").value = bet?.placed_at || isoToday();
    el("bet-event-date").value = bet?.event_date || "";
    el("bet-notes").value = bet?.notes || "";
    el("bet-legs").value = Array.isArray(bet?.legs) ? bet.legs.map(leg => leg.label || "").filter(Boolean).join("\n") : "";
    toggleLegs();
    setMessage("bet-form-message", "");
    el("bet-dialog").showModal();
  }

  function toggleLegs() {
    el("bet-legs-wrap").classList.toggle("hidden", el("bet-kind").value !== "combi");
  }

  async function saveBet(event) {
    event.preventDefault();
    const id = value("bet-id");
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
      updated_at: new Date().toISOString(),
    };
    if (!payload.description || payload.stake <= 0 || payload.odds <= 1) {
      setMessage("bet-form-message", "Vul minimaal een omschrijving, inzet en quotering hoger dan 1,00 in.", true);
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
      payout = parseAmount(raw);
    }
    const { error } = await db.from("aftrap_bets").update({ status, payout, updated_at: new Date().toISOString() }).eq("id", id);
    if (!error) await loadBets();
  }

  async function deleteBet(id) {
    if (!window.confirm("Deze bet definitief verwijderen?")) return;
    const { error } = await db.from("aftrap_bets").delete().eq("id", id);
    if (!error) await loadBets();
  }

  function calculateScenarios() {
    const bankroll = parseAmount(value("scenario-bankroll"));
    document.querySelectorAll(".scenario-card").forEach(card => {
      const stake = parseAmount(card.querySelector("[data-scenario-stake]").value);
      const odds = parseAmount(card.querySelector("[data-scenario-odds]").value);
      const chance = parseAmount(card.querySelector("[data-scenario-chance]").value) / 100;
      const valid = stake > 0 && odds > 1;
      const payout = valid ? stake * odds : 0;
      const winBankroll = bankroll - stake + payout;
      const lossBankroll = bankroll - stake;
      const breakEven = odds > 1 ? 1 / odds : 0;
      const ev = chance > 0 && valid ? stake * (chance * odds - 1) : null;
      const kelly = chance > 0 && odds > 1 ? Math.max(0, (chance * odds - 1) / (odds - 1)) : null;
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
    el("fixture-options").innerHTML = DATA.map(fixture => `<option value="${esc(`${teamName(fixture.home)} – ${teamName(fixture.away)}`)}"></option>`).join("");
  }

  document.addEventListener("DOMContentLoaded", async () => {
    populateFixtureOptions();
    el("email-form").addEventListener("submit", requestOtp);
    el("otp-form").addEventListener("submit", verifyOtp);
    el("auth-back").addEventListener("click", resetOtp);
    el("account-button").addEventListener("click", async () => { await db.auth.signOut(); location.reload(); });
    el("new-bet").addEventListener("click", () => openBetDialog());
    el("bet-form").addEventListener("submit", saveBet);
    el("bet-kind").addEventListener("change", toggleLegs);
    el("close-bet-dialog").addEventListener("click", () => el("bet-dialog").close());
    el("cancel-bet").addEventListener("click", () => el("bet-dialog").close());
    el("save-bankroll").addEventListener("click", saveSettings);
    el("scenario-bankroll").addEventListener("input", calculateScenarios);
    document.querySelectorAll(".scenario-card input").forEach(input => input.addEventListener("input", calculateScenarios));
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

  window.AftrapAccount = { refresh: loadBets };
})();
