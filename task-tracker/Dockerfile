FROM python:3.13-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV TASK_TRACKER_HOST=0.0.0.0
ENV TASK_TRACKER_PORT=9102

RUN pip install --no-cache-dir 'psycopg[binary]'

COPY server.py /app/server.py
COPY migrate.py /app/migrate.py
COPY migrations /app/migrations

EXPOSE 9102

CMD ["python", "/app/server.py"]
