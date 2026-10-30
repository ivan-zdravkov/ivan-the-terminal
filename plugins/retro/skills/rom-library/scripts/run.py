#!/usr/bin/env python3
"""Entry point for `itt run rom-library ...`; see romlib.py for commands."""
import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).with_name("romlib.py")), run_name="__main__")
