#!/usr/bin/env python3
"""
Laadt historische wedstrijddata van football-data.co.uk in de database.

Draaien:
    python3 load_fdcouk.py                    # 2010/11 t/m nu, alle zes
    python3 load_fdcouk.py --from 2015
    python3 load_fdcouk.py --leagues EPL ERE

Levert per wedstrijd: uitslag, ruststand, schoten, schoten op doel, corners,
fouls, kaarten, scheidsrechter waar beschikbaar, en de slotkoersen.

Wat je moet weten over de dekking, geverifieerd op de bron:

  * Schotdata voor de Eredivisie bestaat pas vanaf seizoen 2020/21. Daarvoor
    zijn er alleen uitslagen en quoteringen.
  * Bundesliga en Ligue 1 hebben schoten vanaf ongeveer 2007/08, Premier
    League, La Liga en Serie A vanaf 2005/06 of eerder.
  * Slotkoersen van de hele markt (AvgC*) bestaan vanaf 2020/21; Pinnacle's
    slotkoers (PSC*) gaat terug tot ongeveer 2015/16.
  * Scheidsrechters staan alleen structureel in de Premier League.

Het script downloadt elk bestand één keer en bewaart het ruw in data/raw/,
zodat opnieuw inlezen gratis is en je kunt zien wat er echt binnenkwam.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import sqlite3
import sys
import urllib.error
import urllib.request
from pathlib import Path

import db as store

BASE = "https://www.football-data.co.uk/mmz4281"

# Alles hangt aan de map waar dit script staat, niet aan de map waar je
# toevallig in Terminal staat. Zo kun je het script gewoon vanuit Finder in
# een Terminal-venster slepen zonder eerst ergens naartoe te navigeren, en
# komt de database altijd op dezelfde plek terecht.
HERE = Path(__file__).resolve().parent
RAW = HERE / "data" / "raw"
DEFAULT_DB = str(HERE / "data" / "aftrap.sqlite")

USER_AGENT = "aftrap/1.0 (persoonlijk statistiekproject)"


# ------------------------------------------------------------
# ophalen
# ------------------------------------------------------------


def season_code(season: int) -> str:
    """2023 -> '2324'."""
    return f"{season % 100:02d}{(season + 1) % 100:02d}"


def fetch_csv(season: int, fd_code: str, refresh: bool = False) -> str | None:
    """Download met schijfcache. Geeft None als het bestand niet bestaat."""
    path = RAW / season_code(season) / f"{fd_code}.csv"
    if path.exists() and not refresh:
        return path.read_text(encoding="utf-8", errors="replace")

    url = f"{BASE}/{season_code(season)}/{fd_code}.csv"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=40) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    text = raw.decode("utf-8", errors="replace")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return text


# ------------------------------------------------------------
# parsen
# ------------------------------------------------------------


def parse_date(value: str) -> str | None:
    """football-data gebruikt dd/mm/yy in oudere bestanden en dd/mm/yyyy in
    nieuwere. Beide moeten werken, en een onherkenbare datum moet None geven
    in plaats van een gegokt jaar."""
    value = (value or "").strip()
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return dt.datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def as_int(value: str | None) -> int | None:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


def as_float(value: str | None) -> float | None:
    try:
        f = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def pick(row: dict, *keys: str) -> str | None:
    """Eerste kolom die bestaat én gevuld is. De kolomnamen verschillen per
    seizoen, dus we noemen ze in volgorde van voorkeur."""
    for k in keys:
        v = row.get(k)
        if v not in (None, ""):
            return v
    return None


def parse_rows(text: str) -> list[dict]:
    """Zet een ruwe CSV om naar genormaliseerde wedstrijdrecords."""
    reader = csv.DictReader(io.StringIO(text))
    out: list[dict] = []

    for row in reader:
        # Lege staartregels komen vaak voor in deze bestanden.
        if not row.get("HomeTeam") or not row.get("AwayTeam"):
            continue
        date = parse_date(row.get("Date", ""))
        if not date:
            continue
        hg, ag = as_int(row.get("FTHG")), as_int(row.get("FTAG"))
        if hg is None or ag is None:
            continue  # nog niet gespeeld of afgelast

        # Slotkoersen: Pinnacle's slotkoers is de scherpste publieke schatting
        # die in deze bestanden zit; het marktgemiddelde is de terugval.
        ch = as_float(pick(row, "PSCH", "AvgCH", "MaxCH"))
        cd = as_float(pick(row, "PSCD", "AvgCD", "MaxCD"))
        ca = as_float(pick(row, "PSCA", "AvgCA", "MaxCA"))
        book = "pinnacle_closing" if row.get("PSCH") else "market_avg_closing"

        out.append({
            "date": date,
            "kickoff": (row.get("Time") or "").strip() or None,
            "home": row["HomeTeam"].strip(),
            "away": row["AwayTeam"].strip(),
            "home_goals": hg,
            "away_goals": ag,
            "home_goals_ht": as_int(row.get("HTHG")),
            "away_goals_ht": as_int(row.get("HTAG")),
            "referee": (row.get("Referee") or "").strip() or None,
            "home_shots": as_int(row.get("HS")),
            "away_shots": as_int(row.get("AS")),
            "home_sot": as_int(row.get("HST")),
            "away_sot": as_int(row.get("AST")),
            "home_corners": as_int(row.get("HC")),
            "away_corners": as_int(row.get("AC")),
            "home_fouls": as_int(row.get("HF")),
            "away_fouls": as_int(row.get("AF")),
            "home_yellow": as_int(row.get("HY")),
            "away_yellow": as_int(row.get("AY")),
            "home_red": as_int(row.get("HR")),
            "away_red": as_int(row.get("AR")),
            "odds_home": ch,
            "odds_draw": cd,
            "odds_away": ca,
            "odds_over25": as_float(pick(row, "AvgC>2.5", "B365C>2.5", "BbAv>2.5")),
            "odds_under25": as_float(pick(row, "AvgC<2.5", "B365C<2.5", "BbAv<2.5")),
            "bookmaker": book,
        })
    return out


# ------------------------------------------------------------
# opslaan
# ------------------------------------------------------------


def store_season(
    conn: sqlite3.Connection, league_code: str, season: int, rows: list[dict]
) -> tuple[int, int]:
    inserted = skipped = 0
    for r in rows:
        home_id = store.team_id(conn, league_code, r["home"])
        away_id = store.team_id(conn, league_code, r["away"])

        cur = conn.execute(
            """INSERT OR IGNORE INTO fixtures
               (league_code, season, match_date, kickoff, home_team_id, away_team_id,
                home_goals, away_goals, home_goals_ht, away_goals_ht, referee, status)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,'finished')""",
            (league_code, season, r["date"], r["kickoff"], home_id, away_id,
             r["home_goals"], r["away_goals"], r["home_goals_ht"],
             r["away_goals_ht"], r["referee"]),
        )
        if cur.rowcount == 0:
            skipped += 1
            continue
        inserted += 1
        fid = int(cur.lastrowid)

        for side, tid in (("home", home_id), ("away", away_id)):
            conn.execute(
                """INSERT OR REPLACE INTO fixture_stats
                   (fixture_id, team_id, is_home, shots, shots_on_target,
                    corners, fouls, yellow_cards, red_cards)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (fid, tid, 1 if side == "home" else 0,
                 r[f"{side}_shots"], r[f"{side}_sot"], r[f"{side}_corners"],
                 r[f"{side}_fouls"], r[f"{side}_yellow"], r[f"{side}_red"]),
            )

        if r["odds_home"]:
            conn.execute(
                """INSERT OR REPLACE INTO closing_odds
                   (fixture_id, home, draw, away, over25, under25, bookmaker)
                   VALUES (?,?,?,?,?,?,?)""",
                (fid, r["odds_home"], r["odds_draw"], r["odds_away"],
                 r["odds_over25"], r["odds_under25"], r["bookmaker"]),
            )
    return inserted, skipped


