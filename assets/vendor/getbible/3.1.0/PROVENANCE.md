# GetBible loader adapter

Vendored from https://github.com/getbible/loader at tag **3.1.0**, commit
`03cee779c19c84d00dc652b6a0a38fd65ca1bc0e`. The adjacent MIT license applies.

Upstream files: `src/js/core/{Api,Memory,Reference,Scripture}.js`.
`Reference.js` and `Scripture.js` retain the upstream implementation. `Api.js`
retains the real GetBible query URL and request/cache pipeline, with injectable
fetch, a 12-second abort timeout, omitted credentials and no referrer. `Memory.js`
retains the upstream cache interface, key convention and 30-day TTL, with safe
storage failure handling, corrupt/future entry rejection, a bounded in-memory
fallback, and explicit invalidation for invalid API responses.

The website-owned `assets/scripture-popovers.js` uses these components directly.
It replaces the upstream eager `.getBible` scan, `innerHTML` query extraction,
30-character/ASCII-only reference filter and title-only tooltip presentation.
Canonical `data-reference` values are generated at build time. Source markup is
never queried or rewritten in the browser. API text is validated and rendered
with `textContent`/text nodes; upstream HTML formats are deliberately not used.

The interactive presentation is a non-modal accessible popover with hover,
focus, keyboard and touch support. Its reader destination is fixed to
getbible.life, with a homepage link available if the API fails. No CDN script or live version
lookup is required. No modification was made to the upstream repository.
