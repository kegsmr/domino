"""The parts every docs page shares: the top bar, the sidebar, the table of contents and the
links to the previous and next pages."""

from markupsafe import Markup

import domino.tags as t
from domino import State

import content


# A domino tile, the project's mark
LOGO = Markup(
	'<svg viewBox="0 0 16 28" width="14" height="24" aria-hidden="true">'
	'<rect x="0.75" y="0.75" width="14.5" height="26.5" rx="3" fill="var(--text)"/>'
	'<rect x="3" y="13.6" width="10" height="0.8" fill="var(--bg)"/>'
	'<circle cx="5" cy="5" r="1.4" fill="var(--bg)"/><circle cx="11" cy="9" r="1.4" fill="var(--bg)"/>'
	'<circle cx="8" cy="20.5" r="1.4" fill="var(--accent)"/>'
	'</svg>'
)

GITHUB = Markup(
	'<svg viewBox="0 0 16 16" width="18" height="18" aria-hidden="true" fill="currentColor"><path d="M8 0C3.58 0 0 3.58 0 '
	'8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-'
	'1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-'
	'3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 '
	'2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 '
	'1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></svg>'
)

SUN = Markup(
	'<svg class="sun" viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" fill="none" stroke="currentColor" '
	'stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 '
	'17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>'
)

MOON = Markup(
	'<svg class="moon" viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" fill="none" stroke="currentColor" '
	'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>'
)

MENU = Markup(
	'<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" '
	'stroke-linecap="round"><path d="M4 7h16M4 12h16M4 17h16"/></svg>'
)


class IconButton(t.button):
	"""The top bar's round icon buttons."""

	css = {
		"display": "inline-grid", "place_items": "center",
		"width": "2.25rem", "height": "2.25rem", "padding": 0,
		"border": 0, "border_radius": "8px", "background": "none", "color": "var(--muted)", "cursor": "pointer",
		":hover": {"color": "var(--text)", "background": "var(--hover)"},
	}


class MenuToggle(t.div):
	"""Shows the sidebar on narrow screens. Its handler only changes its own State, so Domino
	renders the other state ahead of time and the browser shows it at once."""

	open = State(False)

	css = {
		"display": "contents",
		"@media (min-width: 64.01rem)": {"display": "none"},
	}


	def render(self):

		return [
			IconButton(type="button", aria_label="Menu", aria_controls="sidebar",
				aria_expanded="true" if self.open else "false", on_click=self.toggle) [
				MENU
			]
		]


	def toggle(self):

		self.open = not self.open


class ThemeToggle(IconButton):
	"""Switches between light and dark. The choice is kept in a cookie, so the server renders
	the next page with it (see pages/layout.py); the docs' little script flips it here."""

	css = {
		".moon": {"display": "none"},
		":root[data-theme=dark] & .sun": {"display": "none"},
		":root[data-theme=dark] & .moon": {"display": "block"},
		"@media (prefers-color-scheme: dark)": {
			":root:not([data-theme=light]) & .sun": {"display": "none"},
			":root:not([data-theme=light]) & .moon": {"display": "block"},
		},
	}


	def init(self):

		self.configure(type="button", aria_label="Switch between light and dark", data_theme_toggle=True)


	def render(self):

		return [SUN, MOON]


class TopBar(t.header):

	css = {
		"position": "sticky", "top": 0, "z_index": "20",
		"display": "flex", "align_items": "center", "gap": "0.75rem",
		"height": "3.75rem", "padding": "0 1rem 0 1.25rem",
		"background": "var(--bar)", "backdrop_filter": "saturate(1.4) blur(10px)",
		"border_bottom": "1px solid var(--line)",
		".brand": {
			"display": "flex", "align_items": "center", "gap": "0.55rem",
			"color": "var(--text)", "text_decoration": "none", "font_weight": "700", "font_size": "1.05rem", "letter_spacing": "-0.01em",
		},
		".version": {
			"font": "500 0.7rem var(--mono)", "color": "var(--muted)", "border": "1px solid var(--line)",
			"padding": "0.1rem 0.4rem", "border_radius": "999px",
		},
		".Search": {"margin_left": "auto"},
		".links": {"display": "flex", "align_items": "center", "gap": "0.15rem"},
		"@media (max-width: 40rem)": {".version": {"display": "none"}, "gap": "0.4rem", "padding": "0 0.5rem"},
	}


	def __init__(self, search):

		self.bar_search = search

		super().__init__()


	def render(self):

		return [
			MenuToggle(),
			t.a(href="/", class_="brand") [
				LOGO,
				"Domino",
				t.span(class_="version") [
					f"v{content.version()}"
				]
			],
			self.bar_search,
			t.div(class_="links") [
				t.a(href="https://github.com/kegsmr/domino", class_="IconButton", aria_label="Domino on GitHub") [
					GITHUB
				],
				ThemeToggle()
			]
		]


