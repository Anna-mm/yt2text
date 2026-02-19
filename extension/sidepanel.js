// sidepanel.js — 极简版

const API_BASE = 'https://yt2text-production.up.railway.app';
const POLL_INTERVAL = 1000;

// ── DOM ──
const videoTitle = document.getElementById('video-title');
const btnAction = document.getElementById('btn-action');
const notVideo = document.getElementById('not-video');
const topBar = document.getElementById('top-bar');
const resultSection = document.getElementById('result-section');
const resultContent = document.getElementById('result-content');
const btnCopy = document.getElementById('btn-copy');
const errorSection = document.getElementById('error-section');
const errorMessage = document.getElementById('error-message');
const formattingStatus = document.getElementById('formatting-status');

// ── 状态 ──
let currentVideoId = null;
let currentUrl = null;
let taskId = null;
let pollingTimer = null;

// ── 初始化 ──
document.addEventListener('DOMContentLoaded', async () => {
  await detectVideo();
  btnAction.addEventListener('click', onAction);
  btnCopy.addEventListener('click', onCopy);

  // 切换标签页
  chrome.tabs.onActivated.addListener(() => detectVideo());

  // 页面 URL 或标题变化（YouTube SPA 导航时 URL 先变，标题稍后才更新）
  chrome.tabs.onUpdated.addListener((_, info) => {
    if (info.url || info.title) detectVideo();
  });
});

// ── 检测当前视频 ──
let _detectTimer = null;

async function detectVideo() {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    const url = tab?.url || '';
    const match = url.match(/youtube\.com\/watch\?v=([\w-]+)/);

    if (match) {
      const newVideoId = match[1];
      const videoChanged = newVideoId !== currentVideoId;
      currentVideoId = newVideoId;
      currentUrl = `https://www.youtube.com/watch?v=${currentVideoId}`;

      const title = await getVideoTitle(tab);
      videoTitle.textContent = title || '未知视频';
      videoTitle.title = title || '';

      topBar.classList.remove('hidden');
      notVideo.classList.add('hidden');

      if (videoChanged) {
        // 视频切换了：重置 UI，恢复该视频的任务状态
        resetUI();
        await restoreTaskState();

        // YouTube SPA 标题更新有延迟，500ms 后再取一次确保标题正确
        clearTimeout(_detectTimer);
        _detectTimer = setTimeout(async () => {
          const [freshTab] = await chrome.tabs.query({ active: true, currentWindow: true });
          if (freshTab) {
            const freshTitle = await getVideoTitle(freshTab);
            if (freshTitle && freshTitle !== videoTitle.textContent) {
              videoTitle.textContent = freshTitle;
              videoTitle.title = freshTitle;
            }
          }
        }, 800);
      }
    } else {
      currentVideoId = null;
      topBar.classList.add('hidden');
      notVideo.classList.remove('hidden');
      resultSection.classList.add('hidden');
      errorSection.classList.add('hidden');
    }
  } catch (err) {
    console.error(err);
  }
}

async function getVideoTitle(tab) {
  // 方案 1：从 tab.title 获取（最可靠，不需要注入脚本）
  const tabTitle = (tab.title || '').replace(/\s*-\s*YouTube\s*$/, '').trim();

  // 方案 2：从页面 DOM 获取（更精确，但需要 scripting 权限）
  try {
    const results = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: () => {
        const el = document.querySelector('h1.ytd-watch-metadata yt-formatted-string');
        return el?.textContent?.trim() || '';
      },
    });
    const domTitle = results?.[0]?.result || '';
    if (domTitle) return domTitle;
  } catch {}

  return tabTitle;
}

// ── 恢复任务状态 ──
async function restoreTaskState() {
  const data = await chrome.storage.local.get(['yt2text_task']);
  const saved = data.yt2text_task;
  if (saved && saved.videoId === currentVideoId && saved.taskId) {
    taskId = saved.taskId;
    try {
      const res = await fetch(`${API_BASE}/api/tasks/${taskId}`);
      const task = await res.json();
      if (task && !task.error && task.status) {
        applyStatus(task.status);
        if (task.status === 'done') {
          if (task.content) showResult(task.content);
          updateFormattingStatus(task.formatting, task.formatting_progress, task.elapsed, task.timing);
          // 格式化还在进行中 → 继续轮询
          if (task.formatting === 'in_progress' || task.formatting === 'pending') {
            startPolling();
          }
        } else if (task.status === 'failed') {
          showError(task.error || '失败');
        } else {
          startPolling();
        }
        return;
      }
    } catch {}
  }
  resetUI();
}

