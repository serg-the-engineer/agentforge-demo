import json
import os
import socket
import subprocess
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse


STATE_KEY = os.environ.get("DEMO_STATE_KEY", "demo-agentforge:best-score")
DATABASE_URL = os.environ.get(
    "DEMO_DATABASE_URL",
    "postgresql://demo_agentforge:demo_agentforge@db:5433/demo_agentforge?sslmode=disable",
)
REDIS_URL = os.environ.get("DEMO_REDIS_URL", "redis://redis:6380/0")
API_HOST = os.environ.get("DEMO_API_HOST", "0.0.0.0")
API_PORT = int(os.environ.get("DEMO_API_PORT", "9001"))


def parse_redis_url(url):
    parsed = urlparse(url)
    if parsed.scheme != "redis":
        raise ValueError("DEMO_REDIS_URL must use redis://")

    host = parsed.hostname or "redis"
    port = parsed.port or 6380
    database = 0

    if parsed.path and parsed.path != "/":
        database = int(parsed.path.lstrip("/"))

    return host, port, database


class RedisClient:
    def __init__(self, url):
        self.host, self.port, self.database = parse_redis_url(url)

    def _write_command(self, connection, *parts):
        chunks = [f"*{len(parts)}\r\n".encode("utf-8")]

        for part in parts:
            encoded = str(part).encode("utf-8")
            chunks.append(f"${len(encoded)}\r\n".encode("utf-8"))
            chunks.append(encoded + b"\r\n")

        connection.sendall(b"".join(chunks))

    def _readline(self, connection):
        data = bytearray()

        while True:
            char = connection.recv(1)
            if not char:
                raise ConnectionError("unexpected EOF from redis")
            data.extend(char)
            if data.endswith(b"\r\n"):
                return bytes(data[:-2])

    def _read_response(self, connection):
        prefix = connection.recv(1)
        if not prefix:
            raise ConnectionError("unexpected EOF from redis")

        if prefix == b"+":
            return self._readline(connection).decode("utf-8")

        if prefix == b":":
            return int(self._readline(connection))

        if prefix == b"$":
            length = int(self._readline(connection))
            if length == -1:
                return None

            payload = bytearray()
            while len(payload) < length:
                chunk = connection.recv(length - len(payload))
                if not chunk:
                    raise ConnectionError("unexpected EOF from redis")
                payload.extend(chunk)

            trailer = connection.recv(2)
            if trailer != b"\r\n":
                raise ConnectionError("malformed bulk string from redis")

            return payload.decode("utf-8")

        if prefix == b"-":
            message = self._readline(connection).decode("utf-8")
            raise RuntimeError(message)

        if prefix == b"*":
            length = int(self._readline(connection))
            return [self._read_response(connection) for _ in range(length)]

        raise RuntimeError(f"unsupported redis response prefix: {prefix!r}")

    def _call(self, *parts):
        with socket.create_connection((self.host, self.port), timeout=2) as connection:
            if self.database:
                self._write_command(connection, "SELECT", self.database)
                self._read_response(connection)

            self._write_command(connection, *parts)
            return self._read_response(connection)

    def ping(self):
        return self._call("PING") == "PONG"

    def get_best_score(self):
        payload = self._call("GET", STATE_KEY)
        if payload is None:
            return None
        return max(int(payload), 0)

    def cache_best_score(self, score):
        self._call("SET", STATE_KEY, max(int(score), 0))


class PostgresClient:
    def __init__(self, database_url):
        self.database_url = database_url
        self._schema_ready = False
        self._schema_lock = threading.Lock()

    def _run_sql(self, statement):
        result = subprocess.run(
            [
                "psql",
                self.database_url,
                "-v",
                "ON_ERROR_STOP=1",
                "-q",
                "-t",
                "-A",
                "-c",
                statement,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    def ensure_schema(self):
        if self._schema_ready:
            return

        with self._schema_lock:
            if self._schema_ready:
                return

            self._run_sql(
                """
                CREATE TABLE IF NOT EXISTS demo_state (
                    id SMALLINT PRIMARY KEY,
                    best_score INTEGER NOT NULL CHECK (best_score >= 0),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )
            self._schema_ready = True

    def ping(self):
        return self._run_sql("SELECT 1;") == "1"

    def get_best_score(self):
        self.ensure_schema()
        payload = self._run_sql(
            "SELECT COALESCE((SELECT best_score FROM demo_state WHERE id = 1), 0);"
        )
        return max(int(payload or "0"), 0)

    def save_best_score(self, score):
        self.ensure_schema()
        candidate = max(int(score), 0)
        payload = self._run_sql(
            (
                "INSERT INTO demo_state (id, best_score) VALUES (1, {candidate}) "
                "ON CONFLICT (id) DO UPDATE SET "
                "best_score = GREATEST(demo_state.best_score, EXCLUDED.best_score), "
                "updated_at = NOW() "
                "RETURNING best_score;"
            ).format(candidate=candidate)
        )
        return max(int(payload or "0"), 0)


class DemoStateHandler(BaseHTTPRequestHandler):
    postgres = PostgresClient(DATABASE_URL)
    redis = RedisClient(REDIS_URL)

    def log_message(self, format, *args):
        return

    def _send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length) if length else b"{}"
        if not raw_body:
            return {}
        return json.loads(raw_body.decode("utf-8"))

    def _load_best_score(self):
        try:
            cached_score = self.redis.get_best_score()
            if cached_score is not None:
                return cached_score, "redis"
        except Exception:
            pass

        best_score = self.postgres.get_best_score()

        try:
            self.redis.cache_best_score(best_score)
        except Exception:
            pass

        return best_score, "postgres"

    def do_GET(self):
        if self.path == "/healthz":
            redis_ok = False

            try:
                self.postgres.ping()
            except Exception as error:
                self._send_json(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    {"ok": False, "postgres": False, "redis": False, "error": str(error)},
                )
                return

            try:
                redis_ok = self.redis.ping()
            except Exception:
                redis_ok = False

            self._send_json(
                HTTPStatus.OK,
                {"ok": True, "postgres": True, "redis": redis_ok},
            )
            return

        if self.path == "/api/state":
            try:
                best_score, source = self._load_best_score()
                self._send_json(
                    HTTPStatus.OK,
                    {"bestScore": best_score, "source": source},
                )
            except Exception as error:
                self._send_json(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    {"error": "backend unavailable", "details": str(error)},
                )
            return

        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self):
        if self.path != "/api/state":
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return

        try:
            payload = self._read_json()
            candidate = max(int(payload.get("bestScore", 0)), 0)
            best_score = self.postgres.save_best_score(candidate)

            cache_updated = True
            try:
                self.redis.cache_best_score(best_score)
            except Exception:
                cache_updated = False

            self._send_json(
                HTTPStatus.OK,
                {
                    "bestScore": best_score,
                    "stored": best_score == candidate,
                    "cacheUpdated": cache_updated,
                },
            )
        except (TypeError, ValueError, json.JSONDecodeError):
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {"error": "bestScore must be a non-negative integer"},
            )
        except Exception as error:
            self._send_json(
                HTTPStatus.SERVICE_UNAVAILABLE,
                {"error": "backend unavailable", "details": str(error)},
            )


if __name__ == "__main__":
    server = ThreadingHTTPServer((API_HOST, API_PORT), DemoStateHandler)
    server.serve_forever()
