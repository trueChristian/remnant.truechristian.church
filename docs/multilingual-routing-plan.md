# Multilingual routing implementation

Each article and category keeps its stable identity independently of its language-specific URL. Visitors navigating the site receive the canonical localized URL. Replacing the language prefix of a known URL resolves the same article or category and redirects directly to the selected language's canonical URL.

## Acceptance criteria

- An article UUID has exactly one canonical article page for each available translation. Its title, content, category path, and article alias use the selected language.
- Categories use localized canonical paths and stable category identities. Changing only a category URL's language prefix resolves the same category and redirects to its canonical path in the selected language.
- Replacing only the language prefix on any known locale's canonical or historical article path resolves the article UUID and redirects directly to the requested locale's canonical URL. The localized category segments in an article path participate in this resolution.
- Site navigation, search results, language selectors, feeds, and sitemaps link to localized canonical URLs rather than compatibility aliases.
- Missing translations display an explicit availability page with an English link and a noindex directive. English article content is never duplicated under another language prefix.
- Existing localized paths, historical paths, and legacy article UUID addresses remain recognized as compatibility redirect endpoints. UUID-bearing addresses never remain canonical URLs or appear in navigation, search results, feeds, or sitemaps.
- New articles and translations automatically receive readable localized aliases derived from their titles and context. Existing canonical aliases containing UUIDs migrate to readable aliases. UUIDs are internal identity only: no UUID fallback or UUID collision suffix is permitted in public article or category aliases. Duplicate titles use readable issue/sequence context or a stable ordinal suffix. Generated readable aliases and paths are saved and remain stable after later title edits or category moves.
- Alias allocation and cross-language resolution are deterministic and collision-safe. A path must never silently resolve to a different article or category.
- Every available translation has a self-referencing canonical URL and reciprocal hreflang links only to actual available translations. Redirect and missing-translation pages are excluded from indexed article alternatives.
- Tests cover runtime redirects, canonical routing, category and article language switching, Unicode aliases, missing translations, existing histories, frozen paths, and alias collisions.

## Delivery

The implementation and regression tests will be committed separately on `fix/localized-alias-language-redirects`. The pull request remains a draft until the runtime behavior and required checks are verified. This document will be updated to describe the final routing behavior and operational details.
