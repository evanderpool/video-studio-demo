"""
render_case_study.py - CASE-STUDY.md -> site/case-study.html

A tiny zero-dependency markdown renderer that outputs a standalone page in the
demo's dark "editing bay" theme. The markdown stays the single source of truth;
this page cannot drift from it. Handles: headings, the leading stat row (first
table), tables, lists, blockquotes, fenced code blocks (the ASCII pipeline
diagram), horizontal rules, and inline bold/italic/code/links.
"""
from __future__ import annotations

import html
import re
from pathlib import Path

ROOT = Path(__file__).parent
SRC = ROOT / "CASE-STUDY.md"
OUT = ROOT / "site" / "case-study.html"


def inline(s: str) -> str:
    s = html.escape(s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", r'<a href="\2">\1</a>', s)
    s = re.sub(r"\*\*([^*]+(?:\*(?!\*)[^*]*)*)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"<em>\1</em>", s)
    return s


def render(md: str) -> str:
    lines = md.split("\n")
    out: list[str] = []
    para: list[str] = []
    lst: list[str] = []
    table: list[str] = []
    quote: list[str] = []
    stats_done = False
    in_code = False
    code: list[str] = []

    def flush_para():
        if para:
            out.append(f"<p>{inline(' '.join(para))}</p>")
            para.clear()

    def flush_list():
        if lst:
            out.append("<ul>" + "".join(f"<li>{inline(x)}</li>" for x in lst) + "</ul>")
            lst.clear()

    def flush_quote():
        if quote:
            out.append(f"<blockquote>{inline(' '.join(quote))}</blockquote>")
            quote.clear()

    def flush_table():
        nonlocal stats_done
        if not table:
            return
        rows = [
            [c.strip() for c in r.split("|")[1:-1]]
            for r in table
            if not re.fullmatch(r"[\s|:-]+", r)
        ]
        table.clear()
        if not rows:
            return
        if not stats_done and len(rows) == 2:
            stats_done = True
            cells = "".join(
                f'<div class="stat"><div class="v">{inline(v)}</div>'
                f'<div class="l">{inline(rows[1][i] if i < len(rows[1]) else "")}</div></div>'
                for i, v in enumerate(rows[0])
            )
            out.append(f'<div class="stats">{cells}</div>')
            return
        head = "".join(f"<th>{inline(c)}</th>" for c in rows[0])
        body = "".join(
            "<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>"
            for r in rows[1:]
        )
        out.append(f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>")

    def flush_all():
        flush_para()
        flush_list()
        flush_table()
        flush_quote()

    for raw in lines:
        line = raw.rstrip()
        if line.startswith("```"):
            if in_code:
                out.append(f"<pre>{html.escape(chr(10).join(code))}</pre>")
                code.clear()
                in_code = False
            else:
                flush_all()
                in_code = True
            continue
        if in_code:
            code.append(raw)
            continue
        h = re.match(r"^(#{1,3})\s+(.+?)\s*$", line)
        if h:
            flush_all()
            lvl = len(h.group(1))
            out.append(f"<h{lvl}>{inline(h.group(2))}</h{lvl}>")
            continue
        if re.fullmatch(r"-{3,}", line):
            flush_all()
            out.append("<hr>")
            continue
        if line.startswith(">"):
            flush_para()
            flush_list()
            flush_table()
            quote.append(line.lstrip("> ").rstrip())
            continue
        if line.startswith("|"):
            flush_para()
            flush_list()
            flush_quote()
            table.append(line)
            continue
        if re.match(r"^-\s+", line):
            flush_para()
            flush_table()
            flush_quote()
            lst.append(re.sub(r"^-\s+", "", line))
            continue
        if re.match(r"^\s+\S", line) and lst:
            lst[-1] += " " + line.strip()
            continue
        if line == "":
            flush_all()
            continue
        flush_table()
        flush_list()
        flush_quote()
        para.append(line)
    flush_all()
    return "\n".join(out)


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>Video Studio — case study</title>
<meta name="description" content="How Video Studio works: a local-first short-form video editor with a swappable brain seam, code-enforced compliance, and a self-reviewing render.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,400;12..96,600;12..96,700;12..96,800&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
<style>
:root{--bg:#0f0e0c;--bg-2:#161411;--panel:#1c1915;--line:#2c2823;--ink:#efe9dd;--ink-2:#a89f90;--ink-3:#6d665b;--accent:#ffb323;--ok:#7fd58a;
--display:"Bricolage Grotesque","Helvetica Neue",sans-serif;--mono:"JetBrains Mono",ui-monospace,Menlo,monospace}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--display);line-height:1.6;font-size:16px;-webkit-font-smoothing:antialiased;
background-image:radial-gradient(1200px 600px at 80% -10%,rgba(255,179,35,.07),transparent 60%)}
.wrap{max-width:820px;margin:0 auto;padding:clamp(1.4rem,4vw,3rem) clamp(1.2rem,5vw,2rem) 5rem}
.eyebrow{font-family:var(--mono);font-size:.7rem;letter-spacing:.16em;text-transform:uppercase;color:var(--ink-3);margin-bottom:2rem}
.eyebrow a{color:var(--accent);text-decoration:none}
h1{font-size:clamp(2rem,5vw,3.2rem);line-height:1.02;font-weight:800;letter-spacing:-.03em;margin:.2em 0 .5em}
h2{font-size:clamp(1.3rem,3vw,1.7rem);font-weight:700;letter-spacing:-.02em;margin:2.6rem 0 .8rem;padding-bottom:.5rem;border-bottom:1px solid var(--line)}
h3{font-size:1.1rem;font-weight:700;margin:1.8rem 0 .5rem}
p{margin:.9rem 0;color:var(--ink)}
a{color:var(--accent)}
strong{color:#fff;font-weight:700}
em{color:var(--ink-2)}
code{background:var(--panel);border:1px solid var(--line);border-radius:4px;padding:1px 6px;font-family:var(--mono);font-size:.85em}
ul{margin:1rem 0;padding-left:1.3rem}
li{margin:.5rem 0;color:var(--ink)}
li::marker{color:var(--accent)}
hr{border:0;border-top:1px solid var(--line);margin:2.5rem 0}
blockquote{margin:1.4rem 0;padding:.9rem 1.2rem;border-left:3px solid var(--accent);background:var(--bg-2);border-radius:0 6px 6px 0;font-size:1.05rem}
blockquote strong{color:var(--accent)}
pre{background:var(--bg-2);border:1px solid var(--line);border-radius:8px;padding:1.1rem 1.2rem;overflow-x:auto;font-family:var(--mono);font-size:.72rem;line-height:1.5;color:var(--ink-2)}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:1px;background:var(--line);border:1px solid var(--line);border-radius:8px;overflow:hidden;margin:2rem 0}
.stat{background:var(--bg-2);padding:1.1rem 1rem}
.stat .v{font-size:1.9rem;font-weight:800;letter-spacing:-.03em;color:var(--accent);line-height:1}
.stat .l{font-size:.72rem;color:var(--ink-3);margin-top:.45rem;line-height:1.35}
table{border-collapse:collapse;width:100%;margin:1.4rem 0;font-size:.92rem;display:block;overflow-x:auto}
th,td{border:1px solid var(--line);padding:.55rem .8rem;text-align:left;vertical-align:top}
th{font-family:var(--mono);font-size:.68rem;letter-spacing:.08em;text-transform:uppercase;color:var(--ink-3);background:var(--bg-2)}
td strong{color:var(--accent)}
.backbar{margin-top:3rem;padding-top:1.4rem;border-top:1px solid var(--line);font-family:var(--mono);font-size:.72rem;color:var(--ink-3)}
.backbar a{color:var(--accent);text-decoration:none}
</style>
</head>
<body>
<main class="wrap">
<div class="eyebrow"><a href="index.html">← back to the demo</a> · case study</div>
__BODY__
<div class="backbar"><a href="index.html">← Video Studio demo</a> · <a href="https://github.com/evanderpool/video-studio-demo">repo</a></div>
</main>
</body>
</html>
"""

if __name__ == "__main__":
    md = SRC.read_text(encoding="utf-8")
    OUT.write_text(PAGE.replace("__BODY__", render(md)), encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB)")
