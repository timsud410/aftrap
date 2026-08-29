"""
Modelkern: teamsterktes uit xG, scorematrix met Dixon-Coles-correctie,
en alle marktkansen die daaruit volgen.

Dit is het deel waar subtiele fouten stil doorwerken naar verkeerde tips,
dus het is expres compact en zijn de belangrijkste invarianten getest.

Ontwerpkeuzes, met reden:

1. Fitten op xG, niet op doelpunten. De xG-ratio is na ongeveer 5 tot 8
   wedstrijden even voorspellend voor toekomstige resultaten als de
   doelpuntenratio na een half seizoen (IJtsma 2015; American Soccer
   Analysis Replication Project 2022 -- die laatste vindt overigens een
   kleinere voorsprong dan het oorspronkelijke onderzoek, dus behandel dit
   als richting en niet als vaste factor).

2. Quasi-Poisson in plaats van Poisson. De response is continu (xG), dus
   de discrete Poisson-variantie-aanname klopt niet. De log-link blijft
   geldig; alleen de dispersie wordt vrijgelaten.

3. Exponentiele tijdsweging. Een wedstrijd van 18 maanden geleden zegt
   weinig over de huidige selectie. Zonder weging reageert het model veel
   te traag op transferzomers en trainerswissels.

4. Dixon-Coles-correctie bij het bouwen van de scorematrix, gefit op
   WERKELIJKE doelpunten. Onafhankelijke Poissons onderschatten 0-0 en 1-1
   systematisch, en dat vertekent precies de markten die we aanbieden
   (under 2.5, BTTS nee).

5. Alle markten uit dezelfde matrix. Zo kan het model nooit tegelijk
   "over 2.5" en "team total under 0.5" aanraden.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Iterable, Sequence

import numpy as np
from scipy.optimize import minimize_scalar
from scipy.stats import poisson

# ============================================================
# 1. Teamsterktes
# ============================================================


@dataclass(frozen=True)
class MatchObservation:
    """Een gespeelde wedstrijd, zoals hij het model in gaat."""

    match_date: date
    home_team: str
    away_team: str
    home_xg: float
    away_xg: float
    # werkelijke doelpunten: niet gebruikt voor de sterktes, wel voor rho
    home_goals: int | None = None
    away_goals: int | None = None


@dataclass
class TeamRatings:
    """Resultaat van de fit. attack hoger = meer produceren,
    defence hoger = minder weggeven."""

    attack: dict[str, float]
    defence: dict[str, float]
    intercept: float
    home_advantage: float
    rho: float
    effective_matches: dict[str, float] = field(default_factory=dict)
    dispersion: float = 1.0

    def expected_goals(self, home_team: str, away_team: str) -> tuple[float, float]:
        """lambda (thuis) en mu (uit) voor een aanstaande wedstrijd."""
        for team in (home_team, away_team):
            if team not in self.attack:
                raise KeyError(
                    f"Onbekend team {team!r}. Promovendi moeten expliciet "
                    f"geinitialiseerd worden (zie initialise_promoted)."
                )
        lam = np.exp(
            self.intercept
            + self.attack[home_team]
            - self.defence[away_team]
            + self.home_advantage
        )
        mu = np.exp(self.intercept + self.attack[away_team] - self.defence[home_team])
        return float(lam), float(mu)


#: Standaard tijdsverval PER DAG.
#:
#: Let op de eenheid -- dit is de klassieke valkuil bij Dixon-Coles.
#: Dixon & Coles (1997) rapporteren xi = 0.0065 per HALVE WEEK. Wie dat
#: getal per dag toepast, laat het model 3,5x te snel vergeten: een
#: halfwaardetijd van 107 dagen in plaats van 373. Herschattingen op
#: dagbasis (opisthokonta, top-competities 2005-2014) komen uit op
#: 0.0018-0.0023 per dag voor Engeland, Duitsland, Nederland en Frankrijk.
#:
#: 0.0025 per dag geeft een halfwaardetijd van ~277 dagen. Kalibreer per
#: competitie binnen 0.0015-0.0050 op de log loss van vooruitvoorspellingen.
DEFAULT_XI_PER_DAY = 0.0025

#: Dixon-Coles rho: empirisch aggregaat over 44.000 wedstrijden in de zes
#: competities (2005-2026). Per competitie loopt het van -0.12 (Bundesliga)
#: tot -0.03 (La Liga); kalibreer dus per competitie.
DEFAULT_RHO = -0.074
RHO_BOUNDS = (-0.20, 0.05)

#: Aandeel doelpunten dat voor rust valt. Empirisch 43,4% (Serie A) tot
#: 44,7% (Bundesliga) over 44.000 wedstrijden; 0.44 is een goede default.
DEFAULT_FIRST_HALF_RATIO = 0.44

#: Tot dit aantal tijdgewogen wedstrijden blijft de empirische
#: promovendusprior gedeeltelijk actief. Bij tien effectieve wedstrijden
#: krijgt de eigen fit het volledige gewicht.
PROMOTED_PRIOR_FULL_WEIGHT_MATCHES = 10.0


def time_weights(
    match_dates: Sequence[date], reference: date, xi: float = DEFAULT_XI_PER_DAY
) -> np.ndarray:
    """Exponentieel verval: w(t) = exp(-xi * dagen_geleden).

    xi is PER DAG. Zie DEFAULT_XI_PER_DAY voor waarom dat onderscheid ertoe
    doet.
    """
    days = np.array([(reference - d).days for d in match_dates], dtype=float)
    if (days < 0).any():
        raise ValueError(
            "Wedstrijd na de referentiedatum in de trainingsset. Dit is "
            "datalekkage en maakt elke backtest waardeloos."
        )
    return np.exp(-xi * days)


def _build_design(
    observations: Sequence[MatchObservation], teams: list[str]
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Bouwt de designmatrix met sum-to-zero-codering.

    Zonder die restrictie is het model niet identificeerbaar: je kunt bij
    elke attack een constante optellen en bij elke defence dezelfde
    constante, zonder dat de voorspellingen veranderen. Het laatste team
    krijgt daarom -1 in alle kolommen, zodat sum(attack) = 0.

    Elke wedstrijd levert twee rijen: een per team.
    """
    n_teams = len(teams)
    idx = {team: i for i, team in enumerate(teams)}
    k = n_teams - 1  # vrije parameters per effect

    rows: list[np.ndarray] = []
    y: list[float] = []
    row_match: list[int] = []

    def effect(team_idx: int) -> np.ndarray:
        """Sum-to-zero-codering voor een team."""
        v = np.zeros(k)
        if team_idx < k:
            v[team_idx] = 1.0
        else:
            v[:] = -1.0
        return v

    for m_i, obs in enumerate(observations):
        h, a = idx[obs.home_team], idx[obs.away_team]

        # rij 1: thuisploeg produceert
        r = np.zeros(2 * k + 2)
        r[0] = 1.0                          # intercept
        r[1 : 1 + k] = effect(h)            # attack thuis
        r[1 + k : 1 + 2 * k] = -effect(a)   # defence uit (negatief)
        r[-1] = 1.0                         # thuisvoordeel
        rows.append(r)
        y.append(obs.home_xg)
        row_match.append(m_i)

        # rij 2: uitploeg produceert
        r = np.zeros(2 * k + 2)
        r[0] = 1.0
        r[1 : 1 + k] = effect(a)
        r[1 + k : 1 + 2 * k] = -effect(h)
        r[-1] = 0.0
        rows.append(r)
        y.append(obs.away_xg)
        row_match.append(m_i)

    return np.array(rows), np.array(y), np.array(row_match)


