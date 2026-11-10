# Build, publication, and recovery

## Website-owned hourly publication

`Build and publish Remnant` runs a lightweight source check hourly, at minute 17
(`17 * * * *`). GitHub schedules are best effort and can start late. The website
reads the current English and translation `main` revisions and compares them,
its own selected revision, and the reviewed theme pin with the last publication
whose `github-pages` deployment GitHub confirms as successful.
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
and display bytes match. Pull requests retain the fast offline unit and contract
validation job, alongside the complete browser review described below. Publication
remains exclusive to trusted main; owner merge is separate.

## Complete browser review before merge

`.github/workflows/browser-review.yml` runs **Review complete browser suite** for
each pull request. It checks out the proposed merge revision (`github.sha`), so
the review exercises the submitted changes together with their current base.
It uses independent cancelable concurrency and a 45-minute timeout.

The review reads and verifies the last successful publication, selects upstream
revisions once with `poll_sources.py --review`, and exports that exact selection.
The normal source-health and no-loss gates run before generation. The published
Scripture ledger, retained content, and durable routes remain part of the build.
It generates the complete multilingual site, checks links and the public-output
contract, then executes unfiltered `npm run test:browser` using the normal
Playwright configuration. Browser assertions fail the check normally.

Permissions are limited to reading repository contents, Actions evidence, and
deployment metadata. The workflow has no Pages environment, artifact packaging,
deployment planning, publication, or publication-state write step. Its browser
report, screenshots, traces, selected source revisions, and bounded build evidence
are retained for 14 days, including when a check fails. A successful review is
evidence for merging; only the existing trusted-main workflow publishes the site.

## Last-successful-deployment baseline

`scripts/publication_state.py` obtains the publication authority from GitHub's
Deployments API. It requires the current successful status for `github-pages`,
checks its linked run belongs to this repository's trusted main workflow, and
verifies that the linked Pages deployment job and deployment step succeeded.
A green build, a skipped deployment, or a historically successful but now inactive
deployment cannot become the baseline.

The `publication-state` branch keeps the exact deployed `deployment.json`,
`routes.json`, and `scripture/manifest.json`, together with a receipt recording
their hashes and the successful deployment identity. This branch is metadata
storage, not website source; source polling continues to use `main`. Reads pin
one immutable state commit and verify it against GitHub's current deployment.
The deployment manifest still includes the exact four source revisions, display
fingerprint, translation health, complete per-language UUID inventory, and
retained source/image provenance.

Candidate metadata is uploaded as
`remnant-publication-metadata-<run-id>-<run-attempt>` before Pages publication.
Only the separate `record` job, after a successful Pages deployment, may update
`publication-state`. If that job is interrupted, the next run recovers the exact
newly deployed artifact instead of using an older state branch. Artifact hashes
and all existing metadata validators must pass. Initial recovery can read the
three files from the exact successful `github-pages` archive. It never recreates
the baseline from current candidate content or the old migration snapshot.

The dedicated artifact is retained for 90 days to recover an interrupted record
job. The state branch supplies durable storage beyond artifact expiry. A failed
build, failed deployment, or pending approval cannot advance the baseline.
Unavailable or invalid evidence for the actual published deployment still stops
publication with a specific recovery error. GitHub API operations have bounded
retries for temporary transport/server failures.

Preflight and build agree on the same deployment ID. Source validation, route
preparation, Scripture-ledger reuse, and final publication planning consume that
verified snapshot. Production builds therefore do not depend on browser access
to the public site's metadata URLs, including Cloudflare challenges or CDN cache
behavior. The metadata files remain packaged with the public site. Local
inspection can still use those URLs when no explicit snapshot is supplied.

The exact checked legacy snapshot in `data/publication-baseline.json` remains
restricted to migration of its matching pre-inventory deployment; it is not a
fallback for missing modern metadata.

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

The check/build jobs have `contents: read`, `actions: read`, and `deployments: read`
to verify and retrieve the published snapshot. Pull-request validation retains
only `contents: read`. The deploy job has only
`pages: write` and `id-token: write`, runs in `github-pages`, and deploys the validated
artifact without checking out or executing source scripts. Every action is pinned
to a full commit SHA. Keep environment protections and restrict production branches
to main; any configured required reviewer still controls deployment. The separate
post-deployment `record` job has `contents: write` plus Actions/deployments read
access. It checks out the exact trusted publisher revision selected by preflight
and may save metadata only for its own confirmed successful Pages deployment.

`dist/` is the only public artifact. Raw checkouts, runtime state, prompts, budgets,
recovery records, and logs are never copied wholesale into it. Detailed build
provenance and omission diagnostics stay in `.build/` and review evidence artifacts.
Public deployment identity and the route registry are packaged with the site;
internal source/runtime records remain private.

## Durable route aliases

Every build runs `scripts/route_registry.py` before generation. Production passes
the verified `.build/published/routes.json` from the successful deployment,
validates it, and merges it with reviewed `data/routes.json` into `.build/routes.json`.
Both generation and source-backed checking use that same merged file. Automatically
assigned localized aliases survive later title corrections and category moves,
even when they have not yet been copied into the committed registry.

