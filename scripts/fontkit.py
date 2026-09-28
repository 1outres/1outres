"""Extract glyph outlines, advances and kerning from font files (dev only).

Needs `pip install uharfbuzz fonttools`. The fonts are downloaded into
scripts/fonts/ (git-ignored) from the Google Fonts repository; both families
are under the SIL Open Font License.

    python3 scripts/fontkit.py        # rebuild scripts/glyphs.json
"""

import json
import urllib.request
from pathlib import Path

import uharfbuzz as hb

HERE = Path(__file__).resolve().parent
FONTS = HERE / "fonts"
SRC = "https://raw.githubusercontent.com/google/fonts/main/ofl/"

FILES = {
    "Newsreader.ttf": "newsreader/Newsreader%5Bopsz,wght%5D.ttf",
    "Newsreader-Italic.ttf": "newsreader/Newsreader-Italic%5Bopsz,wght%5D.ttf",
    "IBMPlexMono-Regular.ttf": "ibmplexmono/IBMPlexMono-Regular.ttf",
}

# key: (file, variations, features)
STYLES = {
    "D": ("Newsreader.ttf", {"opsz": 72, "wght": 380}, {"pnum": True}),        # display
    "T": ("Newsreader.ttf", {"opsz": 14, "wght": 400}, {"pnum": True}),        # text
    "TI": ("Newsreader-Italic.ttf", {"opsz": 14, "wght": 400}, {"pnum": True}),
    "M": ("IBMPlexMono-Regular.ttf", {}, {}),                                  # mono
}

LATIN = "".join(chr(c) for c in range(32, 127)) + "‘’“”–—·×°′″−…é→←↑↓±≈∝№§º"


def fetch() -> None:
    FONTS.mkdir(exist_ok=True)
    for name, path in FILES.items():
        if not (FONTS / name).exists():
            urllib.request.urlretrieve(SRC + path, FONTS / name)


class _Pen:
    """Collects an outline as an SVG path, flipping y so it points down."""

    def __init__(self):
        self.d: list[str] = []

    def _p(self, pt) -> str:
        return f"{round(pt[0])} {round(-pt[1])}"

    def moveTo(self, p):
        self.d.append("M" + self._p(p))

    def lineTo(self, p):
        self.d.append("L" + self._p(p))

    def qCurveTo(self, *pts):
        # TrueType implied on-curve points between consecutive off-curve ones.
        *offs, end = pts
        for i, c in enumerate(offs):
            if i + 1 < len(offs):
                n = offs[i + 1]
                mid = ((c[0] + n[0]) / 2, (c[1] + n[1]) / 2)
                self.d.append("Q" + self._p(c) + " " + self._p(mid))
            else:
                self.d.append("Q" + self._p(c) + " " + self._p(end))

    def curveTo(self, c1, c2, p):
        self.d.append("C" + self._p(c1) + " " + self._p(c2) + " " + self._p(p))

    def closePath(self):
        self.d.append("Z")

    endPath = closePath


class Font:
    def __init__(self, key: str):
        file, variations, features = STYLES[key]
        self.key = key
        blob = hb.Blob.from_file_path(str(FONTS / file))
        self.face = hb.Face(blob)
        self.font = hb.Font(self.face)
        if variations:
            self.font.set_variations(variations)
        self.features = {"kern": True, "liga": False, "calt": False, **features}
        self.upem = self.face.upem
        ext = self.font.get_font_extents("ltr")
        self.asc, self.desc = ext.ascender, ext.descender
        self.cap = self._height("H")

    def _height(self, ch: str) -> int:
        gid = self._shape(ch)[0][0]
        ext = self.font.get_glyph_extents(gid)
        return ext.y_bearing if ext else self.upem * 7 // 10

    def _shape(self, s: str) -> list[tuple[int, int, int]]:
        buf = hb.Buffer()
        buf.add_str(s)
        buf.guess_segment_properties()
        hb.shape(self.font, buf, self.features)
        return [(i.codepoint, p.x_advance, p.x_offset) for i, p in zip(buf.glyph_infos, buf.glyph_positions)]

    def outline(self, gid: int) -> str:
        pen = _Pen()
        self.font.draw_glyph_with_pen(gid, pen)
        return "".join(pen.d)

    def data(self, chars: str, pairs: bool = True) -> dict:
        glyphs, adv = {}, {}
        cmap = self.face.unicodes
        for ch in dict.fromkeys(chars):
            if ord(ch) not in cmap:
                continue
            (gid, a, off), = self._shape(ch)
            glyphs[ch] = [a, self.outline(gid), off]
            adv[ch] = a
        kern = {}
        if pairs:
            for a in adv:
                for b in adv:
                    if a == " " or b == " ":
                        continue
                    got = sum(x[1] for x in self._shape(a + b))
                    if got != adv[a] + adv[b]:
                        kern[a + b] = got - adv[a] - adv[b]
        return {"upem": self.upem, "asc": self.asc, "desc": self.desc, "cap": self.cap,
                "glyphs": glyphs, "kern": kern}


def build() -> dict:
    fetch()
    return {"faces": {key: Font(key).data(LATIN) for key in STYLES}}


if __name__ == "__main__":
    data = build()
    path = HERE / "glyphs.json"
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {path} ({path.stat().st_size // 1024} KB)")
