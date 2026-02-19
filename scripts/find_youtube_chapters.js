#!/usr/bin/env node
/**
 * Script to find YouTube video chapter DOM selectors.
 * Run: npx puppeteer node scripts/find_youtube_chapters.js
 * Or: node scripts/find_youtube_chapters.js (after npm install puppeteer)
 */

const puppeteer = require('puppeteer');

const VIDEO_URL = 'https://www.youtube.com/watch?v=dBxKgNcB-gI';

const SELECTOR_QUERY = `
(async () => {
  const selectors = [
    'ytd-macro-markers-list-item-renderer',
    'ytd-engagement-panel-section-list-renderer',
    '[class*="chapter"]',
    '[class*="marker"]',
    'ytd-macro-markers-list-renderer',
    '.ytp-chapter-container',
    '.ytd-macro-markers-list-item-renderer',
    '[target-id="engagement-panel-macro-markers-description-chapters"]',
    'ytd-structured-description-content-renderer',
  ];

  const results = {};
  for (const sel of selectors) {
    const els = document.querySelectorAll(sel);
    results[sel] = {
      count: els.length,
      sample: els.length > 0 ? els[0].outerHTML.substring(0, 500) : null
    };
  }
  return results;
})();
`;

const CHAPTER_DATA_QUERY = `
(async () => {
  const scripts = document.querySelectorAll('script');
  let chapterData = null;
  for (const s of scripts) {
    const text = s.textContent;
    if (text.includes('chapterRenderer') || text.includes('macroMarkersListItemRenderer')) {
      chapterData = 'Found in script tag';
      break;
    }
  }

  const player = document.getElementById('movie_player');
  const hasGetChapters = player && typeof player.getVideoData === 'function';

  return { chapterData, hasGetChapters, playerExists: !!player };
})();
`;

const PROGRESS_BAR_QUERY = `
(async () => {
  const chapterContainers = document.querySelectorAll('.ytp-chapter-hover-container');
  const progressChapters = [];
  chapterContainers.forEach(el => {
    progressChapters.push({
      text: el.textContent?.trim()?.substring(0, 100),
      html: el.outerHTML?.substring(0, 300)
    });
  });
  return progressChapters;
})();
`;

// Additional query: check ytInitialPlayerResponse for chapter data
const PLAYER_RESPONSE_QUERY = `
(async () => {
  try {
    const scripts = document.querySelectorAll('script');
    for (const s of scripts) {
      const text = s.textContent;
      if (text.includes('ytInitialPlayerResponse')) {
        const match = text.match(/ytInitialPlayerResponse\\s*=\\s*({.+?});/s);
        if (match) {
          const data = JSON.parse(match[1]);
          const chapters = data?.playerOverlays?.playerOverlayRenderer?.decoratedPlayerBarRenderer
            ?.decoratedPlayerBarRenderer?.playerBar?.macroMarkersListRenderer?.contents;
          return {
            hasPlayerResponse: true,
            chaptersInResponse: !!chapters,
            chapterCount: chapters?.length ?? 0,
            sampleChapter: chapters?.[0] ?? null
          };
        }
      }
    }
  } catch (e) {
    return { error: e.message };
  }
  return { hasPlayerResponse: false };
})();
`;

async function main() {
  console.log('Launching browser...');
  const browser = await puppeteer.launch({ headless: true });

  try {
    const page = await browser.newPage();
    await page.setUserAgent(
      'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    );
    await page.setViewport({ width: 1920, height: 1080 });

    console.log('Navigating to:', VIDEO_URL);
    await page.goto(VIDEO_URL, { waitUntil: 'networkidle2', timeout: 30000 });

    console.log('Waiting 5 seconds for full page load...');
    await new Promise((r) => setTimeout(r, 5000));

    // Expand "Show more" / description if needed to reveal chapters
    try {
      const expandBtn = await page.$('tp-yt-paper-button#expand');
      if (expandBtn) {
        await expandBtn.click();
        await new Promise((r) => setTimeout(r, 2000));
      }
    } catch {}

    console.log('\n=== 1. Selector query results ===\n');
    const selectorResults = await page.evaluate(SELECTOR_QUERY);
    console.log(JSON.stringify(selectorResults, null, 2));

    console.log('\n=== 2. Chapter data in scripts / player API ===\n');
    const chapterDataResults = await page.evaluate(CHAPTER_DATA_QUERY);
    console.log(JSON.stringify(chapterDataResults, null, 2));

    console.log('\n=== 3. Progress bar chapter markers (.ytp-chapter-hover-container) ===\n');
    const progressResults = await page.evaluate(PROGRESS_BAR_QUERY);
    console.log(JSON.stringify(progressResults, null, 2));

    console.log('\n=== 4. ytInitialPlayerResponse chapter data ===\n');
    const playerResponseResults = await page.evaluate(PLAYER_RESPONSE_QUERY);
    console.log(JSON.stringify(playerResponseResults, null, 2));

    // Additional: get full structure of first ytd-macro-markers-list-item-renderer
    if (selectorResults['ytd-macro-markers-list-item-renderer']?.count > 0) {
      console.log('\n=== 5. Structure of first ytd-macro-markers-list-item-renderer ===\n');
      const structure = await page.evaluate(() => {
        const el = document.querySelector('ytd-macro-markers-list-item-renderer');
        if (!el) return null;
        return {
          tagName: el.tagName,
          id: el.id,
          className: el.className,
          innerHTML: el.innerHTML.substring(0, 1500),
          childSelectors: {
            title: Array.from(el.querySelectorAll('h4, #details #title, [id="title"]')).map((e) => ({
              tag: e.tagName,
              text: e.textContent?.trim()?.substring(0, 80)
            })),
            time: Array.from(el.querySelectorAll('#time, #text')).map((e) => ({
              tag: e.tagName,
              text: e.textContent?.trim()
            }))
          }
        };
      });
      console.log(JSON.stringify(structure, null, 2));
    }
  } finally {
    await browser.close();
  }
}

main().catch((err) => {
  console.error('Error:', err);
  process.exit(1);
});
