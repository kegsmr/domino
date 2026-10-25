from domino import Component


# A wrapper: <Card heading="...">anything</Card>. What's inside goes where card.html has <slot />
class Card(Component):

	tag = "section"  # a <section>; a Component is a <div> unless it says otherwise

	heading = ""
	note = None