def fit_ratings(
    observations: Sequence[MatchObservation],
    reference: date,
    xi: float = DEFAULT_XI_PER_DAY,
    rho: float | None = None,
    max_iter: int = 100,
    tol: float = 1e-8,
) -> TeamRatings:
    """Time-weighted quasi-Poisson fit via IRLS.

    Handmatige IRLS in plaats van statsmodels, zodat er geen twijfel is
    over hoe de gewichten precies meelopen en de module geen zware
    dependency nodig heeft.
    """
    if not observations:
        raise ValueError("Geen wedstrijden om op te fitten.")

    teams = sorted(
        {o.home_team for o in observations} | {o.away_team for o in observations}
    )
    if len(teams) < 2:
        raise ValueError("Minimaal twee teams nodig.")

    X, y, row_match = _build_design(observations, teams)

    w_match = time_weights([o.match_date for o in observations], reference, xi)
    w = w_match[row_match]  # elke wedstrijd levert twee rijen, zelfde gewicht

    if (y < 0).any():
        raise ValueError("Negatieve xG in de invoer.")

    # IRLS voor een Poisson-GLM met log-link en observatiegewichten
    beta = np.zeros(X.shape[1])
    beta[0] = np.log(max(np.average(y, weights=w), 1e-3))

    for _ in range(max_iter):
        eta = np.clip(X @ beta, -10.0, 10.0)  # voorkomt overflow bij extreme fits
        mu = np.exp(eta)
        # werkende response en gewichten voor de log-link
        z = eta + (y - mu) / mu
        W = w * mu
        XtW = X.T * W
        # kleine ridge-term houdt de matrix inverteerbaar bij weinig data
        A = XtW @ X + 1e-8 * np.eye(X.shape[1])
        b = XtW @ z
        beta_new = np.linalg.solve(A, b)
        if np.max(np.abs(beta_new - beta)) < tol:
            beta = beta_new
            break
        beta = beta_new

    k = len(teams) - 1
    intercept = float(beta[0])
    att_free = beta[1 : 1 + k]
    def_free = beta[1 + k : 1 + 2 * k]
    home_adv = float(beta[-1])

    attack = {t: float(att_free[i]) for i, t in enumerate(teams[:k])}
    attack[teams[k]] = float(-att_free.sum())
    defence = {t: float(def_free[i]) for i, t in enumerate(teams[:k])}
    defence[teams[k]] = float(-def_free.sum())

    # Pearson-dispersie: >1 betekent overdispersie, en dat is bij xG normaal
    eta = np.clip(X @ beta, -10.0, 10.0)
    mu = np.exp(eta)
    dof = max(len(y) - len(beta), 1)
    dispersion = float(np.sum(w * (y - mu) ** 2 / mu) / dof)

    eff: dict[str, float] = {t: 0.0 for t in teams}
    for obs, weight in zip(observations, w_match):
        eff[obs.home_team] += float(weight)
        eff[obs.away_team] += float(weight)

    ratings = TeamRatings(
        attack=attack,
        defence=defence,
        intercept=intercept,
        home_advantage=home_adv,
        rho=0.0,
        effective_matches=eff,
        dispersion=dispersion,
    )

    ratings.rho = rho if rho is not None else fit_rho(observations, ratings)
    return ratings


