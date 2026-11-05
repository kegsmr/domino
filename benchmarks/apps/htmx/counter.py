from flask import Blueprint, render_template


blueprint = Blueprint("counter", __name__)

# A module-level number: htmx keeps state on the server
count = 0


@blueprint.get("/counter")
def counter():
	return render_template("counter.html", count=count)


@blueprint.post("/counter/increment")
def increment():
	global count
	count += 1
	return str(count)
