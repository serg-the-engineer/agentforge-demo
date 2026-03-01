#!/bin/sh
set -eu

host="${BEADS_SHARED_HOST:-127.0.0.1}"
port="${BEADS_SHARED_PORT:-3307}"
user="${BEADS_SHARED_USER:-root}"
attempts="${BEADS_INIT_ATTEMPTS:-1}"

export BEADS_DOLT_PASSWORD="${BEADS_DOLT_PASSWORD:-demo-agentforge-beads}"

need_init=1

if bd backend show >/dev/null 2>&1; then
	backend="$(bd backend show 2>/dev/null | sed -n 's/^Current backend: //p')"

	if [ "$backend" = "dolt" ]; then
		need_init=0
	elif [ "$backend" = "sqlite" ]; then
		count="$(bd count 2>/dev/null | tr -d '[:space:]')"

		if [ "${count:-0}" != "0" ]; then
			echo "refusing to replace a local sqlite beads database that still contains issues" >&2
			echo "clear or migrate .beads first if you need to reattach this checkout" >&2
			exit 1
		fi
	fi
fi

if [ "$need_init" = "1" ]; then
	attempt=1

	while :; do
		if bd init --force --backend dolt --server \
			--server-host "$host" \
			--server-port "$port" \
			--server-user "$user" \
			--skip-hooks \
			--skip-merge-driver >/dev/null 2>&1; then
			break
		fi

		if [ "$attempt" -ge "$attempts" ]; then
			echo "unable to attach this checkout to the shared Beads backend at $host:$port" >&2

			if [ "$host" = "127.0.0.1" ] || [ "$host" = "localhost" ]; then
				echo "if you are off-host, open an SSH tunnel to 127.0.0.1:$port on the demo host first" >&2
			else
				echo "check that the shared Beads backend service is reachable from this environment" >&2
			fi

			exit 1
		fi

		attempt=$((attempt + 1))
		sleep 1
	done
fi

mkdir -p .beads/formulas
cp -f beads/PRIME.md .beads/PRIME.md
cp -f beads/formulas/mol-change-request.formula.json .beads/formulas/mol-change-request.formula.json

bd formula list >/dev/null