def fit_rho(observations: Sequence[MatchObservation], ratings: TeamRatings) -> float:
    """Fit de Dixon-Coles-correlatieparameter op WERKELIJKE doelpunten.

    Niet op xG: de correctie bestaat juist omdat de uitslagenverdeling
    afwijkt van onafhankelijke Poissons rond 0-0 en 1-1.

    Empirisch over 44.000 wedstrijden in de zes competities (2005-2026) ligt
    rho tussen -0.12 (Bundesliga) en -0.03 (La Liga), met -0.074 als
    aggregaat. De optimizerbandbreedte loopt ruimer door tot +0.05, zodat de
    schatting niet tegen een harde grens aanloopt bij competities of periodes
    waar het effect vrijwel verdwijnt.
    """
    scored = [
        o for o in observations if o.home_goals is not None and o.away_goals is not None
    ]
    if len(scored) < 50:
        # te weinig data voor een betrouwbare fit; val terug op het
        # empirische aggregaat in plaats van ruis te fitten
        return DEFAULT_RHO

    lams, mus, xs, ys = [], [], [], []
    for o in scored:
        lam, mu = ratings.expected_goals(o.home_team, o.away_team)
        lams.append(lam)
        mus.append(mu)
        xs.append(o.home_goals)
        ys.append(o.away_goals)

    lams = np.array(lams)
    mus = np.array(mus)
    xs = np.array(xs)
    ys = np.array(ys)

    def neg_loglik(rho: float) -> float:
        tau = dixon_coles_tau(xs, ys, lams, mus, rho)
        if (tau <= 0).any():
            return 1e10
        ll = np.log(tau) + poisson.logpmf(xs, lams) + poisson.logpmf(ys, mus)
        return float(-ll.sum())

    res = minimize_scalar(neg_loglik, bounds=RHO_BOUNDS, method="bounded")
    return float(res.x) if res.success else DEFAULT_RHO


