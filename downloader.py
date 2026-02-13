# downloader.py
import re
import subprocess
from pathlib import Path


class DownloadError(Exception):
    """下载失败时抛出的异常"""
    pass


def _sanitize_filename(name: str) -> str:
    """将视频标题转为安全的文件名"""
    # 移除文件系统不允许的字符
    name = re.sub(r'[\\/*?:"<>|]', '', name)
    # 将空白字符替换为下划线
    name = re.sub(r'\s+', '_', name.strip())
    # 限制长度
    return name[:200] if name else "untitled"


def _get_video_title(url: str, browser: str = None) -> str:
    """获取视频标题"""
    command = ["yt-dlp", "--print", "title", url]
    if browser:
        command += ["--cookies-from-browser", browser]

    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    return ""


def _parse_download_error(stderr: str) -> str:
    """解析下载错误并返回友好提示信息"""
    if "members" in stderr.lower() or "member" in stderr.lower():
        return "该视频为频道会员专属内容，无法下载。请使用 --browser 参数传递登录信息。"
    elif "private" in stderr.lower():
        return "该视频为私密视频，无法下载。"
    elif "unavailable" in stderr.lower() or "not available" in stderr.lower():
        return "该视频不可用（可能已被删除或存在地区限制）。"
    else:
        return f"下载失败：{stderr.strip()}"


def download_audio(url: str, output_dir: str = "output", browser: str = None) -> Path:
    Path(output_dir).mkdir(exist_ok=True)

    # 获取视频标题作为文件名
    print("📋 获取视频标题...")
    title = _get_video_title(url, browser)
    if not title:
        print("⚠️  无法获取视频标题，使用默认文件名")
        safe_title = "audio"
    else:
        safe_title = _sanitize_filename(title)
        print(f"   标题: {title}")

    audio_path = Path(output_dir) / f"{safe_title}.mp3"

    # 如果音频文件已存在，跳过下载
    if audio_path.exists() and audio_path.stat().st_size > 0:
        print(f"⏩ 音频文件已存在，跳过下载: {audio_path}")
        return audio_path

    output_template = f"{output_dir}/{safe_title}.%(ext)s"

    command = [
        "yt-dlp",
        "-x",
        "--audio-format", "mp3",
        url,
        "-o", output_template
    ]

    if browser:
        command += ["--cookies-from-browser", browser]

    result = subprocess.run(command, capture_output=True, text=True)

    if result.returncode != 0:
        msg = _parse_download_error(result.stderr)
        raise DownloadError(msg)

    return audio_path
