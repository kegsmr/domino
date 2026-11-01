from flask import request

import domino.tags as t
from domino import Document

import content
from components.search import Search
from components.shell import Pager, Sidebar, TopBar


# The colors, as CSS variables: light, and dark for visitors whose system prefers it (or who
# chose it with the theme button, which the server reads from the cookie below)
LIGHT = {
	"bg": "#ffffff", "surface": "#ffffff", "surface-2": "#f7f7f9", "bar": "rgba(255, 255, 255, 0.82)",
	"text": "#18181b", "text-2": "#3f3f46", "muted": "#71717a", "line": "#e7e7eb", "hover": "#f2f2f5",
	"accent": "#4f46e5", "accent-bg": "#eef0ff", "demo-accent": "#4f46e5", "accent-soft": "#c7c9f6", "live": "#16a34a", "live-soft": "#dcfce7",
	"inline-code": "#f2f2f5", "code-bg": "#fafafb", "code-text": "#24292f",
	"tok-comment": "#6e7781", "tok-keyword": "#cf222e", "tok-string": "#0a3069", "tok-function": "#8250df",
	"tok-name": "#953800", "tok-number": "#0550ae",
	"shadow": "0 1px 2px rgba(16, 16, 24, 0.04), 0 4px 16px rgba(16, 16, 24, 0.05)",
	"shadow-lg": "0 12px 32px rgba(16, 16, 24, 0.14)",
}

DARK = {
	"bg": "#0f0f12", "surface": "#16161a", "surface-2": "#1b1b20", "bar": "rgba(15, 15, 18, 0.8)",
	"text": "#ececf1", "text-2": "#c4c4cc", "muted": "#8e8e99", "line": "#27272e", "hover": "#1f1f25",
	"accent": "#a5a8ff", "accent-bg": "#23234a", "demo-accent": "#5b5ff0", "accent-soft": "#45468a", "live": "#4ade80", "live-soft": "#14532d",
	"inline-code": "#1f1f25", "code-bg": "#131317", "code-text": "#e6edf3",
	"tok-comment": "#8b949e", "tok-keyword": "#ff7b72", "tok-string": "#a5d6ff", "tok-function": "#d2a8ff",
	"tok-name": "#ffa657", "tok-number": "#79c0ff",
	"shadow": "0 1px 2px rgba(0, 0, 0, 0.3), 0 4px 16px rgba(0, 0, 0, 0.25)",
	"shadow-lg": "0 12px 32px rgba(0, 0, 0, 0.5)",
}

THEMES = {"light": LIGHT, "dark": DARK}

# Kept small and plain: the copy buttons, the theme button and "/" to search. Listeners on the
# document keep working when a link swaps the next page in
SCRIPT = """
document.addEventListener('click', function (event) {
	var copy = event.target.closest('[data-copy]');
	if (copy) {
		var code = copy.closest('figure').querySelector('pre');
		navigator.clipboard.writeText(code.innerText).then(function () {
			copy.textContent = 'Copied';
			copy.setAttribute('data-copied', '');
			setTimeout(function () { copy.textContent = 'Copy'; copy.removeAttribute('data-copied'); }, 1500);
		});
	}
	var toggle = event.target.closest('[data-theme-toggle]');
	if (toggle) {
		var root = document.documentElement;
		var dark = root.dataset.theme ? root.dataset.theme === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
		root.dataset.theme = dark ? 'light' : 'dark';
		document.cookie = 'theme=' + root.dataset.theme + '; path=/; max-age=31536000; samesite=lax';
	}
});
document.addEventListener('keydown', function (event) {
	var field = event.target.closest && event.target.closest('input, textarea, select, [contenteditable]');
	if (event.key === '/' && !field && !event.metaKey && !event.ctrlKey) {
		event.preventDefault();
		document.querySelector('.Search input').focus();
	} else if (event.key === 'Escape' && event.target.closest && event.target.closest('.Search')) {
		document.activeElement.blur();
	}
});
"""


