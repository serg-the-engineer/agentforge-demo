.PHONY: help task-tracker-migrate task-tracker-health task-tracker-snapshot verify-fast verify verify-ci lint-static lint-hygiene lint-contract test-unit

TASK_TRACKER_BASE_URL ?= http://127.0.0.1:9102
TASK_TRACKER_PROJECT_KEY ?= demo

help:
	@printf '%s\n' \
		'task-tracker-migrate  apply task-tracker database migrations via compose' \
		'task-tracker-health   check task-tracker health endpoint' \
		'task-tracker-snapshot fetch task-tracker snapshot for project key' \
		'verify-fast    quick local demo contour' \
		'verify         full local demo contour before handoff or review' \
		'verify-ci      CI-grade alias (currently mirrors verify)' \
		'lint-static    syntax and file-presence checks' \
		'lint-hygiene   placeholder marker checks' \
		'lint-contract  fixed runtime contract checks' \
		'test-unit      focused stdlib unit tests'

task-tracker-migrate:
	@docker compose run --rm task-tracker python /app/migrate.py

task-tracker-health:
	@curl -sS "$(TASK_TRACKER_BASE_URL)/healthz"

task-tracker-snapshot:
	@curl -sS "$(TASK_TRACKER_BASE_URL)/api/v1/ui/snapshot?project_key=$(TASK_TRACKER_PROJECT_KEY)"

verify-fast: lint-static lint-hygiene test-unit

verify: verify-fast lint-contract

verify-ci: verify

lint-static:
	@sh ./scripts/verify.sh static

lint-hygiene:
	@sh ./scripts/verify.sh hygiene

lint-contract:
	@sh ./scripts/verify.sh contract

test-unit:
	@sh ./scripts/verify.sh unit
