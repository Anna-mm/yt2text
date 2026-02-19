// background.js
// 点击扩展图标时直接打开 Side Panel（无需二次确认）

chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true });

// 仅在 YouTube 视频页面启用 Side Panel
chrome.tabs.onUpdated.addListener(async (tabId, changeInfo, tab) => {
  if (!tab.url) return;
  if (tab.url.includes('youtube.com/watch')) {
    await chrome.sidePanel.setOptions({
      tabId,
      path: 'sidepanel.html',
      enabled: true,
    });
  } else {
    await chrome.sidePanel.setOptions({
      tabId,
      enabled: false,
    });
  }
});
