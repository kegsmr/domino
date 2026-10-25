import sys
from pathlib import Path

# The repository root, so the example runs from any folder without installing Domino
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from domino import Domino


# Each file in pages/ is a page. "tailwind": true in settings.json does the rest: Tailwind CSS's
# CLI is downloaded once, builds the classes used in pages/ and components/, and every page links it
app = Domino(__name__)


if __name__ == "__main__":
	app.run(debug=True)
