FROM python:3.12.8-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/reclaim/backend:/opt/reclaim

WORKDIR /opt/reclaim
RUN python -m pip install --no-cache-dir \
      fastapi==0.115.6 \
      hvac==2.3.0 \
      "psycopg[binary]==3.2.3" \
      pydantic==2.10.4 \
      uvicorn==0.34.0 \
    && useradd --create-home --uid 10001 reclaim

COPY backend ./backend
COPY packages ./packages
RUN chown -R reclaim:reclaim /opt/reclaim
USER reclaim

CMD ["/opt/reclaim/infra/secret-broker/entrypoint.sh"]
