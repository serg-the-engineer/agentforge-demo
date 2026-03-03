CREATE TABLE IF NOT EXISTS projects (
    project_key TEXT PRIMARY KEY,
    active_workflow_version_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT projects_project_key_length CHECK (char_length(project_key) BETWEEN 1 AND 120)
);

CREATE TABLE IF NOT EXISTS workflow_versions (
    id UUID PRIMARY KEY,
    project_key TEXT NOT NULL REFERENCES projects(project_key) ON DELETE RESTRICT,
    version INTEGER NOT NULL,
    version_label VARCHAR(120),
    source_toml TEXT NOT NULL,
    normalized_definition JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT workflow_versions_version_positive CHECK (version > 0),
    CONSTRAINT workflow_versions_unique_per_project UNIQUE (project_key, version),
    CONSTRAINT workflow_versions_project_and_id_unique UNIQUE (project_key, id)
);

ALTER TABLE projects
    ADD CONSTRAINT projects_active_workflow_version_fkey
    FOREIGN KEY (active_workflow_version_id)
    REFERENCES workflow_versions(id)
    ON DELETE SET NULL;

CREATE TABLE IF NOT EXISTS workflow_transition_gates (
    id BIGSERIAL PRIMARY KEY,
    workflow_version_id UUID NOT NULL REFERENCES workflow_versions(id) ON DELETE CASCADE,
    from_status TEXT NOT NULL,
    to_status TEXT NOT NULL,
    gate_type TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT workflow_transition_gates_status_pair_unique
        UNIQUE (workflow_version_id, from_status, to_status),
    CONSTRAINT workflow_transition_gates_from_status_allowed
        CHECK (from_status IN ('backlog', 'ready', 'in_progress', 'done')),
    CONSTRAINT workflow_transition_gates_to_status_allowed
        CHECK (to_status IN ('backlog', 'ready', 'in_progress', 'done')),
    CONSTRAINT workflow_transition_gates_gate_type_allowed
        CHECK (gate_type IN ('auto', 'manual')),
    CONSTRAINT workflow_transition_gates_no_self_transition CHECK (from_status <> to_status)
);