def add_xg_proxy(conn: sqlite3.Connection, league_code: str, season: int) -> int:
    """Leidt een xG-vervanger af uit schoten op doel.

    De methode is bewust simpel en controleerbaar: binnen dezelfde competitie
    en hetzelfde seizoen wordt het aantal schoten op doel geschaald op de
    werkelijke doelpuntenproductie.

        proxy = schoten_op_doel * (totaal doelpunten / totaal schoten op doel)

    Dat behoudt het scoreniveau van de competitie en gebruikt de verhouding
    tussen de ploegen als signaal. Het weet niet vanaf welke positie geschoten
    is, en is daarmee duidelijk grover dan echte xG -- maar het is beschikbaar
    voor twintig seizoenen in plaats van drie, en dat is precies waar deze
    proxy voor bedoeld is: het toetsen van signalen op genoeg waarnemingen.

    Of dit voor het model goed genoeg is, is een empirische vraag. Fit beide
    en vergelijk de Brier score op dezelfde wedstrijden.
    """
    totals = conn.execute(
        """SELECT SUM(f.home_goals + f.away_goals) AS goals,
                  SUM(COALESCE(sh.shots_on_target, 0) + COALESCE(sa.shots_on_target, 0)) AS sot
           FROM fixtures f
           JOIN fixture_stats sh ON sh.fixture_id = f.id AND sh.is_home = 1
           JOIN fixture_stats sa ON sa.fixture_id = f.id AND sa.is_home = 0
           WHERE f.league_code = ? AND f.season = ?
             AND sh.shots_on_target IS NOT NULL AND sa.shots_on_target IS NOT NULL""",
        (league_code, season),
    ).fetchone()

    if not totals or not totals["sot"]:
        return 0  # geen schotdata dit seizoen; dat is normaal voor oude Eredivisie

    rate = totals["goals"] / totals["sot"]

    rows = conn.execute(
        """SELECT s.fixture_id, s.team_id, s.shots_on_target
           FROM fixture_stats s
           JOIN fixtures f ON f.id = s.fixture_id
           WHERE f.league_code = ? AND f.season = ? AND s.shots_on_target IS NOT NULL""",
        (league_code, season),
    ).fetchall()

    conn.executemany(
        "INSERT OR REPLACE INTO fixture_xg (fixture_id, team_id, xg, source) VALUES (?,?,?,'sot_proxy')",
        [(r["fixture_id"], r["team_id"], round(r["shots_on_target"] * rate, 4)) for r in rows],
    )
    return len(rows)