// ── 获取 YouTube cookies ──
async function getYouTubeCookies() {
  try {
    const cookies = await chrome.cookies.getAll({ domain: ".youtube.com" });
    return cookies.map(c => ({
      domain: c.domain,
      name: c.name,
      value: c.value,
      path: c.path,
      secure: c.secure,
      httpOnly: c.httpOnly,
      expirationDate: c.expirationDate || 0,
    }));
  } catch (err) {
    console.warn('获取 cookies 失败:', err);
    return [];
  }
}

// ── 操作按钮 ──
async function onAction() {
  // 如果是失败状态，重试
  errorSection.classList.add('hidden');
  resultSection.classList.add('hidden');

  btnAction.disabled = true;
  applyStatus('queued');

  try {
    const ok = await checkServer();
    if (!ok) { showError('后端未启动'); return; }

    const cookies = await getYouTubeCookies();

    const res = await fetch(`${API_BASE}/api/process`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        url: currentUrl,
        title: videoTitle.textContent,
        cookies,
      }),
    });
    const data = await res.json();
    taskId = data.task_id;
    await chrome.storage.local.set({ yt2text_task: { videoId: currentVideoId, taskId } });
    startPolling();
  } catch (err) {
    showError('提交失败');
  }
}

async function checkServer() {
  try {
    const res = await fetch(`${API_BASE}/api/health`, { signal: AbortSignal.timeout(3000) });
    return res.ok;
  } catch { return false; }
}

// ── 轮询 ──
function startPolling() {
  if (pollingTimer) return;
  pollTask(); // 立即执行一次，不等第一个 interval
  pollingTimer = setInterval(pollTask, POLL_INTERVAL);
}
function stopPolling() {
  if (pollingTimer) { clearInterval(pollingTimer); pollingTimer = null; }
}

async function pollTask() {
  if (!taskId) { stopPolling(); return; }
  try {
    const res = await fetch(`${API_BASE}/api/tasks/${taskId}`);
    const task = await res.json();

    // 服务器重启后任务丢失
    if (task.error === 'task not found') {
      stopPolling();
      showError('服务器已重启，任务丢失，请重新转录');
      return;
    }

    applyStatus(task.status);

    if (task.status === 'done') {
      if (task.content) showResult(task.content);
      updateFormattingStatus(task.formatting, task.formatting_progress, task.elapsed, task.timing);

      // 格式化完成或失败 → 停止轮询
      if (task.formatting === 'done' || task.formatting === 'failed' || !task.formatting) {
        stopPolling();
      }
    } else if (task.status === 'transcribing') {
      // 转录过程中 → 实时显示已转录的文字 + 格式化进度
      if (task.content) showResult(task.content);
      updateFormattingStatus(task.formatting, task.formatting_progress, task.elapsed);
    } else if (task.status === 'failed') {
      stopPolling();
      showError(task.error || '失败');
    }
  } catch (err) { console.error(err); }
}

// ── 状态映射 ──
function applyStatus(status) {
  if (status === 'done') {
    btnAction.classList.add('hidden');
    btnCopy.classList.remove('hidden');
  } else if (status === 'failed') {
    btnAction.classList.remove('hidden');
    btnAction.textContent = '重试';
    btnAction.className = 'btn-action';
    btnAction.disabled = false;
    btnCopy.classList.add('hidden');
  } else {
    btnAction.classList.add('hidden');
    btnCopy.classList.add('hidden');

    formattingStatus.classList.remove('hidden');
    formattingStatus.className = 'formatting-status';
    if (status === 'queued') {
      formattingStatus.textContent = '排队中...';
    } else if (status === 'downloading') {
      formattingStatus.textContent = '下载音频中...';
    }
  }
}

