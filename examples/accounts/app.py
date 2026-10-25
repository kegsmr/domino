import sys
from pathlib import Path

# The repository root, so the example runs from any folder without installing Domino
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from domino import Domino


# Logins are kept in a session cookie signed with the secret_key setting. In debug mode
# (as below) a random key is made up if there's none, so logins last until a restart;
# set your own in settings.local.json or DOMINO_SECRET_KEY
app = Domino(__name__)


if __name__ == "__main__":
	app.run(debug=True, threaded=True)