def variables(colors):

	return {f"--{name}": value for name, value in colors.items()}


# Wraps every page: the top bar, the sidebar, the page, and links to the pages around it
def layout(content_):

	path = request.path
	title = content.TITLES.get(path)

	page = Document(title=f"{title} · Domino" if title and path != "/" else "Domino — Python web apps, live in the browser") [
		TopBar(Search()),
		t.div(class_="frame") [
			Sidebar(path),
			t.main(id="content") [
				content_,
				Pager(path)
			]
		],
		t.script() [
			SCRIPT
		]
	]
	page.head.add_children([
		t.meta(name="description", content="Domino is a Python web framework: components on the server, live in the browser, with no JavaScript to write."),
		t.meta(name="color-scheme", content="light dark"),
	])

	# Chosen with the theme button; otherwise the system's preference decides
	theme = request.cookies.get("theme")
	if theme in THEMES:
		page.configure(data_theme=theme)

	page.theme(**variables(LIGHT), dark=variables(DARK))
	for name, colors in THEMES.items():
		page.style(f":root[data-theme={name}]", variables(colors))
	page.style(":root", {
		"--sans": "ui-sans-serif, system-ui, -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif",
		"--mono": "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, 'Liberation Mono', monospace",
		"color-scheme": "light",
	})
	page.style(":root[data-theme=dark]", {"color-scheme": "dark"})
	page.style("@media (prefers-color-scheme: dark)", {":root:not([data-theme=light])": {"color-scheme": "dark"}})
	page.style("*, *::before, *::after", box_sizing="border-box")
	page.style("html", scroll_padding_top="4.5rem", _webkit_text_size_adjust="100%")
	page.style("body", margin=0, font="16px/1.6 var(--sans)", color="var(--text)", background="var(--bg)",
		_webkit_font_smoothing="antialiased")
	page.style("a", color="var(--accent)")
	page.style(":focus-visible", outline="2px solid var(--accent)", outline_offset="2px")
	page.style(".frame", {
		"display": "grid", "grid_template_columns": "17rem minmax(0, 1fr)", "max_width": "90rem", "margin": "0 auto",
		"@media (max-width: 64rem)": {"grid_template_columns": "minmax(0, 1fr)"},
	})
	page.style("main", {
		"min_width": "0", "padding": "2.5rem clamp(1rem, 4vw, 3.5rem) 5rem",
		"h1": {"font_size": "clamp(1.9rem, 4vw, 2.4rem)", "line_height": "1.15", "letter_spacing": "-0.025em", "margin": "0 0 0.75rem"},
		"h1:focus": {"outline": "none"},
		".eyebrow": {"margin": "0 0 0.5rem", "font_size": "0.8rem", "font_weight": "600", "color": "var(--accent)", "letter_spacing": "0.02em"},
		".lead": {"font_size": "1.15rem", "color": "var(--text-2)", "margin": "0 0 2rem", "line_height": "1.6"},
	})
	# The page and its table of contents, side by side on wide screens
	page.style(".doc", {
		"display": "grid", "grid_template_columns": "minmax(0, 46rem) 13rem", "gap": "3.5rem", "justify_content": "space-between",
		"@media (max-width: 80rem)": {"grid_template_columns": "minmax(0, 46rem)"},
	})
	page.style("main > .Pager", max_width="46rem")
	# Before a link's page arrives, a thin bar at the top
	page.style("html[data-domino-loading] body::before", {
		"content": "''", "position": "fixed", "top": 0, "left": 0, "height": "2px", "width": "100%", "z_index": "50",
		"background": "linear-gradient(90deg, transparent, var(--accent), transparent)",
		"animation": "loading 1s linear infinite",
	})
	page.style("@keyframes loading", {"from": {"transform": "translateX(-100%)"}, "to": {"transform": "translateX(100%)"}})

	return page
