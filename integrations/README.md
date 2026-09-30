# Source publication hooks

The source changes are published as **disabled-by-default draft PRs**:

- [Berean Voice PR #65](https://github.com/trueChristian/berean-voice/pull/65), head `506d582de34c3919ca7d4bffcc19c33a8170a46e`, [passing Archive contract CI](https://github.com/trueChristian/berean-voice/actions/runs/36763359495)
- [Berean Translation PR #2](https://github.com/trueChristian/berean-translation/pull/2), head `1d984dde26fdb5d9bab96c4fde68382a08fa5028`, [passing tests](https://github.com/trueChristian/berean-translation/actions/runs/36763433518)

Neither PR is merged or activated. These patch snapshots include the same code,
tests and documentation for review and recovery. The website receiver must be
reviewed and separately authorized for publication before source notifications
are enabled. No article text or translation-publication policy is changed.

| Patch | Inspected source base | Changed workflow |
| --- | --- | --- |
| `berean-voice.patch` | `6af08032b5e2a92ff0671605fb89dffa06780892` | `.github/workflows/archive-contract.yml` |
| `berean-translation.patch` | `d3e8b2c1868caae97c1f0058bd574c5c6ce55630` | `.github/workflows/ai-worker.yml` |

Check that each patch still applies to current `main`; rebase and rerun the
source repository's own tests when it changes. For example, in a clean authorized
implementation checkout:

```sh
git apply --check /path/to/remnant-site/integrations/berean-voice.patch
git apply /path/to/remnant-site/integrations/berean-voice.patch
python3 -m unittest discover -s tests -v
python3 tools/archive.py validate
```

For translations, use `berean-translation.patch`, its test suite, and
`python3 -m berean_translation validate`. No paid campaign is required or started.
The helper modules under `.github/remnant/` are verbatim website copies of
`scripts/dispatch.py` and `scripts/validate_event.py`. Keep those copies synchronized
when the versioned event or fingerprint contract changes.

The English hook runs only after successful archive validation, tests, and
exports on trusted `main`. The translation hook is inserted **directly into the
collector after its publishing command and runtime validation, for collect operations only**, so an automated
`GITHUB_TOKEN` commit does not need to trigger a second push workflow. A new fresh
export is required, followed by a clean HEAD/current remote-main check before any
notification. The same path covers committed human review, notice removal,
source compatibility withdrawal, and publication recovery.

The fingerprint includes actual exported article/metadata/image bytes and the
selected language registry’s display fields, so a newly configured zero-article
locale triggers interface validation. Internal registry guidance is excluded. It omits
only generated manifests and revision-only metadata. It therefore ignores
internal campaign checkpoints while detecting user-facing changes. Its successful
notification marker is stored in Actions cache, never in the source catalogue or
runtime records. The marker advances only after HTTP 204. Cache loss merely
causes a safe duplicate event. A timeout leaves the marker unchanged and is safe
to retry because the website coalesces current main and deduplicates its output.

## Owner-controlled activation

Hooks stay disabled until the owner approves and securely configures both:

- Repository variable `REMNANT_NOTIFICATIONS_ENABLED` set to `true` in each source
  repository
- Secret `REMNANT_DISPATCH_TOKEN` containing an approved, narrowly scoped GitHub
  App installation token or fine-grained credential authorized for the **website
  repository only**, with the permission required by the repository-dispatch API
  (`Contents: write`). Prefer an approved GitHub App installation-token flow for
  maintained installations; short-lived tokens need approved renewal/minting
  setup. The patches deliberately do not create credentials or expand access

An ordinary source `GITHUB_TOKEN` cannot dispatch into another repository.
Installing/minting credentials or entering secrets requires separate owner secure
setup. Never paste credentials into a PR, issue, artifact, or command argument.
The helper reads the credential only from the step environment and sends it only
to the fixed GitHub API destination, with redirects refused.

See [operations](../docs/operations.md) for receiver behavior, deployment guards,
manual recovery, first-publication checks, and current verification limits.
