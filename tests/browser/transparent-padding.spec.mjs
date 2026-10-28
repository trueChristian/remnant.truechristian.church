import { test, expect } from '@playwright/test';
import fs from 'node:fs';
import { execFileSync } from 'node:child_process';

// Use the production transformer and reviewed bounds with a transparent fixture
// of the same dimensions. No upstream download is needed for this regression.
const identity = '10933457-b503-48e1-9346-49ff54d1b6fe';
const filename = `${identity}-2.png`;
const source = `<article data-article-id="${identity}"><p>Preceding prose.</p>
<figure><img src="/images/articles/${filename}" alt="Orchid illustration" width="460" height="901"><figcaption>Original credit.</figcaption></figure>
<blockquote><p>Following quotation remains below the illustration.</p></blockquote></article>`;
const arranged = execFileSync('python3', ['-c', `
import sys
sys.path.insert(0, 'scripts')
from article_figures import arrange_article_figures, load_figure_rules
print(arrange_article_figures(sys.stdin.read(), load_figure_rules('data/article-image-layouts.json')))
`], { input: source, encoding: 'utf8' });
const css = ['assets/site.css', 'assets/article-figures.css'].map(file => fs.readFileSync(file, 'utf8')).join('\n');
const illustration = '<svg xmlns="http://www.w3.org/2000/svg" width="460" height="901"><rect y="384" width="460" height="517" fill="#bd7b22"/></svg>';

for (const javaScriptEnabled of [true, false]) {
  test(`transparent padding takes no layout space, JavaScript ${javaScriptEnabled ? 'on' : 'off'}`, async ({ browser }) => {
    const context = await browser.newContext({ javaScriptEnabled });
    const page = await context.newPage();
    await page.route('**/*', async route => {
      const path = new URL(route.request().url()).pathname;
      if (path.endsWith(filename)) return route.fulfill({ contentType: 'image/svg+xml', body: illustration });
      if (path.endsWith('.js')) return route.fulfill({ contentType: 'text/javascript', body: fs.readFileSync('assets/article-figures.js', 'utf8') });
      return route.fulfill({ contentType: 'text/html', body: `<!doctype html><html><head><style>${css}
        body{margin:16px}.prose{max-width:750px;margin:auto}</style>
        <script type="module" src="/assets/article-figures.js"></script></head><body><div class="prose">${arranged}</div></body></html>` });
    });
    await page.goto('http://127.0.0.1:8080/padding-fixture/');
    for (const width of [1440, 768, 390, 320]) {
      await page.setViewportSize({ width, height: 1000 });
      for (const dir of ['ltr', 'rtl']) {
        await page.locator('html').evaluate((node, value) => node.dir = value, dir);
        const boxes = await page.locator('figure').evaluate(figure => {
          const box = selector => {
            const { top, bottom, left, right, width, height } = figure.querySelector(selector).getBoundingClientRect();
            return { top, bottom, left, right, width, height };
          };
          return { frame: box('.article-image-window'), image: box('img'), caption: box('figcaption'),
            quoteTop: figure.nextElementSibling.getBoundingClientRect().top,
            scrollWidth: document.documentElement.scrollWidth, viewport: innerWidth };
        });
        expect(boxes.frame.width).toBeLessThanOrEqual(460);
        expect(boxes.frame.height / boxes.frame.width).toBeCloseTo(517 / 460, 2);
        // The first visible pixel begins at the frame top, not 384 rows below it.
        expect(Math.abs(boxes.image.top + 384 * boxes.image.width / 460 - boxes.frame.top)).toBeLessThan(1);
        expect(Math.abs(boxes.image.bottom - boxes.frame.bottom)).toBeLessThan(1);
        expect(boxes.caption.top).toBeGreaterThanOrEqual(boxes.frame.bottom);
        expect(boxes.quoteTop).toBeGreaterThanOrEqual(boxes.caption.bottom);
        expect(boxes.scrollWidth).toBeLessThanOrEqual(boxes.viewport);
        await expect(page.locator('figure')).not.toHaveClass(/article-figure--wrap/);
        await expect(page.locator('img')).toHaveAttribute('alt', 'Orchid illustration');
      }
    }
    await page.emulateMedia({ media: 'print' });
    const print = await page.locator('.article-image-window').boundingBox();
    expect(print.height / print.width).toBeCloseTo(517 / 460, 2);
    await expect(page.locator('figcaption')).toHaveText('Original credit.');
    await context.close();
  });
}
