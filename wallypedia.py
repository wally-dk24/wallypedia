#!/usr/bin/env python3
"""wallypedia — a local-first static wiki generator over your markdown notes.

Your notes are plain Markdown files: daily logs, person pages, project
notes, whatever you keep. Wallypedia turns them into a browsable wiki:

  * [[WikiLinks]] between pages, with automatic backlinks
  * #tags with tag pages and a tag cloud
  * full-text client-side search (no server, no dependencies)
  * date-aware index for YYYY-MM-DD daily notes

Privacy by design: this is a *local* build tool. The generator reads your
notes directory and writes a static site you serve yourself. Your notes
never leave your machine; only this engine is meant to be shared.

Usage:
    python3 wallypedia.py build --notes ~/memory --out site/
    python3 wallypedia.py build --config wallypedia.json

Stdlib only. No dependencies.
"""

import argparse
import fnmatch
import html
import json
import os
import re
import sys
from datetime import datetime

# ----------------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------------

DEFAULT_CONFIG = {
    "notes_dir": ".",
    "out_dir": "site",
    "title": "Wallypedia",
    "subtitle": "a self-maintaining personal wiki",
    # Relative paths (from notes_dir) that must never be indexed or copied.
    "exclude": [
        "*/.git/*", ".git/*",
        "*secret*", "*credential*", "*password*", "*token*", "*key*",
        "*.pem", "*.key",
    ],
}

# ----------------------------------------------------------------------------
# Markdown subset renderer (stdlib only)
# ----------------------------------------------------------------------------

WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
TAG_RE = re.compile(r"(?<![\w#/])#([A-Za-z][\w-]*)")
MDLINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
CODE_RE = re.compile(r"`([^`]+)`")
BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
ITALIC_RE = re.compile(r"(?<!\*)\*([^*]+?)\*(?!\*)")
DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def slugify(text):
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "note"


class WikiContext:
    """Carries cross-page state (slug resolution, tag pages) into rendering."""

    def __init__(self):
        self.slug_by_name = {}   # lowercase stem -> slug
        self.slug_by_path = {}   # rel path -> slug

    def add(self, rel_path, slug):
        stem = os.path.splitext(os.path.basename(rel_path))[0]
        self.slug_by_name.setdefault(stem.lower(), slug)
        self.slug_by_path[rel_path] = slug

    def resolve(self, name):
        return self.slug_by_name.get(name.strip().lower())


def render_inline(text, ctx):
    """Render inline markdown: code, bold, italic, wikilinks, tags, links."""
    out = html.escape(text)

    # Stash code spans first so #tags/[[links]] inside code stay literal.
    stashed = []

    def _stash(m):
        stashed.append(m.group(1))
        return "\x00%d\x00" % (len(stashed) - 1)

    def _unstash(m):
        return "<code>%s</code>" % stashed[int(m.group(1))]

    out = CODE_RE.sub(_stash, out)

    def _bold(m):
        return "<strong>%s</strong>" % m.group(1)

    def _italic(m):
        return "<em>%s</em>" % m.group(1)

    def _wikilink(m):
        target, label = m.group(1), m.group(2) or m.group(1)
        slug = ctx.resolve(target)
        if slug:
            return '<a class="wl" href="%s.html">%s</a>' % (slug, html.escape(label))
        return '<span class="wl-missing" title="page not found">%s</span>' % html.escape(label)

    def _tag(m):
        return '<a class="tag" href="tag-%s.html">#%s</a>' % (m.group(1).lower(), m.group(1))

    def _mdlink(m):
        label, url = m.group(1), m.group(2)
        if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", url) or url.startswith("mailto:"):
            return '<a href="%s">%s</a>' % (html.escape(url, quote=True), html.escape(label))
        # Relative markdown link: point at the generated page if we know it
        slug = ctx.resolve(os.path.splitext(os.path.basename(url))[0]) if url.endswith(".md") else None
        href = (slug + ".html") if slug else html.escape(url, quote=True)
        return '<a href="%s">%s</a>' % (href, html.escape(label))

    out = BOLD_RE.sub(_bold, out)
    out = ITALIC_RE.sub(_italic, out)
    out = WIKILINK_RE.sub(_wikilink, out)
    out = TAG_RE.sub(_tag, out)
    out = MDLINK_RE.sub(_mdlink, out)
    out = re.sub(r"\x00(\d+)\x00", _unstash, out)
    return out


