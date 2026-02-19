# server.py
# FastAPI 后端服务 — 为 Chrome Extension 提供下载+转录 API
#
# 启动方式:
#   uvicorn server:app --reload --port 8765
#
# API:
#   POST /api/process         处理单个视频（下载 + 转录）
#   POST /api/batch           批量处理多个视频
#   GET  /api/tasks           查询所有任务状态
#   GET  /api/tasks/{task_id} 查询单个任务状态

import time
import uuid
import threading
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from downloader import download_audio, DownloadError
from transcriber import transcribe_and_format

app = FastAPI(title="yt2text API")

# 允许 Chrome Extension 跨域访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 任务存储 ──────────────────────────────────────────────
# 主状态流转: queued → downloading → transcribing → done / failed
# 格式化状态: None → in_progress → done / failed （后台异步，不阻塞主流程）
tasks: dict[str, dict] = {}
# 串行处理队列（避免同时跑多个 Whisper 吃光内存）
_queue_lock = threading.Lock()
_processing = False


class CookieItem(BaseModel):
    domain: str
    name: str
    value: str
    path: str = "/"
    secure: bool = False
    httpOnly: bool = False
    expirationDate: float = 0


class ProcessRequest(BaseModel):
    url: str
    title: str | None = None
    browser: str | None = "chrome"
    cookies: list[CookieItem] | None = None


class BatchRequest(BaseModel):
    videos: list[ProcessRequest]
    browser: str | None = "chrome"
    cookies: list[CookieItem] | None = None


# ── 任务执行 ──────────────────────────────────────────────

def _run_task(task_id: str, url: str, browser: str | None, cookies: list | None):
    """下载 + 转录 + 格式化融合流水线"""
    global _processing
    try:
        t_start = time.time()
        timing = {}

        # ── 下载 ──
        tasks[task_id]["status"] = "downloading"
        t0 = time.time()
        audio_path = download_audio(url, browser=browser, cookies=cookies, title=tasks[task_id].get("title"))
        tasks[task_id]["audio_path"] = str(audio_path)
        timing["download"] = round(time.time() - t0, 1)
        print(f"⏱️ 下载耗时: {timing['download']}s")

        # ── 转录 + 格式化 ──
        tasks[task_id]["status"] = "transcribing"
        tasks[task_id]["formatting"] = "in_progress"

        def on_update(content: str, formatted_count: int, total_paragraphs: int):
            tasks[task_id]["content"] = content
            if total_paragraphs > 0:
                tasks[task_id]["formatting_progress"] = f"{formatted_count}/{total_paragraphs}"
            tasks[task_id]["elapsed"] = round(time.time() - t_start, 1)

        tf_timing = {}
        transcript_path, final_content = transcribe_and_format(
            audio_path, on_update=on_update, timing=tf_timing,
        )
        timing.update(tf_timing)

        timing["total"] = round(time.time() - t_start, 1)
        tasks[task_id]["status"] = "done"
        tasks[task_id]["content"] = final_content
        tasks[task_id]["result"] = str(transcript_path)
        tasks[task_id]["formatting"] = "done"
        tasks[task_id]["formatting_progress"] = None
        tasks[task_id]["elapsed"] = timing["total"]
        tasks[task_id]["timing"] = timing

        print(f"\n⏱️ ══ 耗时明细 ══")
        print(f"   下载:        {timing.get('download', '-')}s")
        print(f"   模型加载:    {timing.get('model_load', '-')}s")
        print(f"   Whisper转录: {timing.get('whisper', '-')}s")
        print(f"   AI格式化:    {timing.get('ai_format', '-')}s")
        if timing.get('retry'):
            print(f"   失败重试:    {timing['retry']}s")
        if timing.get('structure'):
            print(f"   结构标题:    {timing['structure']}s")
        print(f"   ──────────────")
        print(f"   总计:        {timing['total']}s")

    except DownloadError as e:
        tasks[task_id]["status"] = "failed"
        tasks[task_id]["error"] = str(e)
    except Exception as e:
        tasks[task_id]["status"] = "failed"
        tasks[task_id]["error"] = str(e)
    finally:
        _processing = False
        _process_next()


def _process_next():
    """从队列中取出下一个 queued 任务执行"""
    global _processing
    with _queue_lock:
        if _processing:
            return
        # 找第一个 queued 的任务
        for task_id, task in tasks.items():
            if task["status"] == "queued":
                _processing = True
                thread = threading.Thread(
                    target=_run_task,
                    args=(task_id, task["url"], task["browser"], task.get("cookies")),
                    daemon=True,
                )
                thread.start()
                return


def _create_task(url: str, title: str | None, browser: str | None,
                  cookies: list | None = None) -> str:
    """创建一个新任务并加入队列"""
    task_id = uuid.uuid4().hex[:8]
    tasks[task_id] = {
        "id": task_id,
        "url": url,
        "title": title or url,
        "browser": browser,
        "cookies": cookies,
        "status": "queued",
        "result": None,
        "content": None,
        "formatting": None,
        "formatting_progress": None,
        "elapsed": None,
        "timing": None,
        "audio_path": None,
        "error": None,
    }
    _process_next()
    return task_id


# ── API 路由 ──────────────────────────────────────────────

@app.post("/api/process")
def process_video(req: ProcessRequest):
    """提交单个视频处理任务"""
    cookies_raw = [c.model_dump() for c in req.cookies] if req.cookies else None
    task_id = _create_task(req.url, req.title, req.browser, cookies=cookies_raw)
    return {"task_id": task_id}


@app.post("/api/batch")
def batch_process(req: BatchRequest):
    """批量提交多个视频处理任务"""
    cookies_raw = [c.model_dump() for c in req.cookies] if req.cookies else None
    task_ids = []
    for video in req.videos:
        browser = video.browser or req.browser
        task_id = _create_task(video.url, video.title, browser, cookies=cookies_raw)
        task_ids.append(task_id)
    return {"task_ids": task_ids}


_HIDDEN_FIELDS = {"cookies", "browser", "audio_path"}

def _safe_task(task: dict) -> dict:
    """返回任务信息，过滤掉敏感字段"""
    return {k: v for k, v in task.items() if k not in _HIDDEN_FIELDS}


@app.get("/api/tasks")
def get_all_tasks():
    """查询所有任务状态"""
    return {"tasks": [_safe_task(t) for t in tasks.values()]}


@app.get("/api/tasks/{task_id}")
def get_task(task_id: str):
    """查询单个任务状态"""
    if task_id not in tasks:
        return {"error": "task not found"}
    return _safe_task(tasks[task_id])


@app.get("/api/tasks/{task_id}/download/audio")
def download_audio_file(task_id: str):
    """下载音频文件"""
    if task_id not in tasks:
        return {"error": "task not found"}
    task = tasks[task_id]
    audio = task.get("audio_path")
    if not audio or not Path(audio).exists():
        return {"error": "audio file not available"}
    return FileResponse(audio, filename=Path(audio).name, media_type="audio/mpeg")


@app.get("/api/tasks/{task_id}/download/transcript")
def download_transcript(task_id: str):
    """下载转录 Markdown 文件"""
    if task_id not in tasks:
        return {"error": "task not found"}
    task = tasks[task_id]
    content = task.get("content")
    if not content:
        return {"error": "transcript not available"}
    title = task.get("title", "transcript")
    filename = title.replace("/", "_").replace("\\", "_") + ".md"
    return Response(
        content=content.encode("utf-8"),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/health")
def health():
    return {"status": "ok"}
