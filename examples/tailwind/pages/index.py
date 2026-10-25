import domino.tags as t

from components.signup import Signup


FEATURES = [
	("Python components", "Subclass a tag, keep state in State, return children from render(). No JavaScript to write."),
	("Live by default", "Change data and every open page re-renders the components showing it, over one WebSocket."),
	("Instant clicks", "Simple handlers are predicted in the browser, so toggles and tabs answer before the server does."),
	("Pages from files", "pages/about.py is /about. Layouts nest, tests sit next to their page."),
	("Tailwind built in", "Write classes anywhere. Domino downloads Tailwind's CLI and builds only what you use."),
	("One command to ship", "domino serve runs a worker per core and routes each tab to the worker that has its page."),
]


# The page at /: a hero, a responsive grid of cards and a form, all styled with Tailwind classes
def page():

	return t.div() [
		t.section(class_="mx-auto max-w-6xl px-6 pb-16 pt-20 text-center sm:pt-28") [
			t.p(class_="mx-auto mb-6 w-fit rounded-full bg-indigo-50 px-3 py-1 text-sm font-medium text-indigo-700 ring-1 ring-indigo-200 dark:bg-indigo-500/10 dark:text-indigo-300 dark:ring-indigo-500/30") [
				"New: Tailwind CSS with zero setup"
			],
			t.h1(class_="mx-auto max-w-3xl text-4xl font-extrabold tracking-tight text-balance sm:text-6xl") [
				"Web apps in Python, styled with ",
				t.span(class_="bg-gradient-to-r from-indigo-500 to-sky-500 bg-clip-text text-transparent") ["Tailwind"]
			],
			t.p(class_="mx-auto mt-6 max-w-2xl text-lg text-slate-600 dark:text-slate-400") [
				"Put utility classes on any component, template or page. They just work: no Node, no npm, no config file."
			],
			t.div(class_="mt-10 flex flex-wrap justify-center gap-4") [
				t.a(href="#signup", class_="rounded-lg bg-indigo-600 px-5 py-3 font-semibold text-white shadow-sm hover:bg-indigo-500") [
					"Get started"
				],
				t.a(href="/pricing", class_="rounded-lg px-5 py-3 font-semibold text-slate-700 ring-1 ring-slate-300 hover:bg-slate-50 dark:text-slate-200 dark:ring-slate-700 dark:hover:bg-slate-900") [
					"See pricing"
				]
			]
		],
		t.section(id="features", class_="mx-auto max-w-6xl px-6 py-16") [
			t.h2(class_="text-3xl font-bold tracking-tight") ["Everything in one place"],
			t.div(class_="mt-10 grid gap-6 sm:grid-cols-2 lg:grid-cols-3") [[
				t.article(class_="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm transition hover:-translate-y-0.5 hover:shadow-md dark:border-slate-800 dark:bg-slate-900") [
					t.div(class_="mb-4 grid size-10 place-items-center rounded-lg bg-indigo-600/10 font-bold text-indigo-600 dark:text-indigo-400") [
						str(number)
					],
					t.h3(class_="text-lg font-semibold") [title],
					t.p(class_="mt-2 text-slate-600 dark:text-slate-400") [text]
				]
				for number, (title, text) in enumerate(FEATURES, 1)
			]]
		],
		t.section(id="signup", class_="mx-auto max-w-6xl px-6 py-16") [
			Signup()
		]
	]
