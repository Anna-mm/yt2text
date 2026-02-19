FROM python:3.12-slim

# 系统依赖：ffmpeg（音频处理）、curl/unzip（安装 deno）
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# 安装 Deno（yt-dlp EJS 反爬解题器需要）
RUN curl -fsSL https://deno.land/install.sh | sh
ENV DENO_INSTALL="/root/.deno"
ENV PATH="$DENO_INSTALL/bin:$PATH"

# 安装 yt-dlp
RUN pip install --no-cache-dir yt-dlp

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py downloader.py transcriber.py scraper.py ./

EXPOSE 8765

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8765"]
