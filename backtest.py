#!/usr/bin/env python3
"""Causale walk-forward backtest voor Aftrap.

Elke wedstrijddag wordt opnieuw berekend met uitsluitend wedstrijden van vóór
die dag. Signalen worden individueel opgeslagen; voorlopige gewichten spelen
hier dus geen rol. Slotkoersen zijn een marktbenchmark, geen invoer voor het
model en ook geen echte CLV-meting (daarvoor is een koers op tipmoment nodig).
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sqlite3
import statistics
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import db as store
from load_fdcouk import current_season_start
from run_tips import DEFAULT_DB, analyse_fixture, fit_league_snapshot, settle
from tips import selection_baseline

HERE = Path(__file__).resolve().parent
DEFAULT_REPORT = HERE / "reports" / "backtest_summary.json"
DEFAULT_RECORDS = HERE / "reports" / "backtest_records.csv"
DEFAULT_WEIGHTS = HERE / "signal_weights.json"


def fixture_rows(
    conn: sqlite3.Connection, league: str, target: str
) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT f.id, f.league_code, f.season, l.name league,
                  l.first_half_ratio, l.rho, f.match_date, f.kickoff,
                  th.name home, ta.name away,
                  f.home_goals, f.away_goals,
                  f.home_goals_ht, f.away_goals_ht,
                  o.home odds_home, o.draw odds_draw, o.away odds_away,
                  o.over25 odds_over25, o.under25 odds_under25,
                  o.bookmaker
           FROM fixtures f
           JOIN leagues l ON l.code = f.league_code
           JOIN teams th ON th.id = f.home_team_id
           JOIN teams ta ON ta.id = f.away_team_id
           LEFT JOIN closing_odds o ON o.fixture_id = f.id
           WHERE f.league_code = ? AND f.match_date = ?
             AND f.home_goals IS NOT NULL AND f.away_goals IS NOT NULL
           ORDER BY f.kickoff, th.name""",
        (league, target),
    ).fetchall()


def _devig(prices: list[float | None]) -> list[float | None]:
    if any(p is None or p <= 1.0 for p in prices):
        return [None for _ in prices]
    raw = [1.0 / float(p) for p in prices]
    total = sum(raw)
    return [p / total for p in raw]


def closing_market(
    fixture: sqlite3.Row, selection: str
) -> tuple[float | None, float | None]:
    """Geeft (decimale slotkoers, marge-vrije impliciete kans)."""
    if selection in {"home", "draw", "away"}:
        names = ["home", "draw", "away"]
        prices = [fixture["odds_home"], fixture["odds_draw"], fixture["odds_away"]]
        implied = _devig(prices)
        i = names.index(selection)
        return prices[i], implied[i]
    if selection in {"over_2.5", "under_2.5"}:
        names = ["over_2.5", "under_2.5"]
        prices = [fixture["odds_over25"], fixture["odds_under25"]]
        implied = _devig(prices)
        i = names.index(selection)
        return prices[i], implied[i]
    return None, None


def collect_records(
    conn: sqlite3.Connection,
    from_season: int,
    to_season: int,
    leagues: list[str] | None = None,
    window: int = 10,
) -> list[dict]:
    league_rows = conn.execute("SELECT code, name FROM leagues ORDER BY name").fetchall()
    if leagues:
        wanted = {x.upper() for x in leagues}
        league_rows = [r for r in league_rows if r["code"] in wanted]

    records: list[dict] = []
    for league_row in league_rows:
        league = league_row["code"]
        dates = [
            r["match_date"]
            for r in conn.execute(
                """SELECT DISTINCT match_date
                   FROM fixtures
                   WHERE league_code = ? AND season BETWEEN ? AND ?
                     AND home_goals IS NOT NULL
                   ORDER BY match_date""",
                (league, from_season, to_season),
            )
        ]
        print(f"\n{league_row['name']}: {len(dates)} wedstrijddagen", flush=True)
        for index, target in enumerate(dates, 1):
            snapshot = fit_league_snapshot(conn, league, target)
            if snapshot is None:
                continue
            for fixture in fixture_rows(conn, league, target):
                analysis = analyse_fixture(conn, fixture, target, window, snapshot)
                if analysis is None:
                    continue
                probs = analysis["prediction"]["probs"]
                for signal in analysis["signals"]:
                    probability = probs.get(signal.direction)
                    if probability is None:
                        continue
                    outcome = settle(
                        signal.direction,
                        fixture["home_goals"],
                        fixture["away_goals"],
                        fixture["home_goals_ht"],
                        fixture["away_goals_ht"],
                    )
                    if outcome is None:
                        continue
                    odds, implied = closing_market(fixture, signal.direction)
                    records.append({
                        "date": target,
                        "season": fixture["season"],
                        "league": league,
                        "fixture_id": fixture["id"],
                        "home": fixture["home"],
                        "away": fixture["away"],
                        "signal": signal.key,
                        "selection": signal.direction,
                        "market": signal.market,
                        "strength": round(abs(signal.strength), 6),
                        "model_probability": round(float(probability), 8),
                        "baseline": selection_baseline(signal.direction),
                        "data_quality": round(float(analysis["quality"]), 6),
                        "outcome": int(outcome),
                        "closing_odds": odds,
                        "closing_implied": implied,
                        "market_edge": (
                            round(float(probability - implied), 8)
                            if implied is not None else None
                        ),
                        "profit_at_close": (
                            round((float(odds) if outcome else 0.0) - 1.0, 8)
                            if odds is not None else None
                        ),
                    })
            if index % 50 == 0 or index == len(dates):
                print(
                    f"  {index:>4}/{len(dates)} dagen · {len(records):>6} signalen",
                    flush=True,
                )
    return records


