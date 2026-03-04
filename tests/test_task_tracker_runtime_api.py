import importlib.util
import json
import pathlib
import threading
import unittest
import uuid
from http import HTTPStatus
from urllib import error, request


ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "task-tracker" / "server.py"
MODULE_SOURCE = MODULE_PATH.read_text(encoding="utf-8")


class FakePostgresRuntimeStore:
    def __init__(self):
        self.tasks = {}
        self.transition_attempts = {}
        self.pauses = {}
        self.pause_answers = {}
        self.events = []
        self._clock = 0
        self._event_cursor = 0
        self._lock = threading.RLock()
        self.transition_gates = {
            ("backlog", "ready"): "auto",
            ("ready", "in_progress"): "auto",
            ("in_progress", "done"): "auto",
            ("in_progress", "ready"): "auto",
            ("ready", "backlog"): "auto",
        }

    def _next_timestamp(self):
        self._clock += 1
        return f"2026-03-03T00:00:{self._clock:02d}Z"

    def reset(self):
        self.tasks = {}
        self.transition_attempts = {}
        self.pauses = {}
        self.pause_answers = {}
        self.events = []
        self._clock = 0
        self._event_cursor = 0

    def _emit_event(self, event_type, project_key, task_id, payload):
        self._event_cursor += 1
        event = {
            "cursor": self._event_cursor,
            "event_type": event_type,
            "project_key": project_key,
            "task_id": task_id,
            "occurred_at": self._next_timestamp(),
            "payload": dict(payload or {}),
        }
        self.events.append(event)
        return dict(event)

    def create_task(self, task):
        created = dict(task)
        created["updated_at"] = self._next_timestamp()
        self.tasks[task["id"]] = created
        self._emit_event("task.created", created["project_key"], created["id"], {})
        return dict(self.tasks[task["id"]])

    def get_task(self, task_id):
        task = self.tasks.get(task_id)
        if task is None:
            return None
        return dict(task)

    def update_task(self, task_id, changes):
        task = self.tasks.get(task_id)
        if task is None:
            return None

        task.update(changes)
        task["updated_at"] = self._next_timestamp()
        if changes:
            event_type = "task.updated"
            change_keys = set(changes.keys())
            if "summary" in change_keys:
                event_type = "task.result_reported"
            elif change_keys == {"assignee"}:
                event_type = "task.claimed"
            self._emit_event(event_type, task["project_key"], task_id, {"changes": changes})
        return dict(task)

    def _active_pause_for_task(self, task_id):
        for pause in self.pauses.values():
            if pause["task_id"] == task_id and pause["closed_at"] is None:
                return pause
        return None

    def create_pause(self, task_id, pause_type, payload):
        task = self.tasks.get(task_id)
        if task is None:
            return None
        if task["status"] == "done":
            return {"error": "task_done"}
        if self._active_pause_for_task(task_id) is not None:
            return {"error": "pause_exists"}

        pause_id = str(uuid.uuid4())
        pause = {
            "id": pause_id,
            "task_id": task_id,
            "pause_type": pause_type,
            "reason": payload.get("reason"),
            "details": payload.get("details"),
            "question": payload.get("question"),
            "requested_from": payload.get("requested_from"),
            "due_at": payload.get("due_at"),
            "opened_by": payload.get("actor"),
            "closed_by": None,
            "closed_comment": None,
            "closed_at": None,
        }
        self.pauses[pause_id] = pause
        task["updated_at"] = self._next_timestamp()
        self._emit_event(
            "pause.opened",
            task["project_key"],
            task_id,
            {"pause_id": pause_id, "pause_type": pause_type},
        )
        return dict(pause)

    def get_pause(self, pause_id):
        pause = self.pauses.get(pause_id)
        if pause is None:
            return None
        return dict(pause)

    def add_pause_answer(self, pause_id, actor, answer):
        pause = self.pauses.get(pause_id)
        if pause is None:
            return None
        if pause["closed_at"] is not None:
            return {"error": "pause_closed"}

        answer_id = str(uuid.uuid4())
        record = {
            "id": answer_id,
            "pause_id": pause_id,
            "actor": actor,
            "answer": answer,
        }
        self.pause_answers.setdefault(pause_id, []).append(record)
        task = self.tasks.get(pause["task_id"])
        if task is not None:
            task["updated_at"] = self._next_timestamp()
            self._emit_event(
                "pause.answered",
                task["project_key"],
                pause["task_id"],
                {"pause_id": pause_id, "answer_id": answer_id},
            )
        return dict(record)

    def resume_pause(self, pause_id, actor, comment=None):
        pause = self.pauses.get(pause_id)
        if pause is None:
            return None
        if pause["closed_at"] is not None:
            return {"error": "already_resolved", "pause": dict(pause)}
        if pause["pause_type"] == "awaiting_input" and not self.pause_answers.get(pause_id):
            return {"error": "answers_required"}

        pause["closed_at"] = "closed"
        pause["closed_by"] = actor
        pause["closed_comment"] = comment
        task = self.tasks.get(pause["task_id"])
        if task is not None:
            task["updated_at"] = self._next_timestamp()
            self._emit_event(
                "pause.resumed",
                task["project_key"],
                pause["task_id"],
                {"pause_id": pause_id, "auto_closed": False},
            )
        return dict(pause)

    def set_transition_gate(self, from_status, to_status, gate_type):
        with self._lock:
            self.transition_gates[(from_status, to_status)] = gate_type

    def request_transition(self, task_id, target_status, reason=None, requested_by=None):
        with self._lock:
            task = self.tasks.get(task_id)
            if task is None:
                return None
            from_status = task["status"]
            gate_type = self.transition_gates.get((from_status, target_status))
            if gate_type is None:
                return {"error": "invalid_transition"}

            for pending_attempt in self.transition_attempts.values():
                if pending_attempt["task_id"] == task_id and pending_attempt["status"] == "pending":
                    return {
                        "error": "pending_transition_exists",
                        "attempt": dict(pending_attempt),
                        "task": dict(task),
                    }

            attempt_id = str(uuid.uuid4())
            attempt = {
                "id": attempt_id,
                "task_id": task_id,
                "from_status": from_status,
                "to_status": target_status,
                "gate_type": gate_type,
                "status": "pending" if gate_type == "manual" else "approved",
                "reason": reason,
                "requested_by": requested_by,
                "resolved_by": None,
                "resolved_comment": None,
            }
            closed_pause_id = None

            if gate_type == "auto":
                task["status"] = target_status
                task["updated_at"] = self._next_timestamp()
                attempt["resolved_by"] = requested_by
                if target_status == "done":
                    active_pause = self._active_pause_for_task(task_id)
                    if active_pause is not None:
                        active_pause["closed_at"] = "closed"
                        active_pause["closed_by"] = requested_by
                        closed_pause_id = active_pause["id"]

            self.transition_attempts[attempt_id] = attempt
            self._emit_event(
                "transition.requested",
                task["project_key"],
                task_id,
                {
                    "transition_attempt_id": attempt_id,
                    "from_status": from_status,
                    "to_status": target_status,
                    "gate_type": gate_type,
                },
            )
            if gate_type == "auto":
                self._emit_event(
                    "transition.approved",
                    task["project_key"],
                    task_id,
                    {"transition_attempt_id": attempt_id},
                )
                if closed_pause_id is not None:
                    self._emit_event(
                        "pause.resumed",
                        task["project_key"],
                        task_id,
                        {"pause_id": closed_pause_id, "auto_closed": True},
                    )
                if target_status == "done":
                    self._emit_event("task.completed", task["project_key"], task_id, {})
            return {"attempt": dict(attempt), "task": dict(task)}

    def get_transition_attempt(self, attempt_id):
        attempt = self.transition_attempts.get(attempt_id)
        if attempt is None:
            return None
        return dict(attempt)

    def resolve_transition_attempt(self, attempt_id, decision, actor, comment=None):
        with self._lock:
            attempt = self.transition_attempts.get(attempt_id)
            if attempt is None:
                return None
            if attempt["status"] != "pending":
                return {"error": "already_resolved", "attempt": dict(attempt)}

            task = self.tasks[attempt["task_id"]]
            if task["status"] != attempt["from_status"]:
                return {
                    "error": "stale_transition",
                    "attempt": dict(attempt),
                    "task": dict(task),
                }

            attempt["status"] = "approved" if decision == "approve" else "rejected"
            attempt["resolved_by"] = actor
            attempt["resolved_comment"] = comment
            if decision == "approve":
                task["status"] = attempt["to_status"]
                task["updated_at"] = self._next_timestamp()
                closed_pause_id = None
                if attempt["to_status"] == "done":
                    active_pause = self._active_pause_for_task(attempt["task_id"])
                    if active_pause is not None:
                        active_pause["closed_at"] = "closed"
                        active_pause["closed_by"] = actor
                        closed_pause_id = active_pause["id"]
                self._emit_event(
                    "transition.approved",
                    task["project_key"],
                    attempt["task_id"],
                    {"transition_attempt_id": attempt_id},
                )
                if closed_pause_id is not None:
                    self._emit_event(
                        "pause.resumed",
                        task["project_key"],
                        attempt["task_id"],
                        {"pause_id": closed_pause_id, "auto_closed": True},
                    )
                if attempt["to_status"] == "done":
                    self._emit_event("task.completed", task["project_key"], attempt["task_id"], {})
                return {"attempt": dict(attempt), "task": dict(task)}

            self._emit_event(
                "transition.rejected",
                task["project_key"],
                attempt["task_id"],
                {"transition_attempt_id": attempt_id},
            )
            return {"attempt": dict(attempt), "task": dict(self.tasks[attempt["task_id"]])}

    def get_attention_queues(self, project_key):
        bucket_names = (
            "pending_approval",
            "awaiting_input",
            "blocked",
            "ready_unclaimed",
            "in_progress",
            "done_recent",
        )
        queues = {
            name: {
                "count": 0,
                "tasks": [],
            }
            for name in bucket_names
        }

        for task in self.tasks.values():
            if task.get("project_key") != project_key:
                continue

            pause = self._active_pause_for_task(task["id"])
            pause_type = pause["pause_type"] if pause is not None else None
            has_pending_approval = any(
                attempt.get("task_id") == task["id"] and attempt.get("status") == "pending"
                for attempt in self.transition_attempts.values()
            )

            status = task.get("status")
            if has_pending_approval:
                bucket = "pending_approval"
            elif pause_type == "awaiting_input":
                bucket = "awaiting_input"
            elif pause_type == "blocked":
                bucket = "blocked"
            elif status == "ready" and not task.get("assignee"):
                bucket = "ready_unclaimed"
            elif status == "in_progress":
                bucket = "in_progress"
            elif status == "done":
                bucket = "done_recent"
            else:
                continue

            priority_score = int(task.get("priority") or 0)
            if has_pending_approval:
                priority_score += 100
            elif pause_type == "awaiting_input":
                priority_score += 80
            elif pause_type == "blocked":
                priority_score += 60
            elif status == "ready" and not task.get("assignee"):
                priority_score += 40
            elif status == "in_progress":
                priority_score += 20

            queues[bucket]["tasks"].append(
                {
                    "task_id": task["id"],
                    "title": task["title"],
                    "status": status,
                    "pause_type": pause_type,
                    "priority_score": priority_score,
                    "updated_at": task.get("updated_at"),
                    "closable": bool(
                        status == "in_progress"
                        and pause_type is None
                        and not has_pending_approval
                    ),
                }
            )

        for queue in queues.values():
            queue["tasks"].sort(
                key=lambda item: (
                    item["priority_score"],
                    item.get("updated_at") or "",
                    item["task_id"],
                ),
                reverse=True,
            )
            queue["count"] = len(queue["tasks"])

        return queues

    def get_ui_snapshot(self, project_key):
        tasks = [
            {
                "id": task["id"],
                "project_key": task["project_key"],
                "parent_task_id": task.get("parent_task_id"),
                "title": task["title"],
                "description": task.get("description"),
                "status": task["status"],
                "priority": task["priority"],
                "assignee": task.get("assignee"),
                "summary": task.get("summary"),
                "artifacts": list(task.get("artifacts") or []),
                "updated_at": task.get("updated_at"),
            }
            for task in self.tasks.values()
            if task.get("project_key") == project_key
        ]
        tasks.sort(
            key=lambda item: (
                item["priority"],
                item.get("updated_at") or "",
                item["id"],
            ),
            reverse=True,
        )

        pending_transitions = [
            {
                "id": attempt["id"],
                "task_id": attempt["task_id"],
                "from_status": attempt["from_status"],
                "to_status": attempt["to_status"],
                "gate_type": attempt["gate_type"],
                "status": attempt["status"],
                "reason": attempt.get("reason"),
                "requested_by": attempt.get("requested_by"),
                "resolved_by": attempt.get("resolved_by"),
                "resolved_comment": attempt.get("resolved_comment"),
            }
            for attempt in self.transition_attempts.values()
            if attempt["status"] == "pending"
            and self.tasks.get(attempt["task_id"], {}).get("project_key") == project_key
        ]
        pending_transitions.sort(key=lambda item: item["id"])

        open_pauses = [
            {
                "id": pause["id"],
                "task_id": pause["task_id"],
                "pause_type": pause["pause_type"],
                "reason": pause.get("reason"),
                "details": pause.get("details"),
                "question": pause.get("question"),
                "requested_from": pause.get("requested_from"),
                "due_at": pause.get("due_at"),
                "opened_by": pause.get("opened_by"),
                "closed_by": pause.get("closed_by"),
                "closed_comment": pause.get("closed_comment"),
                "closed_at": pause.get("closed_at"),
            }
            for pause in self.pauses.values()
            if pause["closed_at"] is None
            and self.tasks.get(pause["task_id"], {}).get("project_key") == project_key
        ]
        open_pauses.sort(key=lambda item: item["id"])

        return {
            "cursor": self._event_cursor,
            "queues": self.get_attention_queues(project_key),
            "tasks": tasks,
            "pending_transitions": pending_transitions,
            "open_pauses": open_pauses,
        }

    def get_events_since(self, cursor, limit=200):
        events = [event for event in self.events if event["cursor"] > cursor]
        return [dict(event) for event in events[:limit]]


