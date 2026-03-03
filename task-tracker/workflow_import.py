from __future__ import annotations

import json
import uuid
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None


ALLOWED_STATUSES = {"backlog", "ready", "in_progress", "done"}
ALLOWED_GATE_TYPES = {"auto", "manual"}


class WorkflowImportError(ValueError):
    """Raised when a workflow TOML payload is invalid."""


def _require_string(value: Any, field_name: str, *, max_length: int = 120) -> str:
    if not isinstance(value, str):
        raise WorkflowImportError(f"{field_name} must be a string")

    trimmed = value.strip()
    if not trimmed:
        raise WorkflowImportError(f"{field_name} must not be empty")

    if len(trimmed) > max_length:
        raise WorkflowImportError(f"{field_name} exceeds max length {max_length}")

    return trimmed


def _normalize_transitions(raw_transitions: Any) -> list[dict[str, str]]:
    if not isinstance(raw_transitions, list) or not raw_transitions:
        raise WorkflowImportError("workflow must declare at least one transition")

    normalized: list[dict[str, str]] = []
    seen_pairs: set[tuple[str, str]] = set()

    for index, entry in enumerate(raw_transitions):
        if not isinstance(entry, dict):
            raise WorkflowImportError(f"transitions[{index}] must be a table")

        if "from_status" not in entry or "to_status" not in entry or "gate_type" not in entry:
            raise WorkflowImportError(
                f"transitions[{index}] must include from_status, to_status, and gate_type"
            )

        from_status = _require_string(entry["from_status"], "from_status")
        to_status = _require_string(entry["to_status"], "to_status")
        gate_type = _require_string(entry["gate_type"], "gate_type")

        if from_status not in ALLOWED_STATUSES:
            raise WorkflowImportError(f"invalid from_status: {from_status}")
        if to_status not in ALLOWED_STATUSES:
            raise WorkflowImportError(f"invalid to_status: {to_status}")
        if gate_type not in ALLOWED_GATE_TYPES:
            raise WorkflowImportError(f"invalid gate_type: {gate_type}")
        if from_status == to_status:
            raise WorkflowImportError("self transitions are not allowed")

        pair = (from_status, to_status)
        if pair in seen_pairs:
            raise WorkflowImportError(f"duplicate transition pair: {from_status}->{to_status}")
        seen_pairs.add(pair)

        normalized.append(
            {
                "from_status": from_status,
                "to_status": to_status,
                "gate_type": gate_type,
            }
        )

    return sorted(normalized, key=lambda item: (item["from_status"], item["to_status"]))


def parse_workflow_toml(workflow_toml: str) -> dict[str, Any]:
    if tomllib is None:
        raise RuntimeError("tomllib is not available")

    if not isinstance(workflow_toml, str):
        raise WorkflowImportError("workflow_toml must be a string")

    try:
        parsed = tomllib.loads(workflow_toml)
    except tomllib.TOMLDecodeError as exc:
        raise WorkflowImportError("invalid TOML payload") from exc

    if not isinstance(parsed, dict):
        raise WorkflowImportError("workflow TOML must parse into an object")

    transitions = _normalize_transitions(parsed.get("transitions"))
    return {"transitions": transitions}


def _normalized_definition_json(normalized_definition: dict[str, Any]) -> str:
    return json.dumps(normalized_definition, sort_keys=True, separators=(",", ":"))


def import_workflow(
    connection,
    project_key: str,
    workflow_toml: str,
    version_label: str | None = None,
) -> dict[str, Any]:
    project_key = _require_string(project_key, "project_key")
    normalized_definition = parse_workflow_toml(workflow_toml)
    normalized_json = _normalized_definition_json(normalized_definition)

    cursor = connection.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO projects (project_key)
            VALUES (%s)
            ON CONFLICT (project_key) DO NOTHING
            """,
            (project_key,),
        )

        cursor.execute(
            """
            SELECT id, version
            FROM workflow_versions
            WHERE project_key = %s
              AND normalized_definition = %s::jsonb
            ORDER BY version DESC
            LIMIT 1
            """,
            (project_key, normalized_json),
        )
        existing = cursor.fetchone()

        if existing is not None:
            workflow_version_id, version = existing
        else:
            cursor.execute(
                """
                SELECT COALESCE(MAX(version), 0)
                FROM workflow_versions
                WHERE project_key = %s
                """,
                (project_key,),
            )
            current_version_row = cursor.fetchone()
            next_version = int(current_version_row[0]) + 1
            workflow_version_id = str(uuid.uuid4())

            cursor.execute(
                """
                INSERT INTO workflow_versions (
                    id,
                    project_key,
                    version,
                    version_label,
                    source_toml,
                    normalized_definition
                )
                VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                """,
                (
                    workflow_version_id,
                    project_key,
                    next_version,
                    version_label,
                    workflow_toml,
                    normalized_json,
                ),
            )

            for transition in normalized_definition["transitions"]:
                cursor.execute(
                    """
                    INSERT INTO workflow_transition_gates (
                        workflow_version_id,
                        from_status,
                        to_status,
                        gate_type
                    )
                    VALUES (%s, %s, %s, %s)
                    """,
                    (
                        workflow_version_id,
                        transition["from_status"],
                        transition["to_status"],
                        transition["gate_type"],
                    ),
                )

            version = next_version

        cursor.execute(
            """
            UPDATE projects
            SET active_workflow_version_id = %s,
                updated_at = NOW()
            WHERE project_key = %s
            """,
            (workflow_version_id, project_key),
        )

        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()

    return {
        "workflow_version_id": workflow_version_id,
        "project_key": project_key,
        "version": int(version),
    }
