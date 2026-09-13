"""Shared config/cache locations.

Deliberately NOT relative to this file's location: once installed as a
real package, the source can live anywhere (e.g. site-packages), but the
user's own config and cached API data should live somewhere stable
regardless of how/where the tool is installed or invoked from.
"""
from pathlib import Path

BASE_DIR = Path.home() / ".fantasy-football"
CACHE_DIR = BASE_DIR / "cache"
CONFIG_PATH = BASE_DIR / "espn_config.json"
