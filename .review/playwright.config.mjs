// Temporary original-article review, removed before delivery of the final PR.
import { defineConfig } from '@playwright/test';
import path from 'node:path';
process.env.QUOTE_SOURCE_PATH ||= path.resolve('.review/affections-source.html');
process.env.QUOTE_IMAGE_PATH ||= path.resolve('.review/portrait.jpg');
process.env.QUOTE_THEME_PATH ||= path.resolve('.review/theme.css');
process.env.QUOTE_FONT_DIR ||= path.resolve('.review/fonts');
process.env.LION_SOURCE_PATH ||= path.resolve('.review/lion-source.html');
process.env.LION_IMAGE_PATH ||= path.resolve('.review/lion.jpg');
process.env.LION_SECOND_IMAGE_PATH ||= path.resolve('.review/lion-second.jpg');
process.env.LION_THEME_PATH ||= path.resolve('.review/theme.css');
process.env.LION_FONT_DIR ||= path.resolve('.review/fonts');
process.env.HEALING_SOURCE_PATH ||= path.resolve('.review/healing-source.html');
process.env.HEALING_IMAGE_PATH ||= path.resolve('.review/healing.jpg');
process.env.HEALING_THEME_PATH ||= path.resolve('.review/theme.css');
process.env.HEALING_FONT_DIR ||= path.resolve('.review/fonts');
process.env.REVIEW_ARCHIVE_PATH ||= path.resolve(process.env.CI ? '.review/archive' : '../review-archive-main');
export default defineConfig({
  workers: 1,
  retries: 0,
  timeout: 30000,
  reporter: [['list']],
  outputDir: '../.test-output/article-layout-review',
  use: { browserName: 'chromium', viewport: { width: 1440, height: 1000 }, locale: 'en-GB', colorScheme: 'light',
    trace: 'retain-on-failure', screenshot: 'only-on-failure' },
  projects: [
    { name: 'quotations', testDir: '../tests/browser', testMatch: 'figure-quotes.spec.mjs' },
    { name: 'lion', testDir: '../tests/browser', testMatch: 'native-figure-wrap.spec.mjs' },
    { name: 'family-photos', testDir: '.', testMatch: 'tragedy-layout.spec.mjs' },
    { name: 'healing', testDir: '../tests/browser', testMatch: 'native-verse-quote.spec.mjs' },
    { name: 'poem-sizing', testDir: '../tests/browser', testMatch: 'verse-image-sizing.spec.mjs' },
    { name: 'additional-articles', testDir: '.', testMatch: 'additional-layouts.spec.mjs' },
    { name: 'poetry-corpus', testDir: '.', testMatch: 'verse-corpus.spec.mjs' },
    { name: 'prose-corpus', testDir: '.', testMatch: 'prose-corpus.spec.mjs' },
  ],
});
