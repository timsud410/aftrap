(() => {
  "use strict";

  const DATA = window.AFTRAP_DATA || [];
  const RECOMMENDATION_HISTORY = window.AFTRAP_RECOMMENDATION_HISTORY || [];
  const OFFICIAL_HISTORY = window.AFTRAP_OFFICIAL_HISTORY || [];
  const BAND = {
    high: { score: 4, label: "sterk", bars: 3 },
    medium: { score: 3, label: "goed onderbouwd", bars: 2 },
    low: { score: 2, label: "voorzichtig", bars: 1 },
    thin_data: { score: 1, label: "beperkte topcompetitiehistorie", bars: 1 },
  };
  const RANKING_MIN_QUALITY = 0.45;
  const DASHBOARD_MIN_QUALITY = 0.62;
  const DASHBOARD_MIN_EFFECTIVE_MATCHES = 10;
  const DASHBOARD_MIN_EV = 0.02;
  const DASHBOARD_MAX_EV = 0.20;
  const DASHBOARD_MAX_MARKET_GAP = 0.15;
  const DASHBOARD_VALUE_RULES = [
    { label: "Winnaar value", empty: "winnaar", minProbability: 0.50, maxOdd: 2.50, matches: key => ["home", "away"].includes(key) },
    { label: "Goals value", empty: "over/under-goals", minProbability: 0.50, maxOdd: 2.50, matches: key => /^(over|under)_/.test(key) },
    { label: "BTTS value", empty: "BTTS", minProbability: 0.48, maxOdd: 2.50, matches: key => ["btts_yes", "btts_no"].includes(key) },
  ];
  const OFFICIAL_CATEGORY_ORDER = ["Winnaar", "Goals", "BTTS"];
  const OFFICIAL_MIN_ODD = 1.30;
  const OFFICIAL_MIN_EV = 0.015;
  const OFFICIAL_ODDS_MAX_AGE = 24;
  const PAGE_SIZE = 20;
  let currentDailyCombo = null;
  const state = { view: "tips", date: "all", officialDate: null, league: "all", market: "all", bookmaker: "auto", sort: "probability", minimumOdd: 1.30, visibleCount: PAGE_SIZE, detailMarket: null };
  const TEAM_DISPLAY = {"Nott'm Forest":"Nottingham Forest","Man United":"Manchester United","Man City":"Manchester City","For Sittard":"Fortuna Sittard","Ath Madrid":"Atlético Madrid","Ath Bilbao":"Athletic Club","Sociedad":"Real Sociedad","Espanol":"Espanyol","Paris SG":"Paris Saint-Germain","M'gladbach":"Borussia M'gladbach","Ein Frankfurt":"Eintracht Frankfurt","FC Koln":"1. FC Köln","Nijmegen":"NEC Nijmegen","Den Haag":"ADO Den Haag","Zwolle":"PEC Zwolle","La Coruna":"Deportivo La Coruña","Santander":"Racing Santander"};
  const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[c]));
  const pct = value => Number.isFinite(Number(value)) ? `${Math.round(Number(value) * 100)}%` : "—";
  const pct1 = value => Number.isFinite(Number(value)) ? `${(Number(value) * 100).toFixed(1).replace(".", ",")}%` : "—";
  const pp = value => `${value > 0 ? "+" : ""}${(value * 100).toFixed(1).replace(".", ",")} pp`;
  const signedPercent = value => `${value > 0 ? "+" : ""}${(value * 100).toFixed(1).replace(".", ",")}%`;
  const evText = value => `${signedPercent(value)} EV`;
  const oddText = value => Number(value).toFixed(2).replace(".", ",");
  const goalText = value => Number(value).toFixed(2).replace(".", ",");
  const teamName = value => TEAM_DISPLAY[value] || value;
  const displayText = value => Object.entries(TEAM_DISPLAY).reduce((text, [raw, nice]) => text.replaceAll(raw, nice), String(value));
  const dateObj = value => new Date(`${value}T12:00:00`);
  const localTodayKey = () => {
    const value = new Date();
    return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`;
  };
  const shortDate = value => new Intl.DateTimeFormat("nl-NL", { weekday: "short", day: "numeric", month: "short" }).format(dateObj(value));
  const longDate = value => new Intl.DateTimeFormat("nl-NL", { weekday: "long", day: "numeric", month: "long" }).format(dateObj(value));
  const fixtureStart = fixture => new Date(`${fixture.date}T${fixture.kickoff || "23:59"}:00`);
  const isPreMatch = fixture => !fixture.score && fixtureStart(fixture).getTime() > Date.now();
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
  const resetRanking = () => { state.visibleCount = PAGE_SIZE; };

  function balancedPercentages(entries, decimals = 1) {
    const scale = 10 ** decimals;
    const target = 100 * scale;
    const raw = entries.map(([key, probability]) => ({ key, raw: Math.max(0, Number(probability) || 0) * target }));
    const floors = raw.map(item => ({ ...item, units: Math.floor(item.raw) }));
    let remainder = target - floors.reduce((sum, item) => sum + item.units, 0);
    floors.sort((a, b) => (b.raw - b.units) - (a.raw - a.units));
    for (let index = 0; index < floors.length && remainder > 0; index += 1, remainder -= 1) floors[index].units += 1;
    return Object.fromEntries(floors.map(item => [item.key, `${(item.units / scale).toFixed(decimals).replace(".", ",")}%`]));
  }

  function marketPercentages(fixture) {
    const probs = fixture.probs || {};
    const display = {
      ...balancedPercentages([["home", probs.home], ["draw", probs.draw], ["away", probs.away]]),
      ...balancedPercentages([["fh_home", probs.fh_home], ["fh_draw", probs.fh_draw], ["fh_away", probs.fh_away]]),
      ...balancedPercentages([["btts_yes", probs.btts_yes], ["btts_no", probs.btts_no]]),
    };
    for (const [key, probability] of Object.entries(probs)) {
      const match = key.match(/^(.*?)(over|under)_([0-9.]+)$/);
      if (!match) continue;
      const prefix = match[1];
      const opposite = `${prefix}${match[2] === "over" ? "under" : "over"}_${match[3]}`;
      if (Object.hasOwn(display, key) || !Object.hasOwn(probs, opposite)) continue;
      Object.assign(display, balancedPercentages([[key, probability], [opposite, probs[opposite]]]));
    }
    return display;
  }

  function selectedOdd(fixture, key, bookmaker = state.bookmaker, maxAge = 6) {
    const available = (fixture.odds || []).filter(odd => odd.s === key && (bookmaker === "best" || odd.b === bookmaker));
    const fresh = available.filter(odd => (oddAge(odd) ?? 0) <= maxAge);
    return fresh.sort((a, b) => Number(b.o) - Number(a.o))[0] || null;
  }

  function oddAge(odd) {
    if (!odd?.u) return Number.POSITIVE_INFINITY;
    const hours = (Date.now() - new Date(odd.u).getTime()) / 3600000;
    return Number.isFinite(hours) ? hours : Number.POSITIVE_INFINITY;
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
    const ranking = filteredFixtures().filter(isPreMatch).flatMap(fixture => Object.entries(fixture.probs || {}).flatMap(([key, rawProbability]) => {
      if (key.endsWith("clean_sheet")) return [];
      if (state.market !== "all" && marketGroup(key) !== state.market) return [];
      const probability = Number(rawProbability);
      const odd = selectedOdd(fixture, key);
      const quality = Number(fixture.quality || 0);
      if (quality < RANKING_MIN_QUALITY || !odd || !Number.isFinite(probability) || Number(odd.o) < state.minimumOdd || oddAge(odd) > 6) return [];
      const breakEven = 1 / Number(odd.o);
      const market = odd.f == null ? null : Number(odd.f);
      return [{
        fixture, key, probability, odd, quality, breakEven, market,
        priceEdge: probability - breakEven,
        marketDifference: market == null ? null : probability - market,
        expectedValue: probability * Number(odd.o) - 1,
        verified: fixture.tips.some(tip => tip.raw === key),
      }];
    }));
    if (state.sort === "edge") return ranking.sort((a, b) => b.expectedValue - a.expectedValue || b.probability - a.probability || Number(b.odd.o) - Number(a.odd.o));
    if (state.sort === "odds") return ranking.sort((a, b) => Number(b.odd.o) - Number(a.odd.o) || b.probability - a.probability || b.expectedValue - a.expectedValue);
    return ranking.sort((a, b) => b.probability - a.probability || b.expectedValue - a.expectedValue || Number(b.odd.o) - Number(a.odd.o));
  }

  function availableOfficialDates() {
    const today = localTodayKey();
    const programmeDates = [...new Set(DATA.map(fixture => fixture.date).filter(day => day >= today))].sort();
    return programmeDates.length ? programmeDates : [today];
  }

  function officialFocusDate() {
    const dates = availableOfficialDates();
    if (state.officialDate && dates.includes(state.officialDate)) return state.officialDate;
    const today = localTodayKey();
    state.officialDate = dates.includes(today) ? today : dates.find(day => day > today) || dates[0];
    return state.officialDate;
  }

  function renderOfficialDateNav() {
    const root = document.getElementById("official-date-nav");
    if (!root) return;
    const active = officialFocusDate();
    root.innerHTML = availableOfficialDates().map(day => {
      const hasPick = OFFICIAL_HISTORY.some(item => item.d === day) || DATA.some(fixture => fixture.date === day && (fixture.official || []).length);
      return `<button class="official-date-chip ${day === active ? "active" : ""} ${hasPick ? "has-pick" : ""}" type="button" data-official-date="${esc(day)}" aria-pressed="${day === active ? "true" : "false"}">${esc(relativeDate(day))}</button>`;
    }).join("");
  }

  function officialSelections(focusDate = officialFocusDate()) {
    const frozen = OFFICIAL_HISTORY.filter(item => item.d === focusDate && item.hit == null).flatMap(item => {
      const fixture = DATA.find(candidate => String(candidate.id) === String(item.id))
        || DATA.find(candidate => candidate.date === item.d && candidate.home === item.h && candidate.away === item.a);
      if (!fixture || !isPreMatch(fixture)) return [];
      const liveOdd = selectedOdd(fixture, item.s, "Bet365", OFFICIAL_ODDS_MAX_AGE);
      const adjustedProbability = Number(item.ap);
      const currentPrice = Number(liveOdd?.o);
      const currentEV = liveOdd && Number.isFinite(currentPrice) ? adjustedProbability * currentPrice - 1 : null;
      const executable = Boolean(liveOdd)
        && (oddAge(liveOdd) ?? Infinity) <= OFFICIAL_ODDS_MAX_AGE
        && currentPrice >= OFFICIAL_MIN_ODD
        && currentPrice <= 2.5
        && currentEV >= OFFICIAL_MIN_EV;
      return [{
        key: item.s,
        category: item.c,
        p: Number(item.p),
        market: Number(item.mp),
        adjusted_p: adjustedProbability,
        ev: currentEV == null ? Number(item.ev) : currentEV,
        odd: liveOdd || { o: Number(item.o), b: item.b || "Bet365" },
        issuedOdd: Number(item.o),
        frozen: true,
        executable,
        fixture,
        probability: Number(item.p),
        adjustedProbability,
        expectedValue: currentEV == null ? Number(item.ev) : currentEV,
        breakEven: 1 / (liveOdd ? currentPrice : Number(item.o)),
      }];
    });
    const selections = frozen.length ? frozen : DATA.filter(fixture => fixture.date === focusDate && isPreMatch(fixture)).flatMap(fixture =>
      (fixture.official || []).map(item => ({
        ...item,
        fixture,
        issuedOdd: Number(item.odd?.o),
        frozen: false,
        executable: true,
        probability: Number(item.p),
        adjustedProbability: Number(item.adjusted_p),
        market: Number(item.market),
        expectedValue: Number(item.ev),
        breakEven: 1 / Number(item.odd?.o),
      })),
    );
    return selections.sort((a, b) => OFFICIAL_CATEGORY_ORDER.indexOf(a.category) - OFFICIAL_CATEGORY_ORDER.indexOf(b.category));
  }

  function renderOfficialBetSuggestions() {
    const root = document.getElementById("official-bet-suggestions");
    if (!root) return;
    const suggestions = availableOfficialDates()
      .flatMap(day => officialSelections(day))
      .sort((a, b) => a.fixture.date.localeCompare(b.fixture.date) || b.expectedValue - a.expectedValue);
    if (!suggestions.length) {
      root.innerHTML = `<div class="official-bets-empty"><b>Nog geen plaatsbare officiële selectie</b><span>De Bet365-prijzen worden dagelijks opnieuw gecontroleerd. Modeltips zonder positieve prijswaarde worden hier bewust niet als bet getoond.</span></div>`;
      return;
    }
    root.innerHTML = suggestions.map(item => {
      const fixture = item.fixture;
      const odd = Number(item.odd?.o);
      const disabled = !item.executable || !Number.isFinite(odd);
      return `<article class="official-bet-suggestion"><div><span>${esc(relativeDate(fixture.date))} · ${esc(fixture.kickoff || "tijd n.n.b.")} · ${esc(item.category)}</span><b>${esc(teamName(fixture.home))} – ${esc(teamName(fixture.away))}</b><strong>${esc(marketLabel(item.key, fixture))}</strong></div><div class="official-bet-price"><span>Conservatieve kans ${pct1(item.adjustedProbability)}</span><b>${Number.isFinite(odd) ? `@${oddText(odd)}` : "—"}</b><em>${signedPercent(item.expectedValue)} EV</em></div><button type="button" ${disabled ? "disabled" : `data-add-bet data-fixture-id="${esc(fixture.id)}" data-selection-key="${esc(item.key)}" data-bookmaker="Bet365" data-model-probability="${item.adjustedProbability}"`}>${disabled ? "Prijs gewijzigd" : "+ Zet in logboek"}</button></article>`;
    }).join("");
  }

  function historicalDailyTop10() {
    const grouped = new Map();
    for (const item of RECOMMENDATION_HISTORY) {
      if (item.snapshot_minimum != null && Math.abs(Number(item.snapshot_minimum) - state.minimumOdd) > 0.0001) continue;
      if (Number(item.q || 0) < RANKING_MIN_QUALITY || Number(item.o) < state.minimumOdd) continue;
      if (!grouped.has(item.d)) grouped.set(item.d, []);
      grouped.get(item.d).push(item);
    }
    return [...grouped.entries()].map(([day, rows]) => {
      const recovered = rows.some(item => item.recovered === true);
      const selected = recovered
        ? rows.sort((a, b) => Number(a.rank) - Number(b.rank)).slice(0, 10)
        : rows.sort((a, b) => Number(b.p) - Number(a.p) || (Number(b.p) * Number(b.o)) - (Number(a.p) * Number(a.o)) || Number(b.o) - Number(a.o)).slice(0, 10);
      const settled = selected.filter(item => item.hit != null);
      const hits = settled.filter(item => item.hit === true).length;
      const profit = settled.reduce((total, item) => total + (item.hit ? Number(item.o) - 1 : -1), 0);
      return { day, selected, settled, hits, profit, roi: settled.length ? profit / settled.length : null, recovered };
    }).filter(day => day.selected.length && day.settled.length === day.selected.length).sort((a, b) => b.day.localeCompare(a.day));
  }

  function renderTop10History() {
    const root = document.getElementById("top10-results");
    const threshold = document.getElementById("top10-threshold");
    if (!root || !threshold) return;
    threshold.textContent = `Bet365 · minimum @${oddText(state.minimumOdd)}`;
    const days = historicalDailyTop10();
    if (!days.length) {
      root.innerHTML = `<div class="top10-empty"><b>De dagelijkse meting start nu</b><span>De aanbevelingen worden vóór de aftrap vastgezet. Zodra de eerste speeldag volledig is afgelopen, verschijnen hier goed/fout, hitrate en flat-stake ROI.</span></div>`;
      return;
    }
    const all = days.flatMap(day => day.settled);
    const totalHits = all.filter(item => item.hit === true).length;
    const totalProfit = days.reduce((total, day) => total + day.profit, 0);
    const summary = `<div class="top10-summary"><div><span>Afgewikkeld</span><b>${all.length}</b></div><div><span>Goed</span><b>${totalHits}</b></div><div><span>Hitrate</span><b>${pct1(totalHits / all.length)}</b></div><div><span>Flat-stake ROI</span><b class="${totalProfit >= 0 ? "positive" : "negative"}">${signedPercent(totalProfit / all.length)}</b></div></div>`;
    const rows = days.slice(0, 7).map(day => `<button class="top10-day" type="button" data-open-top10-archive="${esc(day.day)}" aria-label="Open resultaten van ${esc(longDate(day.day))}"><span>${esc(shortDate(day.day))}${day.recovered ? " · hersteld archief" : ""}</span><b>${day.hits}/${day.settled.length} goed</b><em>${pct1(day.hits / day.settled.length)}</em><strong class="${day.profit >= 0 ? "positive" : "negative"}">${day.roi == null ? "—" : signedPercent(day.roi)} ROI</strong><i>›</i></button>`).join("");
    root.innerHTML = `${summary}<div class="top10-days">${rows}</div><p class="top10-note">Tik op een speeldag om alle goede en foute bets te bekijken. Elke selectie telt als één vaste eenheid inzet. De Top 10 wordt per dag bepaald uit vóór de aftrap opgeslagen kandidaten.</p>`;
  }

  function renderOfficialHistory() {
    const root = document.getElementById("official-history");
    if (!root) return;
    const settled = OFFICIAL_HISTORY.filter(item => item.hit != null);
    const open = OFFICIAL_HISTORY.filter(item => item.hit == null).length;
    const hits = settled.filter(item => item.hit === true).length;
    const profit = settled.reduce((total, item) => total + (item.hit ? Number(item.o) - 1 : -1), 0);
    const roi = settled.length ? profit / settled.length : null;
    root.innerHTML = `<div class="official-history-label"><span>Live meetreeks</span><b>Paper trade</b></div><div class="official-history-metrics"><div><span>Afgewikkeld</span><b>${settled.length}</b></div><div><span>Goed</span><b>${hits}</b></div><div><span>Flat-stake ROI</span><b class="${roi != null && roi < 0 ? "negative" : "positive"}">${roi == null ? "—" : signedPercent(roi)}</b></div><div><span>Nog open</span><b>${open}</b></div></div><p>Deze reeks staat los van de Modelverkenner. <button type="button" data-open-official-archive>Bekijk alle officiële resultaten →</button></p>`;
  }

  function archiveResultRow(item, index, showDate = false) {
    const fixture = { home: item.h, away: item.a };
    const resultClass = item.hit === true ? "good" : item.hit === false ? "bad" : "open";
    const resultLabel = item.hit === true ? "Goed" : item.hit === false ? "Fout" : "Open";
    const returnValue = item.hit == null ? "nog niet gespeeld" : item.hit ? `+${oddText(Number(item.o) - 1)} unit` : "−1,00 unit";
    const meta = [showDate ? shortDate(item.d) : null, item.c || marketGroup(item.s), `@${oddText(item.o)}`, item.b].filter(Boolean).join(" · ");
    return `<div class="archive-row"><span class="archive-rank">#${Number(item.rank || index + 1)}</span><div class="archive-copy"><b>${esc(teamName(item.h))} – ${esc(teamName(item.a))}</b><span>${esc(marketLabel(item.s, fixture))}</span><span>${esc(meta)}</span></div><div class="archive-result ${resultClass}"><b>${resultLabel}</b><span>${esc(returnValue)}</span></div></div>`;
  }

  function showResultArchive({ kicker, title, meta, items, showDate = false }) {
    const dialog = document.getElementById("archive-dialog");
    const settled = items.filter(item => item.hit != null);
    const hits = settled.filter(item => item.hit === true).length;
    const profit = settled.reduce((total, item) => total + (item.hit ? Number(item.o) - 1 : -1), 0);
    const roi = settled.length ? profit / settled.length : null;
    document.getElementById("archive-dialog-kicker").textContent = kicker;
    document.getElementById("archive-dialog-title").textContent = title;
    document.getElementById("archive-dialog-meta").textContent = meta;
    document.getElementById("archive-dialog-body").innerHTML = items.length
      ? `<div class="archive-summary"><div><span>Afgewikkeld</span><b>${settled.length}</b></div><div><span>Goed</span><b>${hits}</b></div><div><span>Flat-stake ROI</span><b>${roi == null ? "—" : signedPercent(roi)}</b></div></div><div class="archive-list">${items.map((item, index) => archiveResultRow(item, index, showDate)).join("")}</div>`
      : `<div class="daily-empty"><b>Nog geen officiële resultaten</b><span>Zodra een vastgezette selectie is gespeeld, verschijnt die hier als goed of fout.</span></div>`;
    dialog.showModal();
    dialog.scrollTop = 0;
  }

  function openTop10Archive(day) {
    const result = historicalDailyTop10().find(item => item.day === day);
    if (!result) return;
    showResultArchive({
      kicker: "Modelverkenner · vastgezette Top 10",
      title: longDate(day),
      meta: `${result.hits} van ${result.settled.length} goed · ${result.roi == null ? "geen ROI" : `${signedPercent(result.roi)} ROI`}`,
      items: result.selected,
    });
  }

  function openOfficialArchive() {
    showResultArchive({
      kicker: "Officiële meetreeks · paper trade",
      title: "Alle officiële resultaten",
      meta: "Vastgezet vóór de aftrap; nooit achteraf vervangen",
      items: [...OFFICIAL_HISTORY].sort((a, b) => b.d.localeCompare(a.d) || Number(b.ev) - Number(a.ev)),
      showDate: true,
    });
  }

  function quickFixtureTips(fixture) {
    const groups = [
      key => ["home", "draw", "away"].includes(key),
      key => /^(over|under)_/.test(key),
      key => ["btts_yes", "btts_no"].includes(key),
    ];
    return groups.flatMap(matches => {
      const choices = Object.entries(fixture.probs || {}).flatMap(([key, rawProbability]) => {
        if (!matches(key)) return [];
        const odd = selectedOdd(fixture, key);
        const probability = Number(rawProbability);
        if (!odd || Number(odd.o) < state.minimumOdd || !Number.isFinite(probability)) return [];
        return [{ key, probability, odd }];
      }).sort((a, b) => b.probability - a.probability || Number(b.odd.o) - Number(a.odd.o));
      return choices.slice(0, 1);
    }).sort((a, b) => b.probability - a.probability).slice(0, 3);
  }

  function scoreFeedFixtures() {
    let pool = DATA.filter(fixture => state.league === "all" || fixture.league === state.league);
    let focusDate = state.date;
    if (focusDate === "all") {
      const today = localTodayKey();
      const dates = [...new Set(pool.map(fixture => fixture.date))].sort();
      focusDate = dates.includes(today) ? today : dates.find(day => day > today) || dates[0];
    }
    return { focusDate, fixtures: pool.filter(fixture => fixture.date === focusDate).sort((a, b) => String(a.kickoff || "99:99").localeCompare(String(b.kickoff || "99:99")) || a.league.localeCompare(b.league)) };
  }

  function renderScoreFeed() {
    const root = document.getElementById("score-feed");
    const dateLabel = document.getElementById("score-feed-date");
    if (!root || !dateLabel) return;
    const { focusDate, fixtures } = scoreFeedFixtures();
    dateLabel.textContent = focusDate ? longDate(focusDate) : "Geen programma";
    root.innerHTML = fixtures.length ? fixtures.map(fixture => {
      const tips = quickFixtureTips(fixture);
      const score = fixture.score ? `<strong class="score-feed-score">${esc(fixture.score)}</strong>` : `<strong class="score-feed-time">${esc(fixture.kickoff || "—")}</strong>`;
      const tipLine = tips.length ? tips.map(item => `<span class="score-tip"><b>${esc(marketLabel(item.key, fixture))}</b><i>${pct1(item.probability)} · @${oddText(item.odd.o)}</i></span>`).join("") : `<span class="score-tip-empty">Geen actuele tip boven @${oddText(state.minimumOdd)}</span>`;
      return `<button class="score-feed-row" type="button" data-open-match="${esc(fixture.id)}"><span class="score-feed-kickoff">${score}<small>${esc(fixture.league)}</small></span><span class="score-feed-main"><b>${esc(teamName(fixture.home))}<i>–</i>${esc(teamName(fixture.away))}</b><span class="score-feed-tips">${tipLine}</span></span><span class="score-feed-open">›</span></button>`;
    }).join("") : `<div class="daily-empty">Geen wedstrijden voor deze datum en competitie.</div>`;
  }

  function renderDailyPicks() {
    const root = document.getElementById("daily-picks");
    const dateLabel = document.getElementById("daily-date");
    if (!root || !dateLabel) return;
    const focusDate = officialFocusDate();
    const focusFixtures = DATA.filter(fixture => fixture.date === focusDate && isPreMatch(fixture));
    const picks = officialSelections();
    dateLabel.textContent = longDate(focusDate);
    currentDailyCombo = null;
    if (!focusFixtures.length) {
      root.innerHTML = `<div class="daily-empty official-empty"><b>Geen komende wedstrijden</b><span>Zodra het programma en actuele Bet365-odds beschikbaar zijn, wordt de officiële selectie opnieuw berekend.</span></div>`;
      return;
    }
    if (!picks.length) {
      root.innerHTML = `<div class="daily-empty official-empty"><b>Geen officiële bet voor deze speeldag</b><span>Geen selectie houdt minimaal 1,5% verwachte waarde over na marktcorrectie, datakwaliteit en signaalvalidatie. In de Modelverkenner hieronder blijven alle percentages zichtbaar.</span></div>`;
      return;
    }
    const singles = picks.map((item, index) => {
      const shortReason = modelReason(item.fixture, item.key, item.probability).split(" Herleiding:")[0];
      const price = Number(item.odd.o);
      const priceAction = item.executable
        ? `<button class="odd-pill value official-odd" type="button" data-add-bet data-fixture-id="${esc(item.fixture.id)}" data-selection-key="${esc(item.key)}" data-bookmaker="Bet365" data-model-probability="${item.adjustedProbability}" title="Conservatieve kans ${pct1(item.adjustedProbability)} · break-even ${pct1(item.breakEven)}"><b>@ ${oddText(price)}</b><small>Bet365 nu · break-even ${pct1(item.breakEven)}</small><i>+ bet</i></button>`
        : `<button class="odd-pill official-odd official-odd-unavailable" type="button" disabled><b>@ ${oddText(item.issuedOdd)}</b><small>Uitgegeven odd · huidige prijs niet meer plaatsbaar</small><i>volgen</i></button>`;
      const evLabel = item.executable ? "EV bij huidige odd" : "EV bij uitgifte";
      return `<article class="daily-pick official-pick"><div class="daily-pick-head"><span>Officiële single ${index + 1} · ${esc(item.category)}</span><b>${item.frozen ? "VASTGEZET" : "MEETFASE"}</b></div><h3>${esc(marketLabel(item.key, item.fixture))}</h3><p class="daily-fixture">${esc(teamName(item.fixture.home))} – ${esc(teamName(item.fixture.away))} · ${esc(item.fixture.kickoff || "tijd n.n.b.")}</p><p class="daily-reason">${esc(shortReason)} Het ruwe modelvoordeel is conservatief teruggeschoven richting de markt.</p><div class="daily-metrics official-metrics"><span>Ruw model <b>${pct1(item.probability)}</b></span><span>Markt zonder marge <b>${pct1(item.market)}</b></span><span>Conservatieve kans <b>${pct1(item.adjustedProbability)}</b></span><span>${evLabel} <b>${signedPercent(item.expectedValue)}</b></span></div>${priceAction}<button class="daily-detail" type="button" data-open-match="${esc(item.fixture.id)}" data-open-market="${esc(item.key)}">Volledige onderbouwing</button></article>`;
    }).join("");
    let combination = "";
    const executablePicks = picks.filter(item => item.executable);
    if (executablePicks.length >= 2) {
      const legs = executablePicks.slice(0, 2);
      const combinedOdd = legs.reduce((total, item) => total * Number(item.odd.o), 1);
      const combinedProbability = legs.reduce((total, item) => total * item.adjustedProbability, 1);
      const combinedFair = legs.every(item => item.market != null) ? legs.reduce((total, item) => total * item.market, 1) : null;
      currentDailyCombo = {
        description: `Officiële paper-tradecombi · ${longDate(focusDate)}`,
        eventDate: focusDate,
        selection: legs.map(item => marketLabel(item.key, item.fixture)).join(" + "),
        bookmaker: "Bet365",
        odds: combinedOdd,
        modelProbability: combinedProbability,
        fairMarketProbability: combinedFair,
        edgePp: combinedFair == null ? null : (combinedProbability - combinedFair) * 100,
        legs: legs.map(item => `${teamName(item.fixture.home)} – ${teamName(item.fixture.away)}: ${marketLabel(item.key, item.fixture)}`),
      };
      const combinedBreakEven = 1 / combinedOdd;
      const combinedEV = combinedProbability * combinedOdd - 1;
      combination = `<article class="daily-combo"><div><span>Optionele combi · hogere variantie</span><h3>${currentDailyCombo.legs.map(esc).join("<br>")}</h3><p>Alleen opgebouwd uit twee officiële singles op verschillende wedstrijden. De getoonde kans gebruikt de conservatief aangepaste kansen.</p></div><div class="daily-combo-numbers"><span>Combi-odd <b>@${oddText(combinedOdd)}</b></span><span>Conservatieve kans <b>${pct1(combinedProbability)}</b></span><span>Break-even <b>${pct1(combinedBreakEven)}</b></span><span>Officiële EV <b>${signedPercent(combinedEV)}</b></span><button type="button" data-add-daily-combo>+ combi bijhouden</button></div></article>`;
    }
    root.innerHTML = `<div class="daily-grid">${singles}</div>${combination}`;
  }

  function expectationOrigin(fixture) {
    const breakdown = fixture.expectation || {};
    const homeFactors = breakdown.home;
    const awayFactors = breakdown.away;
    if (!homeFactors || !awayFactors) return "De doelraming komt uit tijdsgewogen aanval-, defensie- en competitiecijfers.";
    const effective = fixture.effective_matches || {};
    const source = fixture.xg_source === "sot_proxy" ? "schoten-op-doelproxy" : fixture.xg_source === "api_football" ? "API-Football xG" : fixture.xg_source === "understat" ? "Understat xG" : "modeldata";
    const home = teamName(fixture.home);
    const away = teamName(fixture.away);
    return `Herleiding: ${home} ${goalText(fixture.lambda_home)} = basis ${goalText(homeFactors.baseline)} × aanval ${goalText(homeFactors.attack)} × defensiecorrectie ${away} ${goalText(homeFactors.opponent_defence)} × thuisfactor ${goalText(homeFactors.venue)}; ${away} ${goalText(fixture.lambda_away)} = basis ${goalText(awayFactors.baseline)} × aanval ${goalText(awayFactors.attack)} × defensiecorrectie ${home} ${goalText(awayFactors.opponent_defence)}. Deze factoren zijn tijdsgewogen uit ${source} met ${Number(effective.home || 0).toFixed(1).replace(".", ",")} / ${Number(effective.away || 0).toFixed(1).replace(".", ",")} effectieve duels.`;
  }

  function modelReason(fixture, key, probability) {
    const home = Number(fixture.lambda_home);
    const away = Number(fixture.lambda_away);
    const total = home + away;
    const lineLabel = value => String(value).replace(".", ",");
    const resultName = key === "home" ? `${teamName(fixture.home)}-winst` : key === "away" ? `${teamName(fixture.away)}-winst` : "gelijkspel";
    const explain = text => `${text} ${expectationOrigin(fixture)}`;

    if (["home", "draw", "away"].includes(key)) {
      return explain(`Scoremodel: ${goalText(home)}–${goalText(away)} verwachte goals; dat geeft ${pct1(probability)} kans op ${resultName}.`);
    }
    if (key === "home_or_draw") return explain(`Thuiswinst ${pct1(fixture.p_home)} + gelijk ${pct1(fixture.p_draw)} = ${pct1(probability)}.`);
    if (key === "away_or_draw") return explain(`Uitwinst ${pct1(fixture.p_away)} + gelijk ${pct1(fixture.p_draw)} = ${pct1(probability)}.`);
    if (key === "home_or_away") return explain(`Thuiswinst ${pct1(fixture.p_home)} + uitwinst ${pct1(fixture.p_away)} = ${pct1(probability)} zonder gelijkspel.`);

    let match = key.match(/^(over|under)_([0-9.]+)$/);
    if (match) return explain(`Verwachting: ${goalText(total)} goals totaal; daaruit volgt ${pct1(probability)} kans op ${match[1]} ${lineLabel(match[2])}.`);

    match = key.match(/^(home|away)_(over|under)_([0-9.]+)$/);
    if (match) {
      const expected = match[1] === "home" ? home : away;
      const team = teamName(match[1] === "home" ? fixture.home : fixture.away);
      return explain(`Voor ${team} verwacht het model ${goalText(expected)} goals; daarmee ${pct1(probability)} kans op ${match[2]} ${lineLabel(match[3])}.`);
    }

    if (key === "btts_yes" || key === "btts_no") {
      const outcome = key === "btts_yes" ? "beide teams scoren" : "niet beide teams scoren";
      return explain(`Goalverwachting ${goalText(home)}–${goalText(away)}; daarmee ${pct1(probability)} kans dat ${outcome}.`);
    }

    const firstHalfRatio = Number.isFinite(Number(fixture.first_half_ratio)) ? Number(fixture.first_half_ratio) : 0.44;
    const firstHalfHome = home * firstHalfRatio;
    const firstHalfAway = away * firstHalfRatio;
    match = key.match(/^fh_(over|under)_([0-9.]+)$/);
    if (match) return explain(`Voor rust verwacht het model ${goalText(firstHalfHome + firstHalfAway)} goals; daarmee ${pct1(probability)} kans op ${match[1]} ${lineLabel(match[2])}.`);
    if (["fh_home", "fh_draw", "fh_away"].includes(key)) {
      const outcome = key === "fh_home" ? `${teamName(fixture.home)} aan de leiding bij rust` : key === "fh_away" ? `${teamName(fixture.away)} aan de leiding bij rust` : "gelijk bij rust";
      return explain(`Rustmodel: ${goalText(firstHalfHome)}–${goalText(firstHalfAway)} verwachte goals; ${pct1(probability)} kans op ${outcome}.`);
    }
    return explain(`Berekend uit het scoremodel met ${goalText(home)}–${goalText(away)} verwachte goals.`);
  }

  function qualityInfo(fixture) {
    const quality = Number(fixture.quality || 0);
    const effective = fixture.effective_matches || {};
    const minimum = Math.min(Number(effective.home ?? 0), Number(effective.away ?? 0));
    if (quality < RANKING_MIN_QUALITY || minimum < 5) return { label: "beperkte topcompetitiehistorie", className: "thin", minimum };
    if (quality < DASHBOARD_MIN_QUALITY || minimum < DASHBOARD_MIN_EFFECTIVE_MATCHES) return { label: "voorzichtig", className: "caution", minimum };
    return { label: "voldoende historie", className: "ready", minimum };
  }

  function chanceRow(item, index) {
    const { fixture, key, probability, verified } = item;
    const quality = qualityInfo(fixture);
    return `<article class="chance-row"><span class="chance-rank">#${index + 1}</span><div class="chance-fixture"><b>${esc(teamName(fixture.home))} – ${esc(teamName(fixture.away))}</b><span>${esc(shortDate(fixture.date))} · ${esc(fixture.kickoff || "tijd n.n.b.")} · ${esc(fixture.league)}</span></div><div class="chance-selection"><b>${esc(marketLabel(key, fixture))}</b><span class="${verified ? "verified-signal" : ""}">${esc(marketGroup(key))}${verified ? " · historisch getoetst signaal" : " · modelmarkt"}</span><span class="chance-reason">${esc(modelReason(fixture, key, probability))}</span></div><div class="chance-probability"><span>Modelkans</span><strong>${pct1(probability)}</strong><small class="quality-badge ${quality.className}">${esc(quality.label)}</small></div>${oddBlock(fixture, { key, p: probability })}<button class="chance-open" type="button" data-open-match="${esc(fixture.id)}" data-open-market="${esc(key)}">Details</button></article>`;
  }

  function oddBlock(fixture, row, compact = false, bookmaker = null) {
    const found = selectedOdd(fixture, row.key, bookmaker || state.bookmaker);
    if (!found) return `<span class="odd-pill missing">geen actuele odd</span>`;
    const breakEven = 1 / Number(found.o);
    const market = found.f == null ? null : Number(found.f);
    const priceEdge = Number(row.p) - breakEven;
    const expectedValue = Number(row.p) * Number(found.o) - 1;
    const stale = (oddAge(found) ?? 0) > 6;
    const marketTitle = market == null ? "" : ` · markt zonder marge ${pct1(market)}`;
    return `<button class="odd-pill ${expectedValue > 0 ? "value" : ""} ${stale ? "stale" : ""}" type="button" data-add-bet data-fixture-id="${esc(fixture.id)}" data-selection-key="${esc(row.key)}" data-bookmaker="${esc(found.b)}" title="Model ${pct1(row.p)} · break-even ${pct1(breakEven)}${marketTitle} · klik om als bet toe te voegen"><b>@ ${oddText(found.o)}</b><small>${esc(found.b)} · ${evText(expectedValue)} · ${pp(priceEdge)}</small>${compact ? "" : "<i>+ bet</i>"}</button>`;
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
      const detail = found?.f != null ? `Markt zonder marge ${pct1(found.f)}` : found ? `Break-even ${pct1(1 / Number(found.o))}` : "Nog niet aangeboden";
      return `<div class="tip-line ${row.primary ? "primary" : ""}"><span class="tip-kind">${esc(row.kind)}</span><span class="tip-line-name">${esc(row.name)}<small>${esc(detail)}</small></span><strong class="tip-line-value">${pct1(row.p)}</strong>${oddBlock(fixture, row)}</div>`;
    }).join("")}</div>`;
  }

  function playerForm(fixture) {
    const players = fixture.players || [];
    if (!players.length) return `<div class="player-empty">Voor deze wedstrijd is nog geen individuele schotdata beschikbaar.</div>`;
    return `<section class="player-form"><div class="player-form-head"><b>Recente spelersschoten</b><span>maximaal vijf optredens</span></div><div class="player-list">${players.map(player => `<div class="player-row"><div class="player-name"><b>${esc(player.name)}</b><span>${esc(teamName(player.team))} · ${player.n} duels</span></div><div class="player-stat"><b>${Number(player.sot_avg).toFixed(1)}</b><span>SoT gem.</span></div><div class="player-stat"><b>${Number(player.shots_avg).toFixed(1)}</b><span>Schoten</span></div><div class="player-stat"><b>${player.sot_hits}/${player.n}</b><span>1+ SoT</span></div></div>`).join("")}</div><p class="player-form-note">Vormdata, geen apart gekalibreerd bets-signaal.</p></section>`;
  }

  function pickCard(fixture, tip, index) {
    const info = BAND[tip.b] || BAND.low;
    return `<article class="pick-card ${index < 2 ? "featured" : ""}"><div class="pick-meta">${index < 2 ? `<span class="featured-label">● Uitgelicht</span><span>·</span>` : ""}<span>${esc(shortDate(fixture.date))} · ${esc(fixture.kickoff || "tijd n.n.b.")}</span><span class="league-pill">${esc(fixture.league)}</span></div><div class="fixture-name">${esc(teamName(fixture.home))}<span>—</span>${esc(teamName(fixture.away))}</div>${marketRows(fixture, tip)}<p class="stack-note">EV gebruikt de aangeboden odd: modelkans × odd − 1. Alleen een positieve EV krijgt een groene markering.</p><div class="confidence"><span class="confidence-copy">Bewijskracht hoofdselectie: <b>${esc(info.label)}</b></span>${confidenceBars(tip.b)}</div><p class="rationale">${esc(displayText(tip.r))}</p><button class="match-detail-button" type="button" data-open-match="${esc(fixture.id)}">Open volledige wedstrijdanalyse →</button></article>`;
  }

  function renderSummary() {
    document.getElementById("tip-count").textContent = highlighted.length;
    document.getElementById("match-count").textContent = DATA.length;
    const coherent = DATA.every(fixture => {
      const p = fixture.probs || {};
      return [p.home, p.draw, p.away].every(Number.isFinite) && Math.abs(Number(p.home) + Number(p.draw) + Number(p.away) - 1) < 0.002;
    });
    const health = document.getElementById("model-health");
    if (health) {
      health.textContent = coherent ? "✓ Marktensommen gecontroleerd" : "⚠ Controle nodig";
      health.classList.toggle("warning", !coherent);
    }
  }

  function renderDashboardStats(ranking) {
    const trusted = ranking.filter(item => {
      const effective = item.fixture.effective_matches || {};
      return item.quality >= DASHBOARD_MIN_QUALITY && Math.min(Number(effective.home ?? 0), Number(effective.away ?? 0)) >= DASHBOARD_MIN_EFFECTIVE_MATCHES;
    });
    const topChance = [...trusted].sort((a, b) => b.probability - a.probability)[0];
    const isRealisticValue = (item, rule) => {
      const odd = Number(item.odd.o);
      return rule.matches(item.key)
        && item.probability >= rule.minProbability
        && odd <= rule.maxOdd
        && item.expectedValue >= DASHBOARD_MIN_EV
        && item.expectedValue <= DASHBOARD_MAX_EV
        && item.marketDifference != null
        && item.marketDifference >= 0.01
        && item.marketDifference <= DASHBOARD_MAX_MARKET_GAP;
    };
    const usedFixtures = new Set();
    const valueTips = DASHBOARD_VALUE_RULES.map(rule => {
      const candidates = trusted.filter(item => isRealisticValue(item, rule)).sort((a, b) => b.expectedValue - a.expectedValue || b.probability - a.probability);
      const item = candidates.find(candidate => !usedFixtures.has(String(candidate.fixture.id))) || candidates[0] || null;
      if (item) usedFixtures.add(String(item.fixture.id));
      return { rule, item };
    });
    const tipCard = (label, item, value, kind, emptyDetail = null) => item ? {
      label, value, kind, fixture: `${teamName(item.fixture.home)} – ${teamName(item.fixture.away)}`,
      selection: marketLabel(item.key, item.fixture), model: item.probability,
      reference: item.breakEven, referenceLabel: "Break-even", bookmaker: item.odd.b,
      odd: Number(item.odd.o), kickoff: `${shortDate(item.fixture.date)} · ${item.fixture.kickoff || "tijd n.n.b."}`,
      action: item,
    } : { label, value: "—", kind, detail: emptyDetail || `Geen betrouwbare actuele selectie vanaf @${oddText(state.minimumOdd)}` };
    const cards = [
      { ...tipCard("Hoogste modelkans", topChance, topChance ? pct1(topChance.probability) : "—", "probability"), primary: true },
      ...valueTips.map(({ rule, item }) => tipCard(
        rule.label,
        item,
        item ? signedPercent(item.expectedValue) : "—",
        "value",
        `Geen realistische ${rule.empty}-value vanaf @${oddText(state.minimumOdd)}`,
      )),
    ];
    document.getElementById("dashboard-stats").innerHTML = cards.map(card => {
      if (!card.action) return `<article class="dashboard-stat empty-stat"><div class="dashboard-stat-head"><span>${esc(card.label)}</span></div><strong>${esc(card.value)}</strong><small>${esc(card.detail)}</small></article>`;
      const modelWidth = Math.round(card.model * 100);
      const referenceWidth = Math.round(card.reference * 100);
      return `<button class="dashboard-stat ${card.primary ? "primary" : ""} ${esc(card.kind)}" style="--model:${modelWidth}%;--market:${referenceWidth}%" type="button" data-open-match="${esc(card.action.fixture.id)}" data-open-market="${esc(card.action.key)}" aria-label="Open ${esc(card.fixture)}, ${esc(card.selection)}"><div class="dashboard-stat-head"><span>${esc(card.label)}</span><i aria-hidden="true">↗</i></div><div class="dashboard-stat-number"><strong>${esc(card.value)}</strong><small>${card.kind === "value" ? "verwachte waarde" : "modelkans"}</small></div><b class="dashboard-stat-fixture">${esc(card.fixture)}</b><span class="dashboard-stat-selection">${esc(card.selection)} <em>@${oddText(card.odd)}</em></span><div class="dashboard-stat-compare" aria-label="Model ${pct1(card.model)}, break-even ${pct1(card.reference)}"><div><span>Model</span><i><b></b></i><strong>${pct1(card.model)}</strong></div><div><span>${esc(card.referenceLabel)}</span><i><b></b></i><strong>${pct1(card.reference)}</strong></div></div><div class="dashboard-stat-meta"><span>${esc(card.bookmaker)}</span><span>${esc(card.kickoff)}</span></div></button>`;
    }).join("");
  }

  function renderFilters() {
    const dates = [...new Set(DATA.map(f => f.date))].sort();
    document.getElementById("date-chips").innerHTML = [`<button class="date-chip ${state.date === "all" ? "active" : ""}" data-date="all">Alle dagen</button>`, ...dates.map(day => `<button class="date-chip ${state.date === day ? "active" : ""}" data-date="${esc(day)}">${esc(relativeDate(day))}</button>`)].join("");
    const leagues = [...new Set(DATA.map(f => f.league))].sort();
    document.getElementById("league-select").innerHTML = `<option value="all">Alle competities</option>${leagues.map(league => `<option value="${esc(league)}">${esc(league)}</option>`).join("")}`;
    const bookmakers = [...new Set(DATA.flatMap(f => (f.odds || []).map(o => o.b)))].sort();
    const select = document.getElementById("bookmaker-select");
    select.innerHTML = bookmakers.length ? `<option value="best">Beste beschikbare odd</option>${bookmakers.map(name => `<option value="${esc(name)}">${esc(name)}</option>`).join("")}` : `<option>Odds nog niet beschikbaar</option>`;
    select.disabled = !bookmakers.length;
    if (state.bookmaker === "auto") state.bookmaker = bookmakers.find(name => name.toLowerCase().replace(/[^a-z0-9]/g, "") === "bet365") || "best";
    if (bookmakers.length) select.value = state.bookmaker;
  }

  function renderTips() {
    const ranking = rankedSelections();
    const visibleRanking = ranking.slice(0, state.visibleCount);
    const minimum = oddText(state.minimumOdd);
    document.getElementById("tip-result-count").textContent = `${ranking.length} ${ranking.length === 1 ? "selectie" : "selecties"} met voldoende data vanaf @${minimum}`;
    document.getElementById("chance-ranking").innerHTML = ranking.length ? visibleRanking.map(chanceRow).join("") : `<div class="empty">Geen actuele quoteringen vanaf @${minimum} voor deze filters.</div>`;
    const remaining = Math.max(0, ranking.length - visibleRanking.length);
    document.getElementById("more-wrap").classList.toggle("hidden", remaining === 0);
    document.getElementById("more-button").textContent = `Laad volgende ${Math.min(PAGE_SIZE, remaining)} selecties`;
    const sortDescriptions = { probability: "hoogste modelkans", edge: "hoogste verwachte waarde", odds: "hoogste odd" };
    const marketDescription = state.market === "all" ? "Alle actuele markten" : state.market;
    document.getElementById("ranking-description").textContent = `${marketDescription}, gesorteerd op ${sortDescriptions[state.sort]}.`;
    renderDashboardStats(ranking);

    const tips = filteredFixtures().filter(f => f.tips.length && Number(f.quality || 0) >= RANKING_MIN_QUALITY).map(fixture => ({ fixture, tip: bestTip(fixture) })).sort((a, b) => (BAND[b.tip.b]?.score || 0) - (BAND[a.tip.b]?.score || 0) || b.tip.p - a.tip.p || a.fixture.date.localeCompare(b.fixture.date));
    document.getElementById("pick-grid").innerHTML = tips.length ? tips.slice(0, 8).map(({ fixture, tip }, index) => pickCard(fixture, tip, index)).join("") : `<div class="empty">Voor deze filters zijn geen uitgelichte signaalwedstrijden gevonden.</div>`;
  }

  function compactOdd(fixture, key) {
    const odd = selectedOdd(fixture, key);
    return odd ? `@ ${oddText(odd.o)}` : "—";
  }

  function renderMatches() {
    const fixtures = [...filteredFixtures()].sort((a, b) => a.date.localeCompare(b.date) || String(a.kickoff || "99:99").localeCompare(String(b.kickoff || "99:99")) || a.league.localeCompare(b.league));
    const groups = [];
    for (const fixture of fixtures) {
      let group = groups.find(item => item.date === fixture.date);
      if (!group) { group = { date: fixture.date, fixtures: [] }; groups.push(group); }
      group.fixtures.push(fixture);
    }
    document.getElementById("match-result-count").textContent = `${fixtures.length} wedstrijden`;
    document.getElementById("matches").innerHTML = groups.length ? groups.map(group => `<section class="match-day"><div class="match-day-head">${esc(longDate(group.date))}</div>${group.fixtures.map(f => {
      const display = marketPercentages(f);
      return `<button class="match-row" type="button" data-open-match="${esc(f.id)}"><span class="match-time">${esc(f.kickoff || "—")}</span><span><span class="match-teams">${esc(teamName(f.home))}<i>—</i>${esc(teamName(f.away))}</span><span class="match-league">${esc(f.league)}</span><span class="match-odds-line"><span>1 <b>${compactOdd(f, "home")}</b></span><span>X <b>${compactOdd(f, "draw")}</b></span><span>2 <b>${compactOdd(f, "away")}</b></span></span></span><span class="match-model"><span>1 <b>${display.home}</b></span><span>X <b>${display.draw}</b></span><span>2 <b>${display.away}</b></span><span>O2.5 <b>${display["over_2.5"] || pct1(f.p_over25)}</b></span></span><span class="match-tip ${f.tips.length ? "" : "none"}">${f.tips.length ? `${f.tips.length} selecties` : "Volledige analyse"}</span></button>`;
    }).join("")}</section>`).join("") : `<div class="empty">Geen wedstrijden gevonden.</div>`;
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
      const breakEven = 1 / Number(item.o);
      const expectedValue = probability * Number(item.o) - 1;
      const stale = (oddAge(item) ?? 0) > 6;
      return `<div class="odds-compare-row ${index === 0 ? "best" : ""}"><div><b>${esc(item.b)}</b><small>${stale ? "⚠ quote ouder dan 6 uur" : item.f == null ? `break-even ${pct1(breakEven)}` : `markt zonder marge ${pct1(item.f)}`}</small></div><div><span>Open</span><b>${move ? oddText(move.a) : "—"}</b></div><div><span>Nu</span><b>@ ${oddText(item.o)}</b></div><div><span>EV</span><b class="${expectedValue > 0 ? "positive" : ""}">${evText(expectedValue)}</b></div>${oddBlock(fixture, { key, p: probability }, true, item.b)}</div>`;
    }).join("")}</div>`;
  }

  function availabilityBlock(fixture) {
    const lineups = fixture.lineups || [];
    const injuries = fixture.injuries || [];
    return `<div class="availability-grid"><section class="detail-section"><div class="detail-section-head"><h3>Opstellingen</h3><span>${lineups.length ? "bevestigd door databron" : "nog niet bevestigd"}</span></div>${lineups.length ? lineups.map(team => `<div class="lineup-team"><b>${esc(teamName(team.team))} · ${esc(team.formation || "formatie n.n.b.")}</b><p>${team.start.map(esc).join(" · ")}</p><small>Bank: ${team.bench.map(esc).join(" · ") || "n.n.b."}</small></div>`).join("") : `<div class="detail-empty">Opstellingen verschijnen doorgaans kort voor de aftrap.</div>`}</section><section class="detail-section"><div class="detail-section-head"><h3>Afwezigheden</h3><span>API-Football</span></div>${injuries.length ? injuries.map(item => `<div class="injury-row"><b>${esc(item.player)}</b><span>${esc(teamName(item.team))} · ${esc(item.reason || item.type || "onbekende reden")}</span></div>`).join("") : `<div class="detail-empty">Geen blessure- of schorsingsmelding beschikbaar.</div>`}</section></div>`;
  }

  function contextBlock(fixture) {
    const context = fixture.context || {};
    const home = context.home || {};
    const away = context.away || {};
    const h2h = context.h2h_venue || {};
    const metric = value => value == null ? "—" : pct1(value);
    const number = value => value == null ? "—" : Number(value).toFixed(2).replace(".", ",");
    const teamCard = (name, profile, venueLabel) => {
      const season = profile.season || {};
      const venue = profile.venue || {};
      return `<article class="context-team"><div class="context-team-head"><b>${esc(teamName(name))}</b><span>${season.n || 0} competitieduels</span></div><div class="context-metrics"><div><span>Punten per duel</span><b>${number(season.ppg)}</b><small>laatste 5: ${number(season.last5_ppg)}</small></div><div><span>${esc(venueLabel)}</span><b>${number(venue.ppg)}</b><small>${venue.n || 0} duels</small></div><div><span>Achter bij rust</span><b>${metric(season.behind_ht_rate)}</b><small>van bekende ruststanden</small></div><div><span>Teruggekomen</span><b>${metric(season.comeback_rate)}</b><small>na rustachterstand</small></div><div><span>Voorsprong weg</span><b>${metric(season.lead_drop_rate)}</b><small>na rustvoorsprong</small></div><div><span>Goals voor / tegen</span><b>${number(season.gf)} / ${number(season.ga)}</b><small>per duel</small></div></div></article>`;
    };
    const h2hCard = h2h.n ? `<article class="context-h2h"><div><span>Historie in dit stadion</span><b>${h2h.n} eerdere duels</b></div><div><span>Thuis / gelijk / uit</span><b>${metric(h2h.home_win_rate)} · ${metric(h2h.draw_rate)} · ${metric(h2h.away_win_rate)}</b></div><div><span>Goals gemiddeld</span><b>${number(h2h.avg_goals)}</b></div></article>` : `<div class="detail-empty">Geen eerdere onderlinge wedstrijd in dit stadion in de database.</div>`;
    return `<section class="detail-section context-section"><div class="detail-section-head"><h3>Seizoen & wedstrijdverloop</h3><span>alleen wedstrijden vóór deze aftrap</span></div><div class="context-grid">${teamCard(fixture.home, home, "Thuis-PPG")}${teamCard(fixture.away, away, "Uit-PPG")}</div>${h2hCard}<p class="context-note">Deze laag controleert het modelbeeld en maakt de analyse uitlegbaar. Een factor verandert het percentage pas nadat een walk-forwardtest extra voorspellende waarde bewijst; zo voorkomen we dubbeltelling met de bestaande aanval- en defensieratings. Comebacks zijn hier ruststand → eindstand.</p></section>`;
  }

  function openMatch(fixtureId, marketKey = null) {
    const fixture = DATA.find(item => String(item.id) === String(fixtureId));
    if (!fixture) return;
    const markets = detailMarkets(fixture);
    const tipped = bestTip(fixture);
    const tippedWithOdd = tipped && selectedOdd(fixture, tipped.raw) ? tipped.raw : null;
    state.detailMarket = marketKey || tippedWithOdd || markets.find(item => item.odd)?.key || "home";
    const active = markets.find(item => item.key === state.detailMarket) || markets[0];
    const grouped = Object.groupBy ? Object.groupBy(markets, item => marketGroup(item.key)) : markets.reduce((all, item) => ((all[marketGroup(item.key)] ||= []).push(item), all), {});
    document.getElementById("match-dialog-title").textContent = `${teamName(fixture.home)} – ${teamName(fixture.away)}`;
    document.getElementById("match-dialog-meta").textContent = `${longDate(fixture.date)} · ${fixture.kickoff || "tijd n.n.b."} · ${fixture.league}`;
    const form = fixture.form || {};
    const display = marketPercentages(fixture);
    const quality = qualityInfo(fixture);
    const sourceLabel = fixture.xg_source === "sot_proxy" ? "Schoten-op-doelmodel" : fixture.xg_source === "api_football" ? "API-Football xG" : fixture.xg_source || "model";
    const qualityNote = quality.className === "thin"
      ? `<div class="model-warning"><b>Beperkte topcompetitiehistorie</b><span>Deze ploeg heeft nog weinig gewogen duels op dit niveau. Een promovendusprior remt uitschieters; de percentages blijven voorlopig buiten de toplijsten. Minimaal effectief aantal duels: ${quality.minimum.toFixed(1).replace(".", ",")}.</span></div>`
      : `<div class="model-quality"><b>${esc(quality.label)}</b><span>Historie op dit niveau is tijdsgewogen. Minimaal effectief aantal duels: ${quality.minimum.toFixed(1).replace(".", ",")}</span></div>`;
    const effective = fixture.effective_matches || {};
    const historyLabel = `${Number(effective.home || 0).toFixed(1).replace(".", ",")} / ${Number(effective.away || 0).toFixed(1).replace(".", ",")}`;
    document.getElementById("match-dialog-body").innerHTML = `${qualityNote}<div class="match-overview"><div><span>Doelverwachting</span><strong>${Number(fixture.lambda_home).toFixed(2)} – ${Number(fixture.lambda_away).toFixed(2)}</strong></div><div><span>Thuis / gelijk / uit</span><strong>${display.home} · ${display.draw} · ${display.away}</strong></div><div><span>Databron model</span><strong>${esc(sourceLabel)}</strong></div><div><span>Gewogen historie thuis / uit</span><strong>${esc(historyLabel)} duels</strong></div></div><section class="detail-section"><div class="detail-section-head"><h3>Herleiding doelverwachting</h3><span>factor boven 1 verhoogt · onder 1 verlaagt</span></div><p class="expectation-explanation">${esc(expectationOrigin(fixture))}</p></section><section class="detail-section"><div class="detail-section-head"><h3>Teamvorm</h3><span>laatste ${form.window || 10} competitieduels vóór deze wedstrijd</span></div><div class="team-form-grid"><div><b>${esc(teamName(fixture.home))}</b><span>Modelinput voor ${Number(form.home?.xg_for || 0).toFixed(2)}</span><span>Modelinput tegen ${Number(form.home?.xg_against || 0).toFixed(2)}</span><span>BTTS ${pct1(form.home?.btts_rate)}</span></div><div><b>${esc(teamName(fixture.away))}</b><span>Modelinput voor ${Number(form.away?.xg_for || 0).toFixed(2)}</span><span>Modelinput tegen ${Number(form.away?.xg_against || 0).toFixed(2)}</span><span>BTTS ${pct1(form.away?.btts_rate)}</span></div></div></section>${contextBlock(fixture)}<section class="detail-section"><div class="detail-section-head"><h3>Alle modelmarkten</h3><span>Kies een markt voor bookmakervergelijking</span></div>${Object.entries(grouped).map(([group, items]) => `<div class="market-group"><b>${esc(group)}</b><div class="market-chip-grid">${items.map(item => `<button class="market-chip ${item.key === active.key ? "active" : ""}" type="button" data-detail-market="${esc(item.key)}" data-fixture-id="${esc(fixture.id)}"><span>${esc(marketLabel(item.key, fixture))}</span><strong>${display[item.key] || pct1(item.probability)}</strong><small>${item.odd ? `@ ${oddText(item.odd.o)}` : "geen actuele odd"}</small></button>`).join("")}</div></div>`).join("")}</section><section class="detail-section"><div class="detail-section-head"><h3>Bookmakers · ${esc(marketLabel(active.key, fixture))}</h3><span>open → actueel · marge verwijderd waar mogelijk</span></div>${renderOddsComparison(fixture, active.key)}</section><section class="detail-section"><div class="detail-section-head"><h3>Spelersvorm</h3><span>schoten op doel uit recente duels</span></div>${playerForm(fixture)}</section>${availabilityBlock(fixture)}`;
    const dialog = document.getElementById("match-dialog");
    const shouldResetScroll = !dialog.open || dialog.dataset.fixtureId !== String(fixture.id);
    dialog.dataset.fixtureId = String(fixture.id);
    if (!dialog.open) dialog.showModal();
    if (shouldResetScroll) {
      dialog.scrollTop = 0;
      requestAnimationFrame(() => { dialog.scrollTop = 0; });
    }
  }

  function addBetFromButton(button) {
    const fixture = DATA.find(item => String(item.id) === button.dataset.fixtureId);
    if (!fixture) return;
    const key = button.dataset.selectionKey;
    const official = Boolean(button.closest(".official-pick,.official-bet-suggestion"));
    const found = selectedOdd(fixture, key, button.dataset.bookmaker || state.bookmaker, official ? OFFICIAL_ODDS_MAX_AGE : 6);
    if (!found) {
      window.alert("Deze quotering is niet meer actueel. De lijst wordt opnieuw gecontroleerd.");
      renderAll();
      return;
    }
    const probability = Number(button.dataset.modelProbability ?? (fixture.probs || {})[key] ?? fixture.tips.find(tip => tip.raw === key)?.p);
    if (found && Number.isFinite(probability)) window.AftrapAccount?.openFromTip(betPayload(fixture, key, probability, found));
  }

  function addDailyCombo() {
    if (currentDailyCombo) window.AftrapAccount?.openFromCombo(currentDailyCombo);
  }

  function renderAll() { renderTips(); renderMatches(); renderOfficialDateNav(); renderDailyPicks(); renderOfficialBetSuggestions(); renderOfficialHistory(); renderTop10History(); renderScoreFeed(); }

  document.addEventListener("DOMContentLoaded", () => {
    document.addEventListener("click", event => {
      const tab = event.target.closest("[data-view]");
      if (tab) {
        state.view = tab.dataset.view;
        document.querySelectorAll(".view-tab").forEach(node => { node.classList.toggle("active", node === tab); node.setAttribute("aria-selected", node === tab ? "true" : "false"); });
        ["tips", "matches", "bets"].forEach(view => document.getElementById(`${view}-view`).classList.toggle("hidden", state.view !== view));
        document.querySelector(".controls").classList.toggle("hidden", state.view === "bets");
        document.querySelectorAll("[data-ranking-filter]").forEach(node => node.classList.toggle("hidden", state.view !== "tips"));
        if (state.view === "bets") window.AftrapAccount?.refresh();
        const targetView = document.getElementById(`${state.view}-view`);
        window.requestAnimationFrame(() => targetView?.scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" }));
      }
      const chip = event.target.closest("[data-date]");
      if (chip) { state.date = chip.dataset.date; resetRanking(); document.querySelectorAll(".date-chip").forEach(node => node.classList.toggle("active", node === chip)); renderAll(); }
      const officialDate = event.target.closest("[data-official-date]");
      if (officialDate) { state.officialDate = officialDate.dataset.officialDate; renderOfficialDateNav(); renderDailyPicks(); }
      const top10Archive = event.target.closest("[data-open-top10-archive]");
      if (top10Archive) openTop10Archive(top10Archive.dataset.openTop10Archive);
      if (event.target.closest("[data-open-official-archive]")) openOfficialArchive();
      const open = event.target.closest("[data-open-match]");
      if (open) openMatch(open.dataset.openMatch, open.dataset.openMarket || null);
      const market = event.target.closest("[data-detail-market]");
      if (market) openMatch(market.dataset.fixtureId, market.dataset.detailMarket);
      const add = event.target.closest("[data-add-bet]");
      if (add) addBetFromButton(add);
      if (event.target.closest("[data-add-daily-combo]")) addDailyCombo();
    });
    document.getElementById("league-select").addEventListener("change", event => { state.league = event.target.value; resetRanking(); renderAll(); });
    document.getElementById("market-select").addEventListener("change", event => { state.market = event.target.value; resetRanking(); renderTips(); });
    document.getElementById("bookmaker-select").addEventListener("change", event => { state.bookmaker = event.target.value; renderAll(); });
    document.getElementById("sort-select").addEventListener("change", event => { state.sort = event.target.value; resetRanking(); renderTips(); });
    const minimumOdd = document.getElementById("minimum-odd");
    minimumOdd.addEventListener("input", event => {
      if (!/^\d+(?:[.,]\d{1,2})?$/.test(event.target.value.trim())) return;
      const parsed = parseMinimumOdd(event.target.value);
      if (parsed < 1.01) return;
      state.minimumOdd = parsed;
      resetRanking();
      renderTips();
    });
    minimumOdd.addEventListener("blur", event => { event.target.value = oddText(state.minimumOdd); });
    document.getElementById("more-button").addEventListener("click", () => { state.visibleCount += PAGE_SIZE; renderTips(); });
    const helpDialog = document.getElementById("help-dialog");
    document.getElementById("open-help").addEventListener("click", () => helpDialog.showModal());
    document.getElementById("close-help").addEventListener("click", () => helpDialog.close());
    document.getElementById("close-match-dialog").addEventListener("click", () => document.getElementById("match-dialog").close());
    document.getElementById("close-archive-dialog").addEventListener("click", () => document.getElementById("archive-dialog").close());
    [helpDialog, document.getElementById("match-dialog"), document.getElementById("archive-dialog")].forEach(dialog => dialog.addEventListener("click", event => { if (event.target === dialog) dialog.close(); }));
    if (DATA.length) {
      renderSummary(); renderFilters(); renderAll();
      window.setInterval(renderAll, 5 * 60 * 1000);
      document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") renderAll(); });
    } else document.querySelector(".workspace").innerHTML = `<div class="empty">Er zijn nog geen wedstrijden beschikbaar.</div>`;
  });
})();
