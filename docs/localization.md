# Localization contract

The site owns one UTF-8 JSON dictionary per public BCP-47 tag in `locales/`.
English and all 20 configured translation languages have a complete interface,
including locales with no published articles. Dictionaries are checked in; no
translation service or paid translation campaign runs during a build.

## Coverage and schema

Each of the 21 current dictionaries supplies:

- `meta`: exact `tag`, `native_name`, `dir`, and upstream folder `code`
- `ui`: 87 navigation, homepage, archive, search, article, accessibility, empty-state,
  download/copy, and issue-presentation labels and messages
- `categories`: every canonical category UUID, with `name`, a substantive
  category-specific `description`, and a persisted `slug`
- `seasons`: Summer, Spring, Winter, Autumn, and Fall translations
- `months`: month names under string keys `"1"` through `"12"`
- `chrome`: the 44 distinct original header/footer labels, subtitles and copyright
  prefix mapped to localized display text

The current 26-category inventory is preserved, including potentially overlapping
Church/Church Matters and Editorial/Sharpened words categories. Those remain
separate editorial identities; a translation does not consolidate them.
Descriptions are website introductions, not quotations or replacements for
article text. They describe each category specifically rather than repeating a
single generic invitation. Existing source article wording and translated article
AI notices are consumed separately and must remain unchanged.

Language metadata follows `berean-translation/config/languages.json`. URL tags
are not folder codes: for example, `zh-Hans` uses upstream code `cmn`, `nb` uses
`nob`, and `af` uses `afr`. The website-only English code is `eng`. Arabic,
Hebrew, and Urdu use `dir="rtl"`; all other configured languages use `ltr`.

The dictionaries were authored with language-model assistance. Automated checks
establish completeness, key/placeholder parity, expected scripts, and route
safety, not expert linguistic review. Native-speaker editorial improvements are
welcome and can be made without withholding English publication or published
article translations. This interface text does not imply that a translated article
has had human review.

## Labels, brands, and global chrome

Translate navigation, controls, category introductions, issue labels, and fixed
footer headings/link labels. Preserve the proper brand names GETBIBLE, Loudvoice,
SHE Cares, Amana, GitHub, Telegram, trueChristian.Church, and the magazine title
The Heartbeat of the Remnant. Keep the theme logo and its required alternative
text `A True Christian Church` untouched. Localizing display text does not change
canonical link destinations, sequence, grouping, external-link behavior, or the
two adjacent footer bands. The explicit multilingual requirement authorizes the
localized display labels; theme source files remain unchanged.

Counts use `{count}` with count-independent wording where needed. This avoids
incorrect singular/plural assumptions in languages with more complex number
rules. `minutes` is a compact reading-time label rather than a pluralized sentence.
All placeholder names must match English exactly. New placeholders must be
simple named identifiers, with no attribute access or formatting expressions.

No English fallback is injected into an otherwise localized page. Empty locales
still have all categories, issue/archive navigation, a translated explanation,
an English shortcut, and available-language choices. Article lists must still
contain only actual published articles in the current language.

## API and integration

`scripts/i18n.py` provides:

- `load_locales(path=ROOT / "locales") -> dict`: loads files keyed by public tag;
  validates the complete dictionary inventory before returning
- `validate_locales(locales, registry=None, categories=None, chrome=None) -> None`:
  raises `ValueError` with actionable errors; optional arguments compare the
  actual upstream registry, catalogue categories, and theme chrome
- `format_issue_date(issue_or_date, locale) -> str`: localized presentation of
  recorded issue date information

Build integration should pass actual source inputs to `validate_locales` so a
new configured language, category, or theme label cannot silently disappear.
A newly configured locale requires adding its dictionary and updating
`LOCALE_META`; a new UI field requires updating `UI_KEYS` and all dictionaries.
Do not silently reuse English strings to pass completeness checks.

Run standalone and upstream-aware validation:

```sh
python3 scripts/i18n.py
python3 scripts/i18n.py \
  --registry ../remnant-translations/config/languages.json \
  --catalogue ../remnant-english/catalogue.json \
  --chrome ../remnant-theme/src/data/site-chrome.json
python3 -m unittest discover -s tests -p test_i18n.py -v
```

The relative source paths above assume sibling source checkouts; CI should pass
its resolved source paths explicitly.

## Date precision

Issue dates describe the magazine issue, not a translation completion time.
Seasonal issues show a localized season and the original year; month-range
issues retain every recorded month and their sequence; year-only issues retain
only the year and any supported source qualifier. The two source forms
`2007 Special Edition` and `Special Edition 2008` use `ui.special_edition`.
Chinese and Korean put the year first with their conventional year marker.
Season names are translated as printed, never shifted for the reader's hemisphere.

No first day of a month or season is invented. A recorded exact day can be
rendered, but never inferred from a seasonal or monthly label. An unfamiliar
editorial date label is retained rather than silently discarded. Such a new label
should receive an explicit localization rule before its localized presentation is
considered complete. Machine-readable publication dates and RSS date policies
must preserve the source precision separately from this presentation helper.

## Stable localized slugs

Category names, descriptions, and slugs are stored by canonical UUID. Slugs were
initialized once and are literal dictionary values. They use the local script,
NFC normalization, and safe hyphens; renderer URLs must use proper UTF-8 URL
encoding where required. The route registry freezes chosen paths, so editing a
category display name must not derive or silently change a public path.

Slug changes require the routing layer's explicit migration/redirect history.
Validate uniqueness, reserved namespaces, path traversal, percent-encoded path
separators, and normalization before accepting a new slug. Do not regenerate all
slugs from translated names during a build.

## Verification boundaries

Unit tests cover complete locale and key inventories, external registry changes,
new source categories, missing dictionaries/keys, placeholder mismatches and
unsafe expressions, RTL metadata, native script presence, untranslated English
fallback paragraphs, distinct descriptions, preserved brands, safe unique slugs,
duplicate JSON keys, filename/tag agreement, and precision-preserving dates.

Layout quality remains a browser concern: test long translated navigation labels,
mobile menus, RTL direction and mixed-direction metadata, keyboard focus, CJK and
Indic font coverage, and light/dark modes. Dictionary validation does not claim
pixel-level layout or font coverage testing.
