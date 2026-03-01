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

for rel_path in ("api/server.py", "tests/test_api_server.py"):
    path = Path(rel_path)
    if not path.is_file():
        raise SystemExit(f"missing required file: {rel_path}")
    ast.parse(path.read_text(encoding="utf-8"), filename=rel_path)

for rel_path in (
    ".gitignore",
    ".github/workflows/cicd.yml",
    "site/index.html",
    "site/assets/game.js",
    "site/assets/styles.css",
    "site/version.json",
    "docker-compose.yml",
    "beads-ui/Dockerfile",
    "nginx/default.conf",
    "AGENTS.md",
    "README.md",
    "Makefile",
    "scripts/beads_shared_init.sh",
    "beads/PRIME.md",
    "beads/formulas/mol-change-request.formula.json",
):
    if not Path(rel_path).is_file():
        raise SystemExit(f"missing required file: {rel_path}")

json.loads(Path("site/version.json").read_text(encoding="utf-8"))
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
    Path("beads"),
    Path("scripts"),
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
beads_ui_dockerfile_text = Path("beads-ui/Dockerfile").read_text(encoding="utf-8")
beads_init_text = Path("scripts/beads_shared_init.sh").read_text(encoding="utf-8")
agents_text = Path("AGENTS.md").read_text(encoding="utf-8")
readme_text = Path("README.md").read_text(encoding="utf-8")
makefile_text = Path("Makefile").read_text(encoding="utf-8")
formula_text = Path("beads/formulas/mol-change-request.formula.json").read_text(
    encoding="utf-8"
)
formula_payload = json.loads(formula_text)
workflow_text = Path(".github/workflows/cicd.yml").read_text(encoding="utf-8")

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
    'demo-agentforge-web',
    '"8081"',
    '"9001"',
    '"3306"',
    '"5433"',
    '"6380"',
    '"127.0.0.1:3307:3306"',
    'dolthub/dolt-sql-server:latest',
    'dockerfile: beads-ui/Dockerfile',
    'sh ./scripts/beads_shared_init.sh',
    'exec node /usr/local/lib/node_modules/beads-ui/server/index.js --host 0.0.0.0 --port 8080',
):
    if marker not in compose_text:
        raise SystemExit(f"docker-compose.yml missing contract marker: {marker}")

for marker in (
    "location /ws",
    "proxy_set_header Upgrade $http_upgrade;",
    'proxy_set_header Connection "upgrade";',
):
    if marker not in nginx_text:
        raise SystemExit(f"nginx/default.conf missing websocket marker: {marker}")

beads_dolt_match = re.search(
    r"\n  beads-dolt:\n(?P<body>.*?)(?:\n  [a-z0-9-]+:\n|\nnetworks:\n)",
    compose_text,
    re.S,
)
if not beads_dolt_match:
    raise SystemExit("docker-compose.yml missing beads-dolt service block")

beads_dolt_block = beads_dolt_match.group("body")
for forbidden in ("- dolt", "- sql-server", "- --host", "- --port"):
    if forbidden in beads_dolt_block:
        raise SystemExit(
            f"docker-compose.yml beads-dolt command must not include {forbidden!r}"
        )

for required in ("- --data-dir", "- /var/lib/dolt"):
    if required not in beads_dolt_block:
        raise SystemExit(
            f"docker-compose.yml beads-dolt command missing required marker: {required}"
        )

for marker in (
    "FROM node:22-bookworm-slim",
    "npm install -g beads-ui",
    "@beads/bd",
):
    if marker not in beads_ui_dockerfile_text:
        raise SystemExit(f"beads-ui/Dockerfile missing contract marker: {marker}")

for marker in (
    "legacy_cli=0",
    "bd init --help",
    "bd init --force --server",
    "--server-host \"$host\"",
    "--server-port \"$port\"",
    "--server-user \"$user\"",
    "--skip-hooks",
    "git init -q",
):
    if marker not in beads_init_text:
        raise SystemExit(f"scripts/beads_shared_init.sh missing marker: {marker}")

