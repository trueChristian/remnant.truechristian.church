# Multilingual routing contract

Each article and category keeps its stable identity independently of its language-specific URL. Visitors navigating the site receive the canonical localized URL. Replacing the language prefix of a known URL resolves the same article or category and redirects directly to the selected language's canonical URL.

## Acceptance criteria

- An article UUID has exactly one canonical article page for each available translation. Its title, content, category path, and article alias use the selected language.
- Categories use localized canonical paths and stable category identities. Changing only a category URL's language prefix resolves the same category and redirects to its canonical path in the selected language.
- Replacing only the language prefix on any known locale's canonical or historical article path resolves the article UUID and redirects directly to the requested locale's canonical URL. The localized category segments in an article path participate in this resolution.
- Site navigation, search results, language selectors, feeds, and sitemaps link to localized canonical URLs rather than compatibility aliases.
- Missing translations display an explicit availability page with an English link and a noindex directive. English article content is never duplicated under another language prefix.
- Existing localized paths, historical paths, and legacy article UUID addresses remain recognized as compatibility redirect endpoints. UUID-bearing addresses never remain canonical URLs or appear in navigation, search results, feeds, or sitemaps.
- New articles and translations automatically receive readable aliases derived from their localized titles. Duplicate aliases use `title`, `title-2`, `title-3`, and so on. No UUID or issue/sequence context is appended. Existing canonical aliases containing UUIDs migrate to readable aliases. UUIDs identify content internally; generated canonical article, category, Markdown, and search-filter URLs contain no UUIDs.
- Saved aliases and the established article category path remain stable after later title corrections, category renaming, or category moves. An intentional migration preserves the previous paths as history redirects.
- Missing translations receive readable planned aliases and noindex availability pages. When the translation publishes, its localized title supplies the canonical alias and the former availability address becomes a redirect.
- Alias allocation and cross-language resolution are deterministic and collision-safe. A path must never silently resolve to a different article or category.
- Every available translation has a self-referencing canonical URL and reciprocal hreflang links only to actual available translations. Redirect and missing-translation pages are excluded from indexed article alternatives.
- Tests cover runtime redirects, canonical routing, category and article language switching, Unicode aliases, missing translations, existing histories, frozen paths, and alias collisions.

## Registry lifecycle

`data/routes.json` owns reviewed editorial migrations. Before generation,
`scripts/route_registry.py` merges it with the last successfully published
`routes.json` into `.build/routes.json`. Generation and checking both use
`--registry .build/routes.json`. The generated candidate is published with the
site and becomes the next durable baseline only when publication succeeds.
Automatically assigned aliases therefore persist without a repository-maintenance
commit. Retired aliases and their histories remain reserved.

Only a 404 response permits a first-publication baseline. Other request failures,
redirects, invalid registry data, and alias conflicts stop preparation rather than
risk changing published URLs. Offline review uses `--published` with a captured
valid registry. See [operations](operations.md) for commands and recovery.

The source article UUID and source HTML remain unchanged. The renderer updates
only a known English UUID-link `href` to its readable English canonical in article
HTML and reader Markdown; AI notice text and attribution are preserved.

## Static-host redirect behavior

GitHub Pages compatibility addresses contain a zero-delay HTML refresh,
destination canonical metadata, and `noindex,follow`. They contain no duplicate
article body and target the final canonical page directly. These are HTML
responses rather than HTTP 301/308 redirects; server-status redirects require
additional hosting support. Legacy UUID addresses are accepted only to repair
existing links and never appear in canonical navigation or reader URLs.

## Verification

Route and generated-site tests check localized alias allocation, numeric
collisions, Unicode paths, frozen published aliases, article/category prefix
changes, history redirects, missing-language pages, canonical/hreflang metadata,
and UUID-free reader links. The independent output checker audits every registered
redirect and rejects chains, cycles, duplicate article bodies, and language
selectors that change article/category identity. Browser tests exercise actual
navigation and URL replacement. Required CI checks and live rollout verification
remain separate from the implementation contract.
