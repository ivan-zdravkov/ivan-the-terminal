#!/usr/bin/env python3
"""Entry point for `itt run add-game ...`; see addgame.py for commands."""
import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).with_name("addgame.py")), run_name="__main__")