for marker in (
    "<!-- BEGIN BEADS INTEGRATION -->",
    "`make beads-init`",
    "`bd prime`",
    "`bd ready`",
    "`review_approval`",
    "review approval is a Beads status gate",
):
    if marker not in agents_text:
        raise SystemExit(f"AGENTS.md missing Beads workflow marker: {marker}")

for marker in (
    "make beads-init",
    "beads/PRIME.md",
    "bd prime",
    "`review_approval`",
    "review approval is recorded by humans in Beads",
):
    if marker not in readme_text:
        raise SystemExit(f"README.md missing Beads workflow marker: {marker}")

if "\nbeads-init:\n" not in makefile_text:
    raise SystemExit("Makefile must expose a beads-init target")

for marker in ("types.custom", "gate"):
    if marker not in beads_init_text:
        raise SystemExit(f"scripts/beads_shared_init.sh missing gate type marker: {marker}")

gitignore_text = Path(".gitignore").read_text(encoding="utf-8")
if ".beads/" not in gitignore_text:
    raise SystemExit(".gitignore must keep .beads/ out of version control")
if ".beads-host/" not in gitignore_text:
    raise SystemExit(".gitignore must keep .beads-host/ out of version control")

for marker in (
    "`make beads-init`",
    "`bd prime`",
    "`make verify-fast`",
    "`make verify`",
    "`review_approval`",
    "without requiring a GitHub PR review approval",
):
    if marker not in formula_text:
        raise SystemExit(
            f"beads/formulas/mol-change-request.formula.json missing marker: {marker}"
        )

formula_steps = formula_payload.get("steps")
if not isinstance(formula_steps, list):
    raise SystemExit("mol-change-request formula must define a steps array")

expected_step_ids = [
    "plan",
    "plan_approval",
    "implement",
    "review",
    "review_approval",
    "ci",
    "merge",
    "deploy",
    "acceptance",
]
actual_step_ids = [step.get("id") for step in formula_steps]
if actual_step_ids != expected_step_ids:
    raise SystemExit(
        "mol-change-request step ids must stay "
        f"{' -> '.join(expected_step_ids)} (got {' -> '.join(str(i) for i in actual_step_ids)})"
    )

step_by_id = {step["id"]: step for step in formula_steps if isinstance(step, dict) and "id" in step}

for human_gate in ("plan_approval", "review_approval", "acceptance"):
    step = step_by_id.get(human_gate)
    if not step:
        raise SystemExit(f"mol-change-request missing required step: {human_gate}")
    if step.get("type") != "human":
        raise SystemExit(f"{human_gate} must stay a human gate")
    gate_type = (step.get("gate") or {}).get("type")
    if gate_type != "human":
        raise SystemExit(f"{human_gate} must use gate.type=human")

ci_step = step_by_id.get("ci")
if not ci_step:
    raise SystemExit("mol-change-request missing required step: ci")
if ci_step.get("type") != "gate":
    raise SystemExit("ci step must stay type=gate")
if (ci_step.get("gate") or {}).get("type") != "gh:run":
    raise SystemExit("ci step must stay gate.type=gh:run")

merge_step = step_by_id.get("merge")
if not merge_step:
    raise SystemExit("mol-change-request missing required step: merge")
merge_deps = merge_step.get("depends_on") or []
if sorted(merge_deps) != ["ci", "review_approval"]:
    raise SystemExit("merge step must depend on ci and review_approval")

if "merge_approval" in step_by_id:
    raise SystemExit("mol-change-request must not define merge_approval anymore")

for marker in (
    "name: CI/CD",
    "validate:",
    "deploy:",
    "needs: validate",
    "make verify-ci",
    "/srv/agentforge-demo",
    "docker compose up --build -d",
):
    if marker not in workflow_text:
        raise SystemExit(f".github/workflows/cicd.yml missing marker: {marker}")
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
