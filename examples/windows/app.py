import sys
from pathlib import Path

# The repository root, so the example runs from any folder without installing Domino
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from domino import Domino


# A page that opens a Settings window: `domino desktop examples/windows` shows them as windows of
# their own, `python examples/windows/app.py` as dialogs in the browser
app = Domino(__name__)


if __name__ == "__main__":
	app.run(debug=True)