def render_block(md_text, ctx):
    """Render block-level markdown: fences, headings, lists, quotes, paragraphs."""
    lines = md_text.split("\n")
    parts = []
    i = 0
    in_fence = False
    fence_buf = []

    def flush_para(buf):
        if buf:
            parts.append("<p>%s</p>" % render_inline(" ".join(buf), ctx))

    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("```"):
            if in_fence:
                parts.append("<pre><code>%s</code></pre>" % html.escape("\n".join(fence_buf)))
                fence_buf = []
                in_fence = False
            else:
                in_fence = True
            i += 1
            continue
        if in_fence:
            fence_buf.append(line)
            i += 1
            continue
        stripped = line.strip()
        if not stripped:
            flush_para([])  # paragraphs are flushed line-by-line below
            i += 1
            continue
        if stripped.startswith("#"):
            m = re.match(r"^(#{1,6})\s+(.*)", stripped)
            if m:
                level = len(m.group(1))
                anchor = slugify(m.group(2))
                parts.append('<h%d id="%s">%s</h%d>' % (level, anchor, render_inline(m.group(2), ctx), level))
                i += 1
                continue
        if stripped.startswith(">"):
            quote = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                quote.append(lines[i].strip()[1:].strip())
                i += 1
            parts.append("<blockquote>%s</blockquote>" % render_block("\n".join(quote), ctx))
            continue
        if re.match(r"^([-*+]|\d+[.)])\s+", stripped):
            items = []
            ordered = bool(re.match(r"^\d+[.)]\s+", stripped))
            while i < len(lines) and re.match(r"^([-*+]|\d+[.)])\s+", lines[i].strip()):
                items.append(re.sub(r"^([-*+]|\d+[.)])\s+", "", lines[i].strip()))
                i += 1
            tag = "ol" if ordered else "ul"
            parts.append("<%s>%s</%s>" % (tag, "".join("<li>%s</li>" % render_inline(t, ctx) for t in items), tag))
            continue
        if re.match(r"^---+$", stripped):
            parts.append("<hr>")
            i += 1
            continue
        # paragraph: gather consecutive plain lines
        buf = []
        while i < len(lines):
            s = lines[i].strip()
            if (not s or s.startswith("#") or s.startswith(">")
                    or re.match(r"^([-*+]|\d+[.)])\s+", s)
                    or s.startswith("```") or re.match(r"^---+$", s)):
                break
            buf.append(s)
            i += 1
        flush_para(buf)
    return "\n".join(parts)


def code_free(text):
    """Remove fenced and inline code spans so #tags inside code stay literal."""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    return CODE_RE.sub(" ", text)


def strip_markdown(md_text):
    """Crude plain-text extraction for the search index."""
    text = re.sub(r"```.*?```", " ", md_text, flags=re.S)
    text = re.sub(r"[#>*`\-]", " ", text)
    text = WIKILINK_RE.sub(lambda m: m.group(2) or m.group(1), text)
    text = MDLINK_RE.sub(lambda m: m.group(1), text)
    return re.sub(r"\s+", " ", text).strip()


# ----------------------------------------------------------------------------
# Notes model
# ----------------------------------------------------------------------------

class Note:
    def __init__(self, rel_path, raw):
        self.rel_path = rel_path
        self.raw = raw
        self.title = self._title()
        self.tags = sorted({t.lower() for t in TAG_RE.findall(code_free(raw))})
        self.links = [m.group(1) for m in WIKILINK_RE.finditer(raw)]
        m = DATE_RE.search(rel_path)
        self.date = m.group(1) if m else None

    def _title(self):
        m = re.search(r"^#\s+(.+)$", self.raw, re.M)
        if m:
            return m.group(1).strip()
        stem = os.path.splitext(os.path.basename(self.rel_path))[0]
        return stem.replace("-", " ").replace("_", " ").title()


def collect_notes(notes_dir, exclude):
    notes = []
    for root, dirs, files in os.walk(notes_dir):
        # skip hidden dirs early (cheap, before exclusions)
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for fname in files:
            if not fname.endswith(".md"):
                continue
            full = os.path.join(root, fname)
            rel = os.path.relpath(full, notes_dir)
            if any(fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(fname, pat) for pat in exclude):
                continue
            try:
                with open(full, encoding="utf-8") as f:
                    raw = f.read()
            except (OSError, UnicodeDecodeError):
                continue
            notes.append(Note(rel, raw))
    return notes


# ----------------------------------------------------------------------------
# Site build
# ----------------------------------------------------------------------------

