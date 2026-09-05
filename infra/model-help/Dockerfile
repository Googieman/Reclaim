FROM ghcr.io/ggml-org/llama.cpp@sha256:51570a4f93c5ce81ac6f2b1ea16a58771cfded2adb34241df7e75329b24fe76e

ENV MODEL_PATH=/models/deepseek-r1-distill-qwen-1.5b-q4_0.gguf \
    MODEL_DIR=/models \
    MODEL_MANIFEST_PATH=/etc/reclaim/help-model-manifest.json \
    PORT=8080

COPY models/help-deepseek/manifest.json /etc/reclaim/help-model-manifest.json
COPY infra/model-help/entrypoint.sh /usr/local/bin/reclaim-help-model
RUN mkdir -p /models \
    && chmod 0555 /usr/local/bin/reclaim-help-model \
    && chown -R 1000:1000 /models /etc/reclaim

USER 1000
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --start-period=60s --retries=12 \
  CMD ["wget", "-q", "-O", "/dev/null", "http://127.0.0.1:8080/health"]

ENTRYPOINT ["/usr/local/bin/reclaim-help-model"]
