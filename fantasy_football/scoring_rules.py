"""Show your ESPN league's fantasy scoring rules -- only the stat
categories that actually award (nonzero) points.
"""
import typer

from . import espn
from .colors import Color, color_enabled, make_painter
from .espn_stat_labels import STAT_LABELS


def command(
    no_color: bool = typer.Option(False, "--no-color", help="Disable colored output"),
):
    """Show your ESPN league's actual scoring rules."""
    paint = make_painter(color_enabled(no_color))

    config = espn.load_config()
    league_name, rules = espn.get_scoring_settings(config)

    print(paint(f"{league_name or 'Your League'} -- scoring rules", Color.BOLD) + "\n")

    if not rules:
        print(paint("No scoring rules found -- check espn_config.json.", Color.DIM))
        return

    rules.sort(key=lambda r: STAT_LABELS.get(r["stat_id"], "").lower())

    for rule in rules:
        label = STAT_LABELS.get(rule["stat_id"], f"Unknown stat (id {rule['stat_id']})")
        points = rule["points"]
        color = Color.GREEN if points >= 0 else Color.RED
        points_text = paint(f"{points:+g}", color)
        note = paint("  (varies by position)", Color.DIM) if rule["varies_by_slot"] else ""
        print(f"  {label:<40} {points_text}{note}")
