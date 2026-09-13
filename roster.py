#!/usr/bin/env python3
"""List your ESPN fantasy football roster (starters and bench), ordered
QB-first, with each player's game day/kickoff time (Central), projected
points from both ESPN and Sleeper (both scored per your league's own
scoring settings), and their actual score for the week once final.

Usage:
    python3 roster.py
    python3 roster.py --week 3
    python3 roster.py --format ppr   # compare against generic PPR instead
"""
import argparse

import custom_scoring
import espn
import sleeper
from colors import Color, color_enabled, make_painter, status_color
from espn_stat_labels import STAT_LABELS

BENCH_SLOTS = {"Bench", "IR"}

# Lineup order fantasy managers expect: QB first, then skill positions,
# then D/ST and K. Bench players fall back to POSITION_ORDER by their
# real position since their slot is uniformly "Bench".
SLOT_ORDER = ["QB", "RB", "RB/WR", "WR", "WR/TE", "TE", "FLEX", "OP", "D/ST", "K"]
POSITION_ORDER = ["QB", "RB", "WR", "TE", "D/ST", "K"]


def sort_key(player):
    if player["slot"] in SLOT_ORDER:
        rank = SLOT_ORDER.index(player["slot"])
    elif player["position"] in POSITION_ORDER:
        rank = len(SLOT_ORDER) + POSITION_ORDER.index(player["position"])
    else:
        rank = 99
    return (rank, player["name"] or "")


def attach_sleeper_pid(roster, sleeper_players):
    for player in roster:
        if player["position"] == "D/ST":
            # Sleeper keys team defenses by team abbreviation, not a
            # searchable name -- match directly instead of by name.
            player["_sleeper_pid"] = player["pro_team"] if player["pro_team"] in sleeper_players else None
        else:
            candidates = sleeper.find_player(player["name"], sleeper_players)
            player["_sleeper_pid"] = candidates[0][0] if candidates else None


def attach_sleeper_projection(roster, projections, scorer):
    for player in roster:
        pid = player.get("_sleeper_pid")
        player["sleeper_projected"] = scorer(projections.get(pid, {})) if pid else None


def attach_game_info(roster, pro_schedule, week):
    for player in roster:
        player["game"] = espn.game_for_team(pro_schedule, player["pro_team"], week)


def game_played(player):
    game = player.get("game")
    return game is not None and game["final"]


def format_pts(value):
    return f"{value:.1f}" if value is not None else "n/a"


COLS = dict(slot=6, name=25, team=4, pos=4, game=21, proj=7)


def print_header(paint):
    header = (f"  {'Slot':<{COLS['slot']}} {'Name':<{COLS['name']}} "
              f"{'Team':<{COLS['team']}} {'Pos':<{COLS['pos']}} "
              f"{'Game':<{COLS['game']}} "
              f"{'ESPN':>{COLS['proj']}} {'Sleeper':>{COLS['proj']}} {'Score':>{COLS['proj']}}  Status")
    print(paint(header, Color.DIM))


def print_group(title, players, paint):
    print(paint(title, Color.BOLD, Color.CYAN))
    if not players:
        print(paint("  (none)", Color.DIM))
        print()
        return
    print_header(paint)
    for p in sorted(players, key=sort_key):
        status = p["injury_status"] or "Healthy"
        status_text = paint(status, status_color(p["injury_status"]))
        played = game_played(p)

        espn_text = f"{format_pts(p['espn_projected']):>{COLS['proj']}}"
        sleeper_text = f"{format_pts(p['sleeper_projected']):>{COLS['proj']}}"
        # Actual result for the week -- ESPN's own recorded score, since
        # that's what actually counts in your league standings.
        score_text = f"{format_pts(p['espn_actual']) if played else '--':>{COLS['proj']}}"
        if played:
            score_text = paint(score_text, Color.BOLD)

        print(f"  {p['slot']:<{COLS['slot']}} {p['name']:<{COLS['name']}} "
              f"{p['pro_team']:<{COLS['team']}} {p['position']:<{COLS['pos']}} "
              f"{espn.format_game(p['game']):<{COLS['game']}} "
              f"{espn_text} {sleeper_text} {score_text}  {status_text}")
    print()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--week", type=int, help="NFL week (defaults to the current week)")
    parser.add_argument("--format", choices=list(custom_scoring.FORMAT_FIELDS.keys()) + ["league"],
                         default="league",
                         help="Scoring format for the Sleeper column (default: league, i.e. your "
                              "actual ESPN scoring rules). ESPN's own column always reflects "
                              "your league's real settings regardless of this flag.")
    parser.add_argument("--no-color", action="store_true", help="Disable colored output")
    args = parser.parse_args()
    paint = make_painter(color_enabled(args.no_color))

    state = sleeper.get_state()
    season = state["league_season"]
    week = args.week or state["display_week"]

    config = espn.load_config()
    team_name, roster = espn.get_my_roster(config, week=week)

    if args.format == "league":
        league_name, rules = espn.get_scoring_settings(config)
        unmapped = custom_scoring.unmapped_rules(rules)
        if unmapped:
            labels = ", ".join(STAT_LABELS.get(r["stat_id"], f"stat {r['stat_id']}") for r in unmapped)
            print(paint(f"Note: {len(unmapped)} of your league's scoring rule(s) can't be "
                        f"computed from Sleeper's data and are excluded from the Sleeper "
                        f"column: {labels}.", Color.DIM) + "\n")
        scorer = custom_scoring.make_scorer("league", rules)
    else:
        scorer = custom_scoring.make_scorer(args.format)

    sleeper_players = sleeper.get_players()
    projections = sleeper.get_projections(season, week)
    pro_schedule = espn.get_pro_schedule(season)

    attach_sleeper_pid(roster, sleeper_players)
    attach_sleeper_projection(roster, projections, scorer)
    attach_game_info(roster, pro_schedule, week)

    print(paint(f"{team_name or 'My Team'} -- Week {week} ({season})", Color.BOLD) + "\n")

    starters = [p for p in roster if p["slot"] not in BENCH_SLOTS]
    bench = [p for p in roster if p["slot"] in BENCH_SLOTS]

    print_group("Starters", starters, paint)
    print_group("Bench", bench, paint)


if __name__ == "__main__":
    main()
