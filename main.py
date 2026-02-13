# main.py
# 下载 YouTube 视频并转录为文本
#
# 用法:
#   单个视频:
#     python main.py "https://www.youtube.com/watch?v=xxxxx" -b chrome
#
#   批量处理（频道页面/播放列表）:
#     python main.py "https://www.youtube.com/@kedaibiao/videos" -b chrome
#     python main.py "https://www.youtube.com/@kedaibiao/videos" -b chrome -l 5
#
# 参数:
#   url              YouTube 视频链接 或 频道/播放列表页面链接
#   --browser, -b    从指定浏览器读取 cookies 以访问会员内容 (chrome/firefox/safari/edge)
#   --limit, -l      批量模式下最多处理的视频数量（默认全部）
#
# 程序会自动判断链接类型：
#   - 包含 /watch?v= 的链接 → 单视频模式
#   - 频道页面、播放列表等 → 批量模式，自动提取所有视频链接并逐一处理


import argparse
from downloader import download_audio, DownloadError
from transcriber import transcribe
from scraper import extract_video_urls


def is_single_video(url: str) -> bool:
    """判断是单个视频还是频道/播放列表页面"""
    # 含 /watch?v= 且不是播放列表的，视为单个视频
    if "/watch?v=" in url and "list=" not in url:
        return True
    return False


def process_single(url: str, browser: str = None):
    """处理单个视频：下载 + 转录"""
    print("⬇️  下载音频...")
    audio_path = download_audio(url, browser=browser)

    print("🧠 转录中...")
    transcript_path = transcribe(audio_path)

    print(f"✅ 完成: {transcript_path}")


def process_batch(page_url: str, browser: str = None, limit: int = None):
    """批量处理：提取页面所有视频链接，逐一下载并转录"""
    urls = extract_video_urls(page_url, browser=browser, limit=limit)

    if not urls:
        print("❌ 未找到任何视频链接")
        return

    total = len(urls)
    success_count = 0
    fail_count = 0
    skipped = []
    completed = []

    for i, url in enumerate(urls, 1):
        print(f"\n{'='*60}")
        print(f"📌 [{i}/{total}] {url}")
        print(f"{'='*60}")

        try:
            print("⬇️  下载音频...")
            audio_path = download_audio(url, browser=browser)

            print("🧠 转录中...")
            transcript_path = transcribe(audio_path)

            print(f"✅ 完成: {transcript_path}")
            completed.append(str(transcript_path))
            success_count += 1

        except DownloadError as e:
            print(f"⚠️  下载失败，跳过: {e}")
            skipped.append((url, str(e)))
            fail_count += 1

        except Exception as e:
            print(f"⚠️  处理出错，跳过: {e}")
            skipped.append((url, str(e)))
            fail_count += 1

    # 打印汇总报告
    print(f"\n{'='*60}")
    print(f"🎉 批量处理完成！")
    print(f"   成功: {success_count} | 失败: {fail_count} | 总计: {total}")
    print(f"{'='*60}")

    if completed:
        print(f"\n✅ 成功转录的文件:")
        for path in completed:
            print(f"   {path}")

    if skipped:
        print(f"\n⚠️  跳过的视频:")
        for url, reason in skipped:
            print(f"   {url}")
            print(f"      原因: {reason}")


def main():
    parser = argparse.ArgumentParser(
        description="下载 YouTube 视频并转录为文本（支持单个视频或批量处理频道/播放列表）"
    )
    parser.add_argument("url", help="YouTube 视频链接 或 频道/播放列表页面链接")
    parser.add_argument(
        "--browser", "-b",
        default=None,
        help="从指定浏览器读取 cookies 以访问会员内容 (chrome/firefox/safari/edge)"
    )
    parser.add_argument(
        "--limit", "-l",
        type=int,
        default=None,
        help="批量模式下最多处理的视频数量（默认处理全部）"
    )
    args = parser.parse_args()

    if is_single_video(args.url):
        print("🎬 单视频模式")
        try:
            process_single(args.url, browser=args.browser)
        except DownloadError as e:
            print(f"❌ {e}")
    else:
        print("📂 批量模式 - 将提取页面上所有视频并逐一处理")
        if args.limit:
            print(f"   限制处理数量: {args.limit}")
        process_batch(args.url, browser=args.browser, limit=args.limit)


if __name__ == "__main__":
    main()
