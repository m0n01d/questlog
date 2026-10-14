"""questlog chart: one self-contained HTML page. Inline SVG and CSS only, no script and no network.
It shows dates and numbers, never repo names or titles. Stdlib only, Python 3.9+."""
from __future__ import annotations

import random
from datetime import date, timedelta

CSS = """
:root{color-scheme:light dark;--bg:#f9f9f7;--card:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--mut:#898781;--grid:#e1e0d9;--base:#c3c2b7;
--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--h0:#e1e0d9;--h1:#86b6ef;--h2:#5598e7;--h3:#256abf;--h4:#104281}
@media(prefers-color-scheme:dark){:root{--bg:#0d0d0d;--card:#1a1a19;--ink:#fff;--ink2:#c3c2b7;--grid:#2c2c2a;--base:#383835;
--s1:#3987e5;--s2:#d95926;--s3:#199e70;--h0:#2c2c2a;--h1:#184f95;--h2:#2a78d6;--h3:#5598e7;--h4:#86b6ef}}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:752px;margin:0 auto;padding:24px 16px}
section{background:var(--card);box-shadow:0 0 0 1px var(--grid);border-radius:12px;padding:16px 16px 12px;margin:0 0 16px}
h1{font-size:20px;margin:0}h2{font-size:14px;margin:0 0 8px}.sub{color:var(--ink2);margin:2px 0 16px}
p{margin:0}svg{display:block;width:100%;height:auto}
.k{display:inline-flex;align-items:center;margin:0 14px 8px 0;color:var(--ink2);font-size:12px}
.k i{width:10px;height:10px;border-radius:2px;margin-right:6px}
.t{fill:var(--mut);font-size:11px}.v{fill:var(--ink);font-size:12px;font-weight:600}
.g,.b{stroke-width:1}.g{stroke:var(--grid)}.b{stroke:var(--base)}
.h0{fill:var(--h0)}.h1{fill:var(--h1)}.h2{fill:var(--h2)}.h3{fill:var(--h3)}.h4{fill:var(--h4)}
.s1{fill:var(--s1)}.s2{fill:var(--s2)}.s3{fill:var(--s3)}.off{fill:none;stroke:var(--mut)}
.m:hover{stroke:var(--ink2);stroke-width:1.5}.hit{fill:transparent}.hit:hover{fill:var(--grid)}
.ln,.ar,.dot{pointer-events:none}.ln{fill:none;stroke:var(--s1);stroke-width:2;stroke-linejoin:round;stroke-linecap:round}
.ar{fill:var(--s1);opacity:.1}.dot{fill:var(--s1);stroke:var(--card);stroke-width:2}
details{margin-top:8px;color:var(--ink2);font-size:12px}table{border-collapse:collapse;margin-top:6px}
td,th{padding:2px 14px 2px 0;text-align:left;font-variant-numeric:tabular-nums}th{color:var(--mut);font-weight:500}
"""
W, ML, MR, T, H = 720, 56, 14, 18, 190     # svg width, left and right margin, plot top, chart height
B = H - 26                                 # y of the baseline of the line and bar charts
HEAT = (1, 10, 20, 35)                     # XP that a day needs for heat level 1 to 4
KEYS = (("merged", "Merged", "s1"), ("review", "Reviewed", "s2"), ("owned", "Owned", "s3"))

def md(d): return f"{d:%b} {d.day}"
def txt(x, y, s, cls="t", anchor="start"): return f'<text class="{cls}" x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}">{s}</text>'
def hline(y, cls="g"): return f'<line class="{cls}" x1="{ML}" x2="{W - MR}" y1="{y:.1f}" y2="{y:.1f}"/>'
def svg(h, label, body): return f'<svg viewBox="0 0 {W} {h}" role="img" aria-label="{label}">{"".join(body)}</svg>'
def legend(items): return "<p>" + "".join(f'<span class=k><i style="{css}"></i>{n}</span>' for css, n in items) + "</p>"

def months(mon0, s0, nw, cw, y):
    """Month names above the week columns, where the month of the Monday changes. The first column names the season start."""
    ds = [max(mon0 + timedelta(days=7 * c), s0) for c in range(nw)]
    return [txt(ML + c * cw, y, f"{d:%b}") for c, d in enumerate(ds) if c == 0 or d.month != ds[c - 1].month]

def heat(mon0, s0, today, days, off, nw, cw):
    out = [txt(ML - 8, 34 + r * 24, n, anchor="end") for r, n in ((0, "Mon"), (2, "Wed"), (4, "Fri"))] + months(mon0, s0, nw, cw, 12)
    for k in range((today - mon0).days + 1):
        d = mon0 + timedelta(days=k)
        if d.weekday() < 5 and d >= s0:
            tip, cls = (f"{days[d]} XP", "h%d" % sum(days[d] >= t for t in HEAT)) if d not in off else ("off day", "off")
            out.append(f'<rect class="m {cls}" x="{ML + k // 7 * cw + 1:.1f}" y="{19 + d.weekday() * 24}" width="{cw - 2:.1f}" '
                       f'height="22" rx="3"><title>{md(d)}: {tip}</title></rect>')
    return svg(140, "Heatmap of XP for each workday", out)

