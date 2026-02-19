# transcriber.py
import os
import time
import concurrent.futures
from openai import OpenAI
from faster_whisper import WhisperModel
from pathlib import Path

# 可选模型（从小到大）: tiny (~75MB), base (~150MB), small (~500MB), medium (~1.5GB), large-v3 (~3GB)
# 模型越大，转录越准确，但下载和运行时间越长
MODEL_SIZE = "base"

# 通义千问 API Key（阿里云百炼，新用户每个模型送 100 万 tokens，有效期 90 天）
# 获取地址：https://bailian.console.aliyun.com/#/api-key
DASHSCOPE_API_KEY = os.environ.get("DASHSCOPE_API_KEY", "sk-a6291c230f014c7491b3a27a0f347b7f")
DASHSCOPE_MODEL = "qwen-turbo"
DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

# 每段发给 LLM 的最大字符数
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

# Whisper 模型单例缓存
_whisper_model = None

def _get_whisper_model():
    """加载并缓存 Whisper 模型，只在首次调用时加载"""
    global _whisper_model
    if _whisper_model is None:
        print(f"📦 首次加载 Whisper 模型 ({MODEL_SIZE})，请稍候...")
        _whisper_model = WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8")
        print("✅ Whisper 模型加载完成（已缓存）")
    return _whisper_model


SEGMENT_PROMPT = (
    "你是一个文本编辑助手。下面是一段语音转录的原始文本片段（由语音识别逐句生成，句子零散）。\n"
    "请将这些零散的短句整理成连贯、流畅的段落。具体要求：\n"
    "1. 将繁体中文转为简体中文\n"
    "2. 把零散的短句合并成完整的、连贯的长段落，添加适当的标点符号\n"
    "3. 按语义和话题组织段落，段落之间用空行隔开\n"
    "4. 不要添加小标题（标题由外部统一处理）\n"
    "5. 不要删除或添加原文的实际内容，只做格式整理\n"
    "6. 直接输出文本，不要用代码块包裹，不要加额外说明\n\n"
)

