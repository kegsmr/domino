import sys
from pathlib import Path

# The repository root, so the docs run from any folder without installing Domino
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from domino import Domino


# The documentation site, a Domino app itself: each file in pages/ is a page, and the guide's
# pages are made from the repository's README.md when the app starts
app = Domino(__name__)


if __name__ == "__main__":
	app.run(debug=True)
