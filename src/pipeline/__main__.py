"""Permet `python -m pipeline`."""

from __future__ import annotations

import sys

from pipeline.cli import main

if __name__ == "__main__":
    sys.exit(main())