// ── 进度状态（统一显示转录 + AI 整理进度 + 耗时） ──
function formatElapsed(seconds) {
  if (!seconds && seconds !== 0) return '';
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}m${s}s`;
}

function updateFormattingStatus(formatting, progress, elapsed, timing) {
  if (!formatting) {
    formattingStatus.classList.add('hidden');
    return;
  }
  formattingStatus.classList.remove('hidden');
  const elapsedStr = elapsed ? ` ${formatElapsed(elapsed)}` : '';

  if (formatting === 'pending') {
    formattingStatus.textContent = `等待 AI 整理...${elapsedStr}`;
    formattingStatus.className = 'formatting-status';
  } else if (formatting === 'in_progress') {
    const progressStr = progress ? ` (${progress})` : '';
    formattingStatus.textContent = `转录并 AI 整理中${progressStr}...${elapsedStr}`;
    formattingStatus.className = 'formatting-status';
  } else if (formatting === 'done') {
    let label = '✅ 完成';
    if (timing) {
      const parts = [];
      if (timing.download) parts.push(`下载${formatElapsed(timing.download)}`);
      if (timing.whisper) parts.push(`转录${formatElapsed(timing.whisper)}`);
      if (timing.ai_format) parts.push(`AI${formatElapsed(timing.ai_format)}`);
      if (timing.structure) parts.push(`结构${formatElapsed(timing.structure)}`);
      if (timing.total) parts.push(`共${formatElapsed(timing.total)}`);
      if (parts.length) label += ` (${parts.join(' · ')})`;
    }
    formattingStatus.textContent = label;
    formattingStatus.className = 'formatting-status done';
  } else if (formatting === 'failed') {
    formattingStatus.textContent = '⚠️ AI 整理失败';
    formattingStatus.className = 'formatting-status failed';
  }
}

// ── 显示结果 ──
function showResult(md) {
  // 去掉内容开头的 # 标题行（顶栏已显示标题，避免重复）
  const cleaned = md.replace(/^#\s+.+\n+/, '');
  resultSection.classList.remove('hidden');
  errorSection.classList.add('hidden');
  resultContent.innerHTML = renderMarkdown(cleaned);
}

function showError(msg) {
  errorSection.classList.remove('hidden');
  errorMessage.textContent = '❌ ' + msg;
  btnAction.textContent = '重试';
  btnAction.className = 'btn-action';
  btnAction.disabled = false;
}

function resetUI() {
  resultSection.classList.add('hidden');
  errorSection.classList.add('hidden');
  btnCopy.classList.add('hidden');
  formattingStatus.classList.add('hidden');
  btnAction.textContent = '转录';
  btnAction.className = 'btn-action';
  btnAction.disabled = false;
  stopPolling();
}

// ── 复制 ──
async function onCopy() {
  const data = await chrome.storage.local.get(['yt2text_task']);
  const saved = data.yt2text_task;
  if (saved?.taskId) {
    try {
      const res = await fetch(`${API_BASE}/api/tasks/${saved.taskId}`);
      const task = await res.json();
      if (task.content) {
        await navigator.clipboard.writeText(task.content);
        btnCopy.textContent = '✅ 已复制';
        setTimeout(() => (btnCopy.textContent = '📋 复制'), 1500);
        return;
      }
    } catch {}
  }
  await navigator.clipboard.writeText(resultContent.innerText);
  btnCopy.textContent = '✅ 已复制';
  setTimeout(() => (btnCopy.textContent = '📋 复制'), 1500);
}

// ── Markdown 渲染 ──
function renderMarkdown(md) {
  let html = escapeHtml(md);
  html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
  html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
  html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>');
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
  html = html.replace(/^&gt; (.+)$/gm, '<blockquote>$1</blockquote>');
  html = html.replace(/\n\n+/g, '</p><p>');
  html = '<p>' + html + '</p>';
  html = html.replace(/\n/g, '<br>');
  html = html.replace(/<p>\s*<\/p>/g, '');
  html = html.replace(/<p>\s*(<h[123]>)/g, '$1');
  html = html.replace(/(<\/h[123]>)\s*<\/p>/g, '$1');
  return html;
}

function escapeHtml(str) {
  const d = document.createElement('div');
  d.textContent = str;
  return d.innerHTML;
}
