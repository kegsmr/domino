import domino.tags as t
from domino import State


PLANS = [
	{"name": "Hobby", "monthly": 0, "text": "For side projects.", "features": ["1 app", "Community support"]},
	{"name": "Pro", "monthly": 19, "text": "For apps people rely on.", "features": ["10 apps", "Email support", "Custom domains"], "featured": True},
	{"name": "Team", "monthly": 49, "text": "For a whole team.", "features": ["Unlimited apps", "Priority support", "SSO"]},
]


# No render(): pricing.html next to this file is its template (a paired Jinja template), styled
# with Tailwind classes like the rest. The toggle's handlers only set State, so clicks show at once
class Pricing(t.section):

	yearly = State(False)


	def plans(self):

		return PLANS


	def show_monthly(self):

		self.yearly = False


	def show_yearly(self):

		self.yearly = True