# ------------------------------------------------------------
# rapport
# ------------------------------------------------------------


def coverage_report(conn: sqlite3.Connection) -> None:
    print(f"\n{'=' * 74}")
    print("  DEKKING")
    print(f"{'=' * 74}")
    print(f"  {'Competitie':<16}{'Seizoenen':<22}{'Duels':>8}{'Schoten':>10}{'Slotkoers':>11}")
    print(f"  {'-' * 70}")

    total = 0
    for lg in conn.execute("SELECT code, name FROM leagues ORDER BY name"):
        row = conn.execute(
            """SELECT COUNT(*) n, MIN(season) s0, MAX(season) s1,
                      SUM(CASE WHEN st.shots_on_target IS NOT NULL THEN 1 ELSE 0 END) with_shots,
                      SUM(CASE WHEN o.fixture_id IS NOT NULL THEN 1 ELSE 0 END) with_odds
               FROM fixtures f
               JOIN fixture_stats st ON st.fixture_id = f.id AND st.is_home = 1
               LEFT JOIN closing_odds o ON o.fixture_id = f.id
               WHERE f.league_code = ?""",
            (lg["code"],),
        ).fetchone()
        if not row or not row["n"]:
            continue
        total += row["n"]
        seasons = f"{row['s0']}/{(row['s0']+1)%100:02d} – {row['s1']}/{(row['s1']+1)%100:02d}"
        print(f"  {lg['name']:<16}{seasons:<22}{row['n']:>8}"
              f"{row['with_shots']:>10}{row['with_odds']:>11}")

    print(f"  {'-' * 70}")
    print(f"  {'Totaal':<38}{total:>8}")

    gaps = conn.execute(
        """SELECT l.name, f.season, COUNT(*) n
           FROM fixtures f
           JOIN leagues l ON l.code = f.league_code
           JOIN fixture_stats st ON st.fixture_id = f.id AND st.is_home = 1
           WHERE st.shots_on_target IS NULL
           GROUP BY l.name, f.season ORDER BY l.name, f.season"""
    ).fetchall()
    if gaps:
        print(f"\n  Seizoenen zonder schotdata (alleen uitslagen en quoteringen):")
        by_league: dict[str, list[int]] = {}
        for g in gaps:
            by_league.setdefault(g["name"], []).append(g["season"])
        for name, seasons in by_league.items():
            print(f"    {name:<16}{min(seasons)}–{max(seasons)}  ({len(seasons)} seizoenen)")
    print()


