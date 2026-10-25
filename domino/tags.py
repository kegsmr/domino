from .core import Element


# Every class in this module is an Element named after the HTML tag it renders,
# e.g. tags.div() renders <div>. Add a tag by adding its name here (and to tags.pyi).
TAGS = [
	"html", "head", "body", "title", "meta", "link", "style", "base",
	"noscript", "script", "section", "article", "aside", "nav", "header",
	"footer", "main", "h1", "h2", "h3", "h4", "h5", "h6", "p", "hr",
	"pre", "blockquote", "ol", "ul", "li", "dl", "dt", "dd", "figure",
	"figcaption", "div", "a", "em", "strong", "small", "s", "cite",
	"q", "abbr", "code", "sub", "sup", "time", "mark", "b", "i", "u",
	"span", "br", "wbr", "img", "iframe", "embed", "object", "param",
	"video", "audio", "source", "track", "map", "area", "canvas", "svg",
	"table", "tr", "td", "th", "thead", "tbody", "tfoot", "col", "colgroup",
	"form", "input", "textarea", "button",
	"label", "select", "option", "optgroup", "fieldset", "legend",
	"datalist", "output", "progress", "meter", "details", "summary",
	"dialog", "caption",
]


def _make_tag(name):

	def __init__(self, parent=None, inner=None, *args, **kwargs):
		super(tag, self).__init__(name, parent, inner, *args, **kwargs)

	__init__.__qualname__ = f"{name}.__init__"

	tag = type(name, (Element,), {
		"__init__": __init__,
		"__module__": __name__,
		"__qualname__": name,
	})

	return tag


for _name in TAGS:
	globals()[_name] = _make_tag(_name)

del _name