def load_server_module():
    if not MODULE_PATH.is_file():
        raise RuntimeError(f"missing required file: {MODULE_PATH}")

    spec = importlib.util.spec_from_file_location(
        "demo_agentforge_task_tracker_runtime_server",
        MODULE_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module from {MODULE_PATH}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TaskTrackerRuntimeApiTests(unittest.TestCase):
    def setUp(self):
        self.server = load_server_module()
        self.store = FakePostgresRuntimeStore()
        self.server.set_runtime_store(self.store)
        self.server.reset_runtime_store()

    def _create_task(self, **overrides):
        payload = {"project_key": "project-a", "title": "Demo task"}
        payload.update(overrides)
        status, response = self.server.create_task(payload)

        self.assertEqual(201, int(status))
        return response["task"]

    def test_runtime_uses_postgres_hook_points(self):
        self.assertTrue(hasattr(self.server, "PostgresTaskStore"))
        self.assertTrue(hasattr(self.server, "set_runtime_store"))
        self.assertTrue(hasattr(self.server, "reset_runtime_store"))
        self.assertTrue(hasattr(self.server, "get_runtime_store"))
        self.assertFalse(hasattr(self.server, "_STORE"))
        self.assertNotIn("runtime_tasks", MODULE_SOURCE)

    def test_create_task_and_get_task_project_key_contract(self):
        created = self._create_task(description="Task details", priority=70)

        self.assertIsInstance(uuid.UUID(created["id"]), uuid.UUID)
        self.assertEqual("project-a", created["project_key"])
        self.assertEqual("Task details", created["description"])
        self.assertEqual(70, created["priority"])
        self.assertEqual("backlog", created["status"])

        status, response = self.server.get_task(created["id"])

        self.assertEqual(200, int(status))
        self.assertEqual(created["id"], response["task"]["id"])
        self.assertEqual("project-a", response["task"]["project_key"])
        self.assertEqual("Demo task", response["task"]["title"])
        self.assertEqual("Task details", response["task"]["description"])
        self.assertEqual(70, response["task"]["priority"])

    def test_create_task_rejects_legacy_project_id(self):
        status, response = self.server.create_task(
            {"project_id": "project-a", "title": "Demo task"}
        )

        self.assertEqual(400, int(status))
        self.assertEqual("invalid_request", response["error"]["code"])

    def test_patch_task_cannot_update_status(self):
        created = self._create_task()
        self.store.update_task(created["id"], {"status": "ready"})

        status, response = self.server.patch_task(
            created["id"],
            {
                "title": "Updated title",
                "status": "in_progress",
                "assignee": "alice",
            },
        )

        self.assertEqual(400, int(status))
        self.assertEqual("invalid_request", response["error"]["code"])

        get_status, get_response = self.server.get_task(created["id"])
        self.assertEqual(200, int(get_status))
        self.assertEqual("ready", get_response["task"]["status"])

    def test_create_child_task_uses_parent_project_key(self):
        parent = self._create_task(project_key="project-parent")

        status, response = self.server.create_child_task(
            parent["id"],
            {
                "project_key": "different-project",
                "title": "Child task",
                "description": "child description",
                "priority": 90,
            },
        )

        self.assertEqual(201, int(status))
        self.assertEqual(parent["id"], response["task"]["parent_task_id"])
        self.assertEqual("project-parent", response["task"]["project_key"])
        self.assertEqual("Child task", response["task"]["title"])
        self.assertEqual("child description", response["task"]["description"])
        self.assertEqual(90, response["task"]["priority"])

    def test_claim_task_sets_assignee(self):
        created = self._create_task()

        status, response = self.server.claim_task(created["id"], {"assignee": "bob"})

        self.assertEqual(200, int(status))
        self.assertEqual("bob", response["task"]["assignee"])

    def test_start_work_ready_to_in_progress_only(self):
        ready_task = self._create_task()
        self.store.update_task(ready_task["id"], {"status": "ready"})
        status, response = self.server.start_work(ready_task["id"])

        self.assertEqual(200, int(status))
        self.assertEqual("in_progress", response["task"]["status"])

        backlog_task = self._create_task(status="backlog")
        status, response = self.server.start_work(backlog_task["id"])

        self.assertEqual(409, int(status))
        self.assertEqual("invalid_transition", response["error"]["code"])

    def test_transition_request_auto_gate_applies_status(self):
        task = self._create_task()
        status, response = self.server.request_transition(
            task["id"], {"target_status": "ready", "reason": "triage complete"}
        )

        self.assertEqual(200, int(status))
        self.assertEqual("approved", response["transition_attempt"]["status"])
        self.assertEqual("ready", response["task"]["status"])

        attempt_id = response["transition_attempt"]["id"]
        get_status, get_response = self.server.get_transition_attempt(attempt_id)
        self.assertEqual(200, int(get_status))
        self.assertEqual("approved", get_response["transition_attempt"]["status"])

    def test_transition_request_manual_gate_and_approval_flow(self):
        task = self._create_task()
        self.store.set_transition_gate("backlog", "ready", "manual")

        status, response = self.server.request_transition(
            task["id"], {"target_status": "ready", "reason": "triage complete"}
        )
        self.assertEqual(202, int(status))
        self.assertEqual("pending", response["transition_attempt"]["status"])
        self.assertEqual("backlog", response["task"]["status"])

        attempt_id = response["transition_attempt"]["id"]
        approve_status, approve_response = self.server.approve_transition_attempt(
            attempt_id, {"actor": "reviewer-1", "comment": "approved"}
        )
        self.assertEqual(200, int(approve_status))
        self.assertEqual("approved", approve_response["transition_attempt"]["status"])
        self.assertEqual("ready", approve_response["task"]["status"])

    def test_transition_request_rejects_when_pending_attempt_exists(self):
        task = self._create_task()
        self.store.set_transition_gate("backlog", "ready", "manual")

        first_status, first_response = self.server.request_transition(
            task["id"], {"target_status": "ready", "reason": "first request"}
        )
        self.assertEqual(202, int(first_status))
        first_attempt_id = first_response["transition_attempt"]["id"]

        second_status, second_response = self.server.request_transition(
            task["id"], {"target_status": "ready", "reason": "duplicate request"}
        )
        self.assertEqual(409, int(second_status))
        self.assertEqual("pending_transition_exists", second_response["error"]["code"])
        self.assertEqual(
            first_attempt_id,
            second_response["transition_attempt"]["id"],
        )
        self.assertEqual(task["id"], second_response["transition_attempt"]["task_id"])

    def test_transition_approval_rejects_stale_attempt(self):
        task = self._create_task()
        self.store.set_transition_gate("backlog", "ready", "manual")

        request_status, request_response = self.server.request_transition(
            task["id"], {"target_status": "ready", "reason": "manual review"}
        )
        self.assertEqual(202, int(request_status))
        attempt_id = request_response["transition_attempt"]["id"]

        self.store.update_task(task["id"], {"status": "ready"})
        approve_status, approve_response = self.server.approve_transition_attempt(
            attempt_id,
            {"actor": "reviewer-1"},
        )
        self.assertEqual(409, int(approve_status))
        self.assertEqual("stale_transition", approve_response["error"]["code"])
        self.assertEqual(task["id"], approve_response["transition_attempt"]["task_id"])

    def test_reject_transition_requires_comment_and_is_final(self):
        task = self._create_task()
        self.store.set_transition_gate("backlog", "ready", "manual")
        status, response = self.server.request_transition(
            task["id"], {"target_status": "ready"}
        )
        self.assertEqual(202, int(status))
        attempt_id = response["transition_attempt"]["id"]

        bad_status, bad_response = self.server.reject_transition_attempt(
            attempt_id, {"actor": "reviewer-1", "comment": ""}
        )
        self.assertEqual(400, int(bad_status))
        self.assertEqual("invalid_request", bad_response["error"]["code"])

        reject_status, reject_response = self.server.reject_transition_attempt(
            attempt_id, {"actor": "reviewer-1", "comment": "missing details"}
        )
        self.assertEqual(200, int(reject_status))
        self.assertEqual("rejected", reject_response["transition_attempt"]["status"])
        self.assertEqual("backlog", reject_response["task"]["status"])

        approve_status, approve_response = self.server.approve_transition_attempt(
            attempt_id, {"actor": "reviewer-2"}
        )
        self.assertEqual(409, int(approve_status))
        self.assertEqual("already_resolved", approve_response["error"]["code"])

    def test_report_result_stores_summary_and_artifacts(self):
        created = self._create_task(status="in_progress")
        artifacts = [{"name": "demo-log", "url": "https://example.com/log"}]

        status, response = self.server.report_result(
            created["id"],
            {"summary": "completed successfully", "artifacts": artifacts},
        )

        self.assertEqual(200, int(status))
        self.assertEqual("completed successfully", response["task"]["summary"])
        self.assertEqual(artifacts, response["task"]["artifacts"])

        get_status, get_response = self.server.get_task(created["id"])
        self.assertEqual(200, int(get_status))
        self.assertEqual("completed successfully", get_response["task"]["summary"])
        self.assertEqual(artifacts, get_response["task"]["artifacts"])

    def test_blocked_pause_lifecycle(self):
        created = self._create_task(status="in_progress")
        status, response = self.server.open_blocked_pause(
            created["id"],
            {"reason": "dependency unavailable", "details": "waiting on service-a"},
        )

        self.assertEqual(201, int(status))
        pause_id = response["pause"]["id"]
        self.assertEqual("blocked", response["pause"]["pause_type"])

        conflict_status, conflict_response = self.server.open_awaiting_input_pause(
            created["id"],
            {"question": "Need reviewer signoff?"},
        )
        self.assertEqual(409, int(conflict_status))
        self.assertEqual("pause_already_open", conflict_response["error"]["code"])

        resume_status, resume_response = self.server.resume_pause(
            pause_id, {"actor": "reviewer-1", "comment": "unblocked"}
        )
        self.assertEqual(200, int(resume_status))
        self.assertIsNotNone(resume_response["pause"]["closed_by"])

    def test_awaiting_input_pause_requires_answer_before_resume(self):
        created = self._create_task(status="ready")
        status, response = self.server.open_awaiting_input_pause(
            created["id"],
            {"question": "Which region should we deploy?"},
        )
        self.assertEqual(201, int(status))
        pause_id = response["pause"]["id"]

        early_resume_status, early_resume_response = self.server.resume_pause(
            pause_id, {"actor": "reviewer-1"}
        )
        self.assertEqual(409, int(early_resume_status))
        self.assertEqual("answers_required", early_resume_response["error"]["code"])

        answer_status, answer_response = self.server.answer_pause(
            pause_id,
            {"actor": "ops-user", "answer": "use us-east-1"},
        )
        self.assertEqual(201, int(answer_status))
        self.assertEqual("ops-user", answer_response["answer"]["actor"])

        resume_status, resume_response = self.server.resume_pause(
            pause_id, {"actor": "reviewer-1"}
        )
        self.assertEqual(200, int(resume_status))
        self.assertEqual("reviewer-1", resume_response["pause"]["closed_by"])

    def test_done_task_rejects_new_pause_and_done_transition_auto_closes_pause(self):
        done_task = self._create_task()
        self.store.update_task(done_task["id"], {"status": "done"})
        reject_status, reject_response = self.server.open_blocked_pause(
            done_task["id"],
            {"reason": "should fail"},
        )
        self.assertEqual(409, int(reject_status))
        self.assertEqual("invalid_state", reject_response["error"]["code"])

        active = self._create_task()
        self.store.update_task(active["id"], {"status": "in_progress"})
        blocked_status, blocked_response = self.server.open_blocked_pause(
            active["id"],
            {"reason": "waiting external input"},
        )
        self.assertEqual(201, int(blocked_status))
        pause_id = blocked_response["pause"]["id"]

        transition_status, _ = self.server.request_transition(
            active["id"], {"target_status": "done", "actor": "agent-1"}
        )
        self.assertEqual(200, int(transition_status))

        pause = self.store.get_pause(pause_id)
        self.assertIsNotNone(pause["closed_at"])

    def test_attention_queues_group_tasks_by_bucket_with_score_and_closable(self):
        pending = self._create_task(title="Pending approval", priority=65)
        self.store.set_transition_gate("backlog", "ready", "manual")
        pending_status, _ = self.server.request_transition(
            pending["id"], {"target_status": "ready", "reason": "triage ready"}
        )
        self.assertEqual(202, int(pending_status))

        awaiting = self._create_task(title="Awaiting input", priority=50)
        self.store.update_task(awaiting["id"], {"status": "ready"})
        awaiting_status, _ = self.server.open_awaiting_input_pause(
            awaiting["id"], {"question": "Pick a region"}
        )
        self.assertEqual(201, int(awaiting_status))

        blocked = self._create_task(title="Blocked task", priority=40)
        self.store.update_task(blocked["id"], {"status": "in_progress"})
        blocked_status, _ = self.server.open_blocked_pause(
            blocked["id"], {"reason": "dependency unavailable"}
        )
        self.assertEqual(201, int(blocked_status))

        ready = self._create_task(title="Ready unclaimed", priority=30)
        self.store.update_task(ready["id"], {"status": "ready"})

        active = self._create_task(title="Active task", priority=25, assignee="agent-1")
        self.store.update_task(active["id"], {"status": "in_progress"})

        done = self._create_task(title="Done task", priority=20)
        self.store.update_task(done["id"], {"status": "done"})

        self._create_task(
            project_key="other-project",
            title="Other project task",
            priority=100,
        )

        status, response = self.server.get_attention_queues("project-a")
        self.assertEqual(200, int(status))
        queues = response["queues"]

        self.assertEqual(1, queues["pending_approval"]["count"])
        self.assertEqual(pending["id"], queues["pending_approval"]["tasks"][0]["task_id"])
        self.assertFalse(queues["pending_approval"]["tasks"][0]["closable"])

        self.assertEqual(1, queues["awaiting_input"]["count"])
        self.assertEqual(awaiting["id"], queues["awaiting_input"]["tasks"][0]["task_id"])
        self.assertEqual(
            "awaiting_input",
            queues["awaiting_input"]["tasks"][0]["pause_type"],
        )

        self.assertEqual(1, queues["blocked"]["count"])
        self.assertEqual(blocked["id"], queues["blocked"]["tasks"][0]["task_id"])
        self.assertEqual("blocked", queues["blocked"]["tasks"][0]["pause_type"])

        self.assertEqual(1, queues["ready_unclaimed"]["count"])
        self.assertEqual(ready["id"], queues["ready_unclaimed"]["tasks"][0]["task_id"])

        self.assertEqual(1, queues["in_progress"]["count"])
        in_progress_summary = queues["in_progress"]["tasks"][0]
        self.assertEqual(active["id"], in_progress_summary["task_id"])
        self.assertTrue(in_progress_summary["closable"])
        self.assertGreater(in_progress_summary["priority_score"], 25)

        self.assertEqual(1, queues["done_recent"]["count"])
        self.assertEqual(done["id"], queues["done_recent"]["tasks"][0]["task_id"])
        self.assertFalse(queues["done_recent"]["tasks"][0]["closable"])

    def test_attention_queues_requires_project_key(self):
        status, response = self.server.route_get("/api/v1/queues/attention")
        self.assertEqual(400, int(status))
        self.assertEqual("invalid_request", response["error"]["code"])

    def test_ui_snapshot_returns_project_scoped_state_and_cursor(self):
        pending = self._create_task(title="Pending transition")
        self.store.set_transition_gate("backlog", "ready", "manual")
        pending_status, _ = self.server.request_transition(
            pending["id"], {"target_status": "ready"}
        )
        self.assertEqual(202, int(pending_status))

        paused = self._create_task(title="Paused task")
        self.store.update_task(paused["id"], {"status": "ready"})
        pause_status, _ = self.server.open_awaiting_input_pause(
            paused["id"], {"question": "Need human answer?"}
        )
        self.assertEqual(201, int(pause_status))

        other_project = self._create_task(project_key="other-project", title="Ignore me")

        status, response = self.server.route_get("/api/v1/ui/snapshot?project_key=project-a")
        self.assertEqual(200, int(status))
        self.assertIsInstance(response["cursor"], int)
        self.assertGreater(response["cursor"], 0)
        self.assertIn("queues", response)
        self.assertIn("tasks", response)
        self.assertIn("pending_transitions", response)
        self.assertIn("open_pauses", response)

        task_ids = {task["id"] for task in response["tasks"]}
        self.assertIn(pending["id"], task_ids)
        self.assertIn(paused["id"], task_ids)
        self.assertNotIn(other_project["id"], task_ids)

        self.assertEqual(1, len(response["pending_transitions"]))
        self.assertEqual(pending["id"], response["pending_transitions"][0]["task_id"])
        self.assertEqual(1, len(response["open_pauses"]))
        self.assertEqual(paused["id"], response["open_pauses"][0]["task_id"])

    def test_ui_snapshot_requires_project_key(self):
        status, response = self.server.route_get("/api/v1/ui/snapshot")
        self.assertEqual(400, int(status))
        self.assertEqual("invalid_request", response["error"]["code"])

    def test_ui_updates_returns_events_after_cursor(self):
        initial_cursor = self.store._event_cursor
        self._create_task()

        status, response = self.server.route_get(
            f"/api/v1/ui/updates?cursor={initial_cursor}&timeout=1"
        )
        self.assertEqual(200, int(status))
        self.assertGreaterEqual(len(response["events"]), 1)
        self.assertGreater(response["cursor"], initial_cursor)
        self.assertEqual(response["cursor"], response["events"][-1]["cursor"])
        self.assertEqual("task.created", response["events"][0]["event_type"])

    def test_ui_updates_timeout_returns_empty_event_list(self):
        status, response = self.server.route_get("/api/v1/ui/updates?cursor=0&timeout=1")
        self.assertEqual(200, int(status))
        self.assertEqual(0, response["cursor"])
        self.assertEqual([], response["events"])

    def test_ui_updates_requires_valid_cursor_and_timeout(self):
        status, response = self.server.route_get("/api/v1/ui/updates")
        self.assertEqual(400, int(status))
        self.assertEqual("invalid_request", response["error"]["code"])

        status, response = self.server.route_get("/api/v1/ui/updates?cursor=-1")
        self.assertEqual(400, int(status))
        self.assertEqual("invalid_request", response["error"]["code"])

        status, response = self.server.route_get("/api/v1/ui/updates?cursor=0&timeout=0")
        self.assertEqual(400, int(status))
        self.assertEqual("invalid_request", response["error"]["code"])


class TaskTrackerRuntimeHttpApiTests(unittest.TestCase):
    def setUp(self):
        self.server = load_server_module()
        self.store = FakePostgresRuntimeStore()
        self.server.set_runtime_store(self.store)
        self.server.reset_runtime_store()

        try:
            self.httpd = self.server.create_server("127.0.0.1", 0)
        except PermissionError as exc:
            self.skipTest(f"socket bind unavailable in this environment: {exc}")
        sockname = self.httpd.socket.getsockname()
        self.base_url = f"http://127.0.0.1:{sockname[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)

    def _request(self, method, path, payload=None):
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = request.Request(
            f"{self.base_url}{path}", data=data, headers=headers, method=method
        )

        try:
            with request.urlopen(req) as response:
                body = response.read().decode("utf-8")
                return response.getcode(), json.loads(body)
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8")
            return exc.code, json.loads(body)

    def _request_raw(self, method, path, payload=None):
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = request.Request(
            f"{self.base_url}{path}", data=data, headers=headers, method=method
        )

        try:
            with request.urlopen(req) as response:
                body = response.read().decode("utf-8")
                return response.getcode(), response.headers.get("Content-Type", ""), body
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8")
            return exc.code, exc.headers.get("Content-Type", ""), body

    def test_http_t05_endpoints(self):
        status, response = self._request(
            "POST",
            "/api/v1/tasks",
            {
                "project_key": "project-http",
                "title": "HTTP task",
                "description": "HTTP details",
                "priority": 80,
            },
        )
        self.assertEqual(HTTPStatus.CREATED, status)
        task = response["task"]
        task_id = task["id"]
        self.assertEqual("HTTP details", task["description"])
        self.assertEqual(80, task["priority"])
        self.assertEqual("backlog", task["status"])

        status, response = self._request("GET", f"/api/v1/tasks/{task_id}")
        self.assertEqual(HTTPStatus.OK, status)
        self.assertEqual("project-http", response["task"]["project_key"])

        status, response = self._request(
            "PATCH",
            f"/api/v1/tasks/{task_id}",
            {"description": "updated details", "priority": 90, "status": "in_progress"},
        )
        self.assertEqual(HTTPStatus.BAD_REQUEST, status)
        self.assertEqual("invalid_request", response["error"]["code"])

        status, response = self._request(
            "PATCH",
            f"/api/v1/tasks/{task_id}",
            {"description": "updated details", "priority": 90},
        )
        self.assertEqual(HTTPStatus.OK, status)
        self.assertEqual("updated details", response["task"]["description"])
        self.assertEqual(90, response["task"]["priority"])

        status, response = self._request(
            "POST",
            f"/api/v1/tasks/{task_id}/actions/claim",
            {"assignee": "api-user"},
        )
        self.assertEqual(HTTPStatus.OK, status)
        self.assertEqual("api-user", response["task"]["assignee"])

        status, response = self._request(
            "POST", f"/api/v1/tasks/{task_id}/actions/start_work", {}
        )
        self.assertEqual(HTTPStatus.CONFLICT, status)
        self.assertEqual("invalid_transition", response["error"]["code"])

        self.store.update_task(task_id, {"status": "ready"})
        status, response = self._request(
            "POST", f"/api/v1/tasks/{task_id}/actions/start_work", {}
        )
        self.assertEqual(HTTPStatus.OK, status)
        self.assertEqual("in_progress", response["task"]["status"])

        status, response = self._request(
            "POST",
            f"/api/v1/tasks/{task_id}/transitions",
            {"target_status": "backlog"},
        )
        self.assertEqual(HTTPStatus.CONFLICT, status)
        self.assertEqual("invalid_transition", response["error"]["code"])

        self.store.update_task(task_id, {"status": "in_progress"})
        status, response = self._request(
            "POST",
            f"/api/v1/tasks/{task_id}/transitions",
            {"target_status": "done"},
        )
        self.assertEqual(HTTPStatus.OK, status)
        self.assertEqual("done", response["task"]["status"])

        transition_attempt_id = response["transition_attempt"]["id"]
        status, response = self._request(
            "GET", f"/api/v1/transitions/{transition_attempt_id}"
        )
        self.assertEqual(HTTPStatus.OK, status)
        self.assertEqual("approved", response["transition_attempt"]["status"])

        status, response = self._request(
            "POST",
            f"/api/v1/tasks/{task_id}/actions/report_result",
            {"summary": "done", "artifacts": [{"name": "a", "url": "https://a"}]},
        )
        self.assertEqual(HTTPStatus.OK, status)
        self.assertEqual("done", response["task"]["summary"])

        status, response = self._request(
            "POST",
            f"/api/v1/tasks/{task_id}/children",
            {"project_key": "ignored", "title": "Child over HTTP"},
        )
        self.assertEqual(HTTPStatus.CREATED, status)
        self.assertEqual(task_id, response["task"]["parent_task_id"])
        self.assertEqual("project-http", response["task"]["project_key"])

    def test_http_transition_approval_endpoints(self):
        status, response = self._request(
            "POST",
            "/api/v1/tasks",
            {
                "project_key": "project-http",
                "title": "HTTP transition task",
            },
        )
        self.assertEqual(HTTPStatus.CREATED, status)
        task_id = response["task"]["id"]
        self.store.set_transition_gate("backlog", "ready", "manual")

        status, response = self._request(
            "POST",
            f"/api/v1/tasks/{task_id}/transitions",
            {"target_status": "ready"},
        )
        self.assertEqual(HTTPStatus.ACCEPTED, status)
        attempt_id = response["transition_attempt"]["id"]
        self.assertEqual("pending", response["transition_attempt"]["status"])

        status, response = self._request(
            "POST",
            f"/api/v1/transitions/{attempt_id}/reject",
            {"actor": "reviewer-1", "comment": "needs more detail"},
        )
        self.assertEqual(HTTPStatus.OK, status)
        self.assertEqual("rejected", response["transition_attempt"]["status"])

        status, response = self._request(
            "POST",
            f"/api/v1/transitions/{attempt_id}/approve",
            {"actor": "reviewer-2"},
        )
        self.assertEqual(HTTPStatus.CONFLICT, status)
        self.assertEqual("already_resolved", response["error"]["code"])

    def test_http_transition_conflict_when_pending_exists(self):
        status, response = self._request(
            "POST",
            "/api/v1/tasks",
            {
                "project_key": "project-http",
                "title": "HTTP pending transition task",
            },
        )
        self.assertEqual(HTTPStatus.CREATED, status)
        task_id = response["task"]["id"]
        self.store.set_transition_gate("backlog", "ready", "manual")

        first_status, first_response = self._request(
            "POST",
            f"/api/v1/tasks/{task_id}/transitions",
            {"target_status": "ready", "reason": "first request"},
        )
        self.assertEqual(HTTPStatus.ACCEPTED, first_status)
        first_attempt_id = first_response["transition_attempt"]["id"]

        second_status, second_response = self._request(
            "POST",
            f"/api/v1/tasks/{task_id}/transitions",
            {"target_status": "ready", "reason": "duplicate request"},
        )
        self.assertEqual(HTTPStatus.CONFLICT, second_status)
        self.assertEqual(
            "pending_transition_exists",
            second_response["error"]["code"],
        )
        self.assertEqual(
            first_attempt_id,
            second_response["transition_attempt"]["id"],
        )

    def test_http_transition_request_race_is_deterministic(self):
        status, response = self._request(
            "POST",
            "/api/v1/tasks",
            {
                "project_key": "project-http",
                "title": "HTTP race task",
            },
        )
        self.assertEqual(HTTPStatus.CREATED, status)
        task_id = response["task"]["id"]
        self.store.set_transition_gate("backlog", "ready", "manual")

        barrier = threading.Barrier(3)
        results = []
        errors = []
        result_lock = threading.Lock()

        def worker(actor):
            try:
                barrier.wait(timeout=2)
                request_status, request_response = self._request(
                    "POST",
                    f"/api/v1/tasks/{task_id}/transitions",
                    {"target_status": "ready", "reason": actor, "actor": actor},
                )
                with result_lock:
                    results.append((request_status, request_response))
            except Exception as exc:  # pragma: no cover - defensive to expose failures
                with result_lock:
                    errors.append(exc)

        thread_a = threading.Thread(target=worker, args=("actor-a",), daemon=True)
        thread_b = threading.Thread(target=worker, args=("actor-b",), daemon=True)
        thread_a.start()
        thread_b.start()
        barrier.wait(timeout=2)
        thread_a.join(timeout=3)
        thread_b.join(timeout=3)

        self.assertEqual([], errors)
        self.assertEqual(2, len(results))

        statuses = sorted(status for status, _ in results)
        self.assertEqual([HTTPStatus.ACCEPTED, HTTPStatus.CONFLICT], statuses)

        snapshot_status, snapshot_response = self._request(
            "GET",
            "/api/v1/ui/snapshot?project_key=project-http",
        )
        self.assertEqual(HTTPStatus.OK, snapshot_status)
        self.assertEqual(1, len(snapshot_response["pending_transitions"]))

    def test_http_pause_endpoints(self):
        status, response = self._request(
            "POST",
            "/api/v1/tasks",
            {"project_key": "project-http", "title": "HTTP pause task"},
        )
        self.assertEqual(HTTPStatus.CREATED, status)
        task_id = response["task"]["id"]

        status, response = self._request(
            "POST",
            f"/api/v1/tasks/{task_id}/pauses/awaiting_input",
            {"question": "Need a decision?"},
        )
        self.assertEqual(HTTPStatus.CREATED, status)
        pause_id = response["pause"]["id"]

        status, response = self._request(
            "POST",
            f"/api/v1/pauses/{pause_id}/resume",
            {"actor": "reviewer-1"},
        )
        self.assertEqual(HTTPStatus.CONFLICT, status)
        self.assertEqual("answers_required", response["error"]["code"])

        status, response = self._request(
            "POST",
            f"/api/v1/pauses/{pause_id}/answers",
            {"actor": "human-1", "answer": "ship it"},
        )
        self.assertEqual(HTTPStatus.CREATED, status)
        self.assertEqual("human-1", response["answer"]["actor"])

        status, response = self._request(
            "POST",
            f"/api/v1/pauses/{pause_id}/resume",
            {"actor": "reviewer-1"},
        )
        self.assertEqual(HTTPStatus.OK, status)
        self.assertEqual("reviewer-1", response["pause"]["closed_by"])

    def test_http_attention_queues_endpoint(self):
        status, response = self._request(
            "POST",
            "/api/v1/tasks",
            {"project_key": "project-http", "title": "HTTP queue task", "priority": 55},
        )
        self.assertEqual(HTTPStatus.CREATED, status)
        task_id = response["task"]["id"]
        self.store.update_task(task_id, {"status": "ready"})

        status, response = self._request(
            "GET",
            "/api/v1/queues/attention?project_key=project-http",
        )
        self.assertEqual(HTTPStatus.OK, status)
        self.assertEqual("project-http", response["project_key"])
        self.assertEqual(1, response["queues"]["ready_unclaimed"]["count"])
        self.assertEqual(
            task_id,
            response["queues"]["ready_unclaimed"]["tasks"][0]["task_id"],
        )

        status, response = self._request("GET", "/api/v1/queues/attention")
        self.assertEqual(HTTPStatus.BAD_REQUEST, status)
        self.assertEqual("invalid_request", response["error"]["code"])

    def test_http_ui_snapshot_and_updates_endpoints(self):
        status, response = self._request(
            "POST",
            "/api/v1/tasks",
            {"project_key": "project-http", "title": "HTTP ui task"},
        )
        self.assertEqual(HTTPStatus.CREATED, status)
        task_id = response["task"]["id"]

        status, response = self._request(
            "GET",
            "/api/v1/ui/snapshot?project_key=project-http",
        )
        self.assertEqual(HTTPStatus.OK, status)
        self.assertIsInstance(response["cursor"], int)
        snapshot_task_ids = {task["id"] for task in response["tasks"]}
        self.assertIn(task_id, snapshot_task_ids)

        status, response = self._request(
            "GET",
            "/api/v1/ui/updates?cursor=0&timeout=1",
        )
        self.assertEqual(HTTPStatus.OK, status)
        self.assertGreaterEqual(len(response["events"]), 1)
        self.assertEqual("task.created", response["events"][0]["event_type"])

    def test_http_operational_ui_page_served(self):
        status, content_type, body = self._request_raw(
            "GET",
            "/ui",
        )

        self.assertEqual(HTTPStatus.OK, status)
        self.assertIn("text/html", content_type)
        self.assertIn('id="tt-board"', body)
        self.assertIn('id="tt-details"', body)
        self.assertIn('const DEFAULT_PROJECT_KEY = "demo";', body)
        self.assertNotIn('id="tt-project-key"', body)
        self.assertNotIn('id="tt-connect"', body)


if __name__ == "__main__":
    unittest.main()
