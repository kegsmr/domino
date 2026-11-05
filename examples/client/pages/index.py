import domino.tags as t
from domino import Document

from components.patterns import Patterns
from components.server_stats import ServerTextStats
from components.stats import TextStats


# Plain JavaScript for the status line: client components dispatch domino:client-ready once
# Python is running in the page
STATUS_SCRIPT = """
document.addEventListener('domino:client-ready', (e) => {
    document.getElementById('runtime').textContent =
        `Python (${e.detail.python}) started in ${Math.round(e.detail.startup)} ms; the board and the left counter now run in this tab.`;
});
"""


# This file is the page at /
def page():

	page = Document(title="Client components") [
		t.h1() [
			"Client components"
		],
		t.p(class_="note") [
			"Components with ", t.code() ["client = True"], " run in the browser, in Python: the server renders them once, "
			"so they show before anything loads, and then MicroPython (about 190 KB) takes over. "
			"Their clicks, keystrokes and timers never wait for the server, and keep working offline."
		],
		t.p(id="runtime", class_="note", aria_live="polite") [
			"Loading Python…"
		],
		t.h2() ["Game of Life, in the browser"],
		Patterns(),
		t.h2() ["The same component, two places"],
		t.div(class_="pair") [
			t.div() [t.h3() ["In the browser"], TextStats()],
			t.div() [t.h3() ["On the server"], ServerTextStats()],
		],
		t.script() [STATUS_SCRIPT]
	]

	page.theme(
		surface="#ffffff", background="#f8fafc", text="#0f172a", muted="#64748b", accent="#2563eb", line="#e2e8f0",
		dark={"surface": "#1e293b", "background": "#0f172a", "text": "#f1f5f9", "muted": "#94a3b8", "accent": "#60a5fa", "line": "#334155"},
	)
	page.style("body", font_family="system-ui, sans-serif", max_width="52rem", margin="2rem auto", padding="0 1rem",
		background="var(--background)", color="var(--text)", line_height="1.5")
	page.style("button, textarea", font="inherit", color="inherit", background="var(--surface)", border="1px solid var(--line)", border_radius="4px")
	page.style("button", padding="0.3rem 0.8rem", cursor="pointer")
	page.style("h2", font_size="1rem", text_transform="uppercase", letter_spacing="0.05em", color="var(--muted)", margin="2rem 0 0.5rem")
	page.style("h3", font_size="1rem", margin="1rem 0 0.25rem")
	page.style(".note", color="var(--muted)")
	page.style(".pair", display="grid", grid_template_columns="repeat(auto-fit, minmax(16rem, 1fr))", gap="1.5rem")

	return page
