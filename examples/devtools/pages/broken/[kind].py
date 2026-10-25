from flask import abort

from components.report import Greeting, Mistake, Report


# /broken/render, /broken/child and /broken/template fail while rendering: in debug mode they
# show Domino's error page (the frames with their source, the component stack, hints); without
# it, a plain 500
def page(kind):

	if kind == "render":
		return Report()
	if kind == "child":
		return Mistake()
	if kind == "template":
		return Greeting()

	abort(404)