class Sidebar(t.nav):
	"""The pages, in groups, the one being shown marked with aria-current."""

	css = {
		"position": "sticky", "top": "3.75rem", "align_self": "start",
		"height": "calc(100vh - 3.75rem)", "overflow_y": "auto",
		"padding": "1.5rem 1rem 3rem 1.25rem", "border_right": "1px solid var(--line)",
		"font_size": "0.92rem",
		"h2": {
			"margin": "1.5rem 0 0.4rem 0.6rem", "font_size": "0.72rem", "font_weight": "600",
			"text_transform": "uppercase", "letter_spacing": "0.08em", "color": "var(--muted)",
		},
		"h2:first-child": {"margin_top": 0},
		"ul": {"list_style": "none", "margin": 0, "padding": 0},
		"a": {
			"display": "block", "padding": "0.32rem 0.6rem", "border_radius": "6px",
			"color": "var(--text-2)", "text_decoration": "none",
		},
		"a:hover": {"background": "var(--hover)", "color": "var(--text)"},
		"a[aria-current=page]": {"background": "var(--accent-bg)", "color": "var(--accent)", "font_weight": "600"},
		# On narrow screens it's hidden until the menu button opens it, over the page
		"@media (max-width: 64rem)": {
			"display": "none",
			"position": "fixed", "z_index": "15", "inset": "3.75rem 0 0 0", "width": "auto", "height": "auto",
			"align_self": "stretch", "background": "var(--bg)", "border_right": 0, "padding": "1.25rem 1.5rem 4rem", "font_size": "1rem",
			":root:has(.MenuToggle [aria-expanded=true]) &": {"display": "block"},
		},
	}


	def init(self):

		self.configure(id="sidebar", aria_label="Documentation")


	def __init__(self, path):

		self.current_path = path

		super().__init__()


	def render(self):

		groups = []
		for group, links in content.NAV:
			groups.append(t.h2() [group])
			groups.append(t.ul()([
				t.li() [
					t.a(href=url, aria_current="page" if url == self.current_path else None) [
						label
					]
				]
				for label, url in links
			]))

		return groups


class Toc(t.aside):
	"""On this page: links to the page's headings, on wide screens."""

	css = {
		"position": "sticky", "top": "5.5rem", "align_self": "start",
		"max_height": "calc(100vh - 7rem)", "overflow_y": "auto",
		"font_size": "0.84rem",
		"p": {"margin": "0 0 0.6rem", "font_weight": "600", "font_size": "0.75rem", "text_transform": "uppercase", "letter_spacing": "0.08em", "color": "var(--muted)"},
		"ul": {"list_style": "none", "margin": 0, "padding": "0 0 0 0.75rem", "border_left": "1px solid var(--line)"},
		"li": {"margin": "0.4rem 0"},
		"a": {"color": "var(--muted)", "text_decoration": "none"},
		"a:hover": {"color": "var(--text)"},
		"@media (max-width: 80rem)": {"display": "none"},
	}


	def __init__(self, headings):

		self.toc_headings = headings

		super().__init__()


	def render(self):

		if not self.toc_headings:
			return []

		return [
			t.p() [
				"On this page"
			],
			t.ul()([
				t.li() [
					t.a(href=f"#{anchor}") [
						title
					]
				]
				for title, anchor in self.toc_headings
			])
		]


class Pager(t.nav):
	"""Links to the previous and next pages, in the sidebar's order."""

	css = {
		"display": "grid", "grid_template_columns": "1fr 1fr", "gap": "1rem",
		"margin_top": "4rem", "padding_top": "1.5rem", "border_top": "1px solid var(--line)",
		"a": {
			"display": "block", "padding": "0.85rem 1rem", "border": "1px solid var(--line)", "border_radius": "10px",
			"color": "var(--text)", "text_decoration": "none", "transition": "border-color .15s",
		},
		"a:hover": {"border_color": "var(--accent)"},
		"small": {"display": "block", "color": "var(--muted)", "font_size": "0.78rem", "margin_bottom": "0.15rem"},
		".next": {"grid_column": "2", "text_align": "right"},
	}


	def __init__(self, path):

		self.pager_path = path

		super().__init__()


	def init(self):

		self.configure(aria_label="Previous and next pages")


	def render(self):

		before, after = content.neighbors(self.pager_path)
		links = []
		if before:
			links.append(t.a(href=before[1], class_="previous", rel="prev") [t.small() ["Previous"], before[0]])
		if after:
			links.append(t.a(href=after[1], class_="next", rel="next") [t.small() ["Next"], after[0]])

		return links
