"""Small ANSI color helper shared by the CLI scripts."""
import os
import sys


class Color:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    CYAN = "\033[36m"


def color_enabled(no_color_flag=False):
    return sys.stdout.isatty() and not no_color_flag and not os.environ.get("NO_COLOR")


def make_painter(enabled):
    if not enabled:
        return lambda text, *_codes: text
    return lambda text, *codes: "".join(codes) + text + Color.RESET


def status_color(injury_status):
    if not injury_status:
        return Color.GREEN
    if injury_status == "Questionable":
        return Color.YELLOW
    return Color.RED  # Out, Doubtful, IR, Suspended, PUP, etc.