The generated candidate registry is published with the site. A failed build or
deployment cannot advance this baseline. Local public-URL acquisition still allows
only HTTP 404 to indicate a missing first-publication registry. Invalid schemas
and collisions stop route preparation; silently discarding the published baseline
could change existing URLs. A verified snapshot is supplied with `--published`
for production and offline review.

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
python3 scripts/publication_state.py fetch --output .build/published
python3 scripts/prepare_sources.py
python3 scripts/check_sources.py --published-deployment .build/published/deployment.json
cp .build/published/scripture/manifest.json .build/scripture-manifest.json
python3 scripts/route_registry.py --published .build/published/routes.json
python3 scripts/build.py --english .build/english --translations .build/translations --theme .build/theme --languages .build/languages.json --registry .build/routes.json --output dist
python3 scripts/check_site.py dist --registry .build/routes.json
npx playwright install --with-deps chromium
npm run test:browser
python3 scripts/deployment.py --published-deployment .build/published/deployment.json
```

Snapshot acquisition accepts `GH_TOKEN` or `GITHUB_TOKEN` with repository contents,
Actions, and deployments read access. Actions supplies its ordinary job token;
no new stored secret is required. The production build allows 45 minutes, including
full validation and large artifact uploads. A prior healthy build reached the
old 30-minute limit during preview upload.

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

The lightweight check can be inspected after snapshot acquisition with
`python3 scripts/poll_sources.py --published-deployment .build/published/deployment.json`.
This reads public remote refs and verified publication metadata but does not build,
deploy, modify source repositories, or advance any deployed state. Its JSON report explains whether
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
complete locale/UUID inventory with the verified last successful publication. Upstream
validation failures and partial losses stop before the generator runs. The
post-build publication gate repeats the checks against actual generated readers.
Publication requires both a ready translation export and ready translated content
in the actual site-build report, with matching site/source/theme revisions. A
missing or stale report also blocks publication. Manual `--force` bypasses only
deduplication; it cannot bypass this validation gate. The last successful site and
its translation pages remain live until the selected inputs validate. Approved translations whose English fingerprint changed remain published with a
localized notice that identifies the older source version. A healthy export with
zero translations is valid only when the verified published inventory also has none.

Every candidate must retain every previously published `(locale, article UUID)`
from the verified last-deployed `deployment.json` inventory. Updates and additions are allowed;
missing UUIDs, lost locales, malformed inventories, and an unavailable verified
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
Source changes no longer omit approved translations. The translation exporter
marks preserved records as `stale` or `source_removed` and supplies their frozen
English snapshot provenance. The website verifies the original HTML and canonical
snapshot hash against immutable English Git objects, then recovers missing issue
and taxonomy metadata from that same revision. It never runs historical source
code. A removed English article is recovered from its last actually published
English revision, which can be newer than a translation's recorded source.

Every successful publication records the English revision for each article and
the exact image origin, digest, and public path for each language/article pair.
The bounded `retention` ledger in `deployment.json` includes an integrity digest;
missing or altered entries fail before fallback can substitute newer image bytes.
The original no-ledger deployment is migrated using its verified English revision.
Later builds carry these origins forward instead of treating each new overall
English revision as the origin of already preserved content.

Preserved images use content-addressed URLs. Previously served unversioned image
URLs remain available when missing from the current archive, without overwriting
newer current image bytes. Human-added shared images use their actual accepted
inventory; they need not have existed in the translation's original source.
A known historical path being absent permits the next verified source candidate;
network errors, unavailable commits, unsafe paths, and hash failures do not.
Asset bytes are verified again against the packaged deployment ledger.

The prebuild gate records a private `.build/retention-context.json` containing the
verified publication baseline and selected revision pins. Generation and source-backed
checking replay that same context. It and the historical Git/image cache remain
private. The public ledger contains only article identities and image/source
provenance, not translation runtime records, prompts, or human reviewer identities.
Reader and Markdown notices distinguish preserved English, a translation preserved after
an English source update, and a translation whose source was removed. They link
to the exact historical English source; the translation notice separately retains
its matching authoritative English reader link.

If an approved translation disappears entirely from the export, or its historical
proof cannot be verified, the global UUID guard still preserves the whole previous
site. A source omission is never permission to delete published content. No build
changes the source publication policy or starts paid translation work.

## Recovery and rollout verification

- **Unchanged healthy sources:** only the lightweight check runs; build/deploy jobs skip
- **English invalid:** fix the source through its normal reviewed workflow; the next hourly check retries, or run the website workflow manually
- **Translation unavailable/export failed:** publication is blocked and the last successful site stays live; repair the source through its normal review process, then allow the next poll or an authorized manual run to retry
- **Build or Pages failed:** the live baseline remains unchanged; inspect the failed job/environment/domain configuration, fix it, and use Run workflow on main if immediate retry is needed
- **Public metadata challenged or unreachable:** production uses the verified GitHub deployment snapshot and continues without accessing the public metadata URLs
- **Missing or stale state branch:** recover the exact currently deployed metadata artifact; never use an older successful publication or the current build candidate as its replacement
- **Pages succeeded but recording failed:** rerun the failed `record` job to finish durable storage. Unchanged hourly checks can read the 90-day recovery artifact but do not write the state branch; the next successful deployment also records its own metadata.
- **Missing all verified deployment evidence:** stop with the specific recovery error; a missing baseline never authorizes an empty archive
- **Manual unchanged rebuild:** Run workflow on main republishes after all validation gates pass; no additional force checkbox is needed and translation failures cannot be overridden

After an authorized rollout, confirm successful Pages and metadata-recording jobs.
Check that the `publication-state` receipt names that actual deployment and that a
fresh read recovers its exact metadata. Confirm an unchanged subsequent source
check skips build/deploy and future source changes are picked up without source
credentials or notifications. Offline tests and green PR CI do not establish this
production end-to-end proof.

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
