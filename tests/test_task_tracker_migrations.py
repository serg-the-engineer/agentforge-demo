import importlib.util
import pathlib
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "task-tracker" / "migrate.py"
MIGRATIONS_DIR = ROOT / "task-tracker" / "migrations"
CORE_MIGRATION_PATH = MIGRATIONS_DIR / "0001_core_schema.sql"


def load_migrate_module():
    if not MODULE_PATH.is_file():
        raise RuntimeError(f"missing required file: {MODULE_PATH}")

    spec = importlib.util.spec_from_file_location(
        "demo_agentforge_task_tracker_migrate",
        MODULE_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module from {MODULE_PATH}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeCursor:
    def __init__(self, connection):
        self._connection = connection
        self._rows = []

    def execute(self, sql, params=None):
        statement = " ".join(sql.split())
        self._connection.statements.append((statement, params))
        lowered = statement.lower()
        if lowered.startswith("select version from task_tracker_schema_migrations"):
            versions = sorted(self._connection.applied_versions)
            self._rows = [(version,) for version in versions]
            return
        if lowered.startswith("insert into task_tracker_schema_migrations"):
            self._connection.applied_versions.add(params[0])
            self._rows = []
            return
        self._rows = []

    def fetchall(self):
        return list(self._rows)

    def close(self):
        return


class _FakeConnection:
    def __init__(self, applied_versions=None):
        self.applied_versions = set(applied_versions or ())
        self.statements = []
        self.commit_count = 0
        self.rollback_count = 0

    def cursor(self):
        return _FakeCursor(self)

    def commit(self):
        self.commit_count += 1

    def rollback(self):
        self.rollback_count += 1


class TaskTrackerSchemaMigrationTests(unittest.TestCase):
    def test_core_schema_migration_defines_core_tables_constraints_and_indexes(self):
        self.assertTrue(
            CORE_MIGRATION_PATH.is_file(),
            f"missing required file: {CORE_MIGRATION_PATH}",
        )

        sql = "\n".join(
            path.read_text(encoding="utf-8").lower()
            for path in sorted(MIGRATIONS_DIR.glob("*.sql"))
        )

        required_markers = (
            "create table if not exists projects",
            "create table if not exists workflow_versions",
            "create table if not exists workflow_transition_gates",
            "create table if not exists tasks",
            "create table if not exists transition_attempts",
            "create table if not exists pauses",
            "create table if not exists pause_answers",
            "create table if not exists events",
            "create table if not exists agentforge_idempotency",
            "create table if not exists agentforge_task_results",
            "check (status in ('backlog', 'ready', 'in_progress', 'done'))",
            "check (gate_type in ('auto', 'manual'))",
            "bigserial primary key",
            "create unique index if not exists idx_transition_attempts_one_pending_per_task",
            "create unique index if not exists idx_pauses_one_open_per_task",
            "where closed_at is null",
            "create unique index if not exists idx_agentforge_idempotency_operation_key",
        )

        for marker in required_markers:
            with self.subTest(marker=marker):
                self.assertIn(marker, sql)


class TaskTrackerMigrationRunnerTests(unittest.TestCase):
    def test_discover_migrations_returns_version_sorted_order(self):
        migrate = load_migrate_module()

        migrations = migrate.discover_migrations(MIGRATIONS_DIR)
        versions = [migration.version for migration in migrations]

        self.assertEqual(sorted(versions), versions)
        self.assertGreaterEqual(len(versions), 1)
        self.assertIn("0001", versions)

    def test_apply_migrations_runs_only_unapplied_versions(self):
        migrate = load_migrate_module()
        connection = _FakeConnection(applied_versions={"0001"})

        with tempfile.TemporaryDirectory() as tmp:
            migration_dir = pathlib.Path(tmp)
            (migration_dir / "0001_init.sql").write_text("select 1;\n", encoding="utf-8")
            (migration_dir / "0002_more.sql").write_text("select 2;\n", encoding="utf-8")

            applied = migrate.apply_migrations(
                connection,
                migrate.discover_migrations(migration_dir),
            )

        self.assertEqual(["0002"], applied)
        self.assertEqual({"0001", "0002"}, connection.applied_versions)
        executed_sql = "\n".join(statement for statement, _ in connection.statements)
        self.assertIn("select 2;", executed_sql.lower())
        self.assertNotIn("select 1;", executed_sql.lower())
        self.assertEqual(2, connection.commit_count)
        self.assertEqual(0, connection.rollback_count)


if __name__ == "__main__":
    unittest.main()