def _mean(rows: list[dict], key: str) -> float | None:
    values = [float(r[key]) for r in rows if r.get(key) is not None]
    return statistics.fmean(values) if values else None


def _wilson_lower(hits: int, n: int, z: float = 1.96) -> float:
    if n == 0:
        return 0.0
    p = hits / n
    denominator = 1 + z * z / n
    centre = p + z * z / (2 * n)
    spread = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n)
    return (centre - spread) / denominator


def metrics(rows: list[dict]) -> dict:
    n = len(rows)
    if not n:
        return {"n": 0}
    hits = sum(int(r["outcome"]) for r in rows)
    probabilities = [min(1 - 1e-12, max(1e-12, float(r["model_probability"]))) for r in rows]
    outcomes = [int(r["outcome"]) for r in rows]
    brier = statistics.fmean((p - y) ** 2 for p, y in zip(probabilities, outcomes))
    log_loss = -statistics.fmean(
        y * math.log(p) + (1 - y) * math.log(1 - p)
        for p, y in zip(probabilities, outcomes)
    )
    odds_rows = [r for r in rows if r.get("closing_odds") is not None]
    hit_rate = hits / n
    avg_probability = statistics.fmean(probabilities)
    roi = _mean(odds_rows, "profit_at_close") if odds_rows else None
    roi_lower = roi_upper = None
    if len(odds_rows) > 1:
        profits = [float(r["profit_at_close"]) for r in odds_rows]
        roi_se = statistics.stdev(profits) / math.sqrt(len(profits))
        roi_lower, roi_upper = roi - 1.96 * roi_se, roi + 1.96 * roi_se
    return {
        "n": n,
        "hits": hits,
        "hit_rate": round(hit_rate, 6),
        "wilson_lower_95": round(_wilson_lower(hits, n), 6),
        "baseline": round(_mean(rows, "baseline") or 0.5, 6),
        "avg_model_probability": round(avg_probability, 6),
        "calibration_gap": round(hit_rate - avg_probability, 6),
        "brier": round(brier, 6),
        "log_loss": round(log_loss, 6),
        "odds_n": len(odds_rows),
        "roi_at_close": round(roi, 6) if roi is not None else None,
        "roi_lower_95": round(roi_lower, 6) if roi_lower is not None else None,
        "roi_upper_95": round(roi_upper, 6) if roi_upper is not None else None,
        "avg_market_edge": (
            round(_mean(odds_rows, "market_edge"), 6) if odds_rows else None
        ),
    }


