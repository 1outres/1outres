"""Set text as SVG outlines, so every plate renders with the same typefaces.

GitHub shows README images through <img>, which can't load web fonts, and
system fonts differ per viewer. Glyph outlines, advances and kerning pairs
are extracted once from the font files (scripts/fontkit.py) and stored in
scripts/glyphs.json; this module only needs the standard library.
"""

import json
from functools import lru_cache
from pathlib import Path

GLYPHS = Path(__file__).resolve().parent / "glyphs.json"


class Face:
    def __init__(self, key: str, data: dict):
        self.key = key
        self.upem = data["upem"]
        self.asc = data["asc"]
        self.desc = data["desc"]
        self.cap = data.get("cap", self.asc)
        self.glyphs = data["glyphs"]  # char -> [advance, path, x offset]
        self.kern = data.get("kern", {})  # "AV" -> units

    def has(self, ch: str) -> bool:
        return ch in self.glyphs

    def advances(self, text: str, tracking: float = 0.0) -> list[float]:
        """Advance of every character in font units, kerning and tracking applied."""
        track = tracking * self.upem
        out = []
        for i, ch in enumerate(text):
            adv = self.glyphs[ch][0] if ch in self.glyphs else self.upem * 0.5
            if i + 1 < len(text):
                adv += self.kern.get(ch + text[i + 1], 0)
            out.append(adv + track)
        return out

    def width(self, text: str, size: float, tracking: float = 0.0) -> float:
        if not text:
            return 0.0
        advs = self.advances(text, tracking)
        advs[-1] -= tracking * self.upem  # no trailing tracking
        return sum(advs) * size / self.upem


@lru_cache(maxsize=1)
def faces() -> dict[str, Face]:
    data = json.loads(GLYPHS.read_text(encoding="utf-8"))
    return {k: Face(k, v) for k, v in data["faces"].items()}


def face(key: str) -> Face:
    return faces()[key]


def fmt(v: float) -> str:
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return s if s != "-0" else "0"


class Doc:
    """Collects the glyphs one SVG uses, so each outline is defined only once."""

    def __init__(self, prefix: str = "g"):
        self.prefix = prefix
        self.used: dict[str, tuple[Face, str]] = {}

    def gid(self, f: Face, ch: str) -> str:
        ident = f"{self.prefix}{f.key}{ord(ch):x}"
        self.used[ident] = (f, ch)
        return ident

    def text(self, s: str, f: Face | str, size: float, x: float, y: float, fill: str,
             anchor: str = "start", tracking: float = 0.0, attrs: str = "") -> str:
        """One line of text. `tracking` is in em; `anchor` is start, middle or end."""
        if isinstance(f, str):
            f = face(f)
        if not s:
            return ""
        w = f.width(s, size, tracking)
        if anchor == "middle":
            x -= w / 2
        elif anchor == "end":
            x -= w
        scale = size / f.upem
        pen, uses = 0.0, []
        for ch, adv in zip(s, f.advances(s, tracking)):
            if ch != " " and f.has(ch):
                ox = pen + f.glyphs[ch][2]
                uses.append(f'<use href="#{self.gid(f, ch)}"' + (f' x="{fmt(ox)}"' if ox else "") + "/>")
            pen += adv
        return (f'<g transform="translate({fmt(x)} {fmt(y)}) scale({scale:.5f})" fill="{fill}"{attrs}>'
                + "".join(uses) + "</g>")

    def defs(self) -> str:
        paths = [f'<path id="{i}" d="{f.glyphs[ch][1]}"/>' for i, (f, ch) in sorted(self.used.items())]
        return "<defs>" + "".join(paths) + "</defs>"
