# YoubeScript

YouTube 视频一键转文字的 Chrome 扩展。在 YouTube 视频页面点击扩展图标，自动下载音频、Whisper 转录、通义千问 AI 整理，生成结构化的可读文本，显示在右侧面板中。

## 功能

- 一键将 YouTube 视频转为结构化文字
- 支持会员专属视频（自动传递浏览器登录态）
- AI 自动整理段落、添加标点、生成章节标题
- 转录结果本地缓存，同一视频无需重复处理
- 支持将结果下载为 Markdown 文件

## 架构

```
Chrome Extension (侧面板)
    │
    │  POST /api/process {url, title, cookies}
    ▼
FastAPI 后端 (Railway 云端 / 本地)
    │
    ├── yt-dlp 下载音频 (opus 格式)
    ├── Faster Whisper 语音转文字
    └── 通义千问 AI 整理格式 + 生成章节标题
```

## 项目结构

```
yt2text/
├── server.py          # FastAPI 后端服务，任务队列调度
├── downloader.py      # yt-dlp 音频下载，cookie 管理
├── transcriber.py     # Whisper 转录 + 通义千问 AI 格式化
├── scraper.py         # 辅助工具
├── Dockerfile         # 容器化部署配置
├── requirements.txt   # Python 依赖
└── extension/         # Chrome 扩展
    ├── manifest.json  # 扩展配置 (Manifest V3)
    ├── background.js  # 扩展图标点击行为
    ├── sidepanel.html # 侧面板 UI
    ├── sidepanel.js   # 核心逻辑：视频检测、API 调用、缓存
    └── sidepanel.css  # 样式
```

## 分发说明

本扩展**不发布到 Chrome Web Store**，仅在朋友之间以开发者模式加载使用。原因如下：

- **YouTube 服务条款限制**：扩展通过 yt-dlp 下载视频音频进行转录，这违反了 YouTube 的服务条款（禁止在未经授权的情况下下载内容），不符合 Chrome Web Store 的上架政策。
- **API Key 安全**：后端硬编码了通义千问 API Key，公开发布会导致密钥泄露和滥用。
- **个人工具定位**：本项目为个人学习和效率工具，不以商业化为目标。

如需分享给朋友使用，可以将 `extension/` 目录打包为 zip 发送，对方在 Chrome 中以开发者模式加载即可，后端已部署在云端，无需额外配置。

## 本地运行

### 1. 后端

需要 Python 3.12+、ffmpeg。

```bash
# 安装依赖
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 设置通义千问 API Key（可选，代码中有默认值）
export DASHSCOPE_API_KEY="sk-xxx"

# 启动服务
uvicorn server:app --port 8765
```

### 2. Chrome 扩展

1. 打开 `chrome://extensions/`，开启「开发者模式」
2. 点击「加载已解压的扩展程序」，选择 `extension/` 目录
3. 打开任意 YouTube 视频页面，点击扩展图标打开侧面板
4. 点击「转录」按钮

> 如果使用本地后端，需要将 `extension/sidepanel.js` 中的 `API_BASE` 改为 `http://localhost:8765`。

## 云端部署 (Railway)

项目已配置 Dockerfile，可直接部署到 Railway：

1. 将代码推送到 GitHub
2. 在 [Railway](https://railway.app) 创建项目，连接 GitHub 仓库
3. 添加环境变量 `DASHSCOPE_API_KEY`
4. 生成公网域名，更新 `extension/sidepanel.js` 和 `extension/manifest.json` 中的地址

**费用说明**：Railway 新用户有 $5 免费额度。当前已于 2025-02-19 升级为付费计划（$5/月），计划在到期前取消，届时回退到免费额度继续使用。

## 技术栈

| 组件 | 技术 |
|------|------|
| 后端框架 | FastAPI + Uvicorn |
| 音频下载 | yt-dlp + Deno (JS 反爬) |
| 语音识别 | Faster Whisper (base 模型) |
| AI 整理 | 通义千问 qwen-turbo (阿里云 DashScope) |
| 前端 | Chrome Extension Manifest V3, Side Panel API |
| 部署 | Docker, Railway |

## API

### POST /api/process

提交视频处理任务。

```json
{
  "url": "https://www.youtube.com/watch?v=xxx",
  "title": "视频标题",
  "cookies": [...]
}
```

返回：`{"task_id": "abc123"}`

### GET /api/tasks/{task_id}

查询任务状态。返回 `status`、`content`、`formatting`、`timing` 等字段。

### GET /api/health

健康检查。返回 `{"status": "ok"}`。
