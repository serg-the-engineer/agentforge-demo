import importlib.util
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "api" / "server.py"


def load_server_module():
    spec = importlib.util.spec_from_file_location(
        "demo_agentforge_api_server",
        MODULE_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module from {MODULE_PATH}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SERVER = load_server_module()


class ParseRedisURLTests(unittest.TestCase):
    def test_parse_redis_url_uses_defaults(self):
        host, port, database = SERVER.parse_redis_url("redis://cache")

        self.assertEqual("cache", host)
        self.assertEqual(6380, port)
        self.assertEqual(0, database)

    def test_parse_redis_url_reads_explicit_parts(self):
        host, port, database = SERVER.parse_redis_url("redis://cache:6391/7")

        self.assertEqual("cache", host)
        self.assertEqual(6391, port)
        self.assertEqual(7, database)

    def test_parse_redis_url_rejects_other_schemes(self):
        with self.assertRaisesRegex(ValueError, "redis://"):
            SERVER.parse_redis_url("http://cache:6391/7")


class RedisClientTests(unittest.TestCase):
    def test_client_uses_parsed_connection_details(self):
        client = SERVER.RedisClient("redis://cache:6399/3")

        self.assertEqual("cache", client.host)
        self.assertEqual(6399, client.port)
        self.assertEqual(3, client.database)


class PostgresClientTests(unittest.TestCase):
    def test_get_best_score_normalizes_missing_or_negative_values(self):
        client = SERVER.PostgresClient("postgresql://demo")
        client._schema_ready = True
        client._run_sql = lambda statement: "-7"

        self.assertEqual(0, client.get_best_score())

    def test_save_best_score_clamps_negative_candidate_before_writing(self):
        client = SERVER.PostgresClient("postgresql://demo")
        client._schema_ready = True
        statements = []

        def fake_run_sql(statement):
            statements.append(statement)
            return "-5"

        client._run_sql = fake_run_sql

        self.assertEqual(0, client.save_best_score(-12))
        self.assertEqual(1, len(statements))
        self.assertIn("VALUES (1, 0)", statements[0])


if __name__ == "__main__":
    unittest.main()