# AI 自动生成结构标题的 prompt（用于没有 YouTube 章节的视频）
STRUCTURE_PROMPT = (
    "你是一个文本结构化助手。下面是一个视频转录文本的各段落摘要（每段只显示前150字）。\n"
    "请分析这些段落的内容，将它们划分为 3-8 个主题板块，为每个板块起一个简洁的标题。\n\n"
    "输出格式（每行一个）：\n"
    "段落编号:标题\n\n"
    "例如：\n"
    "1:个人经历与背景\n"
    "5:团队管理心得\n"
    "12:总结与展望\n\n"
    "要求：\n"
    "1. 段落编号表示该主题从哪个段落开始（第一个板块一般从段落1开始）\n"
    "2. 标题要简短、概括（5-15个字），像 YouTube 视频的章节标题一样\n"
    "3. 只输出上述格式，不要加任何其他内容\n"
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


def _get_llm_client() -> OpenAI:
    """创建通义千问 API 客户端（阿里云百炼 DashScope）"""
    api_key = os.environ.get("DASHSCOPE_API_KEY", DASHSCOPE_API_KEY)
    if not api_key:
        raise RuntimeError(
            "未设置通义千问 API Key。请前往 https://bailian.console.aliyun.com/#/api-key 获取，"
            "然后设置环境变量 DASHSCOPE_API_KEY 或在 transcriber.py 中填写。"
        )
    return OpenAI(api_key=api_key, base_url=DASHSCOPE_BASE_URL)


def _call_llm(client: OpenAI, text: str, part_info: str = "", prompt_template: str = None) -> str:
    """调用通义千问 API 格式化一段文本，带重试"""
    system_prompt = (prompt_template or PROMPT_TEMPLATE).rstrip()
    user_content = f"原始文本：\n{text}"

    max_retries = 5
    for attempt in range(1, max_retries + 1):
        try:
            response = client.chat.completions.create(
                model=DASHSCOPE_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                temperature=0,
                timeout=90,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            if attempt < max_retries:
                # 网络错误用更长等待，其他错误短等待
                is_network = "connect" in str(e).lower() or "timeout" in str(e).lower()
                wait = attempt * 10 if is_network else attempt * 5
                print(f"   ⏳ {part_info}第 {attempt} 次请求失败（{e}），{wait}s 后重试...")
                time.sleep(wait)
            else:
                print(f"   ⚠️ {part_info}请求失败: {e}")
                raise


def _generate_section_headers(client: OpenAI, paragraphs: list[dict]) -> dict[int, str]:
    """为没有 YouTube 章节的视频，用 AI 分析段落摘要生成结构化标题

    返回: {段落索引: "标题", ...}（索引从 0 开始）
    """
    if len(paragraphs) < 3:
        return {}

    # 构建段落摘要：取每段前 150 字
    summaries = []
    for i, p in enumerate(paragraphs):
        text = (p["formatted"] or p["raw"]).strip()
        preview = text[:150].replace("\n", " ").strip()
        summaries.append(f"【段落{i+1}】{preview}")

    outline = "\n".join(summaries)

    result = _call_llm(client, outline, part_info="结构化 ", prompt_template=STRUCTURE_PROMPT)

    # 解析 AI 返回的 "段落编号:标题" 格式
    headers = {}
    for line in result.strip().split("\n"):
        line = line.strip()
        if not line or ":" not in line and "：" not in line:
            continue
        # 支持半角和全角冒号
        sep = "：" if "：" in line else ":"
        parts = line.split(sep, 1)
        try:
            num_str = parts[0].replace("段落", "").strip()
            idx = int(num_str) - 1  # 转为 0-indexed
            title = parts[1].strip()
            if 0 <= idx < len(paragraphs) and title:
                headers[idx] = title
        except (ValueError, IndexError):
            continue

    return headers


def _format_with_llm(raw_text: str) -> str:
    """使用通义千问按逻辑内容对文本进行分段，超长文本自动分段处理"""
    client = _get_llm_client()

    chunks = _split_text(raw_text)

    if len(chunks) == 1:
        print("✨ 正在用通义千问 AI 按逻辑内容分段...")
        return _call_llm(client, chunks[0])
    else:
        print(f"✨ 文本较长（{len(raw_text)} 字），分 {len(chunks)} 段发送给通义千问 AI...")
        results = []
        for i, chunk in enumerate(chunks, 1):
            print(f"   📎 处理第 {i}/{len(chunks)} 段（{len(chunk)} 字）...")
            result = _call_llm(client, chunk, part_info=f"第{i}段 ")
            results.append(result)
        return "\n\n".join(results)


def transcribe_audio(audio_path: Path, on_progress=None) -> str:
    """第一阶段：用 Whisper 将音频转为原始文本，支持逐段回调"""
    model = _get_whisper_model()
    print("✅ 模型就绪，开始转录...")

    segments, info = model.transcribe(str(audio_path), language="zh")

    # 语音中超过 GAP_THRESHOLD 秒的停顿会自动分段（插入空行）
    GAP_THRESHOLD = 1.0
    raw_parts = []
    prev_end = 0.0
    for segment in segments:
        text = segment.text.strip()
        if text:
            gap = segment.start - prev_end
            if raw_parts and gap >= GAP_THRESHOLD:
                raw_parts.append("\n\n")
                print(f"  --- 停顿 {gap:.1f}s，分段 ---")
            print(f"  [{segment.start:.1f}s - {segment.end:.1f}s] {text}")
            raw_parts.append(text)
            prev_end = segment.end
            if on_progress:
                on_progress("".join(raw_parts))

    raw_text = "".join(raw_parts)
    print(f"\n📝 转录完成，共 {len(raw_text)} 字")
    return raw_text


def format_transcript(raw_text: str, audio_path: Path, output_dir: str = "output") -> Path:
    """第二阶段：用通义千问 AI 对原始文本进行逻辑分段并生成 Markdown"""
    transcript_path = Path(output_dir) / f"{audio_path.stem}.md"

    formatted_text = _format_with_llm(raw_text)

    title = audio_path.stem.replace("_", " ")

    with open(transcript_path, "w", encoding="utf-8") as f:
        f.write(f"# {title}\n\n{formatted_text}\n")

    return transcript_path


def transcribe_and_format(audio_path: Path, on_update=None, output_dir: str = "output", timing: dict | None = None):
    """
    融合流水线：Whisper 转录与通义千问格式化并行进行。
    每检测到语音停顿就切出一段，立刻丢给通义千问后台格式化，Whisper 继续转录下一段。
    格式化完成后，AI 自动分析全文内容生成结构化标题。

    on_update(content, formatted_count, total_paragraphs)
        - content: 当前应显示的完整 Markdown（已整理 + 未整理 + 正在转录）
        - formatted_count: 已完成 AI 整理的段落数
        - total_paragraphs: 已切出的段落总数

    timing: 可选字典，函数会将各阶段耗时写入其中
    """
    if timing is None:
        timing = {}
    Path(output_dir).mkdir(exist_ok=True)
    title = audio_path.stem.replace("_", " ")

    client = _get_llm_client()

    t0 = time.time()
    model = _get_whisper_model()
    timing["model_load"] = round(time.time() - t0, 1)
    print(f"⏱️ 模型加载耗时: {timing['model_load']}s")
    print("✅ 模型就绪，开始转录+格式化流水线...")

    t_whisper_start = time.time()
    segments, _info = model.transcribe(
        str(audio_path), language="zh",
        beam_size=1,        # 贪心解码，大幅提速，中文语音质量损失极小
        vad_filter=True,    # 跳过静音/非语音段，减少无效转录
    )

    GAP_THRESHOLD = 1.0
    MAX_PARAGRAPH_CHARS = 500   # 通义千问速率限制宽松（3万RPM），可细粒度分段提升响应速度

    # ── 段落状态 ──
    paragraphs = []         # [{"raw": str, "formatted": str|None}, ...]
    current_parts = []      # 当前正在转录的段落片段
    prev_end = 0.0
    formatted_count = 0

    # ── 章节标题映射（由 AI 在格式化完成后自动生成）──
    chapter_headers = {}    # {paragraph_index: "标题"}

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=5)
    pending_futures = {}    # {paragraph_index: Future}

    def _build_content():
        """组装当前应显示的完整内容（含章节标题）"""
        parts = []
        for i, p in enumerate(paragraphs):
            if i in chapter_headers:
                parts.append(f"## {chapter_headers[i]}")
            parts.append(p["formatted"] if p["formatted"] else p["raw"])
        if current_parts:
            parts.append("".join(current_parts))
        return f"# {title}\n\n" + "\n\n".join(parts)

    def _check_futures():
        """检查已完成的通义千问格式化任务"""
        nonlocal formatted_count
        changed = False
        for idx in list(pending_futures.keys()):
            future = pending_futures[idx]
            if future.done():
                try:
                    paragraphs[idx]["formatted"] = future.result()
                except Exception as e:
                    print(f"  ⚠️ 段落 {idx+1} 格式化失败: {e}")
                formatted_count += 1
                changed = True
                del pending_futures[idx]
        return changed

    def _submit_paragraph():
        """将当前段落提交给通义千问格式化"""
        if not current_parts:
            return
        raw = "".join(current_parts)
        idx = len(paragraphs)
        paragraphs.append({"raw": raw, "formatted": None})
        current_parts.clear()
        future = executor.submit(
            _call_llm, client, raw,
            part_info=f"段落{idx+1} ",
            prompt_template=SEGMENT_PROMPT,
        )
        pending_futures[idx] = future
        print(f"  📤 段落 {idx+1} 已提交通义千问（{len(raw)} 字）")

    def _notify():
        if on_update:
            on_update(_build_content(), formatted_count, len(paragraphs))

    # ── 主循环：Whisper 转录 ──
    for segment in segments:
        text = segment.text.strip()
        if not text:
            continue

        gap = segment.start - prev_end
        current_len = sum(len(p) for p in current_parts)

        # 检测到停顿 或 段落过长 → 切段 → 提交格式化
        if current_parts and (gap >= GAP_THRESHOLD or current_len >= MAX_PARAGRAPH_CHARS):
            reason = f"停顿 {gap:.1f}s" if gap >= GAP_THRESHOLD else f"已达 {current_len} 字"
            print(f"  --- {reason}，分段 ---")
            _submit_paragraph()

        # 顺便检查已完成的格式化
        _check_futures()

        print(f"  [{segment.start:.1f}s - {segment.end:.1f}s] {text}")
        current_parts.append(text)
        prev_end = segment.end

        _notify()

    # ── 提交最后一段 ──
    _submit_paragraph()
    _check_futures()
    _notify()

    timing["whisper"] = round(time.time() - t_whisper_start, 1)
    print(f"⏱️ Whisper 转录耗时: {timing['whisper']}s（{len(paragraphs)} 个段落）")

    # ── 等待所有格式化完成 ──
    t_format_wait = time.time()
    print("  ⏳ 等待剩余通义千问格式化完成...")
    for idx in sorted(pending_futures.keys()):
        future = pending_futures[idx]
        try:
            paragraphs[idx]["formatted"] = future.result()
        except Exception as e:
            print(f"  ⚠️ 段落 {idx+1} 格式化失败: {e}")
        formatted_count += 1
        _notify()

    pending_futures.clear()
    timing["ai_format"] = round(time.time() - t_format_wait, 1)
    print(f"⏱️ AI 格式化等待耗时: {timing['ai_format']}s")

    # ── 重试所有格式化失败的段落 ──
    t_retry = time.time()
    failed_indices = [i for i, p in enumerate(paragraphs) if p["formatted"] is None]
    if failed_indices:
        print(f"\n🔄 {len(failed_indices)} 个段落格式化失败，等待 15s 后集中重试...")
        time.sleep(15)
        for idx in failed_indices:
            try:
                print(f"  🔄 重试段落 {idx+1}（{len(paragraphs[idx]['raw'])} 字）...")
                result = _call_llm(client, paragraphs[idx]["raw"],
                                   f"段落{idx+1} ", SEGMENT_PROMPT)
                paragraphs[idx]["formatted"] = result
                print(f"  ✅ 段落 {idx+1} 重试成功")
                _notify()
            except Exception as e:
                print(f"  ❌ 段落 {idx+1} 重试仍然失败: {e}")
        # 二次重试仍失败的段落
        still_failed = [i for i in failed_indices if paragraphs[i]["formatted"] is None]
        if still_failed:
            print(f"  ⚠️ 仍有 {len(still_failed)} 个段落未能格式化，将使用原始文本")

    timing["retry"] = round(time.time() - t_retry, 1)
    if failed_indices:
        print(f"⏱️ 重试耗时: {timing['retry']}s")

    executor.shutdown(wait=False)

    # ── 用 AI 自动分析内容，生成结构化标题 ──
    t_structure = time.time()
    if len(paragraphs) >= 3:
        print("  📑 正在用 AI 分析内容，生成结构标题...")
        try:
            ai_headers = _generate_section_headers(client, paragraphs)
            if ai_headers:
                chapter_headers.update(ai_headers)
                print(f"  ✅ AI 生成了 {len(ai_headers)} 个结构标题:")
                for idx in sorted(ai_headers):
                    print(f"     段落 {idx+1}: {ai_headers[idx]}")
                _notify()
            else:
                print("  ℹ️ AI 未能生成有效的结构标题")
        except Exception as e:
            print(f"  ⚠️ 结构标题生成失败（不影响内容）: {e}")

    timing["structure"] = round(time.time() - t_structure, 1)
    if timing["structure"] > 0.1:
        print(f"⏱️ 结构标题生成耗时: {timing['structure']}s")

    # ── 保存最终文件 ──
    final_content = _build_content() + "\n"
    transcript_path = Path(output_dir) / f"{audio_path.stem}.md"
    with open(transcript_path, "w", encoding="utf-8") as f:
        f.write(final_content)

    print(f"✅ 转录+格式化全部完成: {transcript_path}")
    return transcript_path, final_content


def transcribe(audio_path: Path, output_dir: str = "output"):
    """完整流程（CLI 兼容）：转录 + AI 格式化"""
    raw_text = transcribe_audio(audio_path)
    return format_transcript(raw_text, audio_path, output_dir)
