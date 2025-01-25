from domino.__init__ import Domino


dom = Domino()


@dom.document()
class html:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("head")
class head:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("body")
class body:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("title")
class title:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("meta")
class meta:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("link")
class link:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("style")
class style:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("base")
class base:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("noscript")
class noscript:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("script")
class script:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("section")
class section:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("article")
class article:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("aside")
class aside:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("nav")
class nav:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("header")
class header:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("footer")
class footer:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("main")
class main:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("h1")
class h1:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("h2")
class h2:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("h3")
class h3:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("h4")
class h4:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("h5")
class h5:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("h6")
class h6:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("p")
class p:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("hr")
class hr:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("pre")
class pre:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("blockquote")
class blockquote:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("ol")
class ol:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("ul")
class ul:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("li")
class li:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("dl")
class dl:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("dt")
class dt:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("dd")
class dd:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("figure")
class figure:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("figcaption")
class figcaption:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("div")
class div:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("a")
class a:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("em")
class em:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("strong")
class strong:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("small")
class small:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("s")
class s:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("cite")
class cite:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("q")
class q:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("abbr")
class abbr:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("code")
class code:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("sub")
class sub:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("sup")
class sup:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("time")
class time:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("mark")
class mark:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("b")
class b:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("i")
class i:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("u")
class u:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("span")
class span:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("br")
class br:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("wbr")
class wbr:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("img")
class img:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("iframe")
class iframe:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("embed")
class embed:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("object")
class object:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("param")
class param:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("video")
class video:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("audio")
class audio:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("source")
class source:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("track")
class track:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("map")
class map:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("area")
class area:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("canvas")
class canvas:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("svg")
class svg:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("table")
class table:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("tr")
class tr:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("td")
class td:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("th")
class th:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("thead")
class thead:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("tbody")
class tbody:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("tfoot")
class tfoot:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("col")
class col:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)


@dom.element("colgroup")
class colgroup:
    def __init__(self, inner="", **kwargs):
        self.inner(inner)
        self.configure(**kwargs)