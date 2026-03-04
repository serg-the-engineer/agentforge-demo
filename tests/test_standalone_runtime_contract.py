import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
COMPOSE_PATH = ROOT / "docker-compose.yml"
NGINX_CONFIG_PATH = ROOT / "nginx" / "default.conf"
NGINX_AUTH_PATH = ROOT / "nginx" / "demo-auth.htpasswd"


class StandaloneRuntimeContractTests(unittest.TestCase):
    def test_compose_publishes_web_port_for_direct_host_access(self):
        compose_text = COMPOSE_PATH.read_text(encoding="utf-8")

        self.assertIn("\n  web:\n", compose_text)
        self.assertIn('      - "8081:8081"', compose_text)

    def test_compose_does_not_require_external_agentforge_network(self):
        compose_text = COMPOSE_PATH.read_text(encoding="utf-8")

        self.assertNotIn("agentforge-edge", compose_text)
        self.assertNotIn("external: true", compose_text)
        self.assertNotIn("demo-agentforge-web", compose_text)

    def test_nginx_requires_basic_auth_for_public_standalone_access(self):
        config_text = NGINX_CONFIG_PATH.read_text(encoding="utf-8")

        self.assertIn('auth_basic "demo-agentforge";', config_text)
        self.assertIn("auth_basic_user_file /etc/nginx/conf.d/demo-auth.htpasswd;", config_text)

    def test_nginx_auth_file_exists_with_admin_credentials(self):
        auth_text = NGINX_AUTH_PATH.read_text(encoding="utf-8").strip()

        self.assertTrue(auth_text.startswith("admin:"))


if __name__ == "__main__":
    unittest.main()
