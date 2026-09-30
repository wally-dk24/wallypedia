# Wallypedia

**Wallypedia** is a local-first static wiki generator for your markdown notes. Point it at a folder of `.md` files — daily logs, people pages, project notes — and it builds a browsable wiki: `[[WikiLinks]]`, backlinks, `#tags`, date archives, and full-text search. One Python file, stdlib only, no dependencies, no server.

## Why

Vector embeddings are great until your notes live in plain text and you just want to *read them*. Wallypedia treats Markdown as the source of truth:

- `[[WikiLinks]]` turn names into pages automatically; every page shows its **backlinks**
- `#tags` become tag pages with a tag cloud
- `search.json` + a tiny script give **client-side full-text search** — no backend, no build step, works off `file://`
- filenames with dates (`2026-09-30.md`) get a **recent/archive** view

Inspirations: the auto-wiki ideas in Tencent/WeKnora, VectifyAI/PageIndex's vectorless document indexing, and the agent-memory projects treating markdown as the source of truth (tigerless-labs/agent-memory, vectorize-io/hindsight).

## Privacy by design

This tool runs **on your machine**. The generator reads your notes directory and writes static HTML you serve yourself. Your notes never leave your computer — only this engine is public. The default `exclude` list skips anything that smells like a secret (`*secret*`, `*credential*`, `*password*`, `*token*`, `*.pem`, …); add your own patterns in the config.

## Usage

```bash
python3 wallypedia.py build --notes ~/my-notes --out ~/my-notes/site
python3 wallypedia.py build --config wallypedia.json
```

`wallypedia.json`:

```json
{
  "notes_dir": "~/my-notes",
  "out_dir": "~/my-notes/site",
  "title": "My Wiki",
  "subtitle": "everything I know",
  "exclude": ["drafts/*", "*secret*"]
}
```

Serve it: `cd site && python3 -m http.server 8000` — or just open `index.html`.

## Wiki syntax

On top of a pragmatic Markdown subset (headings, lists, quotes, code fences, bold/italic, links):

- `[[Page Name]]` / `[[Page Name|label]]` — link to another note by filename or title; missing targets render as a dashed "page not found" hint
- `#tag` — tags become tag pages automatically

## The `example-notes/` directory

A tiny synthetic wiki (nothing real) so you can try it instantly:

```bash
python3 wallypedia.py build --notes example-notes --out site
```

## Roadmap

- [ ] incremental rebuilds (only changed notes)
- [ ] `[[wikilink]]` autocompletion list export for editors
- [ ] RSS/Atom feed of recent dated notes
- [ ] graph view of the link network
- [ ] optional "sleep-time" digest: auto-generated daily summary page from dated notes

## License

MIT

## Docker

```bash
docker pull wallydk24/wallypedia
docker run --rm -v ~/notes:/notes -v ~/site:/site wallydk24/wallypedia \
  build --notes /notes --out /site
```

Then open `~/site/index.html`. Mounted notes are read-only; the site is
written to the `/site` volume.
