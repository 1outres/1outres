"""The images in the README, redrawn every night from GitHub activity."""

import math
from pathlib import Path

from theme import MARGIN, THEMES, label, sheet
from typeset import Doc, fmt



def num(n: float) -> str:
    return f"{round(n):,}"


def compact(n: float) -> str:
    for unit, div in (("M", 1_000_000), ("K", 1_000)):
        if n >= div:
            v = n / div
            return (f"{v:.2f}" if v < 10 else f"{v:.1f}" if v < 100 else f"{v:.0f}").rstrip("0").rstrip(".") + unit
    return str(round(n))


def density(minutes: list[int], bins: int, sigma: float) -> list[float]:
    """Circular kernel density of times within a day, given in minutes."""
    step = 1440 / bins
    out = [0.0] * (bins + 1)
    for m in minutes:
        for k in range(bins + 1):
            d = abs(k * step - m)
            d = min(d, 1440 - d)
            if d < sigma * 3:
                out[k] += math.exp(-(d * d) / (2 * sigma * sigma))
    return out


def visible_runs(rows: list[list[float]], xs: list[float]) -> list[list[list[tuple[float, float]]]]:
    """Hidden-line removal for stacked lines (the "floating horizon").

    rows are y values, back (top) to front (bottom). A point is drawn only
    if it rises above every line in front of it, so no background fill is
    needed and the image stays transparent.
    """
    horizon = [math.inf] * len(xs)
    out: list[list[list[tuple[float, float]]]] = [[] for _ in rows]
    for i in range(len(rows) - 1, -1, -1):
        ys = rows[i]
        runs, cur, prev = [], [], False
        for k, (x, y) in enumerate(zip(xs, ys)):
            vis = y < horizon[k] - 0.05
            if k and vis != prev:
                d0, d1 = ys[k - 1] - horizon[k - 1], y - horizon[k]
                f = d0 / (d0 - d1) if math.isfinite(d0) and math.isfinite(d1) and d0 != d1 else 0.0
                pt = (xs[k - 1] + f * (x - xs[k - 1]), ys[k - 1] + f * (y - ys[k - 1]))
                if vis:
                    cur = [pt]
                else:
                    cur.append(pt)
                    runs.append(cur)
                    cur = []
            if vis:
                cur.append((x, y))
            prev = vis
        if len(cur) > 1:
            runs.append(cur)
        out[i] = [r for r in runs if len(r) > 1]
        horizon = [min(hz, y) for hz, y in zip(horizon, ys)]
    return out


# ---------------------------------------------------------------- header


def header(s: dict, t: dict) -> str:
    doc = Doc("h")
    m = MARGIN
    w = 1000
    x0, x1 = 520, w - m
    base_top, pitch, amp = 74, 4.4, 60
    bins = 144
    weeks = s["pulse"]  # 52 lists of commit minutes after midnight, oldest first

    dens = [density(wk, bins, 22) for wk in weeks]
    # Scale to a typical busy week, and soften anything taller, so one burst
    # of commits can't flatten every other line.
    maxima = sorted(max(d) for d in dens if max(d) > 0)
    peak = maxima[int(len(maxima) * 0.9)] if maxima else 1.0
    xs = [x0 + (x1 - x0) * k / bins for k in range(bins + 1)]
    rows = [[base_top + i * pitch - amp * 1.4 * math.tanh(v / peak / 1.4) for v in d] for i, d in enumerate(dens)]
    front = base_top + (len(rows) - 1) * pitch
    h = int(front + 36)

    out = []
    for i, runs in enumerate(visible_runs(rows, xs)):
        last = i == len(rows) - 1
        for run in runs:
            d = "M" + "L".join(f"{fmt(x)} {fmt(y)}" for x, y in run)
            out.append(f'<path d="{d}" fill="none" stroke="{t["accent"] if last else t["ink"]}" '
                       f'stroke-width="{1.4 if last else 0.9}" stroke-linejoin="round"/>')
    for j, hh in enumerate(("00", "06", "12", "18", "24")):
        xx = x0 + (x1 - x0) * j / 4
        anchor = "start" if j == 0 else "end" if j == 4 else "middle"
        out.append(label(doc, t, hh, xx, front + 28, anchor, "ink3", 10))

    # Line 1: round avatar and handle; line 2: name.
    size, cy = 54, 136
    if s.get("avatar"):
        out.append(f'<clipPath id="av"><circle cx="{m + size / 2}" cy="{cy}" r="{size / 2}"/></clipPath>'
                   f'<image href="{s["avatar"]}" x="{m}" y="{cy - size / 2}" width="{size}" height="{size}" '
                   f'clip-path="url(#av)" preserveAspectRatio="xMidYMid slice"/>')
    out.append(f'<circle cx="{m + size / 2}" cy="{cy}" r="{size / 2 - 0.5}" fill="none" stroke="{t["rule"]}"/>')
    out.append(doc.text("Loutres", "D", 66, m + size + 16, cy + 23, t["ink"], tracking=-0.01))
    out.append(doc.text("Rihito Ninokata", "T", 23, m, cy + 70, t["ink2"]))
    return sheet(doc, w, h, "".join(out), "Loutres (Rihito Ninokata). One line per week of commits by time of day, last 52 weeks.")


