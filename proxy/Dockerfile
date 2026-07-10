# unillm proxy image: OpenAI-compatible Vertex AI Gemini proxy (vendored under
# proxy/unillm). Serves on :8081. The Vertex service-account credential
# is mounted at runtime (GOOGLE_APPLICATION_CREDENTIALS) — never baked into the image.
FROM python:3.12-slim-bookworm

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements_unillm.txt ./
RUN pip install --no-cache-dir -r requirements_unillm.txt

COPY unillm ./unillm
COPY unillm_config.yaml ./unillm_config.yaml

EXPOSE 8081
ENTRYPOINT ["python", "-m", "unillm.proxy.proxy_cli", \
            "--config", "/app/unillm_config.yaml", "--host", "0.0.0.0", "--port", "8081"]
