#!/usr/bin/env python3
"""Compare two fantasy football players and get a start/sit recommendation
for a given week, using free projection and stats data from Sleeper.

Usage:
    python3 compare.py "Christian McCaffrey" "Bijan Robinson"
    python3 compare.py "Josh Allen" "Lamar Jackson" --week 3 --format half_ppr
"""
import argparse
import sys

import custom_scoring
import espn
import sleeper
from colors import Color, color_enabled, make_painter, status_color
from espn_stat_labels import STAT_LABELS

CONCERNING_STATUSES = {"Out", "Doubtful", "IR", "Suspended", "PUP"}
RECENT_GAMES_LOOKBACK = 3

TOSS_UP_MARGIN = 1.0   # projected-point gap below which we lean on recent form instead
LEAN_MARGIN = 3.0      # below this it's a "lean", above it it's a confident start


def volume_label_and_value(position, stat_line):
    """Position-appropriate usage metric: what actually predicts touches."""
    if position == "QB":
        val = stat_line.get("pass_att")
        return "pass attempts", val
    if position == "RB":
        rush = stat_line.get("rush_att") or 0
        tgt = stat_line.get("rec_tgt") or 0
        if rush or tgt:
            return "touches (rush+tgt)", rush + tgt
        return "touches (rush+tgt)", None
    if position in ("WR", "TE"):
        return "targets", stat_line.get("rec_tgt")
    return None, None


def snap_pct(stat_line):
    off_snp = stat_line.get("off_snp")
    tm_off_snp = stat_line.get("tm_off_snp")
    if off_snp is not None and tm_off_snp:
        return 100.0 * off_snp / tm_off_snp
    return None


def compute_recent_form(pid, position, weeks, scorer):
    """Average actual performance over the given (season, week) list,
    skipping weeks the player didn't appear in (bye/injury/inactive).
    """
    games = []
    for season, week in weeks:
        stats = sleeper.get_stats(season, week)
        line = stats.get(pid)
        if not line or line.get("gp") != 1.0:
            continue
        points = scorer(line)
        if points is None:
            continue
        _, volume = volume_label_and_value(position, line)
        games.append({"points": points, "volume": volume, "snap_pct": snap_pct(line)})

    if not games:
        return None

    volumes = [g["volume"] for g in games if g["volume"] is not None]
    snaps = [g["snap_pct"] for g in games if g["snap_pct"] is not None]
    return {
        "games": len(games),
        "avg_points": sum(g["points"] for g in games) / len(games),
        "avg_volume": (sum(volumes) / len(volumes)) if volumes else None,
        "avg_snap_pct": (sum(snaps) / len(snaps)) if snaps else None,
    }


def resolve_player(name, players):
    candidates = sleeper.find_player(name, players)
    if not candidates:
        print(f"Couldn't find any player matching '{name}'.")
        sys.exit(1)
    top = candidates[0]
    others = candidates[1:4]
    if others:
        print(f"Note: '{name}' matched multiple players, using the best guess: "
              f"{top[1].get('full_name')} ({top[1].get('team')} {top[1].get('position')}).")
        print("  Other possible matches: " +
              ", ".join(f"{i.get('full_name')} ({i.get('team')} {i.get('position')})"
                        for _, i in others))
    return top


def build_summary(pid, info, projections, scorer, recent_weeks):
    position = info.get("position")
    proj = projections.get(pid, {})
    volume_label, proj_volume = volume_label_and_value(position, proj)
    return {
        "name": info.get("full_name"),
        "team": info.get("team") or "FA",
        "position": position,
        "injury_status": info.get("injury_status"),
        "points": scorer(proj),
        "volume_label": volume_label,
        "proj_volume": proj_volume,
        "recent": compute_recent_form(pid, position, recent_weeks, scorer),
    }


def print_player_block(label, p, paint):
    header = f"{p['name']} ({p['team']} {p['position']})"
    print(paint(f"{label}: {header}", Color.BOLD, Color.CYAN))

    status_text = p["injury_status"] or "Healthy"
    print(f"  Status:      {paint(status_text, status_color(p['injury_status']))}")

    pts = f"{p['points']:.2f} pts" if p["points"] is not None else paint("no projection available", Color.DIM)
    print(f"  Projected:   {pts}")

    if p["proj_volume"] is not None:
        print(f"  Proj. usage: {p['proj_volume']:.1f} {p['volume_label']}")

    recent = p["recent"]
    if recent:
        trend = ""
        if p["points"]:
            delta_pct = (recent["avg_points"] - p["points"]) / p["points"]
            if delta_pct >= 0.15:
                trend = paint(" (trending up)", Color.GREEN)
            elif delta_pct <= -0.15:
                trend = paint(" (trending down)", Color.RED)
        print(f"  Recent form: {recent['avg_points']:.2f} pts/gm avg "
              f"(last {recent['games']} played){trend}")
        if recent["avg_volume"] is not None:
            print(f"  Recent usage: {recent['avg_volume']:.1f} {p['volume_label']}/gm avg")
        if recent["avg_snap_pct"] is not None:
            snap_note = ""
            if recent["avg_snap_pct"] < 50:
                snap_note = paint(" (limited role)", Color.YELLOW)
            print(f"  Snap share:  {recent['avg_snap_pct']:.0f}%{snap_note}")
    else:
        print(paint(f"  Recent form: no data in the last {RECENT_GAMES_LOOKBACK} weeks checked "
                     "(rookie, inactive, or didn't see the field)", Color.DIM))
    print()


