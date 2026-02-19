#!/usr/bin/env python3
"""
Script to find YouTube video chapter DOM selectors.
Run: pip install playwright && playwright install chromium && python scripts/find_youtube_chapters.py
"""

import asyncio
import json

# Try playwright sync API (simpler) or async
try:
    from playwright.sync_api import sync_playwright
    USE_SYNC = True
except ImportError:
    USE_SYNC = False

VIDEO_URL = "https://www.youtube.com/watch?v=dBxKgNcB-gI"

SELECTOR_QUERY = """
(() => {
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
"""

CHAPTER_DATA_QUERY = """
(() => {
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
"""

PROGRESS_BAR_QUERY = """
(() => {
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
"""


def run_with_sync_playwright():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_extra_http_headers(
            {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
        )

        print("Navigating to:", VIDEO_URL)
        page.goto(VIDEO_URL, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(5000)  # Wait 5 seconds for full load

        # Expand description to reveal chapters
        try:
            expand = page.query_selector('tp-yt-paper-button#expand')
            if expand:
                expand.click()
                page.wait_for_timeout(2000)
        except Exception:
            pass

        results = {}
        print("\n=== 1. Selector query results ===\n")
        results["selectors"] = page.evaluate(SELECTOR_QUERY)
        print(json.dumps(results["selectors"], indent=2))

        print("\n=== 2. Chapter data in scripts / player API ===\n")
        results["chapter_data"] = page.evaluate(CHAPTER_DATA_QUERY)
        print(json.dumps(results["chapter_data"], indent=2))

        print("\n=== 3. Progress bar chapter markers ===\n")
        results["progress_bar"] = page.evaluate(PROGRESS_BAR_QUERY)
        print(json.dumps(results["progress_bar"], indent=2))

        # Structure of first ytd-macro-markers-list-item-renderer
        if results["selectors"].get("ytd-macro-markers-list-item-renderer", {}).get("count", 0) > 0:
            print("\n=== 4. Structure of first ytd-macro-markers-list-item-renderer ===\n")
            structure = page.evaluate("""
                () => {
                  const el = document.querySelector('ytd-macro-markers-list-item-renderer');
                  if (!el) return null;
                  return {
                    tagName: el.tagName,
                    id: el.id,
                    className: el.className,
                    innerHTML: el.innerHTML.substring(0, 1500),
                    childSelectors: {
                      title: Array.from(el.querySelectorAll('h4, #details #title, [id="title"]')).map(e => ({
                        tag: e.tagName,
                        text: e.textContent?.trim()?.substring(0, 80)
                      })),
                      time: Array.from(el.querySelectorAll('#time, #text')).map(e => ({
                        tag: e.tagName,
                        text: e.textContent?.trim()
                      }))
                    }
                  };
                }
            """)
            print(json.dumps(structure, indent=2, ensure_ascii=False))

        browser.close()
        return results


async def run_with_async_playwright():
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_extra_http_headers(
            {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
        )

        print("Navigating to:", VIDEO_URL)
        await page.goto(VIDEO_URL, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(5000)

        try:
            expand = await page.query_selector('tp-yt-paper-button#expand')
            if expand:
                await expand.click()
                await page.wait_for_timeout(2000)
        except Exception:
            pass

        results = {}
        print("\n=== 1. Selector query results ===\n")
        results["selectors"] = await page.evaluate(SELECTOR_QUERY)
        print(json.dumps(results["selectors"], indent=2))

        print("\n=== 2. Chapter data in scripts / player API ===\n")
        results["chapter_data"] = await page.evaluate(CHAPTER_DATA_QUERY)
        print(json.dumps(results["chapter_data"], indent=2))

        print("\n=== 3. Progress bar chapter markers ===\n")
        results["progress_bar"] = await page.evaluate(PROGRESS_BAR_QUERY)
        print(json.dumps(results["progress_bar"], indent=2))

        if results["selectors"].get("ytd-macro-markers-list-item-renderer", {}).get("count", 0) > 0:
            print("\n=== 4. Structure of first ytd-macro-markers-list-item-renderer ===\n")
            structure = await page.evaluate("""
                () => {
                  const el = document.querySelector('ytd-macro-markers-list-item-renderer');
                  if (!el) return null;
                  return {
                    tagName: el.tagName,
                    id: el.id,
                    className: el.className,
                    innerHTML: el.innerHTML.substring(0, 1500),
                    childSelectors: {
                      title: Array.from(el.querySelectorAll('h4, #details #title, [id="title"]')).map(e => ({
                        tag: e.tagName,
                        text: e.textContent?.trim()?.substring(0, 80)
                      })),
                      time: Array.from(el.querySelectorAll('#time, #text')).map(e => ({
                        tag: e.tagName,
                        text: e.textContent?.trim()
                      }))
                    }
                  };
                }
            """)
            print(json.dumps(structure, indent=2, ensure_ascii=False))

        await browser.close()
        return results


def main():
    if USE_SYNC:
        run_with_sync_playwright()
    else:
        print("Installing playwright: pip install playwright && playwright install chromium")
        print("Then run this script again.")
        asyncio.run(run_with_async_playwright())


if __name__ == "__main__":
    main()
