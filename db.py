"""
Opslag voor fase 1: SQLite in plaats van Postgres.

Waarom SQLite om te beginnen: geen server, geen account, geen hosting. Het
schema is met opzet hetzelfde van vorm als schema.sql, zodat de overstap naar
Postgres in fase 2 een migratie is en geen herbouw.

Eén conventie die overal geldt: alles wat het model in gaat krijgt een
`source`-kolom. Zodra je niet meer kunt zien of een getal gemeten of geschat
is, kun je ook niet meer zien of een tip ergens op berust.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS leagues (
    code            TEXT PRIMARY KEY,          -- 'EPL'
    name            TEXT NOT NULL,
    country         TEXT NOT NULL,
    fd_code         TEXT NOT NULL UNIQUE,      -- 'E0'
    api_football_id INTEGER,
    understat_name  TEXT,
    -- empirisch gekalibreerd, zie SPEC.md
    rho             REAL NOT NULL DEFAULT -0.074,
    first_half_ratio REAL NOT NULL DEFAULT 0.44,
    xi_per_day      REAL NOT NULL DEFAULT 0.0025
);

CREATE TABLE IF NOT EXISTS teams (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    league_code TEXT NOT NULL REFERENCES leagues(code),
    name        TEXT NOT NULL,
    UNIQUE (league_code, name)
);

-- Naamvarianten tussen bronnen op één plek oplossen. Fuzzy matching mag
-- suggesties doen bij het inladen, nooit stilzwijgend koppelen: één verkeerd
-- gekoppeld team levert onzin-tips op die er volkomen normaal uitzien.
CREATE TABLE IF NOT EXISTS team_aliases (
    source TEXT NOT NULL,                      -- 'fd_couk' | 'api_football' | 'understat'
    alias  TEXT NOT NULL,
    team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    PRIMARY KEY (source, alias)
);

CREATE TABLE IF NOT EXISTS fixtures (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    league_code  TEXT NOT NULL REFERENCES leagues(code),
    season       INTEGER NOT NULL,             -- startjaar: 2023 = 2023/24
    match_date   TEXT NOT NULL,                -- ISO 'YYYY-MM-DD'
    kickoff      TEXT,                         -- 'HH:MM' indien bekend
    home_team_id INTEGER NOT NULL REFERENCES teams(id),
    away_team_id INTEGER NOT NULL REFERENCES teams(id),
    home_goals   INTEGER,
    away_goals   INTEGER,
    home_goals_ht INTEGER,
    away_goals_ht INTEGER,
    referee      TEXT,
    status       TEXT NOT NULL DEFAULT 'finished',
    UNIQUE (league_code, season, match_date, home_team_id, away_team_id)
);

CREATE INDEX IF NOT EXISTS idx_fix_date   ON fixtures (match_date);
CREATE INDEX IF NOT EXISTS idx_fix_league ON fixtures (league_code, season);

-- Stabiele koppeling met externe fixture-ID's. Zonder deze tabel zou een
-- verplaatste wedstrijd door zijn nieuwe datum als tweede fixture verschijnen.
CREATE TABLE IF NOT EXISTS fixture_external_ids (
    source      TEXT NOT NULL,
    external_id TEXT NOT NULL,
    fixture_id  INTEGER NOT NULL UNIQUE REFERENCES fixtures(id) ON DELETE CASCADE,
    PRIMARY KEY (source, external_id)
);

CREATE TABLE IF NOT EXISTS fixture_stats (
    fixture_id      INTEGER NOT NULL REFERENCES fixtures(id) ON DELETE CASCADE,
    team_id         INTEGER NOT NULL REFERENCES teams(id),
    is_home         INTEGER NOT NULL,
    shots           INTEGER,
    shots_on_target INTEGER,
    corners         INTEGER,
    fouls           INTEGER,
    yellow_cards    INTEGER,
    red_cards       INTEGER,
    PRIMARY KEY (fixture_id, team_id)
);

-- xg_source maakt het verschil tussen meten en schatten zichtbaar tot in de UI.
--   understat    : shot-level xG, 2014/15+
--   api_football  : xG uit API-Football, 2023/24+
--   sot_proxy    : afgeleid van schoten op doel (zie load_fdcouk.add_xg_proxy)
CREATE TABLE IF NOT EXISTS fixture_xg (
    fixture_id INTEGER NOT NULL REFERENCES fixtures(id) ON DELETE CASCADE,
    team_id    INTEGER NOT NULL REFERENCES teams(id),
    xg         REAL NOT NULL,
    source     TEXT NOT NULL,
    PRIMARY KEY (fixture_id, team_id, source)
);

-- Slotkoersen zijn de enige objectieve maatstaf waaraan je een signaal kunt
-- afmeten binnen honderden in plaats van duizenden waarnemingen.
CREATE TABLE IF NOT EXISTS closing_odds (
    fixture_id INTEGER PRIMARY KEY REFERENCES fixtures(id) ON DELETE CASCADE,
    home       REAL,
    draw       REAL,
    away       REAL,
    over25     REAL,
    under25    REAL,
    bookmaker  TEXT NOT NULL     -- 'pinnacle_closing' | 'market_avg_closing'
);

CREATE TABLE IF NOT EXISTS load_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source      TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    status      TEXT NOT NULL DEFAULT 'running',
    inserted    INTEGER DEFAULT 0,
    skipped     INTEGER DEFAULT 0,
    notes       TEXT
);
"""

LEAGUE_SEED = [
    # code, naam, land, fd_code, api_football_id, understat_name, rho, fh_ratio
    ("EPL", "Premier League", "Engeland",    "E0",  39,  "EPL",        -0.052, 0.445),
    ("LIG", "La Liga",        "Spanje",      "SP1", 140, "La_liga",    -0.034, 0.435),
    ("SEA", "Serie A",        "Italië",      "I1",  135, "Serie_A",    -0.078, 0.434),
    ("BUN", "Bundesliga",     "Duitsland",   "D1",  78,  "Bundesliga", -0.118, 0.447),
    ("FR1", "Ligue 1",        "Frankrijk",   "F1",  61,  "Ligue_1",    -0.090, 0.442),
    ("ERE", "Eredivisie",     "Nederland",   "N1",  88,  None,         -0.088, 0.440),
]


def connect(path: str | Path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.executemany(
        """INSERT OR IGNORE INTO leagues
           (code, name, country, fd_code, api_football_id, understat_name, rho, first_half_ratio)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        LEAGUE_SEED,
    )
    conn.commit()
    return conn


def team_id(conn: sqlite3.Connection, league_code: str, name: str) -> int:
    """Zoekt of maakt een team, en registreert de bronnaam als alias."""
    name = name.strip()
    row = conn.execute(
        "SELECT team_id FROM team_aliases WHERE source = 'fd_couk' AND alias = ?", (name,)
    ).fetchone()
    if row:
        return row["team_id"]

    row = conn.execute(
        "SELECT id FROM teams WHERE league_code = ? AND name = ?", (league_code, name)
    ).fetchone()
    if row:
        tid = row["id"]
    else:
        cur = conn.execute(
            "INSERT INTO teams (league_code, name) VALUES (?, ?)", (league_code, name)
        )
        tid = int(cur.lastrowid)

    conn.execute(
        "INSERT OR IGNORE INTO team_aliases (source, alias, team_id) VALUES ('fd_couk', ?, ?)",
        (name, tid),
    )
    return tid