CSS = """body{font-family:Georgia,serif;max-width:760px;margin:0 auto;padding:2rem 1.2rem;color:#222;background:#fdfcf9;line-height:1.65}
a{color:#1a5fb4}a.wl-missing{color:#a33;border-bottom:1px dotted #a33;cursor:help}
a.tag{background:#eef3fb;border-radius:4px;padding:0 .4em;text-decoration:none;font-size:.9em}
pre{background:#f4f1ea;padding:1rem;overflow-x:auto;border-radius:6px}
code{background:#f4f1ea;padding:.1em .3em;border-radius:4px}pre code{background:none;padding:0}
blockquote{border-left:3px solid #c9b458;margin:1em 0;padding:.2em 1em;color:#555;background:#fbf8ef}
header.site{border-bottom:2px solid #222;margin-bottom:1.5rem;padding-bottom:.5rem}
header.site h1{margin:0;font-size:1.6rem}header.site p{margin:.2em 0 0;color:#666;font-style:italic}
nav.top{margin:.6em 0;font-size:.95em}nav.top a{margin-right:1em}
.backlinks{margin-top:2.5rem;border-top:1px solid #ccc;padding-top:1rem;font-size:.95em}
footer{margin-top:3rem;border-top:1px solid #ddd;padding-top:.8rem;color:#888;font-size:.85em}
#search{width:100%;font-size:1.05rem;padding:.5em;border:1px solid #bbb;border-radius:6px}
#results{list-style:none;padding:0}#results li{margin:.6em 0}#results .t{font-weight:bold}
.cloud a{margin:.15em;display:inline-block;text-decoration:none}
table.idx{width:100%;border-collapse:collapse}table.idx td{padding:.35em .5em;border-bottom:1px solid #eee}
"""

SEARCH_JS = """const box=document.getElementById('search'),res=document.getElementById('results');
let idx=[];
fetch('search.json').then(r=>r.json()).then(d=>{idx=d;});
box.addEventListener('input',()=>{
  const q=box.value.trim().toLowerCase();
  if(q.length<2){res.innerHTML='';return;}
  const hits=[];
  for(const n of idx){
    let s=0;
    if(n.title.toLowerCase().includes(q))s+=50;
    for(const t of n.tags){if(t.includes(q))s+=20;}
    const c=n.text.toLowerCase().split(q).length-1;
    s+=Math.min(c,10)*2;
    if(s>0)hits.push([s,n]);
  }
  hits.sort((a,b)=>b[0]-a[0]);
  res.innerHTML=hits.slice(0,25).map(([s,n])=>
    `<li><a class="t" href="${n.slug}.html">${n.title}</a><br><small>${n.tags.map(t=>'#'+t).join(' ')} — ${n.text.slice(0,140)}…</small></li>`
  ).join('')||'<li><em>no matches</em></li>';
});
"""

