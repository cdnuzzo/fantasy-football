"""Computes fantasy points from Sleeper's raw per-stat projections/actuals
using an ESPN league's own scoring rules, so the "Sleeper" numbers in
compare.py/roster.py reflect your actual league instead of a generic
PPR/half-PPR/standard guess.

ESPN scoring rules are keyed by statId (see espn_stat_labels.py); Sleeper's
stat lines are keyed by their own field names. ESPN_TO_SLEEPER below is the
crosswalk between the two, built and spot-checked against real projection
data -- it only covers stats we could verify a confident 1:1 (or clearly
combined) match for.

Deliberately NOT covered (points/yards mismatch would silently misreport
your league's rules rather than obviously fail):
- Distance-tiered kicker scoring (ESPN buckets FG/miss by 0-39/40-49/50+
  etc.; Sleeper's kicker fields don't cleanly line up with those bucket
  boundaries)
- Distance-tiered points-allowed / yards-allowed defense scoring (ESPN's
  brackets, e.g. 18-21 and 22-27, don't match Sleeper's own brackets,
  e.g. 14-20 and 21-27)
- Yardage-based TD bonuses (40+/50+ yard TD, 0-9/10-19/etc yard TD) --
  Sleeper's closest fields (e.g. rush_40p) represent plays of that length,
  which isn't verified to mean "touchdown of that length" specifically
- Return-yardage/return-TD combination rules and IDP (individual defense)
  tackling stats

Any league rule that lands on one of these falls into `unmapped_rules()`
so callers can surface it rather than silently underscoring/overscoring.
"""

FORMAT_FIELDS = {
    "ppr": "pts_ppr",
    "half_ppr": "pts_half_ppr",
    "std": "pts_std",
}

ESPN_TO_SLEEPER = {
    # Passing
    0: "pass_att",
    1: "pass_cmp",
    2: "pass_inc",
    3: "pass_yd",
    4: "pass_td",
    19: "pass_2pt",
    20: "pass_int",
    64: "pass_sack",
    # Rushing
    23: "rush_att",
    24: "rush_yd",
    25: "rush_td",
    26: "rush_2pt",
    # Receiving (41 and 53 are ESPN's two historical statIds for the same
    # "each reception" rule -- map both to Sleeper's one field)
    41: "rec",
    53: "rec",
    42: "rec_yd",
    43: "rec_td",
    44: "rec_2pt",
    58: "rec_tgt",
    # Fumbles
    68: "fum",
    72: "fum_lost",
    # Kicking -- flat totals only, see module docstring
    83: "fgm",
    84: "fga",
    86: "xpm",
    87: "xpa",
    88: "xpmiss",
    # Team defense
    95: "int",
    96: "fum_rec",
    97: "blk_kick",
    98: "safe",
    99: "sack",
    101: "def_kr_td",
    102: "def_pr_td",
    103: "pass_int_td",
    104: "def_fum_td",
    106: "ff",
    # Misc
    210: "gp",
}

# Rules that need more than one Sleeper field summed together.
COMBINED_ESPN_TO_SLEEPER = {
    94: ("pass_int_td", "def_fum_td"),  # "Fumble or INT Return for TD"
}


def unmapped_rules(rules):
    """League scoring rules we can't compute from Sleeper's stat fields."""
    return [r for r in rules
            if r["stat_id"] not in ESPN_TO_SLEEPER and r["stat_id"] not in COMBINED_ESPN_TO_SLEEPER]


def compute_points(stat_line, rules):
    """(total_points, unmapped_rules) for one player's raw Sleeper stat
    line, scored against a list of {stat_id, points} league rules."""
    total = 0.0
    unmapped = []
    for rule in rules:
        stat_id = rule["stat_id"]
        if stat_id in COMBINED_ESPN_TO_SLEEPER:
            value = sum(stat_line.get(f, 0) or 0 for f in COMBINED_ESPN_TO_SLEEPER[stat_id])
        elif stat_id in ESPN_TO_SLEEPER:
            value = stat_line.get(ESPN_TO_SLEEPER[stat_id], 0) or 0
        else:
            unmapped.append(rule)
            continue
        total += value * rule["points"]
    return total, unmapped


def make_scorer(format_name, rules=None):
    """Returns a `score(stat_line) -> float|None` callable. `format_name`
    is one of FORMAT_FIELDS' keys, or "league" to score against `rules`
    (a list of {stat_id, points} from espn.get_scoring_settings)."""
    if format_name == "league":
        def score(stat_line):
            if not stat_line:
                return None
            return compute_points(stat_line, rules or [])[0]
        return score

    field = FORMAT_FIELDS[format_name]

    def score(stat_line):
        if not stat_line:
            return None
        return stat_line.get(field)
    return score
