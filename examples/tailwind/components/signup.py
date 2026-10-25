import domino.tags as t
from domino import State


FIELD = (
	"mt-1 block w-full rounded-lg border border-slate-300 bg-white px-3 py-2 shadow-sm "
	"focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/30 "
	"dark:border-slate-700 dark:bg-slate-950"
)


# A form styled with Tailwind. After a submit it thanks the visitor instead
class Signup(t.div):

	name = State("")


	def render(self):

		if self.name:
			return [
				t.div(class_="rounded-2xl bg-emerald-50 p-8 text-center ring-1 ring-emerald-200 dark:bg-emerald-500/10 dark:ring-emerald-500/30") [
					t.h2(class_="text-2xl font-bold text-emerald-800 dark:text-emerald-300") [f"Welcome aboard, {self.name}!"],
					t.p(class_="mt-2 text-emerald-700 dark:text-emerald-400") ["We'll be in touch."],
					t.button(on_click=self.reset, class_="mt-6 text-sm font-semibold text-emerald-800 underline dark:text-emerald-300") ["Sign up someone else"]
				]
			]

		return [
			t.form(on_submit=self.submit, class_="grid gap-8 rounded-2xl bg-slate-50 p-8 ring-1 ring-slate-200 md:grid-cols-2 dark:bg-slate-900 dark:ring-slate-800") [
				t.div() [
					t.h2(class_="text-2xl font-bold tracking-tight") ["Join the beta"],
					t.p(class_="mt-2 text-slate-600 dark:text-slate-400") ["One email when it's ready. No spam."]
				],
				t.div(class_="space-y-4") [
					t.label(class_="block text-sm font-medium") [
						"Name",
						t.input(name="name", required=True, autocomplete="name", class_=FIELD)
					],
					t.label(class_="block text-sm font-medium") [
						"Email",
						t.input(name="email", type="email", required=True, autocomplete="email", class_=FIELD)
					],
					t.label(class_="flex items-center gap-2 text-sm") [
						t.input(name="news", type="checkbox", class_="size-4 rounded accent-indigo-600"),
						"Send me the changelog too"
					],
					t.button(type="submit", class_="w-full rounded-lg bg-indigo-600 px-4 py-2.5 font-semibold text-white shadow-sm hover:bg-indigo-500 data-loading:opacity-60") [
						"Sign up"
					]
				]
			]
		]


	def submit(self, event):

		self.name = (event.form.get("name") or "").strip()[:50] or "friend"


	def reset(self):

		self.name = ""
