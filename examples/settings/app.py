import sys
from pathlib import Path

# The repository root, so the example runs from any folder without installing Domino
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from domino import Domino


# Reads settings.json, then settings.local.json, from this folder; DOMINO_* environment
# variables override both (e.g. DOMINO_PUBLIC__GREETING=Hi)
app = Domino(__name__)


if __name__ == "__main__":
	app.run(debug=True)
