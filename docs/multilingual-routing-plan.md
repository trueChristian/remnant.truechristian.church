# Multilingual routing contract

Each article and category keeps its stable identity independently of its language-specific URL. Visitors navigating the site receive the canonical localized URL. Replacing the language prefix of a known URL resolves the same article or category and redirects directly to the selected language's canonical URL.

## Acceptance criteria

- An article UUID has exactly one canonical article page for each available translation. Its title, content, category path, and article alias use the selected language.
- Categories use localized canonical paths and stable category identities. Changing only a category URL's language prefix resolves the same category and redirects to its canonical path in the selected language.
- Category pagination preserves the requested page number when that localized page exists; otherwise it opens the same category's localized first page.
- Replacing only the language prefix on any known readable canonical or historical article path resolves the article identity and redirects directly to the requested locale's canonical URL without JavaScript. The localized category segments in an article path participate in this resolution.
- Site navigation, search results, language selectors, feeds, and sitemaps link to localized canonical URLs rather than compatibility aliases.
- Missing translations display an explicit availability page with an English link and a noindex directive. English article content is never duplicated under another language prefix.
- Existing localized paths and histories remain compatibility aliases. Original-language legacy UUID addresses remain static redirect endpoints. Changed-prefix legacy UUID history permutations use exact known-alias recovery from the root 404 page and require JavaScript. UUID-bearing addresses never remain canonical reading URLs or appear in navigation, search results, feeds, or sitemaps.
- New articles and translations automatically receive readable aliases derived from their localized titles. Duplicate aliases use `title`, `title-2`, `title-3`, and so on. No UUID or issue/sequence context is appended. Existing canonical aliases containing UUIDs migrate to readable aliases. UUIDs identify content internally; generated canonical article, category, Markdown, and search-filter URLs contain no UUIDs.
- Saved aliases and the established article category path remain stable after later title corrections, category renaming, or category moves. An intentional migration preserves the previous paths as history redirects.
- Missing translations use noindex availability pages at `/<locale>/articles/<frozen-English-alias>/`. Sharing one readable tail avoids generating distinct localized category/title permutations for every unavailable language. When the translation publishes, its localized category/title supplies the canonical URL and the former availability address becomes a redirect.
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

Readable prefix/history aliases and original-language legacy UUID addresses
contain a zero-delay HTML refresh, destination canonical metadata, and
`noindex,follow`. They contain no duplicate article body, target the final
canonical page directly, and work without JavaScript. These are HTML responses
rather than HTTP 301/308 redirects; server-status redirects require additional
hosting support.

Manually changing the prefix of a legacy UUID-bearing history URL may reach the
root 404 page. That page uses `legacy-route-index.json` to match an exact known
alias and replace the browser URL with the readable canonical in the requested
language. This niche recovery requires JavaScript. Unknown paths remain errors;
there is no guessed alias fallback. Keeping this recovery index compact avoids
generating every legacy UUID history under every language prefix. Legacy UUID
addresses are accepted only to repair existing links and never appear in
canonical navigation or reader URLs.

## Verification

Route and generated-site tests check localized alias allocation, numeric
collisions, Unicode paths, frozen published aliases, article/category prefix
changes, history redirects, missing-language pages, canonical/hreflang metadata,
and UUID-free reader links. The independent output checker audits every registered
redirect and rejects chains, cycles, duplicate article bodies, and language
selectors that change article/category identity. Browser tests exercise actual
navigation and URL replacement. Required CI checks and live rollout verification
remain separate from the implementation contract.
