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
`main`, and run it. A manual run **always builds and deploys**, even when all pins
and display bytes match. Pull requests always build and test for review only.
Opening a PR never deploys it; owner merge is separate.

## Last-successful-deployment baseline

The live `deployment.json` is the only persisted comparison baseline. It includes
exact site/English/translation/theme revisions, a display fingerprint, and
translation health. There is no last-seen source marker or Actions cache that
could incorrectly acknowledge a failed build.

A candidate metadata file is generated inside `dist/` and packaged with the site.
It only becomes the next baseline when GitHub Pages successfully publishes that
artifact. A failed build, failed Pages deployment, or pending environment approval
does not update the live baseline. The next hourly check retries still-unpublished
pins. Missing, malformed, oversized, redirected, or unreachable live metadata
conservatively requests a build; the bounded metadata request sends no credentials
and permits no redirects. A stale CDN response can cause a harmless repeated build.

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
Only the bounded public deployment identity is packaged with the site.

## Local build and CI

Use Python 3.11+, Git, and Node 20+. The generator uses Python's standard library;
Node tooling and Playwright provide parsing and browser QA. No paid API or
translation campaign is started by a website build.

```sh
npm ci
python3 -m unittest discover -s tests -v
node --test tests/*.test.mjs
python3 scripts/prepare_sources.py
python3 scripts/build.py --english .build/english --translations .build/translations --theme .build/theme --languages .build/languages.json --output dist
python3 scripts/check_site.py dist
npx playwright install --with-deps chromium
npm run test:browser
python3 scripts/deployment.py
```

Preparation requires fresh destinations. For a repeat build, use a new
`--build-root` or explicitly remove only disposable generated output. It never
silently cleans a working source checkout. Offline/local source overrides select
committed source HEADs and create isolated detached checkouts:

```sh
python3 scripts/prepare_sources.py --build-root .build-local \
  --english-checkout ../remnant-english \
  --translations-checkout ../remnant-translations \
  --theme-checkout ../remnant-theme
python3 scripts/build.py --english .build-local/english --translations .build-local/translations --theme .build-local/theme --languages .build-local/languages.json --output dist
python3 scripts/deployment.py --source-report .build-local/source-report.json
```

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
good site. Translation acquisition/export failure permits a fresh English-only
publication, never stale or failed-quality translations. It is reported explicitly,
including an honest null revision when no translation revision was obtainable.
A degraded translation status requests another build at the next poll even if
source revisions have not changed, allowing transient export/acquisition recovery.
Normal incompatibility omits only incompatible translations. No build changes the
source publication policy or starts paid translation work.

## Recovery and rollout verification

- **Unchanged healthy sources:** only the lightweight check runs; build/deploy jobs skip
- **English invalid:** fix the source through its normal reviewed workflow; the next hourly check retries, or run the website workflow manually
- **Translation unavailable/export failed:** inspect diagnostics; the next poll retries at the same pins, or force an immediate manual run
- **Build or Pages failed:** the live baseline remains unchanged; inspect the failed job/environment/domain configuration, fix it, and use Run workflow on main if immediate retry is needed
- **Missing live metadata/bootstrap:** a conservative full build/deploy creates the first baseline
- **Manual unchanged rebuild:** Run workflow on main always republishes; no additional force checkbox is needed

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
