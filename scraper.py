# scraper.py
import subprocess


def extract_video_urls(page_url: str, browser: str = None, limit: int = None) -> list[str]:
    """从 YouTube 频道/播放列表页面提取所有视频链接

    使用 yt-dlp 的 --flat-playlist 模式快速提取，不下载视频本身。
    """
    command = [
        "yt-dlp",
        "--flat-playlist",
        "--print", "url",
        page_url,
    ]

    if browser:
        command += ["--cookies-from-browser", browser]

    if limit:
        command += ["--playlist-end", str(limit)]

    print("🔍 正在从页面提取视频链接（可能需要一些时间）...")
    result = subprocess.run(command, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"❌ 提取视频链接失败：\n{result.stderr}")
        return []

    urls = [line.strip() for line in result.stdout.strip().split("\n") if line.strip()]
    print(f"📋 共发现 {len(urls)} 个视频")
    return urls