# ---------------------------------------------------------------- languages


def languages(s: dict, t: dict) -> str:
    doc = Doc("l")
    w, m = 492, MARGIN
    langs = s["languages"]
    total = sum(v for _, v in langs) or 1
    top = list(langs[:7])
    other = total - sum(v for _, v in top)
    if other / total >= 0.005:
        top.append(("Other", other))
    out = [label(doc, t, "Languages", m, 16)]
    y = 58
    for i, (name, v) in enumerate(top):
        share = v / total
        out.append(doc.text(name, "T", 16.5, m, y, t["ink2"] if name == "Other" else t["ink"]))
        out.append(doc.text(f"{share * 100:.1f}%", "M", 11.5, w - m, y, t["ink2"], anchor="end"))
        out.append(f'<rect x="{m}" y="{y + 9}" width="{w - 2 * m}" height="1" fill="{t["faint"]}"/>')
        color = t["accent"] if i == 0 else t["ink3"] if name == "Other" else t["ink"]
        out.append(f'<rect x="{m}" y="{y + 8}" width="{fmt(max((w - 2 * m) * share, 1.5))}" height="3" fill="{color}"/>')
        y += 33
    return sheet(doc, w, 310, "".join(out), "Languages by share of my commits: "
                 + ", ".join(f"{n} {v * 100 / total:.0f}%" for n, v in top))


# ---------------------------------------------------------------- stats


def stats(s: dict, t: dict) -> str:
    doc = Doc("s")
    w, m = 492, MARGIN
    rows = [
        ("Commits", num(s["commits"])),
        ("Pull requests", num(s["prs"])),
        ("Code reviews", num(s["reviews"])),
        ("Issues", num(s["issues"])),
        ("Lines", f"+{compact(s['added'])} / −{compact(s['deleted'])}"),
        ("Repositories", num(s["repos"])),
        ("Longest streak", f"{num(s['longest'])} days"),
        ("Last 365 days", num(s["last_year"])),
    ]
    out = [label(doc, t, "Stats", m, 16)]
    y = 58
    for name, value in rows:
        out.append(doc.text(name, "T", 16.5, m, y, t["ink"]))
        out.append(doc.text(value, "M", 12, w - m, y, t["ink2"], anchor="end"))
        out.append(f'<rect x="{m}" y="{y + 9}" width="{w - 2 * m}" height="1" fill="{t["faint"]}"/>')
        y += 33
    return sheet(doc, w, 310, "".join(out), ", ".join(f"{n}: {v}" for n, v in rows))


# ---------------------------------------------------------------- write


IMAGES = {"header": header, "languages": languages, "stats": stats}


def write_all(s: dict, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for name, render in IMAGES.items():
        for theme, t in THEMES.items():
            (out / f"{name}-{theme}.svg").write_text(render(s, t), encoding="utf-8")
