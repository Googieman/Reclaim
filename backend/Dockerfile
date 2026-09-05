FROM python:3.12.8-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore \
    PYTHONPATH=/opt/reclaim/backend:/opt/reclaim

WORKDIR /opt/reclaim

# The localhost product flow needs the authoritative PostgreSQL adapter and the
# configured LiteLLM boundary. It still keeps all action execution in the local
# deterministic simulator.
RUN python -m pip install \
      aiokafka==0.12.0 \
      fastapi==0.115.6 \
      langgraph==0.2.60 \
      litellm==1.55.8 \
      minio==7.2.12 \
      PyJWT==2.10.1 \
      pydantic==2.10.4 \
      pydantic-settings==2.7.1 \
      "psycopg[binary]==3.2.3" \
      uvicorn==0.34.0

COPY packages ./packages
COPY backend ./backend
COPY tests/fixtures/canonical ./tests/fixtures/canonical

RUN useradd --create-home --uid 10001 reclaim \
    && chown -R reclaim:reclaim /opt/reclaim
USER reclaim

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=6 \
  CMD ["python", "-c", "import json,os,urllib.request; port=os.environ.get('PORT','8000'); assert json.load(urllib.request.urlopen(f'http://127.0.0.1:{port}/health/ready', timeout=2))['status'] == 'ready'"]

CMD ["sh", "-c", "exec python -m uvicorn api.main:app --host 0.0.0.0 --port \"${PORT:-8000}\""]
