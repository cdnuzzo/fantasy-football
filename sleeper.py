"""Thin client for the free, keyless Sleeper API (api.sleeper.app).

Handles fetching + local caching of the player directory and weekly
projections, plus simple name matching so callers can look players up
by the name they'd naturally type.
"""
import json
import re
import time
import urllib.request
from pathlib import Path

BASE_URL = "https://api.sleeper.app/v1"
CACHE_DIR = Path(__file__).parent / ".cache"

PLAYERS_TTL_SECONDS = 7 * 24 * 60 * 60   # player directory changes rarely
PROJECTIONS_TTL_SECONDS = 60 * 60        # projections firm up during the week
STATS_TTL_SECONDS = 30 * 24 * 60 * 60    # completed-week stats never change

FANTASY_POSITIONS = {"QB", "RB", "WR", "TE", "K"}
LAST_REGULAR_SEASON_WEEK = 18


def _fetch_json(url):
    if not url.startswith("http"):
        url = f"{BASE_URL}{url}"
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.load(resp)


def _cached(cache_name, ttl_seconds, fetch_fn):
    CACHE_DIR.mkdir(exist_ok=True)
    cache_file = CACHE_DIR / cache_name
    if cache_file.exists() and (time.time() - cache_file.stat().st_mtime) < ttl_seconds:
        return json.loads(cache_file.read_text())
    data = fetch_fn()
    cache_file.write_text(json.dumps(data))
    return data


def get_state():
    """Current NFL season/week. Not cached -- it's a tiny request."""
    return _fetch_json("/state/nfl")


def get_players():
    """Full player directory, keyed by player_id. Cached for a week."""
    return _cached("players.json", PLAYERS_TTL_SECONDS,
                   lambda: _fetch_json("/players/nfl"))


def get_projections(season, week):
    """Weekly projections, keyed by player_id. Cached for an hour."""
    return _cached(f"projections_{season}_{week}.json", PROJECTIONS_TTL_SECONDS,
                   lambda: _fetch_json(f"/projections/nfl/regular/{season}/{week}"))


def get_stats(season, week):
    """Actual weekly stats, keyed by player_id. Cached indefinitely --
    a completed week's stats don't change.
    """
    return _cached(f"stats_{season}_{week}.json", STATS_TTL_SECONDS,
                   lambda: _fetch_json(f"/stats/nfl/regular/{season}/{week}"))


def recent_weeks(state, count=3):
    """The `count` most recently completed weeks as (season, week) pairs,
    most recent first, stepping back across a season boundary if needed.
    """
    season = int(state["league_season"])
    week = state["display_week"]
    weeks = []
    while len(weeks) < count:
        week -= 1
        if week < 1:
            season -= 1
            week = LAST_REGULAR_SEASON_WEEK
        weeks.append((season, week))
    return weeks


def _normalize(name):
    return re.sub(r"[^a-z0-9]", "", name.lower())


def find_player(name, players):
    """Return a list of (player_id, info) candidates matching `name`,
    best match first. Prefers rostered, active, skill-position players.
    """
    target = _normalize(name)
    exact, partial = [], []
    for pid, info in players.items():
        search_name = info.get("search_full_name")
        if not search_name:
            continue
        if search_name == target:
            exact.append((pid, info))
        elif target in search_name or search_name in target:
            partial.append((pid, info))

    def sort_key(item):
        _, info = item
        active = info.get("status") == "Active"
        has_team = bool(info.get("team"))
        is_skill_pos = info.get("position") in FANTASY_POSITIONS
        # search_rank: lower means more prominent/well-known (Sleeper-assigned).
        # Negate it so sort(reverse=True) still puts the most prominent player first.
        rank = -(info.get("search_rank") or 9999999)
        return (active, has_team, is_skill_pos, rank)

    candidates = exact if exact else partial
    candidates.sort(key=sort_key, reverse=True)
    return candidates