def initialise_promoted(
    ratings: TeamRatings,
    promoted_teams: Iterable[str],
    attack_factor: float = 0.79,
    defence_factor: float = 0.845,
    full_weight_matches: float = PROMOTED_PRIOR_FULL_WEIGHT_MATCHES,
) -> TeamRatings:
    """Pool onervaren teams geleidelijk met de promovendusprior.

    Een promovendus heeft geen historie op dit niveau. De defaults zijn
    empirisch, uit 327 promovendus-teamseizoenen (2006-2026, zes
    competities): promovendi scoren gemiddeld 21% minder dan het
    competitiegemiddelde en incasseren 18% meer.

    Dit zijn vaste aggregaten en geen genest, uitsluitend op de trainingsset
    geschatte hyperparameters. Herschat ze train-only per competitie voordat
    je de prior zelf volledig out-of-sample of winstgevend noemt.

    Die tweede helft is belangrijk. Alleen de aanval verzwakken -- de
    intuitieve fout -- halveert het gemodelleerde kwaliteitsverschil, en
    laat het model promovendi structureel te sterk inschatten.

    Kalibreer per competitie: het effect is het sterkst in de Premier League
    (0.70 recent) en de Eredivisie (0.76), het mildst in Ligue 1 en Serie A
    (0.82).

    De menging gebeurt in log-ratingruimte. Voor ``n`` effectieve wedstrijden
    is het gewicht van de eigen fit ``w = clip(n / full_weight_matches, 0, 1)``
    en wordt de gebruikte rating ``w * fitted + (1 - w) * prior``. Daardoor
    verdwijnt de prior niet abrupt zodra het eerste duel is gespeeld. Teams
    zonder fit starten exact op de prior; vanaf tien effectieve wedstrijden
    blijft de fit ongewijzigd.

    Alle ratingdicts worden gekopieerd. Ook bij een al bekende promovendus
    muteert deze functie het oorspronkelijke ``TeamRatings``-object dus niet.
    """
    if (
        not np.isfinite(attack_factor)
        or attack_factor <= 0.0
        or not np.isfinite(defence_factor)
        or defence_factor <= 0.0
    ):
        raise ValueError("Promovendusfactoren moeten eindig en positief zijn.")
    if not np.isfinite(full_weight_matches) or full_weight_matches <= 0.0:
        raise ValueError("full_weight_matches moet eindig en positief zijn.")

    attack = dict(ratings.attack)
    defence = dict(ratings.defence)
    eff = dict(ratings.effective_matches)

    attack_prior = float(np.log(attack_factor))
    defence_prior = float(np.log(defence_factor))
    # Dezelfde teamnaam tweemaal poolen zou de uitkomst onbedoeld nog verder
    # naar de prior trekken. dict.fromkeys maakt de bewerking idempotent binnen
    # deze aanroep en bewaart tegelijk een voorspelbare volgorde.
    for team in dict.fromkeys(promoted_teams):
        effective = float(eff.get(team, 0.0))
        if not np.isfinite(effective) or effective < 0.0:
            raise ValueError(
                f"effective_matches voor {team!r} moet eindig en niet-negatief zijn."
            )

        if team not in attack or team not in defence:
            attack[team] = attack_prior
            defence[team] = defence_prior
            eff[team] = effective
            continue

        if not np.isfinite(attack[team]) or not np.isfinite(defence[team]):
            raise ValueError(f"Ratings voor {team!r} moeten eindig zijn.")

        weight = min(effective / full_weight_matches, 1.0)
        if weight < 1.0:
            attack[team] = weight * attack[team] + (1.0 - weight) * attack_prior
            defence[team] = weight * defence[team] + (1.0 - weight) * defence_prior
        eff[team] = effective

    return TeamRatings(
        attack=attack,
        defence=defence,
        intercept=ratings.intercept,
        home_advantage=ratings.home_advantage,
        rho=ratings.rho,
        effective_matches=eff,
        dispersion=ratings.dispersion,
    )


# ============================================================
# 2. Scorematrix
# ============================================================