def line(mon0, s0, today, days, steps, nw, cw):
    tot, cum, pts, hits, dw = sum(days.values()), 0, [], [], cw / 7
    ymax = next((v for v, _ in steps if v > tot), tot) or 1
    y = lambda v: B - (B - T) * v / ymax
    out, last = [hline(B, "b"), txt(ML - 8, B + 4, 0, anchor="end")], B
    for v, lv in steps:                                 # a line at each level threshold
        if v <= ymax:
            out.append(hline(y(v)))
            if last - y(v) >= 13:                       # skip labels that would touch
                out += [txt(ML - 8, y(v) + 4, v, anchor="end"), txt(W - MR, y(v) - 4, f"Lv {lv}", anchor="end")]
                last = y(v)
    for k in range((today - s0).days + 1):
        d = s0 + timedelta(days=k)
        cum += days[d]
        x = ML + ((d - mon0).days + .5) * dw
        pts.append(f"{x:.1f},{y(cum):.1f}")
        hits.append(f'<rect class="hit" x="{x - dw / 2:.1f}" y="{T}" width="{dw:.1f}" height="{B - T}">'
                    f'<title>{md(d)}: {cum} XP so far, {days[d]} that day</title></rect>')
    px, py = pts[-1].split(",")
    return svg(H, "Cumulative XP over the season", out + hits + [
        f'<polygon class="ar" points="{pts[0].split(",")[0]},{B} {" ".join(pts)} {px},{B}"/>',
        f'<polyline class="ln" points="{" ".join(pts)}"/>', f'<circle class="dot" cx="{px}" cy="{py}" r="4"/>',
        txt(float(px) - 9, float(py) - 8, cum, "v", "end")] + months(mon0, s0, nw, cw, B + 16))

def bars(mon0, wk, nw, cw):
    top = max([w[k] for w in wk for k, _, _ in KEYS] + [1])
    step = next((s for s in (1, 2, 5, 10, 20, 50) if top / s <= 4), 100)
    ymax, out, bw = -(-top // step) * step, [], 12
    for v in range(0, ymax + 1, step):
        yy = B - (B - T) * v / ymax
        out += [hline(yy, "b" if v == 0 else "g"), txt(ML - 8, yy + 4, v, anchor="end")]
    for c in range(nw):
        wd, mid = md(mon0 + timedelta(days=7 * c)), ML + (c + .5) * cw
        out.append(txt(mid, B + 16, wd, anchor="middle"))
        for i, (k, name, col) in enumerate(KEYS):
            v = wk[c][k] if c < len(wk) else 0
            h = (B - T) * v / ymax
            r, x = min(4, h), mid - 20 + i * (bw + 2)  # 4 px round end, square at the baseline
            if v:
                out.append(f'<path class="m {col}" d="M{x:.1f},{B}v{r - h:.1f}a{r:.1f},{r:.1f} 0 0 1 {r:.1f},{-r:.1f}h{bw - 2 * r:.1f}'
                           f'a{r:.1f},{r:.1f} 0 0 1 {r:.1f},{r:.1f}v{h - r:.1f}z"><title>Week of {wd}: {name} {v}</title></path>')
    return svg(H, "Merged, reviewed and owned PRs for each week", out)

def page(head, s0, s1, today, days, wk, off, steps):
    """days: XP for each day. wk: one Counter for each week up to today. off: off days. steps: (XP, level) thresholds."""
    mon0 = s0 - timedelta(days=s0.weekday())
    nw = (s1 - mon0).days // 7 + 1
    cw = (W - ML - MR) / nw
    labels = ["0"] + [f"{a}–{b - 1}" for a, b in zip(HEAT, HEAT[1:])] + [f"{HEAT[-1]}+"]
    rows = "".join(f"<tr><td>{md(mon0 + timedelta(days=7 * i))}<td>{w['xp']}<td>{w['merged']}<td>{w['review']}<td>{w['owned']}"
                   for i, w in enumerate(wk))
    return (f"<!doctype html><html lang=en><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>questlog chart</title><style>{CSS}</style><main><h1>questlog</h1><p class=sub>{head}</p>"
            f"<section><h2>XP for each workday</h2>{legend([('background:var(--h%d)' % i, n) for i, n in enumerate(labels)] + [('box-sizing:border-box;border:1px solid var(--mut)', 'Off day')])}"
            f"{heat(mon0, s0, today, days, off, nw, cw)}</section>"
            f"<section><h2>Cumulative XP and level thresholds</h2>{line(mon0, s0, today, days, steps, nw, cw)}</section>"
            f"<section><h2>PRs for each week</h2>{legend([(f'background:var(--{c})', n) for _, n, c in KEYS])}{bars(mon0, wk, nw, cw)}"
            f"<details><summary>Table view</summary><table><tr><th>Week of<th>XP<th>Merged<th>Reviewed<th>Owned{rows}</table>"
            f"</details></section></main>")

def demo():
    """A made-up season from a fixed seed, in the shape of the real events. Returns (events, today)."""
    r, d0, today, evs = random.Random(7).random, date(2026, 7, 1), date(2026, 9, 24), []
    for k in range((today - d0).days + 1):
        d, f = d0 + timedelta(days=k), k / 85                  # busier as the season goes on
        add = lambda kind, xp, **kw: evs.append(dict(kind=kind, days=[d], xp=xp, **kw))
        if d.weekday() > 4 or r() < .04:
            if d.weekday() < 5:
                add("off", 0)
            continue
        if r() < .25 + .4 * f:
            clean, tested, owned = r() < .8, r() < .6, r() < .1 + .5 * f
            add("merged", 10 + 5 * clean + 5 * tested + 10 * owned, owned=owned)
        if r() < .2 + .25 * f:
            add("review", 10)
        if r() < .12:
            add("card", 3)
    return evs, today
