import sys
from pathlib import Path

# The repository root, so the example runs from any folder without installing Domino
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from domino import Domino


# A canvas everyone paints together: pages/index.html, components/studio.py and studio.html
app = Domino(__name__)


if __name__ == "__main__":
	app.run(debug=True)
