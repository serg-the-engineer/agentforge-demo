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
    "site/index.html",
    "site/assets/game.js",
    "site/assets/styles.css",
    "site/version.json",
    "docker-compose.yml",
    "nginx/default.conf",
    "AGENTS.md",
    "README.md",
    "Makefile",
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
    "\n  beads-ui:\n",
    'demo-agentforge-web',
    '"8081"',
    '"9001"',
    '"5433"',
    '"6380"',
):
    if marker not in compose_text:
        raise SystemExit(f"docker-compose.yml missing contract marker: {marker}")
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
