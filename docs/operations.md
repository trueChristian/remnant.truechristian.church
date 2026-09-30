# Build, publication, and recovery

## Safe starting state

This implementation prepares GitHub Pages publication but **does not authorize or
perform a merge, deployment, credential setup, domain change, or Pages settings
change**. Pull requests only build, test, and upload review artifacts. Production
publication requires the owner to approve setup and set the website repository
variable `PAGES_DEPLOY_ENABLED` to the exact string `true`. Keep that variable
absent/false during implementation review. Protect the `github-pages` environment
and restrict deployment branches to `main`; use required reviewers for first
publication.

`dist/` is the only public artifact. Raw checkouts, manifests, translation runtime
state, prompts, recovery records, and local logs are never copied wholesale into
it. `dist/deployment.json` contains only a display fingerprint, exact revision tuple, and translation health for conservative deduplication. Detailed provenance, omission diagnostics and budgets are kept in `.build/site-build-report.json` and the separate evidence artifact, outside the published site.

## Local build and CI

Requirements: Python 3.11+, Git, and Node 20+ for the offline JavaScript tests and Playwright browser QA. The static generator itself uses Python's standard library. No database,
server, paid API, or translation campaign is involved.

```sh
python3 -m unittest discover -s tests -v
node --test tests/*.test.mjs
python3 scripts/prepare_sources.py
python3 scripts/build.py --english .build/english --translations .build/translations --theme .build/theme --languages .build/languages.json --output dist
python3 scripts/check_site.py dist
npm ci
npx playwright install --with-deps chromium
npm run test:browser
python3 scripts/dispatch.py plan
```

Preparation uses fresh destinations. For a repeat build, choose an unused
`--build-root` or remove only your disposable prior `.build/` outputs. It does not
silently replace or clean a working source checkout. Use clean local clones when
network access is unavailable:

```sh
python3 scripts/prepare_sources.py --build-root .build-local \
  --english-checkout ../remnant-english \
  --translations-checkout ../remnant-translations \
  --theme-checkout ../remnant-theme
python3 scripts/build.py --english .build-local/english --translations .build-local/translations --theme .build-local/theme --languages .build-local/languages.json --output dist
python3 scripts/dispatch.py plan --source-report .build-local/source-report.json
```

Local overrides select each local source's committed HEAD (never uncommitted
working files), then create isolated detached checkouts. The theme is always
pinned to `3bd0c28956610506f83e3ecd3af6ea775ac7cb45`; changing it requires a reviewed
website update. In CI, English and translation `main` are resolved once each,
then fetched and exported at those exact SHAs. No event payload controls a URL,
shell command, file path, branch, or executable checkout. Site pushes, manual
runs on `main`, and notifications all check out current website `main`, so delayed
runs coalesce newer changes instead of rebuilding an old event commit. PRs use
their merge revision with read-only permissions and no deployment credentials.

The supported English and translation exporters validate the contract again.
Translations use the **same selected English checkout**. The selected translation
checkout’s complete `config/languages.json` is snapshotted privately as
`.build/languages.json` before article export. Thus configured zero-article
languages and registry drift are validated even when article export fails. The
raw registry is never copied into the public site. If translation acquisition is
unavailable, this snapshot remains absent and the build reports that limitation. An invalid English
archive or broken required theme stops the build, preserving the last good site.
Translation fetch/export failure is explicit in the summary and produces a fresh
English-only build, never stale translations. Normal incompatibility omits only
incompatible translations. When translation acquisition fails before a revision
can be selected, the report honestly records an unavailable/null revision.

## Event contract and credential boundary

Event type: `remnant-content-updated`. Exact `client_payload` schema:

```json
{
  "schema": 1,
  "repository": "trueChristian/berean-translation",
  "revision": "0123456789abcdef0123456789abcdef01234567",
  "display_fingerprint": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
}
```

The other allowed sender repository is `trueChristian/berean-voice`. Unknown
fields, source names, event types, and malformed revisions/fingerprints fail
closed. Payloads are audit hints, not proof of content validity and never a ref
selection mechanism. Authentication is supplied by GitHub's dispatch API and the
approved destination-scoped credential. Export validation remains mandatory.

Ordinary `GITHUB_TOKEN` is repository-scoped and cannot perform this cross-repo
request. Source workflows require separate, approved secure configuration. See
[the disabled source hook draft PRs and patch snapshots](../integrations/README.md). Those are separate
source PRs; this website PR alone does not enable source-driven publication.

The build job has only `contents: read`. The separate deploy job has only
`pages: write` and `id-token: write`, deploys the already-produced Pages artifact,
and runs in `github-pages`. It does not execute source scripts or check out PR
code with deployment privileges. All action references are fixed commit SHAs.

## Deduplication and publication ordering

There are two independent layers:

1. Source hooks fingerprint validated public exports, excluding generated
   manifests and revision-only JSON fields. The translation registry’s display
   fields are included even for zero-article locales; private guidance is ignored.
   A durable accepted-notification
   marker lives in branch-scoped Actions cache. Internal campaign checkpoints do
   not repeatedly dispatch unchanged content. Missing cache is safe: it causes
   one redundant notification. The translation collector dispatches explicitly
   after durable publication and validation, including bot commits, rather than
   relying on a `push` workflow that `GITHUB_TOKEN` commits normally do not start.
2. The website fingerprints actual generated display files. Only
   `build-report.json` and `deployment.json` are excluded because they record
   build provenance. A matching fingerprint, exact four-repository revision
   tuple, and translation health at the fixed live
   `https://remnant.truechristian.church/deployment.json` skip the deployment.
   Missing, invalid, oversized, redirected, or unreachable metadata causes a safe
   fresh deployment candidate instead of incorrectly suppressing publication.
   The metadata request sends no credentials and permits no redirects.

