#!/bin/sh
set -eu

if [ $# -ne 1 ]; then
	echo "usage: $0 <static|hygiene|contract|unit>" >&2
	exit 1
fi

target="$1"

check_static() {
	python3 - <<'PY'
from pathlib import Path
import ast
import json

for rel_path in (
    "api/server.py",
    "task-tracker/server.py",
    "tests/test_api_server.py",
    "tests/test_task_tracker_server.py",
    "tests/test_task_tracker_runtime_api.py",
    "tests/test_standalone_runtime_contract.py",
):
    path = Path(rel_path)
    if not path.is_file():
        raise SystemExit(f"missing required file: {rel_path}")
    ast.parse(path.read_text(encoding="utf-8"), filename=rel_path)

for rel_path in (
    ".gitignore",
    ".github/workflows/cicd.yml",
    "site/index.html",
    "site/assets/favicon.svg",
    "site/assets/game.js",
    "site/assets/styles.css",
    "site/version.json",
    "docker-compose.yml",
    "nginx/default.conf",
    "nginx/demo-auth.htpasswd",
    "AGENTS.md",
    "README.md",
    "Makefile",
    "scripts/verify.sh",
    "docs/task-tracker-spec.md",
    "task-tracker/Dockerfile",
    "task-tracker/README.md",
):
    if not Path(rel_path).is_file():
        raise SystemExit(f"missing required file: {rel_path}")

json.loads(Path("site/version.json").read_text(encoding="utf-8"))

html_text = Path("site/index.html").read_text(encoding="utf-8")
if 'rel="icon"' not in html_text or 'href="/assets/favicon.svg"' not in html_text:
    raise SystemExit("site/index.html must link /assets/favicon.svg as rel=icon")
PY
}

check_hygiene() {
	python3 - <<'PY'
from pathlib import Path
import re

roots = (
    Path("AGENTS.md"),
    Path("README.md"),
    Path("Makefile"),
    Path("api"),
    Path("site"),
    Path("nginx"),
    Path("docs"),
    Path("scripts"),
    Path("task-tracker"),
    Path("tests"),
)

tokens = ("TO" + "DO", "FIX" + "ME")
needle = re.compile(r"\b(" + "|".join(tokens) + r")\b")

for root in roots:
    if not root.exists():
        continue

    candidates = [root] if root.is_file() else (
        path for path in root.rglob("*") if path.is_file() and "__pycache__" not in path.parts
    )

    for path in candidates:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        match = needle.search(text)
        if match:
            raise SystemExit(f"placeholder marker found in {path}")
PY
}

check_contract() {
	python3 - <<'PY'
from pathlib import Path
import json
import re

version_payload = json.loads(Path("site/version.json").read_text(encoding="utf-8"))
html_text = Path("site/index.html").read_text(encoding="utf-8")
game_text = Path("site/assets/game.js").read_text(encoding="utf-8")
compose_text = Path("docker-compose.yml").read_text(encoding="utf-8")
nginx_text = Path("nginx/default.conf").read_text(encoding="utf-8")
agents_text = Path("AGENTS.md").read_text(encoding="utf-8")
readme_text = Path("README.md").read_text(encoding="utf-8")
makefile_text = Path("Makefile").read_text(encoding="utf-8")
workflow_text = Path(".github/workflows/cicd.yml").read_text(encoding="utf-8")
task_tracker_spec_text = Path("docs/task-tracker-spec.md").read_text(encoding="utf-8")
task_tracker_server_text = Path("task-tracker/server.py").read_text(encoding="utf-8")
task_tracker_dockerfile_text = Path("task-tracker/Dockerfile").read_text(encoding="utf-8")
task_tracker_readme_text = Path("task-tracker/README.md").read_text(encoding="utf-8")

match = re.search(r'data-app-version="([^"]+)"', html_text)
if not match:
    raise SystemExit("site/index.html must expose data-app-version")

html_version = match.group(1)
json_version = version_payload.get("version")

if version_payload.get("name") != "demo-agentforge":
    raise SystemExit("site/version.json name must stay demo-agentforge")

if html_version != json_version:
    raise SystemExit(
        "site/index.html data-app-version and site/version.json version must match"
    )

for marker in ('"/api/state"', '"/version.json"'):
    if marker not in game_text:
        raise SystemExit(f"site/assets/game.js missing contract marker: {marker}")

for marker in (
    "\n  web:\n",
    "\n  api:\n",
    "\n  db:\n",
    "\n  redis:\n",
    "\n  beads-dolt:\n",
    "\n  beads-ui:\n",
    "\n  task-tracker-db:\n",
    "\n  task-tracker:\n",
    '"8081"',
    "8081:8081",
    '"9001"',
    '"5433"',
    '"6380"',
    '"9102"',
    "127.0.0.1:55432:5432",
    "127.0.0.1:9102:9102",
    "./nginx/demo-auth.htpasswd:/etc/nginx/conf.d/demo-auth.htpasswd:ro",
):
    if marker not in compose_text:
        raise SystemExit(f"docker-compose.yml missing contract marker: {marker}")

for forbidden in ("agentforge-edge", "demo-agentforge-web", "external: true"):
    if forbidden in compose_text:
        raise SystemExit(f"docker-compose.yml contains deprecated shared-host marker: {forbidden}")

for marker in (
    "location /api/",
    "proxy_pass http://$api_upstream;",
    "location = /dev/tasks {",
    "location /dev/tasks/",
    "task-tracker:9102",
    "location = /dev/beads {",
    "location = /dev/beads/ws",
    "location /dev/beads/",
    "beads-ui:8080",
    'auth_basic "demo-agentforge";',
    "auth_basic_user_file /etc/nginx/conf.d/demo-auth.htpasswd;",
    "location / {",
    "try_files $uri $uri/ /index.html;",
):
    if marker not in nginx_text:
        raise SystemExit(f"nginx/default.conf missing runtime marker: {marker}")

for marker in (
    "Use TDD for demo changes",
    "`tests/test_api_server.py`",
    "`scripts/verify.sh`",
    "Use task-tracker as the source of truth for delivery work",
    "`task-tracker/README.md`",
    "`make verify-fast`",
    "`make verify`",
):
    if marker not in agents_text:
        raise SystemExit(f"AGENTS.md missing delivery marker: {marker}")

for marker in (
    "## Stack",
    "## Task Tracking Workflow",
    "## AgentForge Protocol v1 Bridge",
    "/api/agentforge/config",
    "Как подключить AgentForge через `/api/agentforge/config`",
    "## Fixed Compose Contract",
    "## Standalone Host Deployment",
    "`/dev/tasks` -> `task-tracker:9102`",
    "`/dev/beads` -> `beads-ui:8080`",
    "## Local Delivery Workflow",
    "`task-tracker/README.md`",
    "`make task-tracker-migrate`",
    "`make task-tracker-health`",
    "`make task-tracker-snapshot`",
    "`make verify-fast`",
    "`make verify`",
    "`make verify-ci`",
    "## CI/CD Contract",
):
    if marker not in readme_text:
        raise SystemExit(f"README.md missing delivery marker: {marker}")

for target in (
    "task-tracker-migrate",
    "task-tracker-health",
    "task-tracker-snapshot",
    "verify-fast",
    "verify",
    "verify-ci",
    "lint-static",
    "lint-hygiene",
    "lint-contract",
    "test-unit",
):
    if f"\n{target}:" not in makefile_text:
        raise SystemExit(f"Makefile missing target: {target}")

for marker in (
    "name: CI/CD",
    "validate:",
    "deploy:",
    "needs: validate",
    "make verify-ci",
    "/srv/agentforge-demo",
    "docker compose run --rm task-tracker python /app/migrate.py",
    "docker compose up --build -d",
    "docker compose up -d --no-deps --force-recreate task-tracker web",
):
    if marker not in workflow_text:
        raise SystemExit(f".github/workflows/cicd.yml missing marker: {marker}")

for marker in (
    "# Task Tracker MVP Specification",
    "## Status Model",
    "backlog -> ready -> in_progress -> done",
    "blocked",
    "awaiting_input",
    "## Gate Approval Semantics",
    "reject-with-comment",
    "## API Contract",
    "POST /api/v1/tasks/{task_id}/actions/start_work",
    "POST /api/v1/transitions/{attempt_id}/approve",
    "POST /api/v1/transitions/{attempt_id}/reject",
    "GET /api/v1/ui/snapshot",
    "GET /api/v1/ui/updates?cursor=<cursor>&timeout=<seconds>",
    "### AgentForge Bridge (`v1`)",
    "GET /api/agentforge/config",
    "GET /api/agentforge/ready-candidates",
    "POST /api/agentforge/ready-candidates/{external_id}/planned",
    "POST /api/agentforge/ready-candidates/{external_id}/done",
    "HTTP Basic auth",
):
    if marker not in task_tracker_spec_text:
        raise SystemExit(f"docs/task-tracker-spec.md missing contract marker: {marker}")

for marker in (
    "/healthz",
    '"status": "ok"',
    "create_server(",
    'TASK_TRACKER_AGENTFORGE_API_PREFIX = "/api/agentforge"',
    "TASK_TRACKER_AGENTFORGE_CONFIG_PATH",
    "TASK_TRACKER_AGENTFORGE_READY_CANDIDATES_PATH",
    "post_agentforge_planned",
    "post_agentforge_done",
):
    if marker not in task_tracker_server_text:
        raise SystemExit(f"task-tracker/server.py missing contract marker: {marker}")

for marker in (
    "pip install --no-cache-dir 'psycopg[binary]'",
    "COPY server.py /app/server.py",
    'CMD ["python", "/app/server.py"]',
):
    if marker not in task_tracker_dockerfile_text:
        raise SystemExit(f"task-tracker/Dockerfile missing contract marker: {marker}")

for marker in (
    "# Task Tracker Sidecar (T02 Scaffold)",
    "GET /healthz",
    "## T13: AgentForge Bridge Protocol `v1`",
    "GET /api/agentforge/config",
    "GET /api/agentforge/ready-candidates",
    "Idempotency-Key",
    "Как подключить AgentForge через `/api/agentforge/config`",
    "## T12: Sidecar Packaging and Usage",
    "### Compose snippet",
    "task-tracker-db:",
    "task-tracker:",
    "TASK_TRACKER_DATABASE_URL=postgresql://task_tracker:task_tracker@127.0.0.1:55432/task_tracker",
    "### Quickstart",
    "docker compose run --rm task-tracker python /app/migrate.py",
    "curl -sS http://127.0.0.1:9102/healthz",
    "### Runbook",
    "curl -sS \"http://127.0.0.1:9102/api/v1/ui/snapshot?project_key=demo\"",
    "psql \"postgresql://task_tracker:task_tracker@127.0.0.1:55432/task_tracker\"",
):
    if marker not in task_tracker_readme_text:
        raise SystemExit(f"task-tracker/README.md missing contract marker: {marker}")

placeholder_tokens = ("TO" + "DO", "TB" + "D", "TB" + "C", "XX" + "X")
if re.search(r"\b(" + "|".join(placeholder_tokens) + r")\b", task_tracker_spec_text):
    raise SystemExit("docs/task-tracker-spec.md must not contain unresolved placeholders")
PY
}

check_unit() {
	python3 -m unittest discover -s tests -p 'test_*.py'
}

case "$target" in
	static)
		check_static
		;;
	hygiene)
		check_hygiene
		;;
	contract)
		check_contract
		;;
	unit)
		check_unit
		;;
	*)
		echo "unsupported target: $target" >&2
		exit 1
		;;
esac
