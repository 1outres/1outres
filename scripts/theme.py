"""Colours and the bare SVG wrapper shared by every image.

Backgrounds are transparent so the images sit on GitHub's own page; the ink
colours follow GitHub's light and dark text colours, plus one vermilion.
"""

from html import escape

from typeset import Doc

THEMES = {
    "light": {
        "ink": "#1F2328", "ink2": "#59636E", "ink3": "#818B98",
        "rule": "#D1D9E0", "faint": "#EAEEF2", "accent": "#CF3F28",
    },
    "dark": {
        "ink": "#E6EDF3", "ink2": "#9198A1", "ink3": "#7D8590",
        "rule": "#3D444D", "faint": "#262C36", "accent": "#F0643F",
    },
}

MARGIN = 8


def label(doc: Doc, t: dict, s: str, x: float, y: float, anchor: str = "start", color: str = "ink2", size: float = 11) -> str:
    """Small letterspaced capitals in mono."""
    return doc.text(s.upper(), "M", size, x, y, t[color], anchor=anchor, tracking=0.12)


def sheet(doc: Doc, w: int, h: int, body: str, title: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" '
        f'aria-label="{escape(title, quote=True)}"><title>{escape(title)}</title>'
        f"{body}{doc.defs()}</svg>\n"
    )