# ------------------------------------------------------------


def main_with_args(
    db: str = DEFAULT_DB,
    from_season: int = 2010,
    to_season: int | None = None,
    leagues: list[str] | None = None,
    refresh: bool = False,
) -> int:
    """De echte logica, zonder argparse ertussen.

    build_site.py roept deze functie direct aan, zodat er maar één versie
    van het inlaadpad bestaat en de geautomatiseerde run niet stilletjes
    iets anders doet dan de handmatige.
    """
    to_season = to_season or dt.date.today().year
    args = argparse.Namespace(
        db=db, from_season=from_season, to_season=to_season,
        leagues=leagues, refresh=refresh,
    )

    conn = store.connect(args.db)
    leagues_rows = conn.execute(
        "SELECT code, name, fd_code FROM leagues ORDER BY name"
    ).fetchall()
    if args.leagues:
        wanted = {c.upper() for c in args.leagues}
        leagues_rows = [l for l in leagues_rows if l["code"] in wanted]
        if not leagues_rows:
            print(f"Geen bekende competitie in {args.leagues}.")
            return 1
    leagues = leagues_rows

    started = dt.datetime.now().isoformat(timespec="seconds")
    cur = conn.execute(
        "INSERT INTO load_runs (source, started_at) VALUES ('fd_couk', ?)", (started,)
    )
    run_id = cur.lastrowid

    total_in = total_skip = 0
    print(f"Inladen {args.from_season}/{(args.from_season+1)%100:02d} t/m "
          f"{args.to_season}/{(args.to_season+1)%100:02d} "
          f"voor {len(leagues)} competities\n")

    for lg in leagues:
        line = f"  {lg['name']:<16}"
        for season in range(args.from_season, args.to_season + 1):
            try:
                text = fetch_csv(season, lg["fd_code"], refresh=args.refresh)
            except Exception as e:
                line += "!"
                print(f"\n    {season}: downloaden mislukt: {e}")
                continue
            if not text:
                line += "·"   # seizoen bestaat niet
                continue

            rows = parse_rows(text)
            ins, skip = store_season(conn, lg["code"], season, rows)
            add_xg_proxy(conn, lg["code"], season)
            conn.commit()
            total_in += ins
            total_skip += skip
            line += "#" if ins else ("=" if skip else "·")
        print(line)

    conn.execute(
        "UPDATE load_runs SET finished_at = ?, status = 'ok', inserted = ?, skipped = ? WHERE id = ?",
        (dt.datetime.now().isoformat(timespec="seconds"), total_in, total_skip, run_id),
    )
    conn.commit()

    print(f"\n  # = nieuw ingeladen   = = al aanwezig   · = niet beschikbaar   ! = fout")
    print(f"\n  {total_in} wedstrijden toegevoegd, {total_skip} al aanwezig.")
    coverage_report(conn)
    print(f"  Database: {Path(args.db).resolve()}")
    print(f"  Ruwe bestanden: {RAW.resolve()}\n")
    return 0


def main() -> int:
    this_year = dt.date.today().year
    ap = argparse.ArgumentParser(description="Laad football-data.co.uk in de database.")
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--from", dest="from_season", type=int, default=2010)
    ap.add_argument("--to", dest="to_season", type=int, default=this_year)
    ap.add_argument("--leagues", nargs="*", default=None, help="bijv. EPL ERE")
    ap.add_argument("--refresh", action="store_true", help="negeer de schijfcache")
    a = ap.parse_args()
    return main_with_args(a.db, a.from_season, a.to_season, a.leagues, a.refresh)


if __name__ == "__main__":
    sys.exit(main())
