import importlib.util
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "task-tracker" / "server.py"


def load_server_module():
    if not MODULE_PATH.is_file():
        raise RuntimeError(f"missing required file: {MODULE_PATH}")

    spec = importlib.util.spec_from_file_location(
        "demo_agentforge_task_tracker_server",
        MODULE_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module from {MODULE_PATH}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TaskTrackerServerTests(unittest.TestCase):
    def test_healthz_returns_ok_status_payload(self):
        server_module = load_server_module()
        status, payload = server_module.route_get("/healthz")

        self.assertEqual(200, int(status))
        self.assertEqual({"status": "ok"}, payload)

    def test_unknown_path_returns_not_found(self):
        server_module = load_server_module()
        status, payload = server_module.route_get("/not-found")

        self.assertEqual(404, int(status))
        self.assertEqual("not_found", payload.get("error", {}).get("code"))

    def test_operational_ui_template_contains_board_details_and_actions(self):
        server_module = load_server_module()

        html = server_module.render_operational_ui_html("project-ui")

        self.assertIn('id="tt-board"', html)
        self.assertIn('id="tt-details"', html)
        self.assertIn('data-action="approve-transition"', html)
        self.assertIn('data-action="reject-transition"', html)
        self.assertIn('data-action="add-answer"', html)
        self.assertIn('data-action="resume-pause"', html)
        self.assertIn('data-action="open-blocked"', html)
        self.assertIn('data-action="open-awaiting-input"', html)
        self.assertIn('const DEFAULT_PROJECT_KEY = "project-ui";', html)
        self.assertNotIn('id="tt-project-key"', html)
        self.assertNotIn('id="tt-connect"', html)
        self.assertIn('id="tt-project-label"', html)


if __name__ == "__main__":
    unittest.main()
