# web/fonts — self-hosted webfonts

ClipBlitz ships its typography **locally**. There is no Google Fonts (or any other)
CDN request at runtime — the UI renders identically offline, on a locked-down
network, or on a machine with no internet at all.

## What is here

| File | Family | Weight range | Subset |
|---|---|---|---|
| `inter-latin.woff2` | Inter | 400–800 | latin |
| `inter-latin-ext.woff2` | Inter | 400–800 | latin-ext |
| `jetbrains-mono-latin.woff2` | JetBrains Mono | 400–600 | latin |
| `jetbrains-mono-latin-ext.woff2` | JetBrains Mono | 400–600 | latin-ext |
| `space-grotesk-latin.woff2` | Space Grotesk | 600–700 | latin |
| `space-grotesk-latin-ext.woff2` | Space Grotesk | 600–700 | latin-ext |

Total: **213 KB**. All three families are served by Google as *variable* fonts, so
each family is a single file covering its whole weight range rather than one file
per weight.

The `unicode-range` declarations in `styles.css` mean a browser only downloads the
`latin-ext` file if the page actually contains a character from that range — the
normal case downloads just the three `latin` files (~102 KB).

Non-Latin script (Devanagari, Arabic, CJK, …) appears in transcribed video text.
That text is **not** covered by these subsets and falls back to the system font —
which is the correct behaviour, and keeps the repo small.

## Where they came from

Fetched from the Google Fonts CSS API (`fonts.googleapis.com/css2`) with a desktop
Chrome user agent, keeping only the `latin` and `latin-ext` subsets, then renamed
deterministically. The `@font-face` block at the top of `web/styles.css` is
generated from that response and is the only place these files are referenced.

## Licences

All three families are licensed under the **SIL Open Font License 1.1**, which
permits bundling and redistribution:

- **Inter** — Rasmus Andersson — https://github.com/rsms/inter
- **JetBrains Mono** — JetBrains — https://github.com/JetBrains/JetBrainsMono
- **Space Grotesk** — Florian Karsten — https://github.com/floriankarsten/space-grotesk

## Re-fetching

To update, request the CSS for the three families, then keep only the `latin` and
`latin-ext` blocks and download each `url(...woff2)` they point at. Do not add a
CDN `<link>` back into `index.html` — local files only.
