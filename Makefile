.PHONY: help verify-fast verify verify-ci lint-static lint-hygiene lint-contract test-unit

help:
	@printf '%s\n' \
		'verify-fast    quick local demo contour' \
		'verify         full local demo contour before handoff or review' \
		'verify-ci      CI-grade alias (currently mirrors verify)' \
		'lint-static    syntax and file-presence checks' \
		'lint-hygiene   placeholder marker checks' \
		'lint-contract  fixed runtime contract checks' \
		'test-unit      focused stdlib unit tests'

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
