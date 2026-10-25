import domino.tags as t
from domino import State

import store


class Gallery(t.div):

	images = State([])  # ids in the store, newest last
	avatar = State(None)
	message = State("")


	css = {
		"form, .avatar": {"margin": "1rem 0", "padding": "1rem", "border": "1px solid #ddd", "border_radius": "8px"},
		"button": {"font": "inherit", "padding": "0.4rem 1rem"},
		"button[data-loading]": {"opacity": "0.6", "cursor": "progress"},
		# Domino sets data-uploading="<percent>" and --domino-upload-progress (0 to 1) on the
		# form while its files go up: a progress bar and a label from CSS alone
		"form[data-uploading]::after": {
			"content": "''",
			"display": "block",
			"height": "6px",
			"margin_top": "0.75rem",
			"border_radius": "3px",
			"background": "#2a7",
			"width": "calc(var(--domino-upload-progress) * 100%)",
			"transition": "width 0.1s",
		},
		"form[data-uploading]::before": {"content": "'Uploading ' attr(data-uploading) '%'", "display": "block", "color": "#2a7"},
		".message": {"color": "#c33"},
		"ul": {"display": "flex", "flex_wrap": "wrap", "gap": "0.5rem", "padding": 0, "list_style": "none"},
		"ul img": {"width": "96px", "height": "96px", "object_fit": "cover", "border_radius": "4px"},
		".avatar img": {"width": "64px", "height": "64px", "border_radius": "50%", "object_fit": "cover", "vertical_align": "middle"},
	}


	def render(self):

		avatar = [t.img(src=f"/images/{self.avatar}", alt="Avatar")] if self.avatar else []

		return [
			# accept= only filters the file picker; the server checks what arrives
			t.form(on_submit=self.add) [
				t.label() [
					"Photos ",
					t.input(type="file", name="photos", accept="image/*", multiple=True),
				],
				t.button(type="submit") [
					"Upload"
				],
			],
			t.div(class_="avatar") [
				avatar,
				t.label() [
					" Avatar, uploaded as soon as you pick it: ",
					t.input(type="file", name="avatar", accept="image/*", on_change=self.set_avatar),
				],
			],
			t.p(class_="message") [
				self.message
			],
			t.ul() [[
				t.li() [
					t.img(src=f"/images/{id}", alt="Uploaded image")
				]
				for id in self.images
			]],
			t.p() [
				f"{len(self.images)} image(s)"
			],
		]


	def add(self, event):

		# Several files under one name: getlist
		saved = [store.save(file) for file in event.files.getlist("photos")]
		self.images = self.images + [id for id in saved if id]
		self.message = "Only PNG, JPEG, GIF and WebP images, please" if None in saved else ""


	def set_avatar(self, event):

		id = store.save(event.files["avatar"])
		if id:
			self.avatar = id
		self.message = "" if id else "The avatar must be a PNG, JPEG, GIF or WebP image"
