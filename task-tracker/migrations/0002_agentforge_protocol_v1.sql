CREATE TABLE IF NOT EXISTS agentforge_idempotency (
    operation TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    response_status INTEGER,
    response_payload JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (operation, idempotency_key),
    CONSTRAINT agentforge_idempotency_operation_allowed
        CHECK (operation IN ('planned', 'done')),
    CONSTRAINT agentforge_idempotency_response_shape CHECK (
        (response_status IS NULL AND response_payload IS NULL)
        OR (
            response_status BETWEEN 100 AND 599
            AND response_payload IS NOT NULL
            AND jsonb_typeof(response_payload) = 'object'
        )
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_agentforge_idempotency_operation_key
    ON agentforge_idempotency(operation, idempotency_key);

CREATE TABLE IF NOT EXISTS agentforge_task_results (
    task_id UUID PRIMARY KEY REFERENCES tasks(id) ON DELETE CASCADE,
    outcome_status TEXT NOT NULL,
    attempts_used INTEGER NOT NULL,
    max_attempts INTEGER NOT NULL,
    summary TEXT,
    error_code VARCHAR(120),
    done_at TIMESTAMPTZ NOT NULL,
    connector_id VARCHAR(120) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT agentforge_task_results_outcome_status_allowed
        CHECK (outcome_status IN ('completed', 'failed', 'cancelled')),
    CONSTRAINT agentforge_task_results_attempts_used_non_negative
        CHECK (attempts_used >= 0),
    CONSTRAINT agentforge_task_results_max_attempts_positive
        CHECK (max_attempts > 0),
    CONSTRAINT agentforge_task_results_attempts_order
        CHECK (attempts_used <= max_attempts),
    CONSTRAINT agentforge_task_results_summary_length
        CHECK (summary IS NULL OR char_length(summary) <= 10000),
    CONSTRAINT agentforge_task_results_connector_length
        CHECK (char_length(connector_id) BETWEEN 1 AND 120)
);

CREATE INDEX IF NOT EXISTS idx_agentforge_task_results_done_at
    ON agentforge_task_results(done_at DESC);
