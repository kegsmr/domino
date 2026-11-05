"""`python -m domino` runs the `domino` command (useful when its script isn't on PATH, e.g. on Windows)."""

import sys

from ._cli import main


sys.exit(main())
