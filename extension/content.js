// content.js
// 注入 YouTube 页面，提取所有视频链接

/**
 * 从当前 YouTube 页面 DOM 中提取所有视频信息
 * 返回 [{ url, title, duration, videoId }]
 */
function extractVideosFromPage() {
  const videos = [];
  const seen = new Set();

  // 通用选择器：匹配所有包含 /watch?v= 的链接
  const linkElements = document.querySelectorAll('a[href*="/watch?v="]');

  linkElements.forEach((el) => {
    const href = el.href || el.getAttribute('href');
    if (!href) return;

    const match = href.match(/\/watch\?v=([\w-]+)/);
    if (!match) return;

    const videoId = match[1];
    if (seen.has(videoId)) return;
    seen.add(videoId);

    // 尝试获取标题
    let title = '';
    // 方式 1: 自身的 title 属性
    title = el.getAttribute('title') || '';
    // 方式 2: 自身的文本内容（如 #video-title-link）
    if (!title && el.id === 'video-title-link') {
      title = el.textContent?.trim() || '';
    }
    // 方式 3: 从父级视频条目中找标题元素
    if (!title) {
      const renderer = el.closest(
        'ytd-rich-item-renderer, ytd-grid-video-renderer, ytd-video-renderer, ytd-playlist-video-renderer'
      );
      if (renderer) {
        const titleEl =
          renderer.querySelector('#video-title-link') ||
          renderer.querySelector('#video-title') ||
          renderer.querySelector('yt-formatted-string#video-title');
        if (titleEl) {
          title = titleEl.getAttribute('title') || titleEl.textContent?.trim() || '';
        }
      }
    }

    // 尝试获取时长
    let duration = '';
    const renderer = el.closest(
      'ytd-rich-item-renderer, ytd-grid-video-renderer, ytd-video-renderer'
    );
    if (renderer) {
      const durationEl = renderer.querySelector(
        'ytd-thumbnail-overlay-time-status-renderer #text'
      );
      duration = durationEl?.textContent?.trim() || '';
    }

    videos.push({
      videoId,
      url: `https://www.youtube.com/watch?v=${videoId}`,
      title: title || videoId,
      duration,
    });
  });

  return videos;
}

// 监听来自 popup 的消息（作为备用通道）
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.action === 'extractVideos') {
    const videos = extractVideosFromPage();
    sendResponse({ videos });
  }
  return true;
});
