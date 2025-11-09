from .core import Element

class Document(Element):
    """
    Base HTML document for Domino apps.
    Provides:
      - <html>, <head>, <body> structure
      - Default meta tags
      - Optional CSS and favicon
      - content_root for adding children
      - Convenience methods for scripts and components
    """

    def __init__(self, title=None, css=None, favicon=None):

        super().__init__(tag="html")

        # --- HEAD ---
        self.head = Element(tag="head", parent=self)
        self.head.add_children([
            Element(tag="meta", parent=self.head, charset="utf-8"),
            Element(tag="meta", parent=self.head, name="viewport", content="width=device-width, initial-scale=1"),
            Element(tag="title", parent=self.head, inner=title)
        ])

        if css:
            self.head.add_children([
                Element(tag="link", parent=self.head, rel="stylesheet", href=css)
            ])

        if favicon:
            self.head.add_children([
                Element(tag="link", parent=self.head, rel="icon", type="image/png", href=favicon)
            ])

        # --- BODY ---
        self.body = Element(tag="body", parent=self)
        self.content_root = self.body  # Default insertion point for children

        # Optional: list of scripts to append
        self._scripts = []

    # --- Convenience methods ---
    def add_script(self, src, **attrs):
        """Append a <script> tag to the head."""
        self.head.add_children([Element(tag="script", parent=self.head, src=src, **attrs)])
        return self

    def add_component(self, component):
        """Append a component to the content_root (<body>)."""
        self.content_root.add_children([component])
        return self

    # Optional: render full HTML including DOCTYPE
    def render(self, level=0, indent=4):
        doctype = "<!DOCTYPE html>\n"
        return doctype + super().render(level, indent)
