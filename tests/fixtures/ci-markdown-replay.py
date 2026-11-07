#!/usr/bin/env python3
"""Prepare an isolated, trace-backed replay of the one failed reader test.

This only writes beneath the supplied output directory; it never edits the repository.
No browser is launched. The test metadata constants select the exact CI article;
they are local harness inputs, not substitutes for a complete site build.
"""
from __future__ import annotations

import hashlib
import json
import argparse
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit
import zipfile

BASE = '067b086b253aa3487355e1a5662ee4d0e65d10e6'
ARTICLE_ID = '049f2e7d-675c-4dac-9584-5aefceb9b9c1'
ARTICLE_PATH = '/af/redaksioneel/van-die-redakteur-8/'
TEST_NAME = 'Markdown fallback preserves selectable text when clipboard unavailable'
ORIGIN = 'http://127.0.0.1:8080'
ORIGINAL_SOURCE = 'src/e0cda083085bf943bd061cc5554feb0588cbb305.mjs'
THEME_REVISION = '3bd0c28956610506f83e3ecd3af6ea775ac7cb45'
THEME_SHA256 = 'a2d0a48513717595b5f991eaa0c6aa2f75d95d78a0cbb9d2822376e021c1dcf2'
# Verified against exact BASE Git objects before preparing this helper.
SCRIPT_SHA256 = {
    'assets/preferences.js': 'd8b28d082d87f6c30aacddbcab5ec1c452654fcec99ab8bb8c04dea5b1e1d90f',
    'assets/site.js': '94251f3465970dacd68a655b9ede5adfe2685550df7f511ee80c7c252073a804',
    'assets/article-figures.js': 'c18ec66e70d76a51cbd63aa58b334771339ed3b04b06ab7c14d526cdc2a434b9',
    'assets/scripture-popovers.js': '7e68b53d6a1b6b3fff4bebd100f4149f72fad8dbf852c033c2dfaf3fa6feee21',
    'assets/search-core.js': 'ae22e41c31f2eee0494a8859bf92d839978b2d633cb0e67ee112051e8767ca7e',
    'assets/vendor/getbible/3.1.0/Api.js': 'ef1e713a2c2d7c36371bbfbf2a5f4c70e75f8414c50a9f86967c986b8cd7c305',
    'assets/vendor/getbible/3.1.0/Memory.js': 'c85a77fa1a7f2505ffd3f4b30d375a62979517ff309f3ae686ea5d3d8c186a32',
    'assets/vendor/getbible/3.1.0/Scripture.js': '55dc31f9d38635efe3f30df25e5de1c1a105d2749acbf3cb630afe23b1328152',
    'assets/vendor/getbible/3.1.0/Reference.js': '36e436ed9bdb6597ca7e985ceac83349c83d81e44dec05004b32eeb7a54f1c98',
}


def write(work: Path, relative: str, data: bytes) -> Path:
    path = work / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def json_write(work: Path, relative: str, data: object) -> None:
    write(work, relative, (json.dumps(data, indent=2, ensure_ascii=False) + '\n').encode())


