# Fantasy Football Start/Sit Tool

Compares two players and recommends who to start for a given week, using
free weekly projections and stats from the
[Sleeper API](https://docs.sleeper.com/) (no account or API key needed).

## Usage

```
python3 compare.py "Christian McCaffrey" "Bijan Robinson"
python3 compare.py "Josh Allen" "Lamar Jackson" --week 3 --format half_ppr
```

Options:
- `--week N` -- NFL week to compare (defaults to the current week)
- `--season YYYY` -- season year (defaults to the current season)
- `--format ppr|half_ppr|std|league` -- scoring format. Defaults to
  `league` (your actual ESPN league's scoring rules) if `espn_config.json`
  is set up, otherwise `ppr`. Pass this to override either way.
- `--no-color` -- disable colored output (also respected: piping to a
  file/another command, or setting `NO_COLOR`)

When using `league` scoring, points are computed from Sleeper's raw
per-stat projections/actuals weighted by your league's actual point
values (see "League scoring rules" below for how that mapping works
and its limits) -- not Sleeper's own generic PPR/half-PPR/standard
totals.

Player name matching is fuzzy (e.g. `"mccaffrey"` resolves to Christian
McCaffrey) and prefers the most prominent/active match. If a name is
ambiguous, other candidates are listed so you can be more specific.

For each player, the output includes:
- **Status** -- current injury designation (color-coded: green healthy,
  yellow questionable, red out/doubtful/IR/etc.)
- **Projected** -- this week's projected fantasy points
- **Proj. usage** -- position-appropriate projected volume (pass attempts
  for QBs, rush+target touches for RBs, targets for WR/TE)
- **Recent form** -- actual scoring average over the last 3 games they
  played, flagged as trending up/down vs. this week's projection
- **Recent usage** -- actual volume average over that same span
- **Snap share** -- average % of offensive snaps played recently, flagged
  if under 50% (role may be limited)

The recommendation is based primarily on projected points. When two
players are projected within 1 point of each other, it's called a
toss-up and the tiebreaker becomes recent scoring form instead --
the output explains which basis was used. Injury and snap-share
concerns are surfaced as separate cautions regardless of who's favored.

Data is cached in `.cache/` (player directory for a week, weekly
projections for an hour, completed-week stats indefinitely) to avoid
hitting the API on every run.

## Notes

- If a player has no projection, it's usually a bye week or an injury
  (`Out`/`Doubtful`/`IR` etc.), which the tool will call out.
- Possible next steps: matchup/opponent context (e.g. defense strength),
  head-to-head history, or teaching `compare.py` to pull directly from
  your ESPN roster instead of typed names.

## ESPN roster (`roster.py`)

ESPN doesn't have an official public API, but the same unofficial
endpoints the ESPN web app itself uses can list your team's roster.
This only pulls your roster for reference -- projections/recent-form
data still comes from Sleeper via `compare.py`.

### Setup

1. Copy the example config:
   ```
   cp espn_config.example.json espn_config.json
   ```
2. Fill in `league_id`, `season`, and `team_id`. All three are visible
   in the URL when you view your team on the ESPN Fantasy site, e.g.:
   ```
   https://fantasy.espn.com/football/team?leagueId=123456&teamId=1&seasonId=2026
   ```
3. If your league is **private** (most are), you also need `espn_s2`
   and `swid`:
   - Log into fantasy.espn.com in your browser.
   - Open dev tools -> Application (Chrome) or Storage (Firefox) ->
     Cookies -> `https://fantasy.espn.com`.
   - Copy the values of the `espn_s2` and `SWID` cookies into
     `espn_config.json` (keep the curly braces around the SWID value).
   - These are session cookies for your own ESPN account -- they stay
     local in `espn_config.json` (already gitignored) and are only
     ever sent to ESPN. They expire periodically (typically once a
     year, or if you log out), at which point you'll need to re-grab
     them.

### Usage

```
python3 roster.py
python3 roster.py --week 3
python3 roster.py --format ppr   # compare against generic PPR instead
```

Options:
- `--week N` -- NFL week to pull projections for (defaults to the current week)
- `--format ppr|half_ppr|std|league` -- scoring format for the Sleeper
  column (default: `league`, i.e. your actual ESPN scoring rules,
  computed the same way as `compare.py`'s `league` format). The ESPN
  column isn't affected by this -- it always reflects your league's own
  actual scoring settings, straight from ESPN itself.
- `--no-color` -- disable colored output

Lists your starters and bench, QB first (then RB/WR/TE/FLEX/D-ST/K in
typical lineup order), with position, NFL team, injury status, and:
- **Game** -- when that player's team plays this week, with kickoff time
  in Central (e.g. `Sun 9/14 12:00 PM CT`), `<day> Final` once that game
  has finished, `<day> PPD` if postponed, or `BYE` if their team has no
  game this week. Pulled from ESPN's own pro schedule data (exact kickoff
  timestamps, not just a date) -- public season data, no auth needed.
- **ESPN** / **Sleeper** -- each source's projected points (both per
  your league's real scoring settings), always projections regardless
  of whether the game has been played
- **Score** -- the player's actual result for the week, straight from
  ESPN (what actually counts in your league standings). Shows `--`
  until their game is Final, then the real score in bold

A player is matched to Sleeper's data by name, except D/ST which matches
by NFL team code directly (Sleeper has no searchable name for defenses).
If no match is found, that column shows `n/a`.

The banner line shows your team name (pulled from ESPN) and the week
being displayed.

If ESPN rejects the request, the error message will point at what to
check (usually stale `espn_s2`/`swid` or a wrong id).

## League scoring rules (`scoring_rules.py`)

```
python3 scoring_rules.py
```

Prints your league's actual scoring rules pulled from ESPN's settings
(only the stat categories with a nonzero point value -- e.g. if your
league doesn't use return yardage, it won't show up). Positive point
values are green, negative (like interceptions thrown) are red. A rule
flagged `(varies by position)` means ESPN has a different point value
for that stat depending on lineup slot (e.g. a RB rushing for a
receiving TD scored differently than a WR) -- the number shown is the
default/base value.

Stat IDs are translated to readable labels using a mapping transcribed
from the community `espn-api` library's source, rather than guessed --
see `espn_stat_labels.py` for the source link.

### How "league" scoring works (`custom_scoring.py`)

`compare.py --format league` (the default when `espn_config.json`
exists) and `roster.py`'s Sleeper column both compute points by taking
Sleeper's raw per-stat projections/actuals (yards, TDs, receptions,
etc.) and multiplying each by your league's actual point value for
that stat, instead of using Sleeper's own generic PPR/half-PPR/standard
totals.

This crosswalk is solid for the common stuff: passing/rushing/receiving
yards & TDs, receptions, INTs, fumbles lost, 2pt conversions, sacks
(IDP-style), and flat (non-tiered) kicker/defense counting stats. It
deliberately **excludes** anything where Sleeper and ESPN don't cleanly
line up, rather than risk a silently wrong number:
- Distance-tiered kicker scoring (FG/miss by 0-39/40-49/50+ yards, etc.)
- Distance-tiered points-allowed / yards-allowed defense scoring (the
  two APIs use different bracket boundaries)
- Yardage-based TD bonuses (40+/50+ yard TD, etc.)
- Return-yardage/TD combination rules and individual-defender tackling

Any league rule that falls into one of those gets listed in a one-time
note before the output (e.g. "N of your league's scoring rule(s) can't
be computed..."), so it's clear when the Sleeper-based estimate is
incomplete rather than having it look precise and be wrong. This mostly
affects kickers and D/ST -- skill-position (QB/RB/WR/TE) scoring is
rarely affected.
