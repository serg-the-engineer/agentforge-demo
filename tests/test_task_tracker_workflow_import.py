import importlib.util
import json
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "task-tracker" / "workflow_import.py"

VALID_WORKFLOW_TOML = """
[[transitions]]
from_status = "backlog"
to_status = "ready"
gate_type = "auto"

[[transitions]]
from_status = "ready"
to_status = "in_progress"
gate_type = "manual"
""".strip()


class _FakeCursor:
    def __init__(self, connection):
        self._connection = connection
        self._rows = []

    def execute(self, sql, params=None):
        statement = " ".join(sql.split())
        lowered = statement.lower()

        if lowered.startswith("insert into projects"):
            project_key = params[0]
            self._connection.projects.setdefault(
                project_key,
                {
                    "project_key": project_key,
                    "active_workflow_version_id": None,
                },
            )
            self._rows = []
            return

        if lowered.startswith("select id, version from workflow_versions"):
            project_key, normalized_json = params
            normalized = json.loads(normalized_json)
            matches = [
                row
                for row in self._connection.workflow_versions
                if row["project_key"] == project_key
                and row["normalized_definition"] == normalized
            ]
            matches.sort(key=lambda row: row["version"], reverse=True)
            if matches:
                row = matches[0]
                self._rows = [(row["id"], row["version"])]
            else:
                self._rows = []
            return

        if lowered.startswith("select coalesce(max(version), 0) from workflow_versions"):
            project_key = params[0]
            versions = [
                row["version"]
                for row in self._connection.workflow_versions
                if row["project_key"] == project_key
            ]
            self._rows = [(max(versions) if versions else 0,)]
            return

        if lowered.startswith("insert into workflow_versions"):
            workflow_id, project_key, version, version_label, source_toml, normalized_json = params
            self._connection.workflow_versions.append(
                {
                    "id": workflow_id,
                    "project_key": project_key,
                    "version": version,
                    "version_label": version_label,
                    "source_toml": source_toml,
                    "normalized_definition": json.loads(normalized_json),
                }
            )
            self._rows = []
            return

        if lowered.startswith("insert into workflow_transition_gates"):
            workflow_version_id, from_status, to_status, gate_type = params
            self._connection.transition_gates.append(
                {
                    "workflow_version_id": workflow_version_id,
                    "from_status": from_status,
                    "to_status": to_status,
                    "gate_type": gate_type,
                }
            )
            self._rows = []
            return

        if lowered.startswith("update projects set active_workflow_version_id"):
            workflow_version_id, project_key = params
            if project_key not in self._connection.projects:
                self._connection.projects[project_key] = {
                    "project_key": project_key,
                    "active_workflow_version_id": None,
                }
            self._connection.projects[project_key]["active_workflow_version_id"] = workflow_version_id
            self._rows = []
            return

        raise AssertionError(f"unexpected SQL: {statement}")

    def fetchone(self):
        if not self._rows:
            return None
        return self._rows[0]

    def close(self):
        return


class _FakeConnection:
    def __init__(self):
        self.projects = {}
        self.workflow_versions = []
        self.transition_gates = []
        self.tasks = []
        self.commit_count = 0
        self.rollback_count = 0

    def cursor(self):
        return _FakeCursor(self)

    def commit(self):
        self.commit_count += 1

    def rollback(self):
        self.rollback_count += 1


def load_workflow_import_module():
    if not MODULE_PATH.is_file():
        raise RuntimeError(f"missing required file: {MODULE_PATH}")

    spec = importlib.util.spec_from_file_location(
        "demo_agentforge_task_tracker_workflow_import",
        MODULE_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module from {MODULE_PATH}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TaskTrackerWorkflowImportParseTests(unittest.TestCase):
    def test_parse_workflow_toml_rejects_invalid_toml_payload(self):
        workflow_import = load_workflow_import_module()

        with self.assertRaises(workflow_import.WorkflowImportError):
            workflow_import.parse_workflow_toml("[[transitions]\nfrom_status='backlog'")

    def test_parse_workflow_toml_validates_transition_shapes(self):
        workflow_import = load_workflow_import_module()

        invalid_missing_key = """
        [[transitions]]
        from_status = "backlog"
        gate_type = "auto"
        """.strip()

        with self.assertRaises(workflow_import.WorkflowImportError):
            workflow_import.parse_workflow_toml(invalid_missing_key)


class TaskTrackerWorkflowImportDbTests(unittest.TestCase):
    def test_import_workflow_is_idempotent_for_semantically_identical_toml(self):
        workflow_import = load_workflow_import_module()
        connection = _FakeConnection()

        first = workflow_import.import_workflow(
            connection=connection,
            project_key="demo",
            workflow_toml=VALID_WORKFLOW_TOML,
            version_label="v1",
        )
        second = workflow_import.import_workflow(
            connection=connection,
            project_key="demo",
            workflow_toml=VALID_WORKFLOW_TOML,
            version_label="v1-ignored",
        )

        self.assertEqual(first["workflow_version_id"], second["workflow_version_id"])
        self.assertEqual(1, first["version"])
        self.assertEqual(1, second["version"])
        self.assertEqual(1, len(connection.workflow_versions))
        self.assertEqual(2, len(connection.transition_gates))
        self.assertEqual(2, connection.commit_count)
        self.assertEqual(0, connection.rollback_count)

    def test_import_workflow_sets_new_active_version_without_repinning_existing_tasks(self):
        workflow_import = load_workflow_import_module()
        connection = _FakeConnection()

        first = workflow_import.import_workflow(
            connection=connection,
            project_key="demo",
            workflow_toml=VALID_WORKFLOW_TOML,
            version_label="v1",
        )

        connection.tasks.append(
            {
                "id": "task-1",
                "project_key": "demo",
                "workflow_version_id": first["workflow_version_id"],
            }
        )

        second_toml = """
        [[transitions]]
        from_status = "backlog"
        to_status = "ready"
        gate_type = "manual"

        [[transitions]]
        from_status = "ready"
        to_status = "in_progress"
        gate_type = "manual"
        """.strip()

        second = workflow_import.import_workflow(
            connection=connection,
            project_key="demo",
            workflow_toml=second_toml,
            version_label="v2",
        )

        self.assertNotEqual(first["workflow_version_id"], second["workflow_version_id"])
        self.assertEqual(2, second["version"])
        self.assertEqual(
            second["workflow_version_id"],
            connection.projects["demo"]["active_workflow_version_id"],
        )
        self.assertEqual(first["workflow_version_id"], connection.tasks[0]["workflow_version_id"])
        self.assertEqual(2, len(connection.workflow_versions))
        self.assertEqual(4, len(connection.transition_gates))


if __name__ == "__main__":
    unittest.main()
