(() => {
  "use strict";

  const DATA = window.AFTRAP_DATA || [];
  const BAND = {
    high: { score: 4, label: "sterk", bars: 3 },
    medium: { score: 3, label: "goed onderbouwd", bars: 2 },
    low: { score: 2, label: "voorzichtig", bars: 1 },
    thin_data: { score: 1, label: "beperkte historie", bars: 1 },
  };
  const state = { view: "tips", date: "all", league: "all", bookmaker: "best", minimumOdd: 1.30, expanded: false, detailMarket: null };
  const TEAM_DISPLAY = {"Nott'm Forest":"Nottingham Forest","Man United":"Manchester United","Man City":"Manchester City","For Sittard":"Fortuna Sittard","Ath Madrid":"Atlético Madrid","Ath Bilbao":"Athletic Club","Sociedad":"Real Sociedad","Espanol":"Espanyol","Paris SG":"Paris Saint-Germain","M'gladbach":"Borussia M'gladbach","Ein Frankfurt":"Eintracht Frankfurt","FC Koln":"1. FC Köln","Nijmegen":"NEC Nijmegen","Den Haag":"ADO Den Haag","Zwolle":"PEC Zwolle","La Coruna":"Deportivo La Coruña","Santander":"Racing Santander"};
  const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[c]));
  const pct = value => Number.isFinite(Number(value)) ? `${Math.round(Number(value) * 100)}%` : "—";
  const pp = value => `${value > 0 ? "+" : ""}${(value * 100).toFixed(1).replace(".", ",")} pp`;
  const oddText = value => Number(value).toFixed(2).replace(".", ",");
  const teamName = value => TEAM_DISPLAY[value] || value;
  const displayText = value => Object.entries(TEAM_DISPLAY).reduce((text, [raw, nice]) => text.replaceAll(raw, nice), String(value));
  const dateObj = value => new Date(`${value}T12:00:00`);
  const shortDate = value => new Intl.DateTimeFormat("nl-NL", { weekday: "short", day: "numeric", month: "short" }).format(dateObj(value));
  const longDate = value => new Intl.DateTimeFormat("nl-NL", { weekday: "long", day: "numeric", month: "long" }).format(dateObj(value));
  const relativeDate = value => {
    const now = new Date();
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 12);
    const delta = Math.round((dateObj(value) - today) / 86400000);
    if (delta === 0) return "Vandaag";
    if (delta === 1) return "Morgen";
    return shortDate(value);
  };

  function marketLabel(key, fixture) {
    const fixed = {
      home: `${teamName(fixture.home)} wint`, draw: "Gelijkspel", away: `${teamName(fixture.away)} wint`,
      home_or_draw: `${teamName(fixture.home)} of gelijk`, away_or_draw: `${teamName(fixture.away)} of gelijk`,
      home_or_away: "Geen gelijkspel", btts_yes: "Beide teams scoren", btts_no: "Niet beide teams scoren",
      fh_home: `${teamName(fixture.home)} wint 1e helft`, fh_draw: "Gelijk 1e helft", fh_away: `${teamName(fixture.away)} wint 1e helft`,
    };
    if (fixed[key]) return fixed[key];
    let match = key.match(/^(over|under)_([0-9.]+)$/);
    if (match) return `${match[1] === "over" ? "Over" : "Under"} ${match[2]} goals`;
    match = key.match(/^fh_(over|under)_([0-9.]+)$/);
    if (match) return `1e helft ${match[1]} ${match[2]}`;
    match = key.match(/^(home|away)_(over|under)_([0-9.]+)$/);
    if (match) return `${teamName(match[1] === "home" ? fixture.home : fixture.away)} ${match[2]} ${match[3]}`;
    return key.replaceAll("_", " ");
  }

  function marketGroup(key) {
    if (["home", "draw", "away", "home_or_draw", "away_or_draw", "home_or_away"].includes(key)) return "Fulltime";
    if (key.startsWith("fh_")) return "Eerste helft";
    if (key.startsWith("btts_")) return "BTTS";
    if (key.startsWith("home_") || key.startsWith("away_")) return "Team goals";
    return "Totaal goals";
  }

  const bestTip = fixture => [...fixture.tips].sort((a, b) => (BAND[b.b]?.score || 0) - (BAND[a.b]?.score || 0) || b.p - a.p)[0];
  const highlighted = DATA.filter(fixture => fixture.tips.length).map(fixture => ({ fixture, tip: bestTip(fixture) }));
  const filteredFixtures = () => DATA.filter(f => (state.date === "all" || f.date === state.date) && (state.league === "all" || f.league === state.league));

  function selectedOdd(fixture, key, bookmaker = state.bookmaker) {
    const available = (fixture.odds || []).filter(odd => odd.s === key && (bookmaker === "best" || odd.b === bookmaker));
    const fresh = available.filter(odd => (oddAge(odd) ?? 0) <= 6);
    return (fresh.length ? fresh : available).sort((a, b) => Number(b.o) - Number(a.o))[0] || null;
  }

  function oddAge(odd) {
    if (!odd?.u) return null;
    const hours = (Date.now() - new Date(odd.u).getTime()) / 3600000;
    return Number.isFinite(hours) ? hours : null;
  }

  function betPayload(fixture, key, probability, found) {
    return {
      fixtureId: String(fixture.id), description: `${teamName(fixture.home)} – ${teamName(fixture.away)}`,
      eventDate: fixture.date, market: marketGroup(key), selection: marketLabel(key, fixture), selectionKey: key,
      bookmaker: found.b, odds: Number(found.o), modelProbability: Number(probability),
      fairMarketProbability: found.f == null ? null : Number(found.f),
      edgePp: found.f == null ? null : (Number(probability) - Number(found.f)) * 100,
    };
  }

  function parseMinimumOdd(raw) {
    const parsed = Number(String(raw).trim().replace(",", "."));
    return Number.isFinite(parsed) && parsed >= 1.01 ? parsed : 1.30;
  }

  function rankedSelections() {
    return filteredFixtures().flatMap(fixture => Object.entries(fixture.probs || {}).flatMap(([key, rawProbability]) => {
      if (key.endsWith("clean_sheet")) return [];
      const probability = Number(rawProbability);
      const odd = selectedOdd(fixture, key);
      if (!odd || !Number.isFinite(probability) || Number(odd.o) < state.minimumOdd || (oddAge(odd) ?? 0) > 6) return [];
      const reference = odd.f == null ? 1 / Number(odd.o) : Number(odd.f);
      return [{ fixture, key, probability, odd, edge: probability - reference, verified: fixture.tips.some(tip => tip.raw === key) }];
    })).sort((a, b) => b.probability - a.probability || b.edge - a.edge || Number(b.odd.o) - Number(a.odd.o));
  }

  function chanceRow(item, index) {
    const { fixture, key, probability, verified } = item;
    return `<article class="chance-row"><span class="chance-rank">#${index + 1}</span><div class="chance-fixture"><b>${esc(teamName(fixture.home))} – ${esc(teamName(fixture.away))}</b><span>${esc(shortDate(fixture.date))} · ${esc(fixture.kickoff || "tijd n.n.b.")} · ${esc(fixture.league)}</span></div><div class="chance-selection"><b>${esc(marketLabel(key, fixture))}</b><span class="${verified ? "verified-signal" : ""}">${esc(marketGroup(key))}${verified ? " · gevalideerd signaal" : " · modelmarkt"}</span></div><div class="chance-probability"><span>Modelkans</span><strong>${pct(probability)}</strong></div>${oddBlock(fixture, { key, p: probability })}<button class="chance-open" type="button" data-open-match="${esc(fixture.id)}" data-open-market="${esc(key)}">Details</button></article>`;
  }

  function oddBlock(fixture, row, compact = false, bookmaker = null) {
    const found = selectedOdd(fixture, row.key, bookmaker || state.bookmaker);
    if (!found) return `<span class="odd-pill missing">geen odd</span>`;
    const reference = found.f == null ? 1 / Number(found.o) : Number(found.f);
    const edge = Number(row.p) - reference;
    const stale = (oddAge(found) ?? 0) > 6;
    const label = found.f == null ? "break-even" : "markt zonder marge";
    return `<button class="odd-pill ${edge > 0 ? "value" : ""} ${stale ? "stale" : ""}" type="button" data-add-bet data-fixture-id="${esc(fixture.id)}" data-selection-key="${esc(row.key)}" title="Model ${pct(row.p)} · ${label} ${pct(reference)} · klik om als bet toe te voegen"><b>@ ${oddText(found.o)}</b><small>${esc(found.b)} · ${pp(edge)}${stale ? " · oud" : ""}</small>${compact ? "" : "<i>+ bet</i>"}</button>`;
  }

  function confidenceBars(band) {
    const info = BAND[band] || BAND.low;
    return `<div class="confidence-bars" aria-label="Bewijskracht: ${esc(info.label)}">${[1, 2, 3].map(i => `<i class="${i <= info.bars ? "on" : ""}"></i>`).join("")}</div>`;
  }

  function marketRows(fixture, tip) {
    const results = [{ name: `${teamName(fixture.home)} wint`, p: fixture.p_home, key: "home" }, { name: "Gelijkspel", p: fixture.p_draw, key: "draw" }, { name: `${teamName(fixture.away)} wint`, p: fixture.p_away, key: "away" }];
    const fulltime = results.sort((a, b) => b.p - a.p)[0];
    const btts = fixture.p_btts >= .5 ? { name: "Beide teams scoren", p: fixture.p_btts, key: "btts_yes" } : { name: "Niet beide teams scoren", p: 1 - fixture.p_btts, key: "btts_no" };
    const rows = [{ kind: "Hoofdselectie", name: displayText(tip.s), p: tip.p, key: tip.raw, primary: true }, { kind: "Fulltime", ...fulltime }, { kind: "BTTS", ...btts }];
    return `<div class="tip-stack">${rows.map(row => {
      const found = selectedOdd(fixture, row.key);
      const detail = found?.f != null ? `Eerlijke markt ${pct(found.f)}` : found ? `Break-even ${pct(1 / Number(found.o))}` : "Nog niet aangeboden";
      return `<div class="tip-line ${row.primary ? "primary" : ""}"><span class="tip-kind">${esc(row.kind)}</span><span class="tip-line-name">${esc(row.name)}<small>${esc(detail)}</small></span><strong class="tip-line-value">${pct(row.p)}</strong>${oddBlock(fixture, row)}</div>`;
    }).join("")}</div>`;
  }

  function playerForm(fixture) {
    const players = fixture.players || [];
    if (!players.length) return `<div class="player-empty">Voor deze wedstrijd is nog geen individuele schotdata beschikbaar.</div>`;
    return `<section class="player-form"><div class="player-form-head"><b>Recente spelersschoten</b><span>maximaal vijf optredens</span></div><div class="player-list">${players.map(player => `<div class="player-row"><div class="player-name"><b>${esc(player.name)}</b><span>${esc(teamName(player.team))} · ${player.n} duels</span></div><div class="player-stat"><b>${Number(player.sot_avg).toFixed(1)}</b><span>SoT gem.</span></div><div class="player-stat"><b>${Number(player.shots_avg).toFixed(1)}</b><span>Schoten</span></div><div class="player-stat"><b>${player.sot_hits}/${player.n}</b><span>1+ SoT</span></div></div>`).join("")}</div><p class="player-form-note">Vormdata, geen apart gekalibreerd bets-signaal.</p></section>`;
  }

  function pickCard(fixture, tip, index) {
    const info = BAND[tip.b] || BAND.low;
    return `<article class="pick-card ${index < 2 ? "featured" : ""}"><div class="pick-meta">${index < 2 ? `<span class="featured-label">● Uitgelicht</span><span>·</span>` : ""}<span>${esc(shortDate(fixture.date))} · ${esc(fixture.kickoff || "tijd n.n.b.")}</span><span class="league-pill">${esc(fixture.league)}</span></div><div class="fixture-name">${esc(teamName(fixture.home))}<span>—</span>${esc(teamName(fixture.away))}</div>${marketRows(fixture, tip)}<p class="stack-note">Waarde = modelkans minus de bookmakerkans ná verwijdering van de marge. Klik op een odd om de bet voor te vullen.</p><div class="confidence"><span class="confidence-copy">Bewijskracht hoofdselectie: <b>${esc(info.label)}</b></span>${confidenceBars(tip.b)}</div><p class="rationale">${esc(displayText(tip.r))}</p><button class="match-detail-button" type="button" data-open-match="${esc(fixture.id)}">Open volledige wedstrijdanalyse →</button></article>`;
  }

  function renderSummary() {
    const leagues = new Set(DATA.map(f => f.league)).size;
    document.getElementById("hero-summary").innerHTML = `<div class="hero-stat primary"><strong>${highlighted.length}</strong><span>uitgelichte wedstrijden</span></div><div class="hero-stat"><strong>${DATA.length}</strong><span>wedstrijden gecontroleerd</span></div><div class="hero-stat"><strong>${leagues}</strong><span>competities gevolgd</span></div>`;
    document.getElementById("tip-count").textContent = highlighted.length;
    document.getElementById("match-count").textContent = DATA.length;
  }

  function renderFilters() {
    const dates = [...new Set(DATA.map(f => f.date))].sort();
    document.getElementById("date-chips").innerHTML = [`<button class="date-chip active" data-date="all">Alle dagen</button>`, ...dates.map(day => `<button class="date-chip" data-date="${esc(day)}">${esc(relativeDate(day))}</button>`)].join("");
    const leagues = [...new Set(DATA.map(f => f.league))].sort();
    document.getElementById("league-select").innerHTML = `<option value="all">Alle competities</option>${leagues.map(league => `<option value="${esc(league)}">${esc(league)}</option>`).join("")}`;
    const bookmakers = [...new Set(DATA.flatMap(f => (f.odds || []).map(o => o.b)))].sort();
    const select = document.getElementById("bookmaker-select");
    select.innerHTML = bookmakers.length ? `<option value="best">Beste beschikbare odd</option>${bookmakers.map(name => `<option value="${esc(name)}">${esc(name)}</option>`).join("")}` : `<option>Odds nog niet beschikbaar</option>`;
    select.disabled = !bookmakers.length;
  }

  function renderTips() {
    const ranking = rankedSelections();
    const visibleRanking = state.expanded ? ranking : ranking.slice(0, 12);
    const minimum = oddText(state.minimumOdd);
    document.getElementById("tip-result-count").textContent = `${ranking.length} ${ranking.length === 1 ? "selectie" : "selecties"} vanaf @${minimum}`;
    document.getElementById("chance-ranking").innerHTML = ranking.length ? visibleRanking.map(chanceRow).join("") : `<div class="empty">Geen actuele quoteringen vanaf @${minimum} voor deze filters.</div>`;
    document.getElementById("more-wrap").classList.toggle("hidden", state.expanded || ranking.length <= 12);
    document.getElementById("more-button").textContent = `Toon alle ${ranking.length} selecties`;

    const tips = filteredFixtures().filter(f => f.tips.length).map(fixture => ({ fixture, tip: bestTip(fixture) })).sort((a, b) => (BAND[b.tip.b]?.score || 0) - (BAND[a.tip.b]?.score || 0) || b.tip.p - a.tip.p || a.fixture.date.localeCompare(b.fixture.date));
    document.getElementById("pick-grid").innerHTML = tips.length ? tips.slice(0, 8).map(({ fixture, tip }, index) => pickCard(fixture, tip, index)).join("") : `<div class="empty">Voor deze filters zijn geen uitgelichte signaalwedstrijden gevonden.</div>`;
  }

  function compactOdd(fixture, key) {
    const odd = selectedOdd(fixture, key);
    return odd ? `@ ${oddText(odd.o)}` : "—";
  }

  function renderMatches() {
    const fixtures = filteredFixtures();
    const groups = [];
    for (const fixture of fixtures) {
      let group = groups.find(item => item.date === fixture.date);
      if (!group) { group = { date: fixture.date, fixtures: [] }; groups.push(group); }
      group.fixtures.push(fixture);
    }
    document.getElementById("match-result-count").textContent = `${fixtures.length} wedstrijden`;
    document.getElementById("matches").innerHTML = groups.length ? groups.map(group => `<section class="match-day"><div class="match-day-head">${esc(longDate(group.date))}</div>${group.fixtures.map(f => `<button class="match-row" type="button" data-open-match="${esc(f.id)}"><span class="match-time">${esc(f.kickoff || "—")}</span><span><span class="match-teams">${esc(teamName(f.home))}<i>—</i>${esc(teamName(f.away))}</span><span class="match-league">${esc(f.league)}</span><span class="match-odds-line"><span>1 <b>${compactOdd(f, "home")}</b></span><span>X <b>${compactOdd(f, "draw")}</b></span><span>2 <b>${compactOdd(f, "away")}</b></span></span></span><span class="match-model"><span>1 <b>${pct(f.p_home)}</b></span><span>X <b>${pct(f.p_draw)}</b></span><span>2 <b>${pct(f.p_away)}</b></span><span>O2.5 <b>${pct(f.p_over25)}</b></span></span><span class="match-tip ${f.tips.length ? "" : "none"}">${f.tips.length ? `${f.tips.length} selecties` : "Volledige analyse"}</span></button>`).join("")}</section>`).join("") : `<div class="empty">Geen wedstrijden gevonden.</div>`;
  }

  function detailMarkets(fixture) {
    return Object.entries(fixture.probs || {}).filter(([key]) => !key.endsWith("clean_sheet")).map(([key, probability]) => ({ key, probability: Number(probability), odd: selectedOdd(fixture, key) })).sort((a, b) => {
      const groups = ["Fulltime", "Totaal goals", "BTTS", "Team goals", "Eerste helft"];
      return groups.indexOf(marketGroup(a.key)) - groups.indexOf(marketGroup(b.key)) || b.probability - a.probability;
    });
  }

  function renderOddsComparison(fixture, key) {
    const current = (fixture.odds || []).filter(item => item.s === key).sort((a, b) => Number(b.o) - Number(a.o));
    if (!current.length) return `<div class="detail-empty">Geen bookmakerquotes voor deze markt.</div>`;
    const history = fixture.odds_history || [];
    const probability = Number((fixture.probs || {})[key]);
    return `<div class="odds-compare">${current.map((item, index) => {
      const move = history.find(row => row.s === key && row.b === item.b);
      const reference = item.f == null ? 1 / Number(item.o) : Number(item.f);
      const edge = probability - reference;
      const stale = (oddAge(item) ?? 0) > 6;
      return `<div class="odds-compare-row ${index === 0 ? "best" : ""}"><div><b>${esc(item.b)}</b><small>${stale ? "⚠ quote ouder dan 6 uur" : item.f == null ? "ruwe break-even" : `eerlijke markt ${pct(item.f)}`}</small></div><div><span>Open</span><b>${move ? oddText(move.a) : "—"}</b></div><div><span>Nu</span><b>@ ${oddText(item.o)}</b></div><div><span>Waarde</span><b class="${edge > 0 ? "positive" : ""}">${pp(edge)}</b></div>${oddBlock(fixture, { key, p: probability }, true, item.b)}</div>`;
    }).join("")}</div>`;
  }

  function availabilityBlock(fixture) {
    const lineups = fixture.lineups || [];
    const injuries = fixture.injuries || [];
    return `<div class="availability-grid"><section class="detail-section"><div class="detail-section-head"><h3>Opstellingen</h3><span>${lineups.length ? "bevestigd door databron" : "nog niet bevestigd"}</span></div>${lineups.length ? lineups.map(team => `<div class="lineup-team"><b>${esc(teamName(team.team))} · ${esc(team.formation || "formatie n.n.b.")}</b><p>${team.start.map(esc).join(" · ")}</p><small>Bank: ${team.bench.map(esc).join(" · ") || "n.n.b."}</small></div>`).join("") : `<div class="detail-empty">Opstellingen verschijnen doorgaans kort voor de aftrap.</div>`}</section><section class="detail-section"><div class="detail-section-head"><h3>Afwezigheden</h3><span>API-Football</span></div>${injuries.length ? injuries.map(item => `<div class="injury-row"><b>${esc(item.player)}</b><span>${esc(teamName(item.team))} · ${esc(item.reason || item.type || "onbekende reden")}</span></div>`).join("") : `<div class="detail-empty">Geen blessure- of schorsingsmelding beschikbaar.</div>`}</section></div>`;
  }

  function openMatch(fixtureId, marketKey = null) {
    const fixture = DATA.find(item => String(item.id) === String(fixtureId));
    if (!fixture) return;
    const markets = detailMarkets(fixture);
    state.detailMarket = marketKey || bestTip(fixture)?.raw || markets.find(item => item.odd)?.key || "home";
    const active = markets.find(item => item.key === state.detailMarket) || markets[0];
    const grouped = Object.groupBy ? Object.groupBy(markets, item => marketGroup(item.key)) : markets.reduce((all, item) => ((all[marketGroup(item.key)] ||= []).push(item), all), {});
    document.getElementById("match-dialog-title").textContent = `${teamName(fixture.home)} – ${teamName(fixture.away)}`;
    document.getElementById("match-dialog-meta").textContent = `${longDate(fixture.date)} · ${fixture.kickoff || "tijd n.n.b."} · ${fixture.league}`;
    const form = fixture.form || {};
    document.getElementById("match-dialog-body").innerHTML = `<div class="match-overview"><div><span>Verwachte goals</span><strong>${Number(fixture.lambda_home).toFixed(2)} – ${Number(fixture.lambda_away).toFixed(2)}</strong></div><div><span>Thuis / gelijk / uit</span><strong>${pct(fixture.p_home)} · ${pct(fixture.p_draw)} · ${pct(fixture.p_away)}</strong></div><div><span>Databron model</span><strong>${esc(fixture.xg_source || "model")}</strong></div></div><section class="detail-section"><div class="detail-section-head"><h3>Teamvorm</h3><span>laatste ${form.window || 10} competitieduels vóór deze wedstrijd</span></div><div class="team-form-grid"><div><b>${esc(teamName(fixture.home))}</b><span>xG voor ${Number(form.home?.xg_for || 0).toFixed(2)}</span><span>xG tegen ${Number(form.home?.xg_against || 0).toFixed(2)}</span><span>BTTS ${pct(form.home?.btts_rate)}</span></div><div><b>${esc(teamName(fixture.away))}</b><span>xG voor ${Number(form.away?.xg_for || 0).toFixed(2)}</span><span>xG tegen ${Number(form.away?.xg_against || 0).toFixed(2)}</span><span>BTTS ${pct(form.away?.btts_rate)}</span></div></div></section><section class="detail-section"><div class="detail-section-head"><h3>Alle modelmarkten</h3><span>Kies een markt voor bookmakervergelijking</span></div>${Object.entries(grouped).map(([group, items]) => `<div class="market-group"><b>${esc(group)}</b><div class="market-chip-grid">${items.map(item => `<button class="market-chip ${item.key === active.key ? "active" : ""}" type="button" data-detail-market="${esc(item.key)}" data-fixture-id="${esc(fixture.id)}"><span>${esc(marketLabel(item.key, fixture))}</span><strong>${pct(item.probability)}</strong><small>${item.odd ? `@ ${oddText(item.odd.o)}` : "geen odd"}</small></button>`).join("")}</div></div>`).join("")}</section><section class="detail-section"><div class="detail-section-head"><h3>Bookmakers · ${esc(marketLabel(active.key, fixture))}</h3><span>open → actueel · marge verwijderd waar mogelijk</span></div>${renderOddsComparison(fixture, active.key)}</section><section class="detail-section"><div class="detail-section-head"><h3>Spelersvorm</h3><span>schoten op doel uit recente duels</span></div>${playerForm(fixture)}</section>${availabilityBlock(fixture)}`;
    const dialog = document.getElementById("match-dialog");
    if (!dialog.open) dialog.showModal();
  }

  function addBetFromButton(button) {
    const fixture = DATA.find(item => String(item.id) === button.dataset.fixtureId);
    if (!fixture) return;
    const key = button.dataset.selectionKey;
    const found = selectedOdd(fixture, key);
    const probability = Number((fixture.probs || {})[key] ?? fixture.tips.find(tip => tip.raw === key)?.p);
    if (found && Number.isFinite(probability)) window.AftrapAccount?.openFromTip(betPayload(fixture, key, probability, found));
  }

  function renderAll() { renderTips(); renderMatches(); }

  document.addEventListener("DOMContentLoaded", () => {
    document.addEventListener("click", event => {
      const tab = event.target.closest("[data-view]");
      if (tab) {
        state.view = tab.dataset.view;
        document.querySelectorAll(".view-tab").forEach(node => { node.classList.toggle("active", node === tab); node.setAttribute("aria-selected", node === tab ? "true" : "false"); });
        ["tips", "matches", "bets"].forEach(view => document.getElementById(`${view}-view`).classList.toggle("hidden", state.view !== view));
        document.querySelector(".controls").classList.toggle("hidden", state.view === "bets");
        if (state.view === "bets") window.AftrapAccount?.refresh();
      }
      const chip = event.target.closest("[data-date]");
      if (chip) { state.date = chip.dataset.date; state.expanded = false; document.querySelectorAll(".date-chip").forEach(node => node.classList.toggle("active", node === chip)); renderAll(); }
      const open = event.target.closest("[data-open-match]");
      if (open) openMatch(open.dataset.openMatch, open.dataset.openMarket || null);
      const market = event.target.closest("[data-detail-market]");
      if (market) openMatch(market.dataset.fixtureId, market.dataset.detailMarket);
      const add = event.target.closest("[data-add-bet]");
      if (add) addBetFromButton(add);
    });
    document.getElementById("league-select").addEventListener("change", event => { state.league = event.target.value; state.expanded = false; renderAll(); });
    document.getElementById("bookmaker-select").addEventListener("change", event => { state.bookmaker = event.target.value; renderAll(); });
    const minimumOdd = document.getElementById("minimum-odd");
    minimumOdd.addEventListener("input", event => {
      if (!/^\d+(?:[.,]\d{1,2})?$/.test(event.target.value.trim())) return;
      const parsed = parseMinimumOdd(event.target.value);
      if (parsed < 1.01) return;
      state.minimumOdd = parsed;
      state.expanded = false;
      renderTips();
    });
    minimumOdd.addEventListener("blur", event => { event.target.value = oddText(state.minimumOdd); });
    document.getElementById("more-button").addEventListener("click", () => { state.expanded = true; renderTips(); });
    const helpDialog = document.getElementById("help-dialog");
    document.getElementById("open-help").addEventListener("click", () => helpDialog.showModal());
    document.getElementById("close-help").addEventListener("click", () => helpDialog.close());
    document.getElementById("close-match-dialog").addEventListener("click", () => document.getElementById("match-dialog").close());
    [helpDialog, document.getElementById("match-dialog")].forEach(dialog => dialog.addEventListener("click", event => { if (event.target === dialog) dialog.close(); }));
    if (DATA.length) { renderSummary(); renderFilters(); renderAll(); } else document.querySelector(".workspace").innerHTML = `<div class="empty">Er zijn nog geen wedstrijden beschikbaar.</div>`;
  });
})();
