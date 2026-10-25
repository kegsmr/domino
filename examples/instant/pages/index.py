import domino.tags as t
from domino.components import Document

from components.accordion import Accordion
from components.carousel import Carousel
from components.menu import SortMenu
from components.stepper import Stepper
from components.tabs import Tabs


# Plain JavaScript for the latency button: it only sets core.js's latency simulator
LATENCY_SCRIPT = """
function latencyOn() {
    try { return sessionStorage.getItem('domino-latency') === '1000'; } catch (err) { return false; }
}
function showLatency() {
    document.getElementById('latency').textContent = latencyOn()
        ? 'Simulating 1 s of latency (turn off)'
        : 'Simulate 1 s of latency';
}
function toggleLatency() {
    if (latencyOn()) Domino.disableLatencySim(); else Domino.enableLatencySim(1000);
    showLatency();
}
showLatency();
"""


# This file is the page at /
def page():

	page = Document(title="Instant UI") [
		t.h1() [
			"Instant UI"
		],
		t.p(class_="note") [
			"Everything below is written in Python and rendered by the server, yet every click shows at once, "
			"even ten clicks in a row on a slow connection. Turn on the latency simulator and try it: the "
			"dashed outline marks what the server hasn't confirmed yet."
		],
		t.p() [
			t.button(id="latency", type="button", onclick="toggleLatency()") [
				"Simulate 1 s of latency"
			],
			t.span(class_="status") [""]
		],
		t.h2() ["Tabs"],
		Tabs(),
		t.h2() ["Accordion"],
		Accordion(),
		t.h2() ["Dropdown menu"],
		SortMenu(),
		t.h2() ["Stepper"],
		Stepper(),
		t.h2() ["Carousel"],
		Carousel(),
		t.script() [LATENCY_SCRIPT]
	]

	page.theme(
		surface="#ffffff", background="#f8fafc", text="#0f172a", muted="#64748b", accent="#2563eb", line="#e2e8f0",
		dark={"surface": "#1e293b", "background": "#0f172a", "text": "#f1f5f9", "muted": "#94a3b8", "accent": "#60a5fa", "line": "#334155"},
	)
	page.style("body", font_family="system-ui, sans-serif", max_width="40rem", margin="2rem auto", padding="0 1rem",
		background="var(--background)", color="var(--text)", line_height="1.5")
	page.style("button", font="inherit", color="inherit")
	page.style("h2", font_size="1rem", text_transform="uppercase", letter_spacing="0.05em", color="var(--muted)", margin="2rem 0 0.5rem")
	page.style(".note", color="var(--muted)")
	page.style("#latency", padding="0.4rem 0.9rem", cursor="pointer")

	# Shown until the server confirms (core.js marks the component), and while events are in flight
	page.style("[data-predicted]", outline="1px dashed var(--muted)", outline_offset="4px", border_radius="4px")
	page.style(".status", margin_left="0.75rem", color="var(--muted)", font_size="0.9rem")
	page.style("html[data-domino-loading] .status::after", content="'server catching up…'")

	return page
