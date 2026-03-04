import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
NGINX_CONFIG_PATH = ROOT / "nginx" / "default.conf"


class NginxTaskTrackerRoutingTests(unittest.TestCase):
    def test_dev_tasks_and_dev_tasks_slash_redirect_to_demo_project(self):
        config = NGINX_CONFIG_PATH.read_text(encoding="utf-8")

        self.assertIn("location = /dev/tasks {", config)
        self.assertIn("location = /dev/tasks/ {", config)
        self.assertIn("return 302 /dev/tasks/ui?project_key=demo;", config)


if __name__ == "__main__":
    unittest.main()
