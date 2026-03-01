FROM python:3.12-alpine

WORKDIR /app

RUN apk add --no-cache postgresql-client

COPY server.py /app/server.py

EXPOSE 9001

CMD ["python", "/app/server.py"]
