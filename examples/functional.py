import sys

sys.path.append("")

import domino.tags as t
from domino import Domino
from domino.components import Document


app = Domino(__name__)


# --- Define pages ---

@app.route("/")
def home():
    return Document("Home")[
        t.h1()["Welcome to My Website"],
        t.p()["This is the home page."],
        t.nav()[
            t.a(href=about)["About"],
            " | ",
            t.a(href=contact)["Contact"]
        ]
    ]


@app.route("/about")
def about():
    return Document("About")[
        t.h1()["About"],
        t.p()[
            "This site was built with the Domino web framework in Python."
        ],
        t.nav()[
            t.a(href=home)["Home"],
            " | ",
            t.a(href=contact)["Contact"]
        ]
    ]


@app.route("/contact")
def contact():
    return Document("Contact")[
        t.h1()["Contact"],
        t.p()[
            "You can reach us at ",
            t.a(href="mailto:info@example.com")["info@example.com"],
            "."
        ],
        t.nav()[
            t.a(href=home)["Home"],
            " | ",
            t.a(href=about)["About"]
        ]
    ]


if __name__ == "__main__":
    app.run(debug=True)
