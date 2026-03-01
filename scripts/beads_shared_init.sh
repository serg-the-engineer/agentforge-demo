#!/bin/sh
set -eu

host="${BEADS_SHARED_HOST:-127.0.0.1}"
port="${BEADS_SHARED_PORT:-3307}"
user="${BEADS_SHARED_USER:-root}"
attempts="${BEADS_INIT_ATTEMPTS:-1}"

export BEADS_DOLT_PASSWORD="${BEADS_DOLT_PASSWORD:-demo-agentforge-beads}"

if ! command -v bd >/dev/null 2>&1; then
	echo "bd command is not available in this environment" >&2
	exit 1
fi

legacy_cli=0
if bd init --help 2>/dev/null | grep -q -- '--backend'; then
	legacy_cli=1
fi

if command -v git >/dev/null 2>&1; then
	if [ ! -d .git ]; then
		git init -q >/dev/null 2>&1 || true
	fi
elif [ "$legacy_cli" = "0" ]; then
	echo "git is required for bd init with this beads CLI version" >&2
	exit 1
fi

run_bd_init() {
	if [ "$legacy_cli" = "1" ]; then
		bd init --force --backend dolt --server \
			--server-host "$host" \
			--server-port "$port" \
			--server-user "$user" \
			--skip-hooks \
			--skip-merge-driver
	else
		bd init --force --server \
			--server-host "$host" \
			--server-port "$port" \
			--server-user "$user" \
			--skip-hooks
	fi
}

attempt=1
while :; do
	if run_bd_init >/dev/null 2>&1; then
		break
	fi

	if [ "$attempt" -ge "$attempts" ]; then
		echo "unable to attach this checkout to the shared Beads backend at $host:$port" >&2

		if [ "$host" = "127.0.0.1" ] || [ "$host" = "localhost" ]; then
			echo "if you are off-host, open an SSH tunnel to 127.0.0.1:$port on the demo host first" >&2
		else
			echo "check that the shared Beads backend service is reachable from this environment" >&2
		fi

		set +e
		run_bd_init
		status=$?
		set -e
		exit "$status"
	fi

	attempt=$((attempt + 1))
	sleep 1
done

mkdir -p .beads/formulas
cp -f beads/PRIME.md .beads/PRIME.md
cp -f beads/formulas/mol-change-request.formula.json .beads/formulas/mol-change-request.formula.json

current_custom_types="$(bd config get types.custom 2>/dev/null || true)"
normalized_custom_types="$(printf '%s' "$current_custom_types" | tr -d '[:space:]')"

case ",$normalized_custom_types," in
	*,gate,*)
		;;
	",,")
		bd config set types.custom gate >/dev/null
		;;
	*)
		bd config set types.custom "${normalized_custom_types},gate" >/dev/null
		;;
esac

bd formula list >/dev/null