The **entire production workflow**, from source selection through Pages
completion, shares one concurrency group and is never canceled mid-deploy. PRs
have separate cancelable groups. GitHub can replace an older pending run, but each
admitted run resolves current main anew. Thus a queued old notification cannot
publish its old payload snapshot over a newer completed publication. No global
ordering is inferred from timestamps or source-event SHAs. Use the same workflow
for manual recovery; do not add a second independent production deployment job.
A delayed CDN marker normally causes a redundant safe deploy. Requiring the
revision tuple as well as the digest prevents a historical marker from suppressing
a normal content-revert commit. This assumes protected source history: do not
force-reset main to a historical commit; use a new reviewed revert commit instead.

Source display-only deduplication leaves the public provenance marker at the last
actual deployment when only upstream bookkeeping changes and no event is sent.
An explicitly triggered website build conservatively republishes if its exact
revision tuple has changed, even when the display digest matches.

## Failure and recovery

- **English invalid:** repair the source in its normal reviewed workflow. The
  existing publication remains. The next successful source hook, website push,
  or manual website run retries validation
- **Translations unavailable/invalid export:** publish valid English with no
  stale translation output. Inspect translation diagnostics. Once repaired,
  manually run the website workflow on `main` if no new source notification is
  expected; restored translation pages yield a changed display fingerprint
- **Dispatch HTTP rejection, timeout, or missing credential:** no successful
  fingerprint marker advances. Check the narrowly scoped owner-managed token,
  receiver workflow presence on main, and source job error. Rerun the failed
  trusted source workflow. A timeout may have delivered an event, but duplicates
  are safe. The collector's next successful run also retries unsent display
  changes. No token/response body is written to recovery evidence
- **Dispatch accepted but website build fails:** notification acceptance is not
  deployment success. Inspect the website Actions run and repair the failure,
  then manually rerun on `main`; source cache need not be erased
- **Pages failure:** the workflow reports failure and retains review evidence.
  Inspect the Pages job/environment/domain setup. Rerun the website workflow on
  `main`; select `force_rebuild` when deliberately republishing byte-identical
  output or recovering a site whose live fingerprint is already present
- **Duplicate/old notification:** validate it, build current selected sources,
  then skip an unchanged live display. No source payload is replayed

Do not delete translations, rewrite source history, force-push, regenerate paid
work, or change credentials as an automatic response to a build failure.

## Owner-authorized first publication checklist

1. Resolve the shared theme's currently unspecified software/asset licensing with
   the owner. The website GPL file does not relicense third-party articles or
   brand assets
2. Review and merge the website implementation; separately review the English
   and translation hook PRs. Configure approved source dispatch access securely
3. Inspect Settings → Pages for the website repository. Select GitHub Actions as
   the build/deployment source. Configure the actual custom-domain field as
   `remnant.truechristian.church`; a `CNAME` file alone does not configure an
   Actions deployment
4. Verify current authoritative DNS before changing it. For a subdomain, the
   Pages documentation describes a CNAME targeting the appropriate account Pages
   hostname; confirm the account and existing records instead of guessing or
   overwriting records. Verify domain ownership as appropriate
5. Wait for DNS/certificate readiness and enable Enforce HTTPS. Review
   `github-pages` protections and restrict it to `main`
6. Only after owner authorization, enable `PAGES_DEPLOY_ENABLED=true` and run the
   workflow on `main`. Approve the environment if required. Verify the exact
   deployed SHAs in `deployment.json`, successful Pages job, real custom-domain
   HTTPS, root language selection, English/compatible translations, Markdown,
   feeds, and direct deep-link loads
7. Enable `REMNANT_NOTIFICATIONS_ENABLED=true` in approved source repositories;
   perform a harmless authorized source-publication test and verify the receiver
   run. Keep article publication automatic after that setup

### Verification limits at implementation time (2026-09-30)

A read-only request to the public custom-domain URL from the implementation
environment returned a proxy 502, and its system hostname lookup returned no
answer. This does **not** prove a DNS error or establish current site availability.
The available repository connector did not expose Pages settings. No domain,
DNS, certificate, Pages setting, secret, token, repository variable, or environment
protection was created or changed. Live end-to-end dispatch and Pages deployment
remain owner-authorized setup/verification tasks. Offline mock tests cover the
event, bot path, deduplication, failed delivery, unchanged marker, old-event
coalescing, degraded build, and recovery behavior.

## Official references

- [GITHUB_TOKEN behavior](https://docs.github.com/en/actions/concepts/security/github_token)
- [Repository dispatch API and required permission](https://docs.github.com/en/rest/repos/repos#create-a-repository-dispatch-event)
- [Custom Pages workflows](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)
- [Custom-domain configuration](https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/managing-a-custom-domain-for-your-github-pages-site)
- [Workflow concurrency](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency)
- Pinned official actions: [checkout](https://github.com/actions/checkout/commit/3d3c42e5aac5ba805825da76410c181273ba90b1), [upload-artifact](https://github.com/actions/upload-artifact/commit/043fb46d1a93c77aae656e7c1c64a875d1fc6a0a), [upload-pages-artifact](https://github.com/actions/upload-pages-artifact/commit/7b1f4a764d45c48632c6b24a0339c27f5614fb0b), [deploy-pages](https://github.com/actions/deploy-pages/commit/d6db90164ac5ed86f2b6aed7e0febac5b3c0c03e), [source-hook cache](https://github.com/actions/cache/commit/caa296126883cff596d87d8935842f9db880ef25)
