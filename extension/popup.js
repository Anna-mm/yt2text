// popup.js
// Chrome Extension 弹窗逻辑

const API_BASE = 'http://localhost:8765';
const POLL_INTERVAL = 5000; // 轮询间隔 5s

// ── DOM 元素 ──
const serverStatus = document.getElementById('server-status');
const btnExtract = document.getElementById('btn-extract');
const btnBatch = document.getElementById('btn-batch');
const selectAll = document.getElementById('select-all');
const videoSection = document.getElementById('video-section');
const videoList = document.getElementById('video-list');
const videoCount = document.getElementById('video-count');
const emptyState = document.getElementById('empty-state');

// ── 状态 ──
let videos = [];           // 提取到的视频列表
let taskMap = {};          // videoId → taskId 映射
let pollingTimer = null;   // 轮询定时器

// ── 持久化 ──
async function saveState() {
  await chrome.storage.local.set({
    yt2text_videos: videos,
    yt2text_taskMap: taskMap,
  });
}

async function loadState() {
  const data = await chrome.storage.local.get(['yt2text_videos', 'yt2text_taskMap']);
  if (data.yt2text_videos && data.yt2text_videos.length > 0) {
    videos = data.yt2text_videos;
    taskMap = data.yt2text_taskMap || {};
    return true;
  }
  return false;
}

// ── 初始化 ──
document.addEventListener('DOMContentLoaded', async () => {
  await checkServer();
  btnExtract.addEventListener('click', onExtract);
  btnBatch.addEventListener('click', onBatchProcess);
  selectAll.addEventListener('change', onSelectAll);

  // 尝试从缓存恢复上次的状态
  const restored = await loadState();
  if (restored) {
    renderVideoList();
    videoSection.classList.remove('hidden');
    emptyState.classList.add('hidden');
    // 恢复后立即同步一次后端任务状态
    await pollTasks();
    // 如果有进行中的任务，继续轮询
    if (hasActiveTasks()) {
      startPolling();
    }
  }
});

// ── 检查后端服务 ──
async function checkServer() {
  try {
    const res = await fetch(`${API_BASE}/api/health`, { signal: AbortSignal.timeout(3000) });
    if (res.ok) {
      serverStatus.textContent = '✅ 后端服务已连接';
      serverStatus.className = 'status-bar status-ok';
      btnExtract.disabled = false;
    } else {
      throw new Error();
    }
  } catch {
    serverStatus.innerHTML = '❌ 后端服务未启动<br><span style="font-size:11px">请运行: uvicorn server:app --port 8765</span>';
    serverStatus.className = 'status-bar status-error';
    btnExtract.disabled = true;
  }
}

// ── 提取视频 ──
async function onExtract() {
  btnExtract.textContent = '⏳ 正在提取...';
  btnExtract.disabled = true;

  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });

    // 直接在页面上执行提取函数，不依赖消息通信，更可靠
    const results = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: () => {
        const videos = [];
        const seen = new Set();
        const linkElements = document.querySelectorAll('a[href*="/watch?v="]');

        linkElements.forEach((el) => {
          const href = el.href || el.getAttribute('href');
          if (!href) return;
          const match = href.match(/\/watch\?v=([\w-]+)/);
          if (!match) return;
          const videoId = match[1];
          if (seen.has(videoId)) return;
          seen.add(videoId);

          let title = el.getAttribute('title') || '';
          if (!title && el.id === 'video-title-link') {
            title = el.textContent?.trim() || '';
          }
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
      },
    });

    videos = results?.[0]?.result || [];
    taskMap = {}; // 新提取时清空旧的任务映射

    if (videos.length > 0) {
      renderVideoList();
      videoSection.classList.remove('hidden');
      emptyState.classList.add('hidden');
      await saveState();
    } else {
      videoSection.classList.add('hidden');
      emptyState.classList.remove('hidden');
    }
  } catch (err) {
    console.error('提取失败:', err);
    videoSection.classList.add('hidden');
    emptyState.classList.remove('hidden');
  }

  btnExtract.textContent = '🔍 提取当前页面所有视频';
  btnExtract.disabled = false;
}

// ── 渲染视频列表 ──
function renderVideoList() {
  videoList.innerHTML = '';
  videoCount.textContent = `${videos.length} 个视频`;

  videos.forEach((video, index) => {
    const li = document.createElement('li');
    li.className = 'video-item';
    li.dataset.videoId = video.videoId;

    li.innerHTML = `
      <input type="checkbox" class="video-checkbox" data-index="${index}">
      <div class="video-info">
        <div class="video-title" title="${escapeHtml(video.title)}">${escapeHtml(video.title)}</div>
        <div class="video-meta">${video.duration || ''}</div>
        <div class="video-status"></div>
      </div>
      <div class="video-actions">
        <button class="btn btn-primary btn-sm btn-process" data-index="${index}">
          ▶ 转录
        </button>
      </div>
    `;

    // 单个转录按钮
    li.querySelector('.btn-process').addEventListener('click', () => {
      processVideo(index);
    });

    // 复选框变化时更新批量按钮状态
    li.querySelector('.video-checkbox').addEventListener('change', updateBatchButton);

    videoList.appendChild(li);
  });

  updateBatchButton();
}

