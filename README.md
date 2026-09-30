# The Heartbeat of the Remnant

A multilingual, static magazine archive for **remnant.truechristian.church**.
Built from the authoritative [Berean Voice archive](https://github.com/trueChristian/berean-voice), its [compatible translations](https://github.com/trueChristian/berean-translation), and the pinned [True Christian Church theme](https://github.com/trueChristian/theme).

## Reading experience

- Complete interfaces in English and all 20 configured translation languages, including localized categories and issue dates
- First-class magazine issues, faithful article text and imagery, useful empty translation pages, and persistent locale/theme choices
- Per-language full-text search in a Web Worker, with Unicode matching, body snippets, category/issue filters and shareable pagination
- Stable UUID-based Markdown downloads with copy fallback, original issue citation, per-language RSS, sitemaps and canonical alias routes
- Static HTML and ordinary links for discovery and reading; JavaScript enhances preferences, search and archive rotation

English publishes independently. Only compatible completed translations appear; their exact existing AI notice is preserved. Human review removes that notice but does not gate publication. No build starts a paid translation campaign.

## Stack

The generator and source adapter use **Python 3.11+ standard library only**. Client code is small, dependency-free ES modules and CSS. The only npm development dependency is pinned Playwright for repeatable browser/visual QA. There is no framework runtime, application server or database.

## Build and check

```sh
python3 scripts/prepare_sources.py
python3 scripts/build.py
python3 scripts/check_site.py dist
npm test
npm ci
npx playwright install --with-deps chromium
npm run test:browser
npm run serve
```

Visit `http://localhost:8080/en/`. `dist/` is disposable generated output and is not committed. For a new build, explicitly remove old generated `dist/`; preparation requires clean output directories. For offline builds and recovery, see [operations](docs/operations.md).

## Editing and extending

- [Source adapters, route persistence and Markdown](docs/source-adapter.md)
- [Complete dictionaries and truthful date formatting](docs/localization.md)
- [Visual identity, accessibility and performance](docs/design-and-quality.md)
- [Build workflows, publication and recovery](docs/operations.md)
- [Source-publisher hook patches](integrations/README.md)

Aliases are owned by `data/routes.json`, keyed by permanent UUID. Existing paths do not change with corrected titles or category moves. New publications have deterministic UUID-safe routes until a reviewed alias update; old category paths redirect. See the routing guide before editing aliases.

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

## Publication is deliberately disabled initially

The draft implementation does not merge, deploy or change DNS. After review, the owner must separately approve source hook PRs, securely configure destination-scoped dispatch credentials, enable Pages Actions, configure the actual custom domain and HTTPS, and enable `PAGES_DEPLOY_ENABLED`. A `CNAME` file alone does not configure a GitHub Pages Actions domain.

## Rights and provenance

The repository's existing GPL-3.0 license covers website code as applicable; it does **not** relicense magazine articles, photographs, trademarks, or upstream theme assets. Article permissions and attribution remain governed by the source archive's publisher records. Source-excluded articles remain excluded.

The theme currently supplies no software license. This implementation references its pinned repository at build time rather than silently assigning it this site's GPL license. The owner should confirm intended code/asset redistribution terms before production publication. Logo, favicon and skyline bytes are preserved unchanged. No proprietary YOOtheme stylesheet is copied.
