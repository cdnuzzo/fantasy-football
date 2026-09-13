"""Thin client for ESPN's unofficial fantasy football API.

There's no official public API for ESPN fantasy football; this uses the
same endpoints the ESPN web app itself calls. For a private league (the
common case) it needs the `espn_s2` and `SWID` cookies from a browser
logged into your ESPN account -- see README.md for how to grab those.
"""
import gzip
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from .paths import CACHE_DIR, CONFIG_PATH

# The old fantasy.espn.com/apis/v3/... host now just redirects to the
# marketing site; the live API sits behind this read host instead.
URL_TEMPLATE = ("https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{season}"
                "/segments/0/leagues/{league_id}")
# Season-level, not tied to any one league -- no auth cookies needed.
PRO_SCHEDULE_URL = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{season}?view=proTeamSchedules"
PRO_SCHEDULE_TTL_SECONDS = 15 * 60  # game status/kickoff can matter on game day

CENTRAL = ZoneInfo("America/Chicago")

POSITION_MAP = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "D/ST"}

SLOT_MAP = {
    0: "QB", 2: "RB", 3: "RB/WR", 4: "WR", 5: "WR/TE", 6: "TE", 7: "OP",
    16: "D/ST", 17: "K", 20: "Bench", 21: "IR", 23: "FLEX",
}

PRO_TEAM_MAP = {
    0: "FA", 1: "ATL", 2: "BUF", 3: "CHI", 4: "CIN", 5: "CLE", 6: "DAL",
    7: "DEN", 8: "DET", 9: "GB", 10: "TEN", 11: "IND", 12: "KC", 13: "LV",
    14: "LAR", 15: "MIA", 16: "MIN", 17: "NE", 18: "NO", 19: "NYG",
    20: "NYJ", 21: "PHI", 22: "ARI", 23: "PIT", 24: "LAC", 25: "SF",
    26: "SEA", 27: "TB", 28: "WAS", 29: "CAR", 30: "JAX", 33: "BAL", 34: "HOU",
}

INJURY_STATUS_MAP = {
    "QUESTIONABLE": "Questionable",
    "DOUBTFUL": "Doubtful",
    "OUT": "Out",
    "INJURY_RESERVE": "IR",
    "SUSPENSION": "Suspended",
    "PROBATION": "PUP",
}


def config_exists():
    return CONFIG_PATH.exists()


def load_config():
    if not CONFIG_PATH.exists():
        raise SystemExit(
            f"No ESPN config found at {CONFIG_PATH}.\n"
            "Copy espn_config.example.json to espn_config.json and fill in "
            "your league_id, season, team_id, and (for a private league) "
            "espn_s2 / swid. See README.md for how to find these."
        )
    config = json.loads(CONFIG_PATH.read_text())
    missing = [k for k in ("league_id", "season", "team_id") if not config.get(k)]
    if missing:
        raise SystemExit(f"espn_config.json is missing required field(s): {', '.join(missing)}")
    return config


def _fetch_league(config, views):
    url = URL_TEMPLATE.format(season=config["season"], league_id=config["league_id"])
    query = "&".join(f"view={v}" for v in views)
    headers = {
        # ESPN's CDN gzips responses regardless of what we advertise, and
        # some edge nodes reject requests with no User-Agent at all.
        "User-Agent": "Mozilla/5.0 (fantasy-football-cli)",
        "Accept": "application/json",
    }
    if config.get("espn_s2") and config.get("swid"):
        headers["Cookie"] = f"espn_s2={config['espn_s2']}; SWID={config['swid']}"

    request = urllib.request.Request(f"{url}?{query}", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as resp:
            raw = resp.read()
            if resp.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            text = raw.decode("utf-8")
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 404):
            # ESPN returns 404 (not 401/403) for a private league when the
            # request isn't authenticated, indistinguishable from a truly
            # wrong league_id.
            raise SystemExit(
                f"ESPN returned {e.code} for league_id={config['league_id']}, "
                f"season={config['season']}. Either: the league_id/season is wrong, "
                "or this is a private league and espn_s2/swid are missing, wrong, "
                "or expired. Re-check the URL on fantasy.espn.com and re-grab the "
                "cookies from your browser if needed."
            ) from e
        raise

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise SystemExit(
            "ESPN didn't return JSON -- likely a bad league_id/season, or a private "
            "league without valid espn_s2/swid. First 200 chars of the response:\n"
            f"{text[:200]!r}"
        ) from e


def _normalize_injury_status(raw):
    if not raw or raw == "ACTIVE":
        return None
    return INJURY_STATUS_MAP.get(raw, raw.title())


# statSourceId: 0 = actual stats, 1 = projected stats.
ACTUAL_STAT_SOURCE_ID = 0
PROJECTED_STAT_SOURCE_ID = 1


def _applied_total(player_stats, scoring_period_id, stat_source_id):
    """Pull a fantasy point total (per your league's own scoring settings)
    out of a player's `stats` list, if present, for the given source
    (projected vs actual)."""
    for stat_line in player_stats or []:
        if (stat_line.get("scoringPeriodId") == scoring_period_id
                and stat_line.get("statSourceId") == stat_source_id):
            return stat_line.get("appliedTotal")
    return None