def decide(a, b):
    """Pick a winner. Leans on the projection gap, but falls back to
    recent scoring average as a tiebreaker when the projections are
    a toss-up (within TOSS_UP_MARGIN of each other)."""
    proj_gap = abs(a["points"] - b["points"])
    proj_winner, proj_loser = (a, b) if a["points"] >= b["points"] else (b, a)

    if proj_gap >= TOSS_UP_MARGIN or not a["recent"] or not b["recent"]:
        return {"winner": proj_winner, "loser": proj_loser, "proj_gap": proj_gap, "basis": "projection"}

    recent_gap = abs(a["recent"]["avg_points"] - b["recent"]["avg_points"])
    if recent_gap < 0.05:
        return {"winner": proj_winner, "loser": proj_loser, "proj_gap": proj_gap, "basis": "coin_flip"}

    recent_winner, recent_loser = (a, b) if a["recent"]["avg_points"] >= b["recent"]["avg_points"] else (b, a)
    return {"winner": recent_winner, "loser": recent_loser, "proj_gap": proj_gap,
            "recent_gap": recent_gap, "basis": "recent_form"}


def print_recommendation(a, b, paint):
    if a["points"] is None or b["points"] is None:
        missing, present = (a, b) if a["points"] is None else (b, a)
        reason = f"listed as {missing['injury_status']}" if missing["injury_status"] \
            else "bye week, inactive, or too early for data"
        print(paint(f"Recommendation: START {present['name']}", Color.BOLD, Color.GREEN) +
              f" -- no projection found for {missing['name']} ({reason}).")
        return

    result = decide(a, b)
    winner, loser = result["winner"], result["loser"]
    lead_in = paint(f"Recommendation: START {winner['name']}", Color.BOLD, Color.GREEN)

    if result["basis"] == "projection":
        confidence = "confident" if result["proj_gap"] >= LEAN_MARGIN else "lean"
        print(lead_in + f" ({confidence} start, +{result['proj_gap']:.2f} projected pts "
                         f"over {loser['name']}).")
    elif result["basis"] == "coin_flip":
        print(lead_in + f" -- dead even on both projections and recent scoring "
                         f"(Δ{result['proj_gap']:.2f} pts); basically a coin flip.")
    else:
        print(lead_in + f" -- projections are nearly even (Δ{result['proj_gap']:.2f} pts), "
                         f"so the call comes down to recent form: {winner['name']} has "
                         f"averaged {winner['recent']['avg_points']:.2f} pts/gm over the last "
                         f"{winner['recent']['games']} games vs {loser['name']}'s "
                         f"{loser['recent']['avg_points']:.2f}.")

    for p in (a, b):
        if p["injury_status"] in CONCERNING_STATUSES:
            print(paint(f"  Caution: {p['name']} is listed as {p['injury_status']}", Color.YELLOW) +
                  " -- confirm their status before kickoff.")
        recent = p["recent"]
        if recent and recent["avg_snap_pct"] is not None and recent["avg_snap_pct"] < 50:
            print(paint(f"  Caution: {p['name']} has played under half the offensive snaps "
                        f"recently ({recent['avg_snap_pct']:.0f}%)", Color.YELLOW) +
                  " -- role may be limited.")


def setup_scorer(format_arg, paint):
    """Picks a scoring format and returns (scorer, label_for_header).
    Defaults to your ESPN league's own rules when espn_config.json is
    set up; falls back to generic ppr/half_ppr/std otherwise. --format
    can always override the default explicitly.
    """
    format_name = format_arg
    if format_name is None:
        format_name = "league" if espn.config_exists() else "ppr"

    if format_name == "league":
        config = espn.load_config()
        league_name, rules = espn.get_scoring_settings(config)
        unmapped = custom_scoring.unmapped_rules(rules)
        if unmapped:
            labels = ", ".join(STAT_LABELS.get(r["stat_id"], f"stat {r['stat_id']}") for r in unmapped)
            print(paint(f"Note: {len(unmapped)} of your league's scoring rule(s) can't be "
                        f"computed from Sleeper's data and are excluded from these estimates: "
                        f"{labels}.", Color.DIM) + "\n")
        return custom_scoring.make_scorer("league", rules), f"{league_name or 'your league'} scoring"

    return custom_scoring.make_scorer(format_name), f"{format_name} scoring"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("player_a", help="First player's name")
    parser.add_argument("player_b", help="Second player's name")
    parser.add_argument("--week", type=int, help="NFL week number (defaults to the current week)")
    parser.add_argument("--season", help="Season year (defaults to the current season)")
    parser.add_argument("--format", choices=list(custom_scoring.FORMAT_FIELDS.keys()) + ["league"],
                         default=None,
                         help="Scoring format (default: your ESPN league's rules if "
                              "espn_config.json exists, else ppr)")
    parser.add_argument("--no-color", action="store_true", help="Disable colored output")
    args = parser.parse_args()

    paint = make_painter(color_enabled(args.no_color))
    scorer, format_label = setup_scorer(args.format, paint)

    state = sleeper.get_state()
    season = args.season or state["league_season"]
    week = args.week or state["display_week"]
    recent_weeks = sleeper.recent_weeks(state, count=RECENT_GAMES_LOOKBACK)

    print(paint(f"Comparing for {season} week {week} ({format_label})...", Color.BOLD) + "\n")

    players = sleeper.get_players()
    projections = sleeper.get_projections(season, week)

    pid_a, info_a = resolve_player(args.player_a, players)
    pid_b, info_b = resolve_player(args.player_b, players)
    print()

    a = build_summary(pid_a, info_a, projections, scorer, recent_weeks)
    b = build_summary(pid_b, info_b, projections, scorer, recent_weeks)

    print_player_block("Player A", a, paint)
    print_player_block("Player B", b, paint)

    print_recommendation(a, b, paint)


if __name__ == "__main__":
    main()