CREATE TABLE IF NOT EXISTS tasks (
    id UUID PRIMARY KEY,
    project_key TEXT NOT NULL REFERENCES projects(project_key) ON DELETE RESTRICT,
    workflow_version_id UUID NOT NULL REFERENCES workflow_versions(id) ON DELETE RESTRICT,
    parent_task_id UUID,
    title VARCHAR(200) NOT NULL,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'backlog',
    priority INTEGER NOT NULL DEFAULT 50,
    assignee VARCHAR(120),
    result_summary TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    CONSTRAINT tasks_id_project_key_unique UNIQUE (id, project_key),
    CONSTRAINT tasks_title_length CHECK (char_length(title) BETWEEN 1 AND 200),
    CONSTRAINT tasks_description_length CHECK (description IS NULL OR char_length(description) <= 10000),
    CONSTRAINT tasks_status_allowed CHECK (status IN ('backlog', 'ready', 'in_progress', 'done')),
    CONSTRAINT tasks_priority_range CHECK (priority BETWEEN 0 AND 100),
    CONSTRAINT tasks_assignee_length CHECK (assignee IS NULL OR char_length(assignee) BETWEEN 1 AND 120),
    CONSTRAINT tasks_parent_not_self CHECK (parent_task_id IS NULL OR parent_task_id <> id),
    CONSTRAINT tasks_parent_same_project_fkey
        FOREIGN KEY (parent_task_id, project_key)
        REFERENCES tasks(id, project_key)
        ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS transition_attempts (
    id UUID PRIMARY KEY,
    task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    from_status TEXT NOT NULL,
    to_status TEXT NOT NULL,
    gate_type TEXT NOT NULL,
    status TEXT NOT NULL,
    reason TEXT,
    requested_by VARCHAR(120),
    requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_by VARCHAR(120),
    resolved_comment TEXT,
    resolved_at TIMESTAMPTZ,
    CONSTRAINT transition_attempts_from_status_allowed
        CHECK (from_status IN ('backlog', 'ready', 'in_progress', 'done')),
    CONSTRAINT transition_attempts_to_status_allowed
        CHECK (to_status IN ('backlog', 'ready', 'in_progress', 'done')),
    CONSTRAINT transition_attempts_gate_type_allowed CHECK (gate_type IN ('auto', 'manual')),
    CONSTRAINT transition_attempts_status_allowed CHECK (status IN ('pending', 'approved', 'rejected')),
    CONSTRAINT transition_attempts_reason_length CHECK (reason IS NULL OR char_length(reason) <= 500),
    CONSTRAINT transition_attempts_requested_by_length
        CHECK (requested_by IS NULL OR char_length(requested_by) BETWEEN 1 AND 120),
    CONSTRAINT transition_attempts_resolved_by_length
        CHECK (resolved_by IS NULL OR char_length(resolved_by) BETWEEN 1 AND 120),
    CONSTRAINT transition_attempts_resolution_state CHECK (
        (status = 'pending' AND resolved_at IS NULL AND resolved_by IS NULL AND resolved_comment IS NULL)
        OR (status = 'approved' AND resolved_at IS NOT NULL)
        OR (
            status = 'rejected'
            AND resolved_at IS NOT NULL
            AND resolved_comment IS NOT NULL
            AND char_length(resolved_comment) > 0
        )
    )
);

CREATE TABLE IF NOT EXISTS pauses (
    id UUID PRIMARY KEY,
    task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    pause_type TEXT NOT NULL,
    reason TEXT,
    details TEXT,
    question TEXT,
    requested_from VARCHAR(120),
    due_at TIMESTAMPTZ,
    opened_by VARCHAR(120),
    opened_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    closed_by VARCHAR(120),
    closed_comment TEXT,
    closed_at TIMESTAMPTZ,
    CONSTRAINT pauses_type_allowed CHECK (pause_type IN ('blocked', 'awaiting_input')),
    CONSTRAINT pauses_details_length CHECK (details IS NULL OR char_length(details) <= 5000),
    CONSTRAINT pauses_requested_from_length
        CHECK (requested_from IS NULL OR char_length(requested_from) BETWEEN 1 AND 120),
    CONSTRAINT pauses_opened_by_length CHECK (opened_by IS NULL OR char_length(opened_by) BETWEEN 1 AND 120),
    CONSTRAINT pauses_closed_by_length CHECK (closed_by IS NULL OR char_length(closed_by) BETWEEN 1 AND 120),
    CONSTRAINT pauses_blocked_shape CHECK (
        pause_type <> 'blocked' OR (
            reason IS NOT NULL
            AND char_length(reason) BETWEEN 1 AND 500
            AND question IS NULL
        )
    ),
    CONSTRAINT pauses_awaiting_input_shape CHECK (
        pause_type <> 'awaiting_input' OR (
            question IS NOT NULL
            AND char_length(question) BETWEEN 1 AND 1000
            AND reason IS NULL
        )
    )
);

CREATE TABLE IF NOT EXISTS pause_answers (
    id UUID PRIMARY KEY,
    pause_id UUID NOT NULL REFERENCES pauses(id) ON DELETE CASCADE,
    actor VARCHAR(120) NOT NULL,
    answer TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT pause_answers_actor_length CHECK (char_length(actor) BETWEEN 1 AND 120),
    CONSTRAINT pause_answers_answer_length CHECK (char_length(answer) BETWEEN 1 AND 5000)
);

CREATE TABLE IF NOT EXISTS events (
    cursor BIGSERIAL PRIMARY KEY,
    event_type TEXT NOT NULL,
    project_key TEXT NOT NULL REFERENCES projects(project_key) ON DELETE RESTRICT,
    task_id UUID REFERENCES tasks(id) ON DELETE SET NULL,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT events_event_type_length CHECK (char_length(event_type) BETWEEN 1 AND 120),
    CONSTRAINT events_payload_object CHECK (jsonb_typeof(payload) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_workflow_versions_project_created_at
    ON workflow_versions(project_key, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_workflow_transition_gates_lookup
    ON workflow_transition_gates(workflow_version_id, from_status, to_status);

CREATE INDEX IF NOT EXISTS idx_tasks_project_status_priority
    ON tasks(project_key, status, priority DESC, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_tasks_parent_task_id
    ON tasks(parent_task_id)
    WHERE parent_task_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_transition_attempts_task_requested_at
    ON transition_attempts(task_id, requested_at DESC);

CREATE INDEX IF NOT EXISTS idx_transition_attempts_pending
    ON transition_attempts(status, requested_at DESC)
    WHERE status = 'pending';

CREATE UNIQUE INDEX IF NOT EXISTS idx_transition_attempts_one_pending_per_task
    ON transition_attempts(task_id)
    WHERE status = 'pending';

CREATE UNIQUE INDEX IF NOT EXISTS idx_pauses_one_open_per_task
    ON pauses(task_id)
    WHERE closed_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_pauses_open_by_type
    ON pauses(pause_type, opened_at DESC)
    WHERE closed_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_pause_answers_pause_created_at
    ON pause_answers(pause_id, created_at ASC);

CREATE INDEX IF NOT EXISTS idx_events_project_cursor
    ON events(project_key, cursor DESC);

CREATE INDEX IF NOT EXISTS idx_events_task_cursor
    ON events(task_id, cursor DESC)
    WHERE task_id IS NOT NULL;
