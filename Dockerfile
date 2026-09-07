# 曲曲+塔罗 双人格AI 云端部署镜像
# 用法: docker build -t ququ . && docker run -d -p 8001:8001 -e DEEPSEEK_API_KEY=xxx -v ququ_data:/app/data ququ
FROM python:3.11-slim

WORKDIR /app

# 只装运行 ququ_server 需要的轻量依赖(不含 whisper/playwright,省体积)
RUN pip install --no-cache-dir \
    fastapi>=0.115 \
    'uvicorn[standard]>=0.30' \
    pydantic>=2.7 \
    pydantic-settings>=2.3 \
    openai>=1.40 \
    edge-tts>=6.1

# 只复制 ququ 站必需的文件(不搬 AI Orchestrator 的 workspace/plans)
COPY ququ_server.py .
COPY backend/__init__.py backend/
COPY backend/config.py backend/
COPY backend/expert.py backend/
COPY backend/utils.py backend/
COPY data/reference/ququ_skill.md data/reference/ququ_skill.md

# 数据目录挂载点(聊天记录/邀请码落盘到这里,容器重启不丢)
VOLUME ["/app/data"]

EXPOSE 8001

# 注: /api/stt(语音转文字)依赖本地 whisper,云端默认不启用;
#     如需语音,再补 COPY distill 并装 whisper + ffmpeg。
# 用 $PORT:Render 会自动注入端口号(默认10000);本地跑则回退 8001。
CMD ["sh", "-c", "uvicorn ququ_server:app --host 0.0.0.0 --port ${PORT:-8001}"]
