# UI Kit — Buddha Cognitive Lab Docs & Blog

Developer docs and the research blog for the **lab** brand. Three-column docs layout, syntax-highlighted code, callouts, an API parameter table, and a research blog with a reading view.

## Run
Open `index.html`. React + Babel + Lucide from CDN; tokens from `../../colors_and_type.css`.

## Files
- `index.html` — entry.
- `docs.css` — all styles (header, docs grid, article typography, code blocks, callouts, param table, blog).
- `docs-content.jsx` — content/data: `DOC_NAV` (sidebar tree), `ARTICLE` (the Quickstart, as ordered blocks), `POSTS` + `POST_BODY` (blog), and the `Icon` wrapper.
- `docs-app.jsx` — components (`Header, DocsView, CodeBlock, Block, BlogIndex, BlogPost, Footer`) + `App` + mount.
- `tweaks-panel.jsx` — Tweaks shell.

## Interactions
- **Header tabs:** `Docs` · `Blog` · `Research`.
- **Docs:** left nav (active item highlights), article with code blocks (**copy** button), callouts, and a params table; right "On this page" jumps to sections.
- **Blog:** post grid (one featured) → click a post → reading view → back.

## Tweaks
- **Theme → Surface:** `dark` · `light`.

## Authoring
Docs are data: edit the `ARTICLE.blocks` array in `docs-content.jsx`. Each block is `{ t: 'h2' | 'p' | 'code' | 'callout' | 'params', … }`. Code blocks are arrays of `[className, text]` token lines (`cm` comment · `kw` keyword · `st` string · `fn` function · `nm` plain · `pu` punctuation).

## Notes
Cosmetic recreation; search is non-functional. Copy is illustrative of the brand voice.
