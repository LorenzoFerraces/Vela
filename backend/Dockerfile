FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY . .
RUN pip install --no-cache-dir .

# Migrations use the sync psycopg driver (VELA_DATABASE_URL is rewritten in
# app/db/engine.py); the API then runs without uvicorn reload (run.py is dev-only).
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.api.app:app --host 0.0.0.0 --port 8000"]
