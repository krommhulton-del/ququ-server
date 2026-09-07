# 鏇叉洸+濉旂綏 鍙屼汉鏍糀I 浜戠閮ㄧ讲闀滃儚
# 鐢ㄦ硶: docker build -t ququ . && docker run -d -p 8001:8001 -e DEEPSEEK_API_KEY=xxx -v ququ_data:/app/data ququ
FROM python:3.11-slim

WORKDIR /app

# 鍙杩愯 ququ_server 闇€瑕佺殑杞婚噺渚濊禆(涓嶅惈 whisper/playwright,鐪佷綋绉?
RUN pip install --no-cache-dir \
    fastapi>=0.115 \
    'uvicorn[standard]>=0.30' \
    pydantic>=2.7 \
    pydantic-settings>=2.3 \
    openai>=1.40 \
    edge-tts>=6.1 \
    python-multipart>=0.0.9

# 鍙鍒?ququ 绔欏繀闇€鐨勬枃浠?涓嶆惉 AI Orchestrator 鐨?workspace/plans)
COPY ququ_server.py .
COPY backend/__init__.py backend/
COPY backend/config.py backend/
COPY backend/expert.py backend/
COPY backend/utils.py backend/
COPY data/reference/ququ_skill.md data/reference/ququ_skill.md

# 鏁版嵁鐩綍鎸傝浇鐐?鑱婂ぉ璁板綍/閭€璇风爜钀界洏鍒拌繖閲?瀹瑰櫒閲嶅惎涓嶄涪)
VOLUME ["/app/data"]

EXPOSE 8001

# 娉? /api/stt(璇煶杞枃瀛?渚濊禆鏈湴 whisper,浜戠榛樿涓嶅惎鐢?
#     濡傞渶璇煶,鍐嶈ˉ COPY distill 骞惰 whisper + ffmpeg銆?# 鐢?$PORT:Render 浼氳嚜鍔ㄦ敞鍏ョ鍙ｅ彿(榛樿10000);鏈湴璺戝垯鍥為€€ 8001銆?CMD ["sh", "-c", "uvicorn ququ_server:app --host 0.0.0.0 --port ${PORT:-8001}"]