// ── 处理单个视频 ──
async function processVideo(index) {
  const video = videos[index];
  const li = videoList.children[index];
  const btn = li.querySelector('.btn-process');
  const statusDiv = li.querySelector('.video-status');

  btn.disabled = true;
  btn.textContent = '⏳ 排队中';
  setStatusTag(statusDiv, 'queued', '排队中');

  try {
    const res = await fetch(`${API_BASE}/api/process`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url: video.url, title: video.title }),
    });
    const data = await res.json();
    taskMap[video.videoId] = data.task_id;
    await saveState();

    // 开始轮询
    startPolling();
  } catch (err) {
    setStatusTag(statusDiv, 'failed', '请求失败');
    btn.disabled = false;
    btn.textContent = '▶ 转录';
  }
}

// ── 批量处理 ──
async function onBatchProcess() {
  const selected = getSelectedIndices();
  if (selected.length === 0) return;

  btnBatch.disabled = true;
  btnBatch.textContent = '⏳ 提交中...';

  const videoPayloads = selected.map((i) => ({
    url: videos[i].url,
    title: videos[i].title,
  }));

  try {
    const res = await fetch(`${API_BASE}/api/batch`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ videos: videoPayloads }),
    });
    const data = await res.json();

    // 映射 task_id
    selected.forEach((videoIndex, i) => {
      const video = videos[videoIndex];
      taskMap[video.videoId] = data.task_ids[i];

      const li = videoList.children[videoIndex];
      const btn = li.querySelector('.btn-process');
      const statusDiv = li.querySelector('.video-status');
      btn.disabled = true;
      btn.textContent = '⏳ 排队中';
      setStatusTag(statusDiv, 'queued', '排队中');
    });

    await saveState();
    startPolling();
  } catch (err) {
    console.error('批量提交失败:', err);
  }

  btnBatch.textContent = '⚡ 批量下载并转录';
  updateBatchButton();
}

// ── 轮询任务状态 ──
function startPolling() {
  if (pollingTimer) return;
  pollingTimer = setInterval(pollTasks, POLL_INTERVAL);
}

function stopPolling() {
  if (pollingTimer) {
    clearInterval(pollingTimer);
    pollingTimer = null;
  }
}

function hasActiveTasks() {
  for (const videoId of Object.keys(taskMap)) {
    const li = videoList.querySelector(`[data-video-id="${videoId}"]`);
    if (!li) continue;
    const statusDiv = li.querySelector('.video-status');
    const currentTag = statusDiv.querySelector('.status-tag');
    if (!currentTag) return true;
    if (!currentTag.classList.contains('tag-done') && !currentTag.classList.contains('tag-failed')) {
      return true;
    }
  }
  return false;
}

async function pollTasks() {
  if (Object.keys(taskMap).length === 0) {
    stopPolling();
    return;
  }

  try {
    const res = await fetch(`${API_BASE}/api/tasks`);
    const data = await res.json();

    const taskById = {};
    data.tasks.forEach((t) => (taskById[t.id] = t));

    let hasActive = false;

    // 更新每个视频的状态
    for (const [videoId, taskId] of Object.entries(taskMap)) {
      const task = taskById[taskId];
      if (!task) continue;

      const li = videoList.querySelector(`[data-video-id="${videoId}"]`);
      if (!li) continue;

      const btn = li.querySelector('.btn-process');
      const statusDiv = li.querySelector('.video-status');

      switch (task.status) {
        case 'queued':
          setStatusTag(statusDiv, 'queued', '排队中');
          btn.textContent = '⏳ 排队中';
          btn.disabled = true;
          hasActive = true;
          break;
        case 'downloading':
          setStatusTag(statusDiv, 'downloading', '⬇️ 下载中...');
          btn.textContent = '⬇️ 下载中';
          btn.disabled = true;
          hasActive = true;
          break;
        case 'transcribing':
          setStatusTag(statusDiv, 'transcribing', '🎙️ 语音转文字中...');
          btn.textContent = '🎙️ 转录中';
          btn.disabled = true;
          hasActive = true;
          break;
        case 'formatting':
          setStatusTag(statusDiv, 'formatting', '✨ AI 整理内容中...');
          btn.textContent = '✨ AI 整理中';
          btn.disabled = true;
          hasActive = true;
          break;
        case 'done':
          setStatusTag(statusDiv, 'done', `✅ ${task.result || '完成'}`);
          btn.textContent = '✅ 完成';
          btn.disabled = true;
          break;
        case 'failed':
          setStatusTag(statusDiv, 'failed', `❌ ${task.error || '失败'}`);
          btn.textContent = '▶ 重试';
          btn.disabled = false;
          break;
      }
    }

    if (!hasActive) {
      stopPolling();
    }
  } catch (err) {
    console.error('轮询失败:', err);
  }
}

// ── 全选 / 批量按钮 ──
function onSelectAll() {
  const checked = selectAll.checked;
  videoList.querySelectorAll('.video-checkbox').forEach((cb) => {
    cb.checked = checked;
  });
  updateBatchButton();
}

function getSelectedIndices() {
  const indices = [];
  videoList.querySelectorAll('.video-checkbox').forEach((cb) => {
    if (cb.checked) indices.push(parseInt(cb.dataset.index));
  });
  return indices;
}

function updateBatchButton() {
  const selected = getSelectedIndices();
  btnBatch.disabled = selected.length === 0;
  btnBatch.textContent = selected.length > 0
    ? `⚡ 批量转录 (${selected.length})`
    : '⚡ 批量下载并转录';
}

// ── 工具函数 ──
function setStatusTag(container, type, text) {
  container.innerHTML = `<span class="status-tag tag-${type}">${escapeHtml(text)}</span>`;
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}
