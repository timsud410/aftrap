"""
Signaallaag en tipselectie.

Het model uit model.py geeft een kans. Deze module geeft de reden, en kiest
welke 2-3 tips per wedstrijd getoond worden.

Twee regels die de rest van het ontwerp bepalen:

1. Signalen produceren nooit tekst, alleen cijfers plus een template.
   Elk getal in de uiteindelijke onderbouwing is daardoor traceerbaar naar
   `evidence`. Een LLM mag de zinnen vloeiend maken, maar mag geen cijfer
   aandragen.

2. Een signaal weegt mee naar rato van zijn eigen historische hitrate.
   Signalen met minder dan MIN_OBSERVATIONS waarnemingen wegen niet mee.
   Zonder deze administratie bouw je een machine die overtuigend klinkende
   onzin produceert, en dat is erger dan geen tips: het wekt vertrouwen dat
   niet verdiend is.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Sequence

MIN_OBSERVATIONS = 100

# ------------------------------------------------------------
# Correlatieclusters
# ------------------------------------------------------------
# "Over 2.5", "BTTS ja" en "beide teams over 0.5" zijn grotendeels dezelfde
# weddenschap. Drie zulke tips naast elkaar tonen suggereert drie
# onafhankelijke kansen waar er een is -- en verdrievoudigt stilletjes de
# inzet op een enkele uitkomst. Per cluster mag er maximaal een tip door.

CORRELATION_CLUSTERS: dict[str, str] = {
    "over_1.5": "goals_up",
    "over_2.5": "goals_up",
    "over_3.5": "goals_up",
    "btts_yes": "goals_up",
    "under_1.5": "goals_down",
    "under_2.5": "goals_down",
    "under_3.5": "goals_down",
    "btts_no": "goals_down",
    "home_clean_sheet": "goals_down",
    "away_clean_sheet": "goals_down",
    "home_over_0.5": "home_scoring",
    "home_over_1.5": "home_scoring",
    "home_over_2.5": "home_scoring",
    "home_under_0.5": "home_quiet",
    "home_under_1.5": "home_quiet",
    "away_over_0.5": "away_scoring",
    "away_over_1.5": "away_scoring",
    "away_over_2.5": "away_scoring",
    "away_under_0.5": "away_quiet",
    "away_under_1.5": "away_quiet",
    "home": "result",
    "draw": "result",
    "away": "result",
    "home_or_draw": "result",
    "away_or_draw": "result",
    "home_or_away": "result",
    "fh_over_0.5": "first_half",
    "fh_over_1.5": "first_half",
    "fh_under_0.5": "first_half",
    "fh_under_1.5": "first_half",
    "fh_home": "first_half_result",
    "fh_draw": "first_half_result",
    "fh_away": "first_half_result",
}

# Welke clusters elkaar tegenspreken. Gebruikt om te voorkomen dat dezelfde
# wedstrijd tegelijk een overtuigende over- en een overtuigende under-tip
# oplevert.
_OPPOSING_CLUSTER: dict[str, str] = {
    "goals_up": "goals_down",
    "goals_down": "goals_up",
    "home_scoring": "home_quiet",
    "home_quiet": "home_scoring",
    "away_scoring": "away_quiet",
    "away_quiet": "away_scoring",
}


@dataclass(frozen=True)
class Signal:
    key: str
    market: str
    direction: str          # de selectiesleutel waar dit signaal voor pleit
    strength: float         # -1.0 .. +1.0
    evidence: dict          # ruwe cijfers; enige toegestane bron van getallen
    template: str           # bevat {placeholders} die uit evidence komen

    def render(self) -> str:
        return self.template.format(**self.evidence)


@dataclass
class MatchContext:
    """Alles wat de signalen nodig hebben, al opgehaald uit de database."""

    home_team: str
    away_team: str
    lambda_home: float
    lambda_away: float
    league_avg_goals: float
    # voortschrijdende gemiddelden over het gekozen venster
    home_xg_for: float
    home_xg_against: float
    away_xg_for: float
    away_xg_against: float
    home_goals_against: float       # werkelijk, voor keeper-overperformance
    away_goals_against: float
    home_btts_rate: float           # aandeel wedstrijden met BTTS, thuis
    away_btts_rate: float
    home_fh_xg: float
    away_fh_xg: float
    rest_days_home: int
    rest_days_away: int
    european_match_home: bool
    european_match_away: bool
    missing_xg_share_home: float    # aandeel team-xG dat ontbreekt door blessures
    missing_xg_share_away: float
    matchday: int
    window: int = 10


SignalFn = Callable[[MatchContext], Signal | None]
REGISTRY: dict[str, SignalFn] = {}


def signal(fn: SignalFn) -> SignalFn:
    REGISTRY[fn.__name__] = fn
    return fn


# ------------------------------------------------------------
# Over/under en BTTS
# ------------------------------------------------------------


@signal
def combined_xg(ctx: MatchContext) -> Signal | None:
    """De sterkste enkele voorspeller voor totaalmarkten."""
    total = ctx.lambda_home + ctx.lambda_away
    diff = total - ctx.league_avg_goals
    if abs(diff) < 0.30:
        return None
    return Signal(
        key="combined_xg",
        market="over_under",
        direction="over_2.5" if diff > 0 else "under_2.5",
        strength=max(-1.0, min(1.0, diff / 1.2)),
        evidence={
            "total_xg": round(total, 2),
            "league_avg": round(ctx.league_avg_goals, 2),
            "diff": round(abs(diff), 2),
        },
        template=(
            "gecombineerde xG-verwachting {total_xg}, tegen een "
            "competitiegemiddelde van {league_avg}"
        ),
    )


@signal
def defensive_frailty(ctx: MatchContext) -> Signal | None:
    """Beide verdedigingen boven het competitiegemiddelde aan xG tegen."""
    avg_side = ctx.league_avg_goals / 2
    h, a = ctx.home_xg_against, ctx.away_xg_against
    if h <= avg_side or a <= avg_side:
        return None
    excess = (h - avg_side) + (a - avg_side)
    return Signal(
        key="defensive_frailty",
        market="over_under",
        direction="over_2.5",
        strength=min(1.0, excess / 0.9),
        evidence={
            "home_team": ctx.home_team,
            "away_team": ctx.away_team,
            "home_xga": round(h, 2),
            "away_xga": round(a, 2),
            "window": ctx.window,
        },
        template=(
            "beide verdedigingen geven bovengemiddeld weg over de laatste "
            "{window} duels: {home_team} {home_xga} xG tegen, {away_team} {away_xga}"
        ),
    )


@signal
def keeper_overperformance(ctx: MatchContext) -> Signal | None:
    """Een keeper die structureel onder zijn xG tegen blijft, keert doorgaans
    terug naar het gemiddelde. Dit is een van de weinige signalen met een
    aantoonbaar corrigerend mechanisme erachter."""
    gap_home = ctx.home_xg_against - ctx.home_goals_against
    gap_away = ctx.away_xg_against - ctx.away_goals_against
    gap = max(gap_home, gap_away)
    if gap < 0.35:
        return None
    team = ctx.home_team if gap_home >= gap_away else ctx.away_team
    return Signal(
        key="keeper_overperformance",
        market="over_under",
        direction="over_2.5",
        strength=min(0.7, gap / 0.8),
        evidence={
            "team": team,
            "gap": round(gap, 2),
            "window": ctx.window,
        },
        template=(
            "{team} incasseert {gap} doelpunt per wedstrijd minder dan de "
            "kwaliteit van de toegestane kansen doet verwachten over "
            "{window} duels; dat loopt doorgaans terug"
        ),
    )


@signal
def btts_rate(ctx: MatchContext) -> Signal | None:
    rate = (ctx.home_btts_rate + ctx.away_btts_rate) / 2
    if 0.40 < rate < 0.65:
        return None
    return Signal(
        key="btts_rate",
        market="btts",
        direction="btts_yes" if rate >= 0.65 else "btts_no",
        strength=min(1.0, abs(rate - 0.525) / 0.30),
        evidence={
            "rate_pct": round(rate * 100),
            "window": ctx.window,
            "home_team": ctx.home_team,
            "away_team": ctx.away_team,
        },
        template=(
            "in {rate_pct}% van de laatste {window} duels van {home_team} en "
            "{away_team} scoorden beide ploegen"
        ),
    )


# ------------------------------------------------------------
# Team totals
# ------------------------------------------------------------


@signal
def attack_defence_mismatch(ctx: MatchContext) -> Signal | None:
    """Sterke aanval tegen zwakke verdediging, per kant apart."""
    avg_side = ctx.league_avg_goals / 2
    home_edge = ctx.lambda_home - avg_side
    away_edge = ctx.lambda_away - avg_side
    if max(home_edge, away_edge) < 0.45:
        return None
    if home_edge >= away_edge:
        team, edge, direction = ctx.home_team, home_edge, "home_over_1.5"
        xg_for, xga = ctx.home_xg_for, ctx.away_xg_against
    else:
        team, edge, direction = ctx.away_team, away_edge, "away_over_1.5"
        xg_for, xga = ctx.away_xg_for, ctx.home_xg_against
    return Signal(
        key="attack_defence_mismatch",
        market="team_total",
        direction=direction,
        strength=min(1.0, edge / 0.9),
        evidence={
            "team": team,
            "xg_for": round(xg_for, 2),
            "opp_xga": round(xga, 2),
            "expected": round(ctx.lambda_home if home_edge >= away_edge else ctx.lambda_away, 2),
        },
        template=(
            "{team} produceert {xg_for} xG per duel tegen een verdediging die "
            "{opp_xga} weggeeft; modelverwachting {expected}"
        ),
    )


@signal
def key_attacker_absent(ctx: MatchContext) -> Signal | None:
    """Blessures wegen alleen als de ontbrekende speler een substantieel
    aandeel in de teamproductie had."""
    share = max(ctx.missing_xg_share_home, ctx.missing_xg_share_away)
    if share < 0.18:
        return None
    home_worst = ctx.missing_xg_share_home >= ctx.missing_xg_share_away
    return Signal(
        key="key_attacker_absent",
        market="team_total",
        direction="home_under_1.5" if home_worst else "away_under_1.5",
        strength=-min(1.0, share / 0.40),
        evidence={
            "team": ctx.home_team if home_worst else ctx.away_team,
            "share_pct": round(share * 100),
        },
        template="{team} mist spelers die samen {share_pct}% van de team-xG leverden",
    )


# ------------------------------------------------------------
# Eerste helft
# ------------------------------------------------------------


@signal
def first_half_tempo(ctx: MatchContext) -> Signal | None:
    total_fh = ctx.home_fh_xg + ctx.away_fh_xg
    expected_fh = ctx.league_avg_goals * 0.44
    diff = total_fh - expected_fh
    if abs(diff) < 0.22:
        return None
    return Signal(
        key="first_half_tempo",
        market="first_half",
        direction="fh_over_1.5" if diff > 0 else "fh_under_1.5",
        strength=max(-1.0, min(1.0, diff / 0.5)),
        evidence={
            "fh_xg": round(total_fh, 2),
            "fh_avg": round(expected_fh, 2),
        },
        template=(
            "samen {fh_xg} xG voor rust, tegen een competitiegemiddelde "
            "van {fh_avg} in de eerste helft"
        ),
    )


# ------------------------------------------------------------
# Einduitslag
# ------------------------------------------------------------


@signal
def form_vs_underlying(ctx: MatchContext) -> Signal | None:
    """Een team dat op uitslagen beter presteert dan op onderliggende cijfers
    valt doorgaans terug, en andersom. Dit is precies het signaal dat de
    publieke opinie mist, omdat die naar de ranglijst kijkt."""
    home_gap = ctx.home_xg_for - ctx.home_xg_against
    away_gap = ctx.away_xg_for - ctx.away_xg_against
    delta = home_gap - away_gap
    if abs(delta) < 0.45:
        return None
    return Signal(
        key="form_vs_underlying",
        market="match_result",
        direction="home" if delta > 0 else "away",
        strength=max(-1.0, min(1.0, delta / 1.2)),
        evidence={
            "leader": ctx.home_team if delta > 0 else ctx.away_team,
            "home_team": ctx.home_team,
            "away_team": ctx.away_team,
            "home_diff": round(home_gap, 2),
            "away_diff": round(away_gap, 2),
        },
        template=(
            "op onderliggende cijfers staat {leader} duidelijk voor: "
            "xG-saldo {home_diff} voor {home_team} tegen {away_diff} voor {away_team}"
        ),
    )


@signal
def rest_advantage(ctx: MatchContext) -> Signal | None:
    """Europees voetbal binnen 72 uur weegt zwaarder dan rustdagen alleen."""
    delta = ctx.rest_days_home - ctx.rest_days_away
    euro_penalty = (1 if ctx.european_match_away else 0) - (
        1 if ctx.european_match_home else 0
    )
    score = delta / 3.0 + euro_penalty * 0.5
    if abs(score) < 0.5:
        return None
    return Signal(
        key="rest_advantage",
        market="match_result",
        direction="home" if score > 0 else "away",
        strength=max(-0.6, min(0.6, score / 1.5)),
        evidence={
            "home_team": ctx.home_team,
            "away_team": ctx.away_team,
            "home_rest": ctx.rest_days_home,
            "away_rest": ctx.rest_days_away,
        },
        template=(
            "{home_team} had {home_rest} dagen rust, {away_team} {away_rest}"
        ),
    )


def collect_signals(ctx: MatchContext) -> list[Signal]:
    out: list[Signal] = []
    for fn in REGISTRY.values():
        s = fn(ctx)
        if s is not None:
            out.append(s)
    return out


# ------------------------------------------------------------
# Tipselectie
# ------------------------------------------------------------


@dataclass
class SignalPerformance:
    """Uit de view signal_performance. Hier zit de eerlijkheid."""

    hit_rate: float
    n: int

    # Een hitrate van 60% is voor deze markten al uitzonderlijk goed; de
    # schaal loopt daarom van 50% (waardeloos) tot EXCELLENT_HIT_RATE
    # (maximaal gewicht). Delen door 0.5 zou elk signaal een verwaarloosbaar
    # gewicht geven en de ranking effectief uitschakelen.
    EXCELLENT_HIT_RATE = 0.60

    @property
    def weight(self) -> float:
        if self.n < MIN_OBSERVATIONS:
            return 0.0
        edge = self.hit_rate - 0.5
        return max(0.0, min(1.0, edge / (self.EXCELLENT_HIT_RATE - 0.5)))


@dataclass
class Tip:
    selection: str
    market: str
    model_prob: float
    score: float
    confidence_band: str
    correlation_cluster: str
    rationale: str
    signals: list[Signal] = field(default_factory=list)


def build_tips(
    probs: dict[str, float],
    signals: Sequence[Signal],
    data_quality: float,
    performance: dict[str, SignalPerformance],
    max_tips: int = 3,
    min_score: float = 0.10,
) -> list[Tip]:
    """Rangschik kandidaten en kies maximaal een tip per correlatiecluster.

    score = modelvertrouwen x signaalsteun x datakwaliteit

    Zonder odds in de formule meet dit "hoe waarschijnlijk", niet "hoe
    rendabel". Dat is een bewuste keuze: de tracker maakt achteraf zichtbaar
    of de tips ook geld opleveren.
    """
    from model import confidence_band as _band

    by_selection: dict[str, list[Signal]] = {}
    for s in signals:
        by_selection.setdefault(s.direction, []).append(s)

    candidates: list[Tip] = []
    for selection, sigs in by_selection.items():
        prob = probs.get(selection)
        if prob is None:
            continue

        model_confidence = min(1.0, abs(prob - 0.5) / 0.30)

        support = 0.0
        for s in sigs:
            perf = performance.get(s.key)
            w = perf.weight if perf else 0.0
            support += s.strength * w

        # Signalen die voor de TEGENGESTELDE kant van hetzelfde cluster
        # pleiten trekken de steun omlaag. Zonder deze aftrek kan een
        # wedstrijd tegelijk een sterke over-tip en een sterke under-tip
        # opleveren, en zien beide er even overtuigend uit.
        cluster = CORRELATION_CLUSTERS.get(selection, selection)
        opposite = _OPPOSING_CLUSTER.get(cluster)
        if opposite:
            for s in signals:
                if CORRELATION_CLUSTERS.get(s.direction) != opposite:
                    continue
                perf = performance.get(s.key)
                w = perf.weight if perf else 0.0
                support -= abs(s.strength) * w

        support = max(0.0, min(1.0, support))

        score = model_confidence * support * data_quality
        if score < min_score:
            continue

        used = sorted(
            (s for s in sigs if (performance.get(s.key) or SignalPerformance(0, 0)).weight > 0),
            key=lambda s: abs(s.strength),
            reverse=True,
        )[:2]
        if not used:
            continue

        candidates.append(
            Tip(
                selection=selection,
                market=sigs[0].market,
                model_prob=prob,
                score=score,
                confidence_band=_band(prob, data_quality),
                correlation_cluster=CORRELATION_CLUSTERS.get(selection, selection),
                rationale=" · ".join(s.render() for s in used),
                signals=used,
            )
        )

    candidates.sort(key=lambda t: t.score, reverse=True)

    chosen: list[Tip] = []
    seen_clusters: set[str] = set()
    for tip in candidates:
        if tip.correlation_cluster in seen_clusters:
            continue
        seen_clusters.add(tip.correlation_cluster)
        chosen.append(tip)
        if len(chosen) == max_tips:
            break
    return chosen
