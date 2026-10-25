import domino.tags as t


# A wrapper: <Card heading="...">anything</Card>. What's inside goes where card.html has <slot />
class Card(t.section):

	heading = ""
	note = None