def target_block(source: str) -> str:
    start = source.index(f"test('{TEST_NAME}',")
    end = source.index('\n});', start) + len('\n});')
    return source[start:end]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trace', required=True, type=Path)
    parser.add_argument('--repo', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--theme', required=True, type=Path,
                        help='Exact theme.js fixture from verified previous Pages archive')
    args = parser.parse_args()
    work, repo = args.output.resolve(), args.repo.resolve()
    work.mkdir(parents=True, exist_ok=True)
    theme = args.theme.read_bytes()
    assert hashlib.sha256(theme).hexdigest() == THEME_SHA256, 'Theme fixture digest mismatch'
    assert f"THEME_REVISION = '{THEME_REVISION}'" in (
        repo / 'scripts/prepare_sources.py').read_text(), 'Pinned theme revision changed'
    manifest = {
        'purpose': 'LOCAL REPLAY HARNESS ONLY: one recorded failing browser test, not full-site validation',
        'failed_run_id': 42354921017,
        'article_id': ARTICLE_ID,
        'article_path': ARTICLE_PATH,
        'base_commit': BASE,
        'theme_revision': THEME_REVISION,
        'recorded_browser': 'Chromium 156.0.8078.4 / Playwright 1.64.1',
        'local_browser_execution': 'Not attempted: parent reported sandbox socket denial and rejected escalation',
        'files': [],
    }
    external = {}
    missing = {}
    with zipfile.ZipFile(args.trace) as archive:
        original = archive.read(ORIGINAL_SOURCE).decode()
        for line in archive.read('1-trace.network').splitlines():
            snapshot = json.loads(line).get('snapshot', {})
            request = snapshot.get('request', {})
            if not request:
                continue
            url = request['url']
            response = snapshot['response']
            assert response['status'] == 200, (url, response['status'])
            content = response['content']
            resource = content.get('_file')
            parsed = urlsplit(url)
            path = unquote(parsed.path).lstrip('/')
            assert '..' not in PurePosixPath(path).parts
            local = f'{parsed.scheme}://{parsed.netloc}' == ORIGIN
            if resource is None:
                assert local and path.endswith('.js'), url
                missing[path] = url
                continue
            data = archive.read(resource)
            if local:
                destination = f'dist/{path}' + ('index.html' if path.endswith('/') else '')
            else:
                destination = f'external/{PurePosixPath(resource).name}'
                external[url] = {'path': destination, 'contentType': content['mimeType']}
            write(work, destination, data)
            manifest['files'].append({
                'path': destination, 'bytes': len(data),
                'sha256': hashlib.sha256(data).hexdigest(),
                'source': f'trace.zip:{resource}', 'request_url': url,
                'captured_body_preserved_exactly': True,
            })
    # Playwright did not capture module-script response bodies. Require repository
    # assets to match SHA-256 hashes verified against the exact run's Git objects.
    for path, url in missing.items():
        if path == 'assets/theme.js':
            data = theme
            source = 'verified-previous-pages:artifact.tar:./assets/theme.js'
        else:
            data = (repo / path).read_bytes()
            assert hashlib.sha256(data).hexdigest() == SCRIPT_SHA256[path], path
            source = f'git:{BASE}:{path}'
        destination = 'dist/' + path
        write(work, destination, data)
        manifest['files'].append({
            'path': destination, 'bytes': len(data),
            'sha256': hashlib.sha256(data).hexdigest(),
            'source': source, 'request_url': url,
            'captured_body_preserved_exactly': None,
            'note': 'Trace records HTTP 200 but omits the module response body',
        })
    json_write(work, 'external-resources.json', external)
    current = (repo / 'tests/browser/reader.spec.mjs').read_text()
    prefix = f'''// LOCAL REPLAY HARNESS: exact CI article selection, not full export metadata.
import {{ test, expect }} from '../replay-fixture.mjs';
const afCandidate = {{ id: {json.dumps(ARTICLE_ID)} }};
const noticeRequired = true;
const article = locale => {{
  if (locale !== 'af') throw new Error('Replay only contains the captured Afrikaans article');
  return {json.dumps(ARTICLE_PATH)};
}};

'''
    for name, source in [('original', original), ('fixed', current)]:
        block = target_block(source)
        write(work, f'tests/reader.{name}.spec.mjs', (prefix + block + '\n').encode())
        manifest[f'{name}_test_block_sha256'] = hashlib.sha256(block.encode()).hexdigest()
    write(work, 'replay-fixture.mjs', b'''// LOCAL REPLAY HARNESS: serve captured external fonts without remote requests.
import { test as base, expect } from '@playwright/test';
import fs from 'node:fs';
const resources = JSON.parse(fs.readFileSync(new URL('./external-resources.json', import.meta.url)));
export const test = base.extend({
  page: async ({ page }, use) => {
    await page.route('**/*', async route => {
      const url = route.request().url();
      if (new URL(url).origin === 'http://127.0.0.1:8080') return route.continue();
      const entry = resources[url];
      if (!entry) throw new Error(`Uncaptured external resource in local replay: ${url}`);
      await route.fulfill({ status: 200, contentType: entry.contentType,
        body: fs.readFileSync(new URL(entry.path, import.meta.url)) });
    });
    await use(page);
  },
});
export { expect };
''')
    write(work, 'playwright.config.mjs', f'''// LOCAL REPLAY HARNESS ONLY. No repository configuration changes.
import {{ defineConfig }} from '@playwright/test';
export default defineConfig({{
  testDir: './tests', fullyParallel: false, workers: 1, retries: 0, timeout: 30000,
  reporter: [['list']],
  outputDir: './results/' + (process.env.REPLAY_VARIANT || 'replay'),
  use: {{
    baseURL: '{ORIGIN}', viewport: {{ width: 1440, height: 1000 }},
    locale: 'en-GB', colorScheme: 'light', trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  }},
  projects: [{{ name: 'chromium', use: {{ browserName: 'chromium' }} }}],
  webServer: {{
    command: 'python3 -m http.server 8080 --bind 127.0.0.1 --directory dist',
    url: '{ORIGIN}{ARTICLE_PATH}', reuseExistingServer: false, timeout: 30000,
  }},
}});
'''.encode())
    modules = work / 'node_modules'
    if not modules.exists():
        modules.symlink_to(repo / 'node_modules', target_is_directory=True)
    # Markdown's recorded resource is the trace's captured text representation.
    # Its resource bytes differ from recorded Content-Length. Keep them intact;
    # do not claim they reconstruct uncaptured network octets.
    manifest['trace_text_encoding_limit'] = {
        'markdown_captured_resource_bytes': 5488,
        'markdown_recorded_content_length': 5355,
        'note': 'Replay preserves trace resource bytes exactly; trace may reencode captured text.',
    }
    json_write(work, 'provenance.json', manifest)
    write(work, 'README.txt', '''LOCAL TRACE REPLAY HARNESS ONLY

This isolates the exact Markdown fallback test and selected CI article. It is
not a complete site build and does not assert the integrity of all exports.
Every captured response resource is preserved byte-for-byte. Missing script
bodies come from the exact run's site Git commit or the unchanged pinned theme
from the existing verified prior Pages artifact. See provenance.json.

Original and fixed test bodies are extracted without edits. Only their import
and top-level article-selection inputs are supplied by this local harness.
Captured external fonts are fulfilled from local bytes. Unknown external
requests fail; no live site or Cloudflare access is needed.

Browser execution was not attempted: the parent reported a sandbox local-socket
denial and an explicitly rejected escalation. Do not use this helper to bypass
that restriction. It may be moved to an authorized CI runner with dependencies
and the configured browser installed. This config uses the regular browser
installed by the repository's pinned Playwright 1.64.1 package.

For an authorized environment, run from this directory:
  REPLAY_VARIANT=original node node_modules/@playwright/test/cli.js test tests/reader.original.spec.mjs
  REPLAY_VARIANT=fixed node node_modules/@playwright/test/cli.js test tests/reader.fixed.spec.mjs

Expected original result is the exact case-sensitive publication-title failure.
Expected fixed result checks the full download, fallback visibility, focus,
complete selection, AI notice, issue URL, and re-enabled copy button.

Trace caveat: the Markdown resource is 5488 bytes but its recorded HTTP
Content-Length is 5355. Its captured representation is retained unchanged.
'''.encode())
    print(json.dumps({
        'directory': str(work), 'recorded_resources': len(external) + sum(
            item['captured_body_preserved_exactly'] is True and item['path'].startswith('dist/')
            for item in manifest['files']),
        'recovered_scripts': len(missing),
        'original_test_block_sha256': manifest['original_test_block_sha256'],
        'fixed_test_block_sha256': manifest['fixed_test_block_sha256'],
    }, indent=2))


if __name__ == '__main__':
    main()
