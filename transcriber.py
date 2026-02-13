# transcriber.py
import os
import google.generativeai as genai
from faster_whisper import WhisperModel
from pathlib import Path

# 可选模型（从小到大）: tiny (~75MB), base (~150MB), small (~500MB), medium (~1.5GB), large-v3 (~3GB)
# 模型越大，转录越准确，但下载和运行时间越长
MODEL_SIZE = "base"

# Gemini API Key
GEMINI_API_KEY = "AIzaSyCnZ8s1hnroyOEsQ8oUjb7sOt0OmCoPOlU"


# 每段发给 Gemini 的最大字符数（约 8000 字，留足余量避免超时）
CHUNK_SIZE = 8000

PROMPT_TEMPLATE = (
    "你是一个文本编辑助手。下面是一段语音转录的原始文本（没有分段）。"
    "请你先判断这段内容是「多人对话」还是「单人独白」，然后按对应格式整理为 Markdown。\n\n"
    "**如果是多人对话（访谈、播客、聊天等）：**\n"
    "1. 识别不同的说话人，用 **说话人A：**、**说话人B：** 等标记（如果能从内容推断出名字则用名字）\n"
    "2. 每次说话人切换时换行，如实记录每个人说的话\n"
    "3. 不需要添加小标题，不需要合并段落，忠实还原对话过程\n\n"
    "**如果是单人独白（演讲、vlog、讲解等）：**\n"
    "1. 按照话题和逻辑转折来分段，不要机械地按固定字数分\n"
    "2. 用 ## 为每个主要话题段落添加小标题（小标题由你根据内容总结）\n"
    "3. 段落之间用空行隔开\n\n"
    "**通用要求：**\n"
    "1. 将所有繁体中文转换为简体中文\n"
    "2. 除了繁简转换外，不要修改、删除或添加任何原文内容\n"
    "3. 直接输出 Markdown 内容，不要用代码块包裹，不要加额外说明\n\n"
)


def _split_text(text: str, chunk_size: int = CHUNK_SIZE) -> list[str]:
    """将长文本按句号/问号/感叹号等断句点切分为多段，每段不超过 chunk_size 字符"""
    if len(text) <= chunk_size:
        return [text]

    chunks = []
    start = 0

    while start < len(text):
        # 如果剩余文本不超过限制，直接收入
        if start + chunk_size >= len(text):
            chunks.append(text[start:])
            break

        # 在 chunk_size 范围内从后往前找断句点
        end = start + chunk_size
        split_pos = -1
        for sep in ["。", "？", "！", ".", "?", "!", "；", "\n"]:
            pos = text.rfind(sep, start, end)
            if pos > split_pos:
                split_pos = pos

        if split_pos > start:
            # 包含断句符号本身
            chunks.append(text[start:split_pos + 1])
            start = split_pos + 1
        else:
            # 找不到断句点，硬切
            chunks.append(text[start:end])
            start = end

    return chunks


def _call_gemini(api_key: str, text: str, part_info: str = "") -> str:
    """调用 Gemini API 格式化一段文本，带重试"""
    import time

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.5-flash")

    prompt = PROMPT_TEMPLATE + f"原始文本：\n{text}"

    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            response = model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(temperature=0),
                request_options={"timeout": 600},
            )
            return response.text.strip()
        except Exception as e:
            if attempt < max_retries:
                wait = attempt * 10
                print(f"   ⏳ {part_info}第 {attempt} 次请求失败（{e}），{wait}s 后重试...")
                time.sleep(wait)
            else:
                raise


def _format_with_llm(raw_text: str) -> str:
    """使用 Gemini 按逻辑内容对文本进行分段，超长文本自动分段处理"""
    api_key = os.environ.get("GEMINI_API_KEY", GEMINI_API_KEY)

    chunks = _split_text(raw_text)

    if len(chunks) == 1:
        print("✨ 正在用 Gemini AI 按逻辑内容分段...")
        return _call_gemini(api_key, chunks[0])
    else:
        print(f"✨ 文本较长（{len(raw_text)} 字），分 {len(chunks)} 段发送给 Gemini AI...")
        results = []
        for i, chunk in enumerate(chunks, 1):
            print(f"   📎 处理第 {i}/{len(chunks)} 段（{len(chunk)} 字）...")
            result = _call_gemini(api_key, chunk, part_info=f"第{i}段 ")
            results.append(result)
        return "\n\n".join(results)


def transcribe(audio_path: Path, output_dir: str = "output"):
    print(f"📦 加载 Whisper 模型 ({MODEL_SIZE})，首次运行需下载模型，请耐心等待...")
    model = WhisperModel(
        MODEL_SIZE,
        device="cpu",
        compute_type="int8"
    )
    print("✅ 模型加载完成，开始转录...")

    segments, info = model.transcribe(str(audio_path), language="zh")

    # 使用与音频相同的文件名（去掉 .mp3 后缀，加 .md）
    transcript_path = Path(output_dir) / f"{audio_path.stem}.md"

    # 先拼接为完整文本
    raw_parts = []
    for segment in segments:
        text = segment.text.strip()
        if text:
            print(f"  [{segment.start:.1f}s - {segment.end:.1f}s] {text}")
            raw_parts.append(text)

    raw_text = "".join(raw_parts)
    print(f"\n📝 转录完成，共 {len(raw_text)} 字")

    # 用 Gemini 按逻辑内容分段并生成 Markdown
    formatted_text = _format_with_llm(raw_text)

    # 用文件名（即视频标题）作为一级标题
    title = audio_path.stem.replace("_", " ")

    with open(transcript_path, "w", encoding="utf-8") as f:
        f.write(f"# {title}\n\n{formatted_text}\n")

    return transcript_path
