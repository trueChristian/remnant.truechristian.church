# Build, publication, and recovery

## Website-owned hourly publication

`Build and publish Remnant` runs a lightweight source check hourly, at minute 17
(`17 * * * *`). GitHub schedules are best effort and can start late. The website
reads the current English and translation `main` revisions and compares them,
its own selected revision, and the reviewed theme pin with the live
[`deployment.json`](https://remnant.truechristian.church/deployment.json).
If those pins match a healthy successful publication, the check exits: no source
clones, package installation, site generation, browser suite, or deployment runs.

The source repositories only own their normal validation, content, and translation
processing. Website notifications, cross-repository dispatch tokens, extra
activation variables, and source-side notification caches are no longer required.
This change does not delete or modify existing configured secrets or settings.
Bot-generated translation commits are discovered by the next poll without relying
on a second push workflow.

Website `main` pushes remain automatic. For immediate recovery or a deliberate
rebuild, open **Actions → Build and publish Remnant → Run workflow**, choose
`main`, and run it. A manual run **always builds and deploys after validation passes**, even when all pins
and display bytes match. Pull requests run offline unit and contract validation
only, including small synthetic rendered fixtures. They never generate the full
production site, export upstream repositories, or run the full-site browser suite.
Those production checks run only from trusted main; owner merge is separate.

## Last-successful-deployment baseline

The live `deployment.json` is the only persisted comparison baseline. It includes
exact site/English/translation/theme revisions, a display fingerprint, and
translation health, and the complete per-language UUID inventory. The exact checked
legacy snapshot in `data/publication-baseline.json` is used only to migrate the
existing pre-inventory deployment. There is no last-seen source marker or Actions cache that
could incorrectly acknowledge a failed build.

A candidate metadata file is generated inside `dist/` and packaged with the site.
It only becomes the next baseline when GitHub Pages successfully publishes that
artifact. A failed build, failed Pages deployment, or pending environment approval
does not update the live baseline. The next hourly check retries still-unpublished
pins. Missing, malformed, oversized, redirected, or unreachable live metadata
conservatively requests a build; the bounded metadata request sends no credentials
and permits no redirects. Preflight may conservatively repeat work after a stale response. Publication
planning separately retrieves a cache-busted live manifest with no-cache/no-store
headers; missing or invalid retention evidence blocks publication.

The preflight selects immutable full commit SHAs once. The build checks out that
exact website revision and passes the same source selection to preparation;
it never silently resolves newer source heads partway through the build. A later
source change is picked up by the next check. The theme stays pinned to
`3bd0c28956610506f83e3ecd3af6ea775ac7cb45` until a reviewed website change updates it.

The entire production workflow, from preflight through Pages completion, shares
one concurrency group and never cancels an in-flight deployment. PR groups remain
separate and cancelable. GitHub may replace a pending run; every admitted production
run starts by reading current website `main`. Use this same workflow for manual
recovery rather than creating another competing deployment path. Do not force-reset
source main to a historical commit; use a reviewed new revert commit instead.

## Publication boundary

GitHub Pages must use Actions. Packaging and deployment require this website
repository, `refs/heads/main`, a non-PR event, successful build checks, and a changed
or manually forced deployment plan. The event validator accepts only main pushes,
hourly schedules, manual runs on main, and review-only pull requests. Unsupported
notification events are rejected. There is no extra repository-variable opt-in.

The check/build jobs have only `contents: read`. The deploy job has only
`pages: write` and `id-token: write`, runs in `github-pages`, and deploys the validated
artifact without checking out or executing source scripts. Every action is pinned
to a full commit SHA. Keep environment protections and restrict production branches
to main; any configured required reviewer still controls deployment.

`dist/` is the only public artifact. Raw checkouts, runtime state, prompts, budgets,
recovery records, and logs are never copied wholesale into it. Detailed build
provenance and omission diagnostics stay in `.build/` and review evidence artifacts.
Public deployment identity and the route registry are packaged with the site;
internal source/runtime records remain private.

## Durable route aliases

Every build runs `scripts/route_registry.py` before generation. It retrieves the
previously published `https://remnant.truechristian.church/routes.json`, validates
it, and merges it with reviewed `data/routes.json` into `.build/routes.json`.
Both generation and source-backed checking use that same merged file. Automatically
assigned localized aliases survive later title corrections and category moves,
even when they have not yet been copied into the committed registry.

The generated candidate registry is published with the site. A failed build or
deployment cannot advance this baseline. Only HTTP 404 permits a first-publication
build using the committed registry alone. Network errors, other HTTP failures,
redirects, invalid schemas, and collisions stop route preparation; silently
discarding the published baseline could change existing URLs. Restore access to
the valid published registry and retry, or use a captured valid registry for an
offline review with `--published`.

Articles and categories retain localized canonical aliases. Manually replacing a
known URL's language prefix redirects directly to the same object's canonical
alias in that language, including historical paths and article category segments.
Missing translations share readable availability tails at
`/<locale>/articles/<frozen-English-alias>/`, with noindex metadata and no copied
English article body. When a translation publishes, its localized category/title
canonical retains the former availability address as a redirect. Sharing these
tails avoids a separate category/title combination for every unavailable
language. Duplicate titles use numeric suffixes, while saved aliases remain frozen. See the
[routing contract](multilingual-routing-plan.md) for migrations and validation.

Category pagination redirects to the same localized page number when available,
or that category's localized first page when the selected language has fewer
pages.

GitHub Pages has no application redirect handler. Readable prefix/history aliases
and original-language legacy UUID links serve a zero-delay HTML refresh, a
canonical link to the destination, and `noindex,follow`. They contain no duplicate
article body, lead directly to the final canonical, and work without JavaScript.
These are HTML responses, not HTTP 301/308 redirects; server-status redirects
would require a hosting layer that supports them.

The only JavaScript-dependent compatibility case is manually changing the
language prefix of a legacy UUID-bearing history URL that has no static file in
that language. The root 404 page reads the compact `legacy-route-index.json`,
matches an exact known alias, and replaces the browser address with the readable
canonical in the requested locale. Unknown paths remain errors. This avoids
publishing every legacy UUID history under every language prefix. Normal
readable article/category prefix changes remain static and work without
JavaScript. All generated navigation, feeds, sitemaps, reader Markdown, and
search-filter URLs use readable canonical aliases; legacy UUID URLs are
compatibility endpoints only.

## Local build and CI

Use Python 3.11+, Git, and Node 20+. The generator uses Python's standard library;
Node tooling and Playwright provide parsing and browser QA. No paid API or
translation campaign is started by a website build.

```sh
npm ci
python3 -m unittest discover -s tests -v
node --test tests/*.test.mjs
python3 scripts/prepare_sources.py
python3 scripts/route_registry.py
python3 scripts/build.py --english .build/english --translations .build/translations --theme .build/theme --languages .build/languages.json --registry .build/routes.json --output dist
python3 scripts/check_site.py dist --registry .build/routes.json
npx playwright install --with-deps chromium
npm run test:browser
python3 scripts/deployment.py
```

Preparation requires fresh destinations. For a repeat build, use a new
`--build-root` or explicitly remove only disposable generated output. It never
silently cleans a working source checkout. Offline/local source overrides select
committed source HEADs and create isolated detached checkouts. For an offline
review of a published site, capture its `routes.json` while online and make that
file available as `.build/published-routes.json` before running:

```sh
python3 scripts/prepare_sources.py --build-root .build-local \
  --english-checkout ../remnant-english \
  --translations-checkout ../remnant-translations \
  --theme-checkout ../remnant-theme
python3 scripts/route_registry.py --published .build/published-routes.json \
  --output .build-local/routes.json --report .build-local/route-registry-report.json
python3 scripts/build.py --english .build-local/english --translations .build-local/translations --theme .build-local/theme --languages .build-local/languages.json --registry .build-local/routes.json --output dist
python3 scripts/check_site.py dist --english .build-local/english --translations .build-local/translations --theme .build-local/theme --registry .build-local/routes.json
python3 scripts/deployment.py --source-report .build-local/source-report.json
```

`--published` reads a validated local snapshot instead of accessing the network.
Use a captured publication registry to preserve live aliases; `data/routes.json`
alone can omit automatically published additions. For an isolated initial-build
fixture, it can explicitly serve as the local baseline, but it is not a substitute
for the published registry when preparing a replacement deployment.

The lightweight check can be inspected with `python3 scripts/poll_sources.py`.
This reads public remote refs and live metadata but does not build, deploy, modify
source repositories, or advance any deployed state. Its JSON report explains whether
a build is needed. CI's selected revisions are passed through validated job outputs,
never through user-controlled URLs or executable ref expressions.

## Translation compatibility and failures

The English and translation exporters validate their contracts again. Translations
use the exact same selected English checkout. The selected translation language
registry is privately snapshotted before article export, so configured zero-article
locales and registry drift remain checkable. Raw language registry data is not
copied wholesale into public output.

Invalid English or a broken required theme stops the build and retains the last
good site. Translation acquisition/export failure still permits an English-only
local build for inspection, but deployment planning refuses to publish it.
Before generating any site pages, `scripts/check_sources.py` requires a healthy
export, validates its actual content and selected revisions, and compares its
complete locale/UUID inventory with the verified live publication. Upstream
validation failures and partial losses stop before the generator runs. The
post-build publication gate repeats the checks against actual generated readers.
Publication requires both a ready translation export and ready translated content
in the actual site-build report, with matching site/source/theme revisions. A
missing or stale report also blocks publication. Manual `--force` bypasses only
deduplication; it cannot bypass this validation gate. The last successful site and
its translation pages remain live until the selected inputs validate. No older
translations are mixed with newer English. A healthy export with zero compatible
translations is valid only when the verified live inventory also has none.

Every candidate must retain every previously published `(locale, article UUID)`
from the live `deployment.json` inventory. Updates and additions are allowed;
missing UUIDs, lost locales, malformed inventories, and an unavailable live
baseline block the entire publication. Counts alone are never sufficient. The
candidate inventory is checked against its search indexes, actual reader pages,
and build-report counts. `--force` cannot authorize removals, and neither a
source omission nor an incompatible revision is treated as a manual deletion.
Intentional removal requires a separate explicit owner action; there is no
automatic removal override in this workflow.

For the one-time migration, `data/publication-baseline.json` records the 21
served search indexes independently verified on 2026-10-04: 1,155 English and
1,935 translated articles. It is accepted only for the exact stored live
fingerprint and all four revision pins. A different or missing legacy manifest
fails closed. Never regenerate this baseline from a new candidate or assume
missing metadata means a new empty archive. Subsequent deployments carry their
own complete inventory in `deployment.json`; the legacy snapshot is then unused.
A failed candidate never advances the live baseline, so the next poll retries
the changed pins after the source has been repaired.
Normal incompatibility omits only incompatible translations. No build changes the
source publication policy or starts paid translation work.

## Recovery and rollout verification

- **Unchanged healthy sources:** only the lightweight check runs; build/deploy jobs skip
- **English invalid:** fix the source through its normal reviewed workflow; the next hourly check retries, or run the website workflow manually
- **Translation unavailable/export failed:** publication is blocked and the last successful site stays live; repair the source through its normal review process, then allow the next poll or an authorized manual run to retry
- **Build or Pages failed:** the live baseline remains unchanged; inspect the failed job/environment/domain configuration, fix it, and use Run workflow on main if immediate retry is needed
- **Missing live metadata/bootstrap:** polling requests a build, but publication fails closed until the actual last successful inventory is independently verified and restored; a missing baseline never authorizes an empty archive
- **Manual unchanged rebuild:** Run workflow on main republishes after all validation gates pass; no additional force checkbox is needed and translation failures cannot be overridden

Merge the website polling PR and the two source cleanup PRs through normal owner
review. Confirm a successful Pages job, then inspect live deployment revisions and
content. Confirm an unchanged subsequent scheduled check skips build/deploy. Confirm
future source changes are picked up without source credentials or notifications.
Offline tests and green PR CI do not establish this live end-to-end proof.

Do not delete translations, rewrite source history, force-push, regenerate paid
work, or change credentials automatically in response to a build failure. These
changes do not alter Pages settings, secrets, custom domain, DNS, or protection rules.
The owner has already reported Pages/Actions and domain setup; verify their actual
state before diagnosing a settings issue. The theme's unspecified software/asset
license remains an owner clarification; this website's GPL license does not
relicense third-party magazine articles or theme assets.

## Official references

- [Scheduled workflows and limitations](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)
- [Custom Pages workflows](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)
- [Custom-domain configuration](https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/managing-a-custom-domain-for-your-github-pages-site)
- [Workflow concurrency](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency)