PAGE_TMPL = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{page_title} — {site_title}</title><link rel="stylesheet" href="style.css"></head>
<body>
<header class="site"><h1><a href="index.html" style="text-decoration:none;color:inherit">{site_title}</a></h1>
<p>{subtitle}</p><nav class="top"><a href="index.html">Home</a><a href="tags.html">Tags</a><a href="archive.html">Archive</a><a href="search.html">Search</a></nav></header>
{body}
<footer>Built with wallypedia · <a href="https://github.com/wally-dk24/wallypedia">source</a></footer>
</body></html>"""


def page(site, title, body):
    return PAGE_TMPL.format(page_title=html.escape(title), site_title=html.escape(site["title"]),
                            subtitle=html.escape(site["subtitle"]), body=body)


def build(notes_dir, out_dir, config):
    notes = collect_notes(notes_dir, config["exclude"])
    ctx = WikiContext()
    slugs = {}
    for n in notes:
        base = slugify(os.path.splitext(n.rel_path)[0].replace(os.sep, "-"))
        slug = base
        k = 2
        while slug in slugs.values():
            slug = "%s-%d" % (base, k)
            k += 1
        n.slug = slug
        slugs[n.rel_path] = slug
        ctx.add(n.rel_path, slug)

    # backlinks
    backlinks = {n.slug: [] for n in notes}
    for n in notes:
        for link in n.links:
            target = ctx.resolve(link)
            if target and target != n.slug and n.slug not in [b.slug for b in backlinks[target]]:
                backlinks[target].append(n)

    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "style.css"), "w") as f:
        f.write(CSS)

    site = {"title": config["title"], "subtitle": config["subtitle"]}

    # note pages
    for n in notes:
        body = render_block(n.raw, ctx)
        if backlinks[n.slug]:
            bl = "".join('<li><a href="%s.html">%s</a></li>' % (b.slug, html.escape(b.title))
                         for b in sorted(backlinks[n.slug], key=lambda x: x.title))
            body += '<div class="backlinks"><h3>Backlinks</h3><ul>%s</ul></div>' % bl
        tagline = ""
        if n.tags:
            tagline = '<p>' + " ".join('<a class="tag" href="tag-%s.html">#%s</a>' % (t, t) for t in n.tags) + "</p>"
        with open(os.path.join(out_dir, n.slug + ".html"), "w") as f:
            f.write(page(site, n.title, tagline + body))

    # index: dated notes first (journal-style), then everything alphabetical
    dated = sorted([n for n in notes if n.date], key=lambda n: n.date, reverse=True)
    others = sorted([n for n in notes if not n.date], key=lambda n: n.title.lower())
    rows = "".join('<tr><td>%s</td><td><a href="%s.html">%s</a></td></tr>' %
                   (n.date or "—", n.slug, html.escape(n.title)) for n in dated + others)
    recent = "".join('<li><a href="%s.html">%s</a> <small>%s</small></li>' %
                     (n.slug, html.escape(n.title), n.date) for n in dated[:10])
    index_body = ("<h2>Recent</h2><ul>%s</ul><h2>All pages (%d)</h2>"
                  '<table class="idx">%s</table>' % (recent or "<li><em>no dated notes</em></li>",
                                                    len(notes), rows))
    with open(os.path.join(out_dir, "index.html"), "w") as f:
        f.write(page(site, "Home", index_body))

    # archive by date
    arch = "".join('<li><a href="%s.html">%s</a></li>' % (n.slug, html.escape(n.title)) for n in dated)
    with open(os.path.join(out_dir, "archive.html"), "w") as f:
        f.write(page(site, "Archive",
                     "<h2>Dated notes</h2><ul>%s</ul>" % (arch or "<li><em>none</em></li>")))

    # tags
    by_tag = {}
    for n in notes:
        for t in n.tags:
            by_tag.setdefault(t, []).append(n)
    cloud = " ".join(
        '<a class="tag" style="font-size:%d%%" href="tag-%s.html">#%s</a>'
        % (90 + min(len(v), 10) * 8, t, t) for t, v in sorted(by_tag.items()))
    with open(os.path.join(out_dir, "tags.html"), "w") as f:
        f.write(page(site, "Tags", "<h2>Tags</h2><div class='cloud'>%s</div>" % (cloud or "<em>none</em>")))
    for t, v in by_tag.items():
        items = "".join('<li><a href="%s.html">%s</a></li>' % (n.slug, html.escape(n.title))
                        for n in sorted(v, key=lambda x: x.title.lower()))
        with open(os.path.join(out_dir, "tag-%s.html" % t), "w") as f:
            f.write(page(site, "#%s" % t, "<h2>#%s</h2><ul>%s</ul>" % (t, items)))

    # search
    index = [{"slug": n.slug, "title": n.title, "tags": n.tags,
              "text": strip_markdown(n.raw)[:4000]} for n in notes]
    with open(os.path.join(out_dir, "search.json"), "w") as f:
        json.dump(index, f)
    search_body = ('<h2>Search</h2><input id="search" type="search" '
                   'placeholder="type to search your wiki…" autocomplete="off">'
                   '<ul id="results"></ul><script>%s</script>' % SEARCH_JS)
    with open(os.path.join(out_dir, "search.html"), "w") as f:
        f.write(page(site, "Search", search_body))

    return len(notes)


def load_config(path, overrides):
    cfg = dict(DEFAULT_CONFIG)
    if path:
        with open(path) as f:
            cfg.update(json.load(f))
    for k, v in overrides.items():
        if v is not None:
            cfg[k] = v
    return cfg


def main(argv=None):
    ap = argparse.ArgumentParser(description="wallypedia — local-first static wiki over markdown notes")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="build the static site")
    b.add_argument("--notes", help="directory of markdown notes")
    b.add_argument("--out", help="output directory for the site")
    b.add_argument("--config", help="JSON config file")
    b.add_argument("--title", help="wiki title")
    b.add_argument("--exclude", action="append", help="extra fnmatch exclusion (repeatable)")
    args = ap.parse_args(argv)

    cfg = load_config(args.config, {"notes_dir": args.notes, "out_dir": args.out, "title": args.title})
    if args.exclude:
        cfg["exclude"] = list(cfg["exclude"]) + args.exclude
    count = build(os.path.expanduser(cfg["notes_dir"]), os.path.expanduser(cfg["out_dir"]), cfg)
    print("wallypedia: built %d notes -> %s" % (count, cfg["out_dir"]))


if __name__ == "__main__":
    main()
