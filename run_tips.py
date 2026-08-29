#!/usr/bin/env python3
"""
Genereert tips uit de database en schrijft het dashboard weg.

    python3 run_tips.py                    # vooruitblik, of terugkijkmodus zonder API-data
    python3 run_tips.py --date 2025-11-08
    python3 run_tips.py --window 8 --open aftrap.html

Met ingeladen API-Football-fixtures toont dit de komende acht dagen. Als die
ontbreken draait het in terugkijkmodus: het model wordt gefit op uitsluitend
data van vóór de speeldatum, genereert tips alsof die ochtend was, en zet er
vervolgens de werkelijke uitslag naast.

Dat is nuttiger dan het klinkt. Een tip die je vooraf ziet met de uitslag
ernaast vertelt je meteen of de onderbouwing ergens op sloeg -- en de
cutoff-regel zorgt dat het model niets weet wat het toen niet wist.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import sys
import webbrowser
from datetime import date, datetime, timedelta
from pathlib import Path

import db as store
from model import (
    MatchObservation,
    data_quality_score,
    fit_ratings,
    initialise_promoted,
    predict_fixture,
)
from tips import MatchContext, SignalPerformance, build_tips, collect_signals

# Zie load_fdcouk.py: alles hangt aan de map van het script, zodat je het
# vanuit Finder in Terminal kunt slepen zonder eerst te navigeren.
HERE = Path(__file__).resolve().parent
DEFAULT_DB = str(HERE / "data" / "aftrap.sqlite")
TEMPLATE = HERE / "dashboard_template.html"
DEFAULT_OUT = str(HERE / "aftrap.html")
WEIGHTS_FILE = HERE / "signal_weights.json"
MONTH_LABELS = (
    "jan", "feb", "mrt", "apr", "mei", "jun",
    "jul", "aug", "sep", "okt", "nov", "dec",
)

# xG-bronnen in volgorde van betrouwbaarheid.
XG_PREFERENCE = ("understat", "api_football", "sot_proxy")

def load_signal_performance(path: Path = WEIGHTS_FILE) -> dict[str, SignalPerformance]:
    """Lees uitsluitend door de walk-forward backtest goedgekeurde gewichten."""
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        key: SignalPerformance(
            hit_rate=float(value["hit_rate"]),
            n=int(value["n"]),
            baseline=float(value.get("baseline", 0.5)),
        )
        for key, value in payload.get("signals", {}).items()
    }


# ------------------------------------------------------------
# lezen uit de database
# ------------------------------------------------------------


def best_xg_source(conn: sqlite3.Connection, league: str) -> str | None:
    have = {r["source"] for r in conn.execute(
        """SELECT DISTINCT x.source FROM fixture_xg x
           JOIN fixtures f ON f.id = x.fixture_id WHERE f.league_code = ?""", (league,))}
    for s in XG_PREFERENCE:
        if s in have:
            return s
    return None


def load_observations(
    conn: sqlite3.Connection, league: str, source: str, cutoff: str
) -> list[MatchObservation]:
    """Alle gespeelde wedstrijden vóór de cutoff, met xG uit één bron.

    De cutoff is heilig: alles wat erna ligt is datalekkage en maakt de
    uitkomst mooier dan hij is.
    """
    rows = conn.execute(
        """SELECT f.match_date, th.name home, ta.name away,
                  f.home_goals, f.away_goals,
                  xh.xg home_xg, xa.xg away_xg
           FROM fixtures f
           JOIN teams th ON th.id = f.home_team_id
           JOIN teams ta ON ta.id = f.away_team_id
           JOIN fixture_xg xh ON xh.fixture_id = f.id AND xh.team_id = f.home_team_id AND xh.source = ?
           JOIN fixture_xg xa ON xa.fixture_id = f.id AND xa.team_id = f.away_team_id AND xa.source = ?
           WHERE f.league_code = ? AND f.match_date < ? AND f.home_goals IS NOT NULL
           ORDER BY f.match_date""",
        (source, source, league, cutoff),
    ).fetchall()

    return [
        MatchObservation(
            match_date=date.fromisoformat(r["match_date"]),
            home_team=r["home"], away_team=r["away"],
            home_xg=float(r["home_xg"]), away_xg=float(r["away_xg"]),
            home_goals=r["home_goals"], away_goals=r["away_goals"],
        )
        for r in rows
    ]


def team_form(
    conn: sqlite3.Connection, league: str, team: str, cutoff: str, window: int, source: str
) -> dict:
    """Voortschrijdende cijfers over de laatste `window` duels vóór de cutoff."""
    rows = conn.execute(
        """SELECT f.match_date,
                  (f.home_team_id = t.id) AS at_home,
                  CASE WHEN f.home_team_id = t.id THEN f.home_goals ELSE f.away_goals END gf,
                  CASE WHEN f.home_team_id = t.id THEN f.away_goals ELSE f.home_goals END ga,
                  CASE WHEN f.home_team_id = t.id THEN f.home_goals_ht ELSE f.away_goals_ht END gf_ht,
                  xs.xg xg_for, xo.xg xg_against
           FROM fixtures f
           JOIN teams t ON t.name = ? AND t.league_code = ?
           LEFT JOIN fixture_xg xs ON xs.fixture_id = f.id AND xs.team_id = t.id AND xs.source = ?
           LEFT JOIN fixture_xg xo ON xo.fixture_id = f.id AND xo.source = ?
                AND xo.team_id = CASE WHEN f.home_team_id = t.id THEN f.away_team_id ELSE f.home_team_id END
           WHERE f.league_code = ? AND f.match_date < ? AND f.home_goals IS NOT NULL
             AND (f.home_team_id = t.id OR f.away_team_id = t.id)
           ORDER BY f.match_date DESC LIMIT ?""",
        (team, league, source, source, league, cutoff, window),
    ).fetchall()

    if not rows:
        return {}

    def avg(key, default=None):
        vals = [r[key] for r in rows if r[key] is not None]
        return statistics.fmean(vals) if vals else default

    btts = [1.0 if (r["gf"] or 0) > 0 and (r["ga"] or 0) > 0 else 0.0 for r in rows]
    return {
        "n": len(rows),
        "xg_for": avg("xg_for"),
        "xg_against": avg("xg_against"),
        "goals_against": avg("ga", 0.0),
        "btts_rate": statistics.fmean(btts),
        "fh_goals": avg("gf_ht", 0.0),
        "last_date": rows[0]["match_date"],
    }


def player_shot_form(
    conn: sqlite3.Connection,
    team_id: int,
    cutoff: str,
    appearances: int = 5,
    limit: int = 2,
) -> list[dict]:
    """Beste recente schotprofielen, op maximaal vijf eerdere optredens.

    Dit is beschrijvende vormdata en nadrukkelijk geen gekalibreerde
    spelers-probability. De steekproefgrootte blijft zichtbaar, ook als door de
    start van een nieuw seizoen nog minder dan vijf optredens beschikbaar zijn.
    """
    rows = conn.execute(
        """SELECT p.id, p.name, s.match_date, s.minutes,
                  s.shots, s.shots_on_target
           FROM player_match_stats s
           JOIN players p ON p.id = s.player_id
           WHERE s.team_id = ? AND s.match_date < ?
             AND s.shots_on_target IS NOT NULL
             AND COALESCE(s.minutes, 0) > 0
           ORDER BY p.id, s.match_date DESC""",
        (team_id, cutoff),
    ).fetchall()
    by_player: dict[int, list[sqlite3.Row]] = {}
    for row in rows:
        group = by_player.setdefault(int(row["id"]), [])
        if len(group) < appearances:
            group.append(row)

    candidates = []
    for player_rows in by_player.values():
        sot = [int(row["shots_on_target"]) for row in player_rows]
        shots = [int(row["shots"] or 0) for row in player_rows]
        hits = sum(value >= 1 for value in sot)
        candidates.append({
            "name": player_rows[0]["name"],
            "n": len(player_rows),
            "sot_avg": round(statistics.fmean(sot), 2),
            "shots_avg": round(statistics.fmean(shots), 2),
            "sot_hits": hits,
            "sot_hit_rate": round(hits / len(sot), 3),
        })
    candidates.sort(
        key=lambda item: (
            item["n"], item["sot_avg"], item["sot_hit_rate"], item["shots_avg"]
        ),
        reverse=True,
    )
    return candidates[:limit]


def pick_review_date(conn: sqlite3.Connection, min_matches: int = 6) -> str | None:
    row = conn.execute(
        """SELECT match_date, COUNT(*) n FROM fixtures
           WHERE home_goals IS NOT NULL
           GROUP BY match_date HAVING n >= ?
           ORDER BY match_date DESC LIMIT 1""",
        (min_matches,),
    ).fetchone()
    return row["match_date"] if row else None


def pick_upcoming_dates(
    conn: sqlite3.Connection,
    start: date | None = None,
    horizon_days: int = 8,
) -> list[str]:
    """Komende speeldagen met daadwerkelijk nog te spelen API-fixtures."""
    start = start or date.today()
    end = start + timedelta(days=horizon_days)
    return [
        row["match_date"]
        for row in conn.execute(
            """SELECT DISTINCT f.match_date
               FROM fixtures f
               JOIN fixture_external_ids x ON x.fixture_id = f.id
               WHERE x.source = 'api_football'
                 AND f.match_date BETWEEN ? AND ?
                 AND f.home_goals IS NULL AND f.away_goals IS NULL
                 AND f.status IN ('NS', 'TBD')
               ORDER BY f.match_date""",
            (start.isoformat(), end.isoformat()),
        )
    ]


def matchday_label(targets: list[str]) -> str:
    """Korte Nederlandse datumregel voor de kop van het dashboard."""
    parsed = [date.fromisoformat(value) for value in targets]
    start, end = parsed[0], parsed[-1]
    first = f"{start.day} {MONTH_LABELS[start.month - 1]}"
    if start == end:
        return f"{first} {start.year}"
    last = f"{end.day} {MONTH_LABELS[end.month - 1]}"
    suffix = f" {end.year}" if end.year != start.year else ""
    return f"{first} – {last}{suffix}"


# ------------------------------------------------------------
# afwikkelen
# ------------------------------------------------------------


def settle(
    selection: str,
    hg: int,
    ag: int,
    hg_ht: int | None = None,
    ag_ht: int | None = None,
) -> bool | None:
    """Kwam de tip uit? None als we het niet kunnen bepalen."""
    if selection.startswith("fh_"):
        if hg_ht is None or ag_ht is None:
            return None
        rest = selection[3:]
        total_ht = hg_ht + ag_ht
        if rest.startswith("over_"):
            return total_ht > float(rest[5:])
        if rest.startswith("under_"):
            return total_ht < float(rest[6:])
        if rest == "home":
            return hg_ht > ag_ht
        if rest == "away":
            return ag_ht > hg_ht
        if rest == "draw":
            return hg_ht == ag_ht
        return None

    total = hg + ag
    if selection.startswith("over_"):
        return total > float(selection[5:])
    if selection.startswith("under_"):
        return total < float(selection[6:])
    if selection == "btts_yes":
        return hg > 0 and ag > 0
    if selection == "btts_no":
        return hg == 0 or ag == 0
    if selection == "home":
        return hg > ag
    if selection == "away":
        return ag > hg
    if selection == "draw":
        return hg == ag
    if selection == "home_or_draw":
        return hg >= ag
    if selection == "away_or_draw":
        return ag >= hg
    for prefix, goals in (("home_", hg), ("away_", ag)):
        if selection.startswith(prefix):
            rest = selection[len(prefix):]
            if rest.startswith("over_"):
                return goals > float(rest[5:])
            if rest.startswith("under_"):
                return goals < float(rest[6:])
    return None


def label(selection: str, home: str, away: str) -> str:
    fixed = {
        "btts_yes": "Beide teams scoren", "btts_no": "Niet beide teams scoren",
        "draw": "Gelijkspel", "home": f"{home} wint", "away": f"{away} wint",
        "home_or_draw": f"{home} of gelijk", "away_or_draw": f"{away} of gelijk",
    }
    if selection in fixed:
        return fixed[selection]
    if selection.startswith(("over_", "under_")):
        kind, line = selection.split("_")
        return f"{'Over' if kind == 'over' else 'Under'} {line}"
    if selection.startswith("fh_"):
        rest = selection[3:]
        if rest.startswith(("over_", "under_")):
            kind, line = rest.split("_")
            return f"1e helft {'over' if kind == 'over' else 'under'} {line}"
    for prefix, team in (("home_", home), ("away_", away)):
        if selection.startswith(prefix):
            rest = selection[len(prefix):]
            for kind in ("over", "under"):
                if rest.startswith(kind + "_"):
                    return f"{team} {kind} {rest[len(kind) + 1:]}"
    return selection.replace("_", " ")


# ------------------------------------------------------------
# hoofdlus
# ------------------------------------------------------------


def fit_league_snapshot(
    conn: sqlite3.Connection, league: str, target: str, min_observations: int = 100
) -> tuple | None:
    """Fit één causale competitiesnapshot voor hergebruik in UI en backtest."""
    source = best_xg_source(conn, league)
    if not source:
        return None
    obs = load_observations(conn, league, source, target)
    if len(obs) < min_observations:
        return None
    ratings = fit_ratings(obs, date.fromisoformat(target))
    avg_total = statistics.fmean([o.home_xg + o.away_xg for o in obs[-400:]])
    return ratings, source, avg_total, len(obs)


def analyse_fixture(
    conn: sqlite3.Connection,
    fixture: sqlite3.Row,
    target: str,
    window: int,
    snapshot: tuple,
    as_of: str | None = None,
) -> dict | None:
    """Alle pre-match informatie voor één fixture, zonder tipgewichten."""
    cutoff = as_of or target
    ratings, source, league_avg, _ = snapshot
    missing = [
        t for t in (fixture["home"], fixture["away"]) if t not in ratings.attack
    ]
    fixture_ratings = initialise_promoted(ratings, missing) if missing else ratings
    pred = predict_fixture(
        fixture_ratings,
        fixture["home"],
        fixture["away"],
        fixture["first_half_ratio"],
    )
    hf = team_form(
        conn, fixture["league_code"], fixture["home"], cutoff, window, source
    )
    af = team_form(
        conn, fixture["league_code"], fixture["away"], cutoff, window, source
    )
    if not hf or not af or hf.get("xg_for") is None or af.get("xg_for") is None:
        return None

    lam, mu = pred["lambda_home"], pred["lambda_away"]
    matchday = _matchday(
        conn,
        fixture["league_code"],
        fixture["season"],
        fixture["home"],
        fixture["away"],
        target,
    )
    ctx = MatchContext(
        home_team=fixture["home"], away_team=fixture["away"],
        lambda_home=lam, lambda_away=mu, league_avg_goals=league_avg,
        home_xg_for=hf["xg_for"], home_xg_against=hf["xg_against"],
        away_xg_for=af["xg_for"], away_xg_against=af["xg_against"],
        home_goals_against=hf["goals_against"], away_goals_against=af["goals_against"],
        home_btts_rate=hf["btts_rate"], away_btts_rate=af["btts_rate"],
        home_fh_goals=hf["fh_goals"], away_fh_goals=af["fh_goals"],
        first_half_ratio=fixture["first_half_ratio"],
        rest_days_home=_rest(hf, target), rest_days_away=_rest(af, target),
        european_match_home=False, european_match_away=False,
        missing_xg_share_home=0.0, missing_xg_share_away=0.0,
        matchday=matchday, window=window,
    )
    quality = data_quality_score(
        fixture_ratings.effective_matches.get(fixture["home"], 0.0),
        fixture_ratings.effective_matches.get(fixture["away"], 0.0),
        xg_source=source,
        matchday=matchday,
    )
    return {
        "prediction": pred,
        "signals": collect_signals(ctx),
        "quality": quality,
        "source": source,
        "matchday": matchday,
    }


def build_day(
    conn: sqlite3.Connection,
    target: str,
    window: int,
    performance: dict[str, SignalPerformance] | None = None,
    as_of: str | None = None,
) -> list[dict]:
    cutoff = as_of or target
    performance = performance if performance is not None else load_signal_performance()
    fixtures = conn.execute(
        """SELECT f.id, f.league_code, f.season, l.name league,
                  l.first_half_ratio, l.rho,
                  f.kickoff, f.home_team_id, f.away_team_id,
                  th.name home, ta.name away,
                  f.home_goals, f.away_goals,
                  f.home_goals_ht, f.away_goals_ht
           FROM fixtures f
           JOIN leagues l ON l.code = f.league_code
           JOIN teams th ON th.id = f.home_team_id
           JOIN teams ta ON ta.id = f.away_team_id
           WHERE f.match_date = ?
           ORDER BY l.name, f.kickoff, th.name""",
        (target,),
    ).fetchall()

    if not fixtures:
        return []

    leagues = sorted({f["league_code"] for f in fixtures})
    models: dict[str, tuple] = {}
    for lg in leagues:
        snapshot = fit_league_snapshot(conn, lg, cutoff)
        if snapshot is None:
            print(f"  {lg}: onvoldoende modeldata vóór {cutoff}; overgeslagen")
            continue
        ratings, source, _, n_obs = snapshot
        models[lg] = snapshot
        print(f"  {lg}: {n_obs} duels, bron {source}, "
              f"rho {ratings.rho:+.3f}, thuisvoordeel {ratings.home_advantage:+.3f}")

    out = []
    for f in fixtures:
        if f["league_code"] not in models:
            continue
        analysis = analyse_fixture(
            conn, f, target, window, models[f["league_code"]], as_of=cutoff
        )
        if analysis is None:
            continue
        pred = analysis["prediction"]
        source = analysis["source"]
        quality = analysis["quality"]
        lam, mu = pred["lambda_home"], pred["lambda_away"]
        chosen = build_tips(
            pred["probs"], analysis["signals"], quality, performance
        )

        hg, ag = f["home_goals"], f["away_goals"]
        played = hg is not None and ag is not None
        players = []
        for team_id, team_name in (
            (int(f["home_team_id"]), f["home"]),
            (int(f["away_team_id"]), f["away"]),
        ):
            for player in player_shot_form(conn, team_id, cutoff):
                players.append({**player, "team": team_name})

        out.append({
            "league": f["league"], "league_code": f["league_code"],
            "date": target,
            "kickoff": f["kickoff"] or "",
            "home": f["home"], "away": f["away"],
            "lambda_home": round(lam, 2), "lambda_away": round(mu, 2),
            "p_home": round(pred["probs"]["home"], 3),
            "p_draw": round(pred["probs"]["draw"], 3),
            "p_away": round(pred["probs"]["away"], 3),
            "p_over25": round(pred["probs"]["over_2.5"], 3),
            "p_btts": round(pred["probs"]["btts_yes"], 3),
            "quality": round(quality, 2), "xg_source": source,
            "score": f"{hg}-{ag}" if played else None,
            "players": players,
            "tips": [{
                "s": label(t.selection, f["home"], f["away"]),
                "raw": t.selection, "m": t.market, "p": round(t.model_prob, 3),
                "b": t.confidence_band, "r": t.rationale,
                "g": [s.key for s in t.signals],
                "hit": settle(
                    t.selection,
                    hg,
                    ag,
                    f["home_goals_ht"],
                    f["away_goals_ht"],
                ) if played else None,
            } for t in chosen],
        })
    return out


def _rest(form: dict, target: str) -> int:
    if not form.get("last_date"):
        return 7
    delta = (date.fromisoformat(target) - date.fromisoformat(form["last_date"])).days
    return max(1, min(21, delta))


def _matchday(
    conn: sqlite3.Connection,
    league: str,
    season: int,
    home: str,
    away: str,
    target: str,
) -> int:
    """Conservatieve speelronde: minste aantal eerdere duels van beide teams + 1."""
    counts = []
    for team in (home, away):
        row = conn.execute(
            """SELECT COUNT(*) n
               FROM fixtures f
               JOIN teams t ON t.league_code = f.league_code
                 AND t.name = ?
               WHERE f.league_code = ? AND f.season = ? AND f.match_date < ?
                 AND (f.home_team_id = t.id OR f.away_team_id = t.id)""",
            (team, league, season, target),
        ).fetchone()
        counts.append(int(row["n"]))
    return min(counts) + 1


# ------------------------------------------------------------


def main_with_args(
    db: str = DEFAULT_DB,
    target_date: str | None = None,
    window: int = 10,
    out: str = DEFAULT_OUT,
    do_open: bool = False,
) -> int:
    """De echte logica, zonder argparse ertussen; zie load_fdcouk."""
    args = argparse.Namespace(
        db=db, date=target_date, window=window, out=out, do_open=do_open
    )

    if not Path(args.db).exists():
        print(f"Database {args.db} bestaat niet. Draai eerst load_fdcouk.py.")
        return 1

    conn = store.connect(args.db)
    today = date.today()
    upcoming = [] if args.date else pick_upcoming_dates(conn, today)
    targets = [args.date] if args.date else upcoming
    forward = bool(upcoming)
    if not targets:
        review_date = pick_review_date(conn)
        targets = [review_date] if review_date else []
    if not targets:
        print("Geen speeldag met genoeg wedstrijden gevonden.")
        return 1

    cutoff = today.isoformat() if forward else targets[0]
    if forward:
        print(
            f"\nVooruitblik {targets[0]} t/m {targets[-1]} — "
            f"modeldata van vóór {cutoff}\n"
        )
    else:
        print(f"\nSpeeldag {targets[0]} — model fitten op uitsluitend data daarvóór\n")
    performance = load_signal_performance()
    if not performance:
        print("  Geen gevalideerde signaalgewichten; er worden geen tips getoond.")
    fixtures = []
    for target in targets:
        fixtures.extend(
            build_day(conn, target, args.window, performance, as_of=cutoff)
        )
    if not fixtures:
        print("\nGeen wedstrijden om te tonen. Probeer een andere datum met --date.")
        return 1

    tips = [t for f in fixtures for t in f["tips"]]
    settled = [t for t in tips if t["hit"] is not None]
    hits = sum(1 for t in settled if t["hit"])

    print(f"\n  {len(fixtures)} wedstrijden, {len(tips)} tips, "
          f"{sum(1 for f in fixtures if not f['tips'])} zonder tip")
    if settled:
        print(f"  {hits} van {len(settled)} afgewikkelde tips kwam uit "
              f"({hits / len(settled):.0%})")

    display_matchday = matchday_label(targets)
    html = TEMPLATE.read_text(encoding="utf-8").replace(
        "/*__DATA__*/[]",
        json.dumps(fixtures, ensure_ascii=False, separators=(",", ":")),
    ).replace("__MATCHDAY__", display_matchday).replace(
        "__GENERATED__", datetime.now().strftime("%d-%m-%Y %H:%M"))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"\n  Dashboard: {out.resolve()}\n")
    if args.do_open:
        webbrowser.open(out.resolve().as_uri())
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Genereer tips en schrijf het dashboard.")
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument(
        "--date",
        default=None,
        help="YYYY-MM-DD; standaard komende API-speeldagen of laatste speelronde",
    )
    ap.add_argument("--window", type=int, default=10, help="aantal duels voor vormcijfers")
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--open", dest="do_open", action="store_true", help="open in de browser")
    a = ap.parse_args()
    return main_with_args(a.db, a.date, a.window, a.out, a.do_open)


if __name__ == "__main__":
    sys.exit(main())