def summarise(
    records: list[dict], validation_start: int, test_start: int
) -> tuple[dict, dict]:
    by_signal: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        by_signal[record["signal"]].append(record)

    def split(rows: list[dict]) -> tuple[dict, dict, dict, dict]:
        train = [r for r in rows if int(r["season"]) < validation_start]
        validation = [
            r for r in rows if validation_start <= int(r["season"]) < test_start
        ]
        test = [r for r in rows if int(r["season"]) >= test_start]
        return metrics(train), metrics(validation), metrics(test), metrics(rows)

    def approved(m_train: dict, m_validation: dict, m_test: dict) -> tuple[bool, str]:
        if m_train["n"] < 100 or m_validation["n"] < 30 or m_test["n"] < 30:
            return False, "onvoldoende waarnemingen"
        if m_train["wilson_lower_95"] <= m_train["baseline"]:
            return False, "training niet boven baseline"
        if m_validation["hit_rate"] <= m_validation["baseline"]:
            return False, "validatie niet boven baseline"
        if m_test["wilson_lower_95"] <= m_test["baseline"]:
            return False, "test niet overtuigend boven baseline"
        if m_test["odds_n"] >= max(30, int(0.8 * m_test["n"])):
            if (
                m_test["roi_lower_95"] is None
                or m_test["roi_lower_95"] <= 0
            ):
                return False, "rendement tegen slotkoers niet overtuigend positief"
            return True, "voorspellend en overtuigend positief tegen slotkoers"
        return True, "voorspellend; voor deze markt ontbreken slotkoersen"

    report_signals = {}
    weights = {}
    for signal, rows in sorted(by_signal.items()):
        m_train, m_validation, m_test, m_all = split(rows)
        directions = {}
        for selection in sorted({r["selection"] for r in rows}):
            selected = [r for r in rows if r["selection"] == selection]
            d_train, d_validation, d_test, d_all = split(selected)
            keep, reason = approved(d_train, d_validation, d_test)
            directions[selection] = {
                "approved_final": keep,
                "reason": reason,
                "train": d_train,
                "validation": d_validation,
                "test": d_test,
                "all": d_all,
            }
            if keep:
                fit_rows = [r for r in selected if int(r["season"]) < test_start]
                fitted = metrics(fit_rows)
                weights[f"{signal}:{selection}"] = {
                    "signal": signal,
                    "selection": selection,
                    "hit_rate": fitted["hit_rate"],
                    "n": fitted["n"],
                    "baseline": fitted["baseline"],
                    "reason": reason,
                    "validation_hit_rate": d_validation["hit_rate"],
                    "test_hit_rate": d_test["hit_rate"],
                    "test_n": d_test["n"],
                    "test_roi_at_close": d_test.get("roi_at_close"),
                }
        report_signals[signal] = {
            "train": m_train,
            "validation": m_validation,
            "test": m_test,
            "all": m_all,
            "directions": directions,
        }

    report = {
        "method": "daily walk-forward; every model snapshot uses match_date < target",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "records": len(records),
        "validation_start_season": validation_start,
        "test_start_season": test_start,
        "overall": metrics(records),
        "signals": report_signals,
    }
    weight_file = {
        "source": "walk_forward_backtest",
        "generated_at": report["generated_at"],
        "trained_through_season": test_start - 1,
        "selection_rule": (
            "directional: train n>=100 and Wilson lower 95% > baseline; "
            "validation n>=30 and hit rate > baseline; test n>=30 and Wilson "
            "lower 95% > baseline; when closing odds cover >=80%, the lower "
            "95% bound of test ROI must be > 0"
        ),
        "signals": weights,
    }
    return report, weight_file


def write_records(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not records:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)


def read_records(path: Path) -> list[dict]:
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    integer_fields = {"season", "fixture_id", "outcome"}
    float_fields = {
        "strength", "model_probability", "baseline", "data_quality",
        "closing_odds", "closing_implied", "market_edge", "profit_at_close",
    }
    for row in rows:
        for key in integer_fields:
            row[key] = int(row[key])
        for key in float_fields:
            row[key] = float(row[key]) if row.get(key) not in (None, "") else None
    return rows


def main() -> int:
    current = current_season_start()
    ap = argparse.ArgumentParser(description="Walk-forward signaalbacktest")
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--from-season", type=int, default=max(2011, current - 15))
    ap.add_argument("--to-season", type=int, default=current - 1)
    ap.add_argument("--validation-start", type=int, default=None)
    ap.add_argument("--test-start", type=int, default=None)
    ap.add_argument("--leagues", nargs="*", default=None)
    ap.add_argument("--window", type=int, default=10)
    ap.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    ap.add_argument("--records", type=Path, default=DEFAULT_RECORDS)
    ap.add_argument("--weights", type=Path, default=DEFAULT_WEIGHTS)
    ap.add_argument(
        "--reuse-records",
        action="store_true",
        help="sla de modelrun over en maak het rapport opnieuw uit de bestaande CSV",
    )
    args = ap.parse_args()

    if not Path(args.db).exists():
        print(f"Database ontbreekt: {args.db}")
        return 1
    validation_start = args.validation_start or args.to_season - 3
    test_start = args.test_start or args.to_season - 1
    if not args.from_season < validation_start < test_start <= args.to_season:
        print("Ongeldige chronologische train/validatie/test-splitsing.")
        return 1

    if args.reuse_records:
        if not args.records.exists():
            print(f"Records ontbreken: {args.records}")
            return 1
        records = read_records(args.records)
    else:
        conn = store.connect(args.db)
        records = collect_records(
            conn,
            args.from_season,
            args.to_season,
            leagues=args.leagues,
            window=args.window,
        )
    report, weights = summarise(records, validation_start, test_start)
    write_records(args.records, records)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    args.weights.write_text(json.dumps(weights, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nRecords: {args.records.resolve()}")
    print(f"Rapport: {args.report.resolve()}")
    print(f"Goedgekeurde gewichten: {args.weights.resolve()}")
    print(f"Signalen behouden: {', '.join(weights['signals']) or 'geen'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
