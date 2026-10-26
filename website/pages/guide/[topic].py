from flask import abort

import domino.tags as t

import content
import markup
from components.prose import blocks
from components.shell import Toc


# /guide/<topic>: a page of the guide, made from docs/guide/<topic>.md when the app starts
def page(topic):

	topic = content.TOPICS.get(topic)
	if topic is None:
		abort(404)

	headings = [(title, markup.slug(title)) for title in content.topic_headings(topic)]
	source = f"{markup.REPOSITORY}/blob/main/docs/guide/{topic.slug}.md"

	return t.div(class_="doc") [
		t.article()([
			t.p(class_="eyebrow") [
				topic.group
			],
			t.h1() [
				topic.title
			],
			t.p(class_="lead") [
				topic.lead
			]
		] + blocks(content.topic_parts(topic)) + [
			t.p(class_="source") [
				t.a(href=source) [
					"Edit this page on GitHub (docs/guide/" + topic.slug + ".md)"
				]
			]
		]),
		Toc(headings)
	]