def get_my_roster(config, week=None):
    """Returns (team_name, [player dicts]) for the configured team_id.

    `week` overrides which scoring period to pull ESPN's projection/actual
    for; defaults to the league's current period.
    """
    data = _fetch_league(config, ["mRoster", "mTeam"])
    scoring_period_id = week or data.get("scoringPeriodId")

    team_id = config["team_id"]
    team = next((t for t in data.get("teams", []) if t.get("id") == team_id), None)
    if team is None:
        available = [t.get("id") for t in data.get("teams", [])]
        raise SystemExit(f"No team with id {team_id} in this league. Team ids found: {available}")

    roster = []
    for entry in team.get("roster", {}).get("entries", []):
        player = entry.get("playerPoolEntry", {}).get("player", {})
        stats = player.get("stats")
        roster.append({
            "name": player.get("fullName"),
            "position": POSITION_MAP.get(player.get("defaultPositionId"), "?"),
            "pro_team": PRO_TEAM_MAP.get(player.get("proTeamId"), "?"),
            "slot": SLOT_MAP.get(entry.get("lineupSlotId"), f"Slot {entry.get('lineupSlotId')}"),
            "injury_status": _normalize_injury_status(player.get("injuryStatus")),
            "espn_projected": _applied_total(stats, scoring_period_id, PROJECTED_STAT_SOURCE_ID),
            "espn_actual": _applied_total(stats, scoring_period_id, ACTUAL_STAT_SOURCE_ID),
        })

    # Current ESPN API uses a single "name" field; older leagues/exports
    # may still split it into location + nickname.
    team_name = team.get("name") or f"{team.get('location', '')} {team.get('nickname', '')}".strip()
    return team_name, roster


def get_scoring_settings(config):
    """Returns (league_name, [{stat_id, points, varies_by_slot}]) -- only
    scoring rules with a nonzero point value, i.e. rules your league
    actually uses."""
    data = _fetch_league(config, ["mSettings"])
    settings = data.get("settings", {})
    scoring_items = settings.get("scoringSettings", {}).get("scoringItems", [])

    rules = []
    for item in scoring_items:
        points = item.get("points")
        if not points:
            continue
        rules.append({
            "stat_id": item.get("statId"),
            "points": points,
            "varies_by_slot": bool(item.get("pointsOverrides")),
        })
    return settings.get("name"), rules


def _cached(cache_name, ttl_seconds, fetch_fn):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / cache_name
    if cache_file.exists() and (time.time() - cache_file.stat().st_mtime) < ttl_seconds:
        return json.loads(cache_file.read_text())
    data = fetch_fn()
    cache_file.write_text(json.dumps(data))
    return data


def _fetch_pro_schedule(season):
    headers = {"User-Agent": "Mozilla/5.0 (fantasy-football-cli)", "Accept": "application/json"}
    request = urllib.request.Request(PRO_SCHEDULE_URL.format(season=season), headers=headers)
    with urllib.request.urlopen(request, timeout=30) as resp:
        raw = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        data = json.loads(raw.decode("utf-8"))

    # Trim down to just what we need -- the full payload includes
    # play-by-play for every completed game, which we don't want to cache.
    schedule = {}
    for team in data.get("settings", {}).get("proTeams", []):
        abbrev = team.get("abbrev")
        if not abbrev:
            continue
        by_week = {"bye_week": team.get("byeWeek")}
        for week_str, games in (team.get("proGamesByScoringPeriod") or {}).items():
            if not games:
                continue
            game = games[0]
            by_week[week_str] = {
                "date_ms": game.get("date"),
                "postponed": bool(game.get("postponed")),
                "final": game.get("detail") == "Final",
            }
        schedule[abbrev] = by_week
    return schedule


def get_pro_schedule(season):
    """{team_abbrev: {"bye_week": N, <week>: {date_ms, postponed, final}}}
    for every NFL team's full-season schedule. This is public season
    metadata (not tied to any one league), so no auth cookies needed.
    """
    return _cached(f"pro_schedule_{season}.json", PRO_SCHEDULE_TTL_SECONDS,
                   lambda: _fetch_pro_schedule(season))


def game_for_team(pro_schedule, team_abbrev, week):
    """This team's game info for `week`, or None if they're on a bye."""
    return pro_schedule.get(team_abbrev, {}).get(str(week))


def format_game(game):
    """Human-readable game status: 'Sun 9/14 1:00 PM CT' before kickoff,
    'Sun 9/14 Final' once played, 'BYE' if there's no game that week."""
    if game is None:
        return "BYE"
    dt = datetime.fromtimestamp(game["date_ms"] / 1000, tz=timezone.utc).astimezone(CENTRAL)
    day_str = dt.strftime("%a %-m/%-d")
    if game["postponed"]:
        return f"{day_str} PPD"
    if game["final"]:
        return f"{day_str} Final"
    return f"{day_str} {dt.strftime('%-I:%M %p CT')}"