def dixon_coles_tau(
    x: np.ndarray, y: np.ndarray, lam: np.ndarray, mu: np.ndarray, rho: float
) -> np.ndarray:
    """De lage-score-correctie van Dixon & Coles (1997).

    Onafhankelijke Poissons onderschatten 0-0 en 1-1 en overschatten 1-0 en
    0-1. Alleen die vier cellen worden aangepast; de rest blijft 1.
    """
    x = np.asarray(x)
    y = np.asarray(y)
    lam = np.asarray(lam, dtype=float)
    mu = np.asarray(mu, dtype=float)
    tau = np.ones(x.shape, dtype=float)

    m00 = (x == 0) & (y == 0)
    m01 = (x == 0) & (y == 1)
    m10 = (x == 1) & (y == 0)
    m11 = (x == 1) & (y == 1)

    tau[m00] = 1.0 - lam[m00] * mu[m00] * rho
    tau[m01] = 1.0 + lam[m01] * rho
    tau[m10] = 1.0 + mu[m10] * rho
    tau[m11] = 1.0 - rho
    return tau


def score_matrix(
    lam: float, mu: float, rho: float = DEFAULT_RHO, max_goals: int = 10
) -> np.ndarray:
    """Kansmatrix P[x, y] voor thuis x doelpunten en uit y doelpunten.

    max_goals=10 vangt in de praktijk meer dan 99,99% van de kansmassa af;
    de rest wordt via normalisatie herverdeeld.
    """
    if lam <= 0 or mu <= 0:
        raise ValueError("lambda en mu moeten positief zijn.")

    xs = np.arange(max_goals + 1)
    px = poisson.pmf(xs, lam)
    py = poisson.pmf(xs, mu)
    m = np.outer(px, py)

    xx, yy = np.meshgrid(xs, xs, indexing="ij")
    tau = dixon_coles_tau(xx, yy, np.full(xx.shape, lam), np.full(yy.shape, mu), rho)
    m = m * tau

    if (m < 0).any():
        raise ValueError(
            f"Negatieve kans na Dixon-Coles-correctie (rho={rho}, lam={lam}, "
            f"mu={mu}). rho ligt buiten het geldige bereik voor deze lambdas."
        )
    return m / m.sum()


# ============================================================
# 3. Marktkansen
# ============================================================


def market_probabilities(
    matrix: np.ndarray,
    goal_lines: Sequence[float] = (1.5, 2.5, 3.5),
    team_lines: Sequence[float] = (0.5, 1.5, 2.5),
) -> dict[str, float]:
    """Alle v1-markten, afgeleid uit dezelfde matrix.

    Dat ze uit een bron komen is het punt: zo kunnen de tips elkaar niet
    tegenspreken.
    """
    n = matrix.shape[0]
    xs = np.arange(n)
    xx, yy = np.meshgrid(xs, xs, indexing="ij")
    totals = xx + yy

    probs: dict[str, float] = {}

    # einduitslag
    probs["home"] = float(matrix[xx > yy].sum())
    probs["draw"] = float(matrix[xx == yy].sum())
    probs["away"] = float(matrix[xx < yy].sum())

    # dubbele kans, valt gratis mee
    probs["home_or_draw"] = probs["home"] + probs["draw"]
    probs["away_or_draw"] = probs["away"] + probs["draw"]
    probs["home_or_away"] = probs["home"] + probs["away"]

    # totalen
    for line in goal_lines:
        over = float(matrix[totals > line].sum())
        probs[f"over_{line}"] = over
        probs[f"under_{line}"] = 1.0 - over

    # beide teams scoren
    btts = float(matrix[(xx >= 1) & (yy >= 1)].sum())
    probs["btts_yes"] = btts
    probs["btts_no"] = 1.0 - btts

    # team totals, uit de marginalen
    home_marg = matrix.sum(axis=1)
    away_marg = matrix.sum(axis=0)
    for line in team_lines:
        h_over = float(home_marg[xs > line].sum())
        a_over = float(away_marg[xs > line].sum())
        probs[f"home_over_{line}"] = h_over
        probs[f"home_under_{line}"] = 1.0 - h_over
        probs[f"away_over_{line}"] = a_over
        probs[f"away_under_{line}"] = 1.0 - a_over

    # clean sheets
    probs["home_clean_sheet"] = float(away_marg[0])
    probs["away_clean_sheet"] = float(home_marg[0])

    return probs


