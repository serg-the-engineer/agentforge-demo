import argparse
import os
import re
import sys
from pathlib import Path
from typing import Iterable, NamedTuple


MIGRATION_FILE_PATTERN = re.compile(r"^(?P<version>\d{4})_(?P<name>[a-z0-9_]+)\.sql$")
DEFAULT_MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
SCHEMA_MIGRATIONS_TABLE = "task_tracker_schema_migrations"


class Migration(NamedTuple):
    version: str
    name: str
    path: Path


def discover_migrations(migrations_dir: Path | str = DEFAULT_MIGRATIONS_DIR) -> list[Migration]:
    migration_root = Path(migrations_dir)
    if not migration_root.is_dir():
        raise ValueError(f"migrations directory does not exist: {migration_root}")

    migrations: list[Migration] = []
    seen_versions: set[str] = set()

    for path in sorted(migration_root.iterdir()):
        if not path.is_file():
            continue

        match = MIGRATION_FILE_PATTERN.match(path.name)
        if not match:
            continue

        version = match.group("version")
        if version in seen_versions:
            raise ValueError(f"duplicate migration version detected: {version}")
        seen_versions.add(version)

        migrations.append(
            Migration(
                version=version,
                name=match.group("name"),
                path=path,
            )
        )

    return migrations


def _execute_with_transaction(connection, statements: Iterable[tuple[str, tuple | None]]) -> None:
    cursor = connection.cursor()
    try:
        for sql, params in statements:
            if params is None:
                cursor.execute(sql)
            else:
                cursor.execute(sql, params)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()


def _ensure_schema_migrations_table(connection) -> None:
    _execute_with_transaction(
        connection,
        (
            (
                f"""
                CREATE TABLE IF NOT EXISTS {SCHEMA_MIGRATIONS_TABLE} (
                    version TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """,
                None,
            ),
        ),
    )


def _fetch_applied_versions(connection) -> set[str]:
    cursor = connection.cursor()
    try:
        cursor.execute(
            f"""
            SELECT version
            FROM {SCHEMA_MIGRATIONS_TABLE}
            ORDER BY version
            """
        )
        return {row[0] for row in cursor.fetchall()}
    finally:
        cursor.close()


def apply_migrations(connection, migrations: Iterable[Migration]) -> list[str]:
    _ensure_schema_migrations_table(connection)
    applied_versions = _fetch_applied_versions(connection)
    applied_now: list[str] = []

    for migration in migrations:
        if migration.version in applied_versions:
            continue

        sql = migration.path.read_text(encoding="utf-8")
        _execute_with_transaction(
            connection,
            (
                (sql, None),
                (
                    f"""
                    INSERT INTO {SCHEMA_MIGRATIONS_TABLE} (version, name)
                    VALUES (%s, %s)
                    """,
                    (migration.version, migration.name),
                ),
            ),
        )

        applied_now.append(migration.version)
        applied_versions.add(migration.version)

    return applied_now


def _build_dsn_from_env() -> str:
    explicit = os.environ.get("TASK_TRACKER_DB_DSN")
    if explicit:
        return explicit

    host = os.environ.get("PGHOST", "127.0.0.1")
    port = os.environ.get("PGPORT", "5432")
    dbname = os.environ.get("PGDATABASE", "postgres")
    user = os.environ.get("PGUSER", "postgres")
    password = os.environ.get("PGPASSWORD", "postgres")

    return (
        f"host={host} "
        f"port={port} "
        f"dbname={dbname} "
        f"user={user} "
        f"password={password}"
    )


def _connect(dsn: str):
    try:
        import psycopg

        return psycopg.connect(dsn)
    except ModuleNotFoundError:
        try:
            import psycopg2

            return psycopg2.connect(dsn)
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "missing PostgreSQL driver: install psycopg or psycopg2"
            ) from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply task-tracker PostgreSQL migrations")
    parser.add_argument(
        "--migrations-dir",
        default=str(DEFAULT_MIGRATIONS_DIR),
        help="Path to migration SQL files",
    )
    parser.add_argument(
        "--dsn",
        default=None,
        help="PostgreSQL DSN; defaults to TASK_TRACKER_DB_DSN/PG* env vars",
    )
    args = parser.parse_args(argv)

    migrations = discover_migrations(Path(args.migrations_dir))
    dsn = args.dsn or _build_dsn_from_env()

    connection = _connect(dsn)
    try:
        applied_versions = apply_migrations(connection, migrations)
    finally:
        connection.close()

    if applied_versions:
        print(
            "applied migrations: " + ", ".join(applied_versions),
            file=sys.stdout,
        )
    else:
        print("no pending migrations", file=sys.stdout)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
