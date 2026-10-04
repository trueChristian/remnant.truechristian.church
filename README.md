# The Heartbeat of the Remnant

A multilingual, static magazine archive for **remnant.truechristian.church**.
Built from the authoritative [Berean Voice archive](https://github.com/trueChristian/berean-voice), its [approved translations](https://github.com/trueChristian/berean-translation), and the pinned [True Christian Church theme](https://github.com/trueChristian/theme).

## Reading experience

- Complete interfaces in English and all 20 configured translation languages, including localized categories and issue dates
- Author directories and profiles in every language, with recorded details, article counts and canonical reader links
- First-class magazine issues, faithful article text and imagery, useful empty translation pages, and persistent locale/theme choices
- Per-language full-text search in a Web Worker, with Unicode matching, body snippets, category/issue filters and shareable pagination
- Site-only Scripture popovers with cached multilingual detection and editable false-positive overrides
- Stable localized article and category aliases, matching Markdown downloads with copy fallback, original issue citation, per-language RSS, sitemaps and canonical URLs
- Static HTML and ordinary links for discovery and reading; JavaScript enhances preferences, search and archive rotation

English articles do not wait for their translations. Production updates require a healthy translation export and build; validation or acquisition failures preserve the last published site. Every update must retain every published article UUID in every language; missing articles, lost locales, or an unverified live inventory block publication, even on manual runs. Completed translations publish with their recorded English provenance. Previously published English articles and approved translations remain available after source edits or removal, using verified historical source and image bytes with a localized version notice. Existing AI notice text is preserved, with its English link updated to the readable canonical URL. Human edits use the source-generated human-reviewed notice with an authoritative English link; model versions and reviewer identities are not displayed. Every translated reader links to its GitHub source editor so readers can propose a review or correction. No build starts a paid translation campaign.

## Stack

The generator and source adapter use **Python 3.11+ standard library**. Scripture detection uses the pinned OpenBible parser with Node 20+ at build time. Client code is small ES modules and CSS, with self-hosted GetBible loader components for on-demand Scripture popovers. Pinned Playwright supplies repeatable browser/visual QA. There is no framework runtime, application server or database.

## Build and check

```sh
npm ci
python3 scripts/prepare_sources.py
python3 scripts/route_registry.py
python3 scripts/build.py --registry .build/routes.json
python3 scripts/check_site.py dist --registry .build/routes.json
npm test
npx playwright install --with-deps chromium
npm run test:browser
npm run serve
```

Visit `http://localhost:8080/en/`. `dist/` is disposable generated output and is not committed. For a new build, explicitly remove old generated `dist/`; preparation requires clean output directories. For offline builds and recovery, see [operations](docs/operations.md).

## Editing and extending

- [Shared homepage rotation and verified publisher PDFs](docs/homepage-selection.md)
- [Cached Scripture references, Bible choices and false-positive overrides](docs/scripture-references.md)
- [Author directories, reviewed name aliases and multilingual article lists](docs/authors.md)
- [Source adapters, route persistence and Markdown](docs/source-adapter.md)
- [Complete dictionaries and truthful date formatting](docs/localization.md)
- [Visual identity, accessibility and performance](docs/design-and-quality.md)
- [Build workflows, publication and recovery](docs/operations.md)

Articles and categories have one canonical alias per language, keyed internally by permanent UUID. Changing only the language prefix of a known article or category URL redirects to that object's localized canonical URL. Duplicate aliases use numeric suffixes such as `title-2` and `title-3`; UUIDs never appear in canonical article, category, Markdown, or search-filter URLs. Existing UUID addresses remain redirect endpoints for old links.

`data/routes.json` owns reviewed alias changes. Each build merges it with the last successfully published `routes.json`, preserving automatically assigned aliases after title corrections and category moves. Missing translations use readable noindex pages at `/<locale>/articles/<saved-English-alias>/`, with no copied English article body. GitHub Pages serves readable prefix aliases and original-language legacy links as zero-delay HTML refresh pages with canonical/noindex metadata, rather than HTTP 301 responses. Manually changing the prefix of an old UUID-bearing history URL uses the root 404 page and a compact known-route lookup; that niche recovery requires JavaScript and replaces the browser URL with the readable canonical. Normal readable article/category prefix changes also work without JavaScript. See the [routing guide](docs/multilingual-routing-plan.md) before editing aliases.

Optional future physical covers are configured in `data/covers.json`, keyed by issue UUID:

```json
{
  "an-existing-issue-uuid": {
    "path": "/covers/approved-cover.jpg",
    "alt": { "en": "Accurate description of the supplied cover" }
  }
}
```

Place owner-approved files in `public/covers/` and supply alt text in every locale. Missing covers use explicitly typographic archive identities. No cover photography or issue facts are invented.

## Publication through GitHub Pages Actions

Pull requests run offline unit and contract tests with synthetic fixtures; they never generate the production website, fetch upstream content, run full-site browsers, or deploy. Full source-backed builds and browser checks run only from trusted main after the upstream health and no-loss gates pass. Once GitHub Pages is configured to use Actions, successful trusted `main` builds publish changed output through the `github-pages` environment and its protection rules. No extra repository variable is required. Website pushes remain automatic; manual Actions “Run workflow” on main always rebuilds and republishes after validation passes, even when revisions match. A manual run cannot bypass failed translation validation.

The website checks source revisions hourly (best effort, at minute 17). Unchanged successfully deployed pins skip the build; changes trigger a fixed-revision build and deployment. The live deployment manifest advances only with a successful Pages publication. No source notification hooks, dispatch tokens, or extra activation variables are required. Configure the actual Pages custom domain and HTTPS in the repository settings; a `CNAME` file alone does not configure a GitHub Pages Actions domain. See [operations](docs/operations.md) for setup, deduplication, and recovery.

## Rights and provenance

The repository's existing GPL-3.0 license covers website code as applicable; it does **not** relicense magazine articles, photographs, trademarks, or upstream theme assets. Article permissions and attribution remain governed by the source archive's publisher records. Source-excluded articles remain excluded.

The theme currently supplies no software license. This implementation references its pinned repository at build time rather than silently assigning it this site's GPL license. The owner should confirm intended code/asset redistribution terms before production publication. Logo, favicon and skyline bytes are preserved unchanged. No proprietary YOOtheme stylesheet is copied.