def first_half_probabilities(
    lam: float,
    mu: float,
    rho: float = DEFAULT_RHO,
    first_half_ratio: float = DEFAULT_FIRST_HALF_RATIO,
    lines: Sequence[float] = (0.5, 1.5),
) -> dict[str, float]:
    """Eerstehelft-markten via een eigen, geschaalde matrix.

    De ratio is NIET 0.5. In de grote competities valt structureel zo'n 44%
    van de doelpunten voor rust: teams beginnen voorzichtiger, en de tweede
    helft heeft meer blessuretijd en meer open ruimte. Kalibreer de ratio
    per competitie op de historische ruststanden.
    """
    if not 0.0 < first_half_ratio < 1.0:
        raise ValueError("first_half_ratio moet tussen 0 en 1 liggen.")

    m = score_matrix(lam * first_half_ratio, mu * first_half_ratio, rho, max_goals=6)
    n = m.shape[0]
    xs = np.arange(n)
    xx, yy = np.meshgrid(xs, xs, indexing="ij")
    totals = xx + yy

    probs: dict[str, float] = {}
    for line in lines:
        over = float(m[totals > line].sum())
        probs[f"fh_over_{line}"] = over
        probs[f"fh_under_{line}"] = 1.0 - over
    probs["fh_home"] = float(m[xx > yy].sum())
    probs["fh_draw"] = float(m[xx == yy].sum())
    probs["fh_away"] = float(m[xx < yy].sum())
    return probs


def predict_fixture(
    ratings: TeamRatings,
    home_team: str,
    away_team: str,
    first_half_ratio: float = DEFAULT_FIRST_HALF_RATIO,
) -> dict:
    """Alles wat een wedstrijd oplevert, in een aanroep."""
    lam, mu = ratings.expected_goals(home_team, away_team)
    matrix = score_matrix(lam, mu, ratings.rho)
    probs = market_probabilities(matrix)
    probs.update(first_half_probabilities(lam, mu, ratings.rho, first_half_ratio))
    return {
        "lambda_home": lam,
        "lambda_away": mu,
        "expected_total": lam + mu,
        "probs": probs,
        "matrix": matrix,
    }


# ============================================================
# 4. Datakwaliteit
# ============================================================


def data_quality_score(
    effective_matches_home: float,
    effective_matches_away: float,
    xg_source: str,
    matchday: int | None = None,
) -> float:
    """0..1. Bepaalt de betrouwbaarheidsklasse in de UI.

    Een tip uit dunne data hoort er zichtbaar zwakker uit te zien dan een
    tip uit volle data. Valse precisie is de snelste manier om vertrouwen
    te wekken dat niet verdiend is.
    """
    q = 1.0

    # Weinig waarnemingen is de scherpe straf: een net gepromoveerde ploeg
    # met drie duels op dit niveau is echt onbekend terrein.
    thin = min(effective_matches_home, effective_matches_away)
    if thin < 10.0:
        q *= max(0.35, thin / 10.0)

    # De bron weegt bewust MILD mee. Een schoten-op-doel-proxy over zestien
    # seizoenen is een schatting, geen gebrek aan data -- dat onderscheid ging
    # in de eerste versie verloren, waardoor elke tip het label "weinig data"
    # kreeg en het hoogste betrouwbaarheidsniveau onbereikbaar was. Dat de
    # maat een benadering is, staat al zichtbaar op de kaart zelf.
    q *= {
        "understat": 1.0,
        "api_football": 0.97,
        "own_model": 0.90,
        "sot_proxy": 0.85,
    }.get(xg_source, 0.6)

    # vroeg in het seizoen weet niemand iets
    if matchday is not None and matchday <= 5:
        q *= 0.6 + 0.08 * matchday

    return float(min(1.0, max(0.0, q)))


def confidence_band(model_prob: float, data_quality: float) -> str:
    """Vertaalt kans plus datakwaliteit naar een label voor de UI.

    De drempels zijn afgestemd op de bron die je werkelijk hebt. Met de oude
    waarden (hoog vanaf kwaliteit 0.85) was "hoog" onbereikbaar zolang het
    model op een proxy draait, en zag elke tip er even zwak uit -- ook die met
    zestien seizoenen eronder. Dat is geen voorzichtigheid maar ruis: als
    alles zwak heet, zegt het label niets meer.

    "thin_data" is nu voorbehouden aan wat het woord belooft: te weinig
    waarnemingen, in de praktijk promovendi vroeg in het seizoen.
    """
    if data_quality < 0.45:
        return "thin_data"
    edge = abs(model_prob - 0.5)
    if edge > 0.20 and data_quality > 0.80:
        return "high"
    if edge > 0.12 and data_quality > 0.62:
        return "medium"
    return "low"
