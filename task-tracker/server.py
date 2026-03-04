import json
import os
import time
import uuid
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse


TASK_TRACKER_HOST = os.environ.get("TASK_TRACKER_HOST", "0.0.0.0")
TASK_TRACKER_PORT = int(os.environ.get("TASK_TRACKER_PORT", "9102"))
TASK_TRACKER_DATABASE_URL = os.environ.get(
    "TASK_TRACKER_DATABASE_URL",
    "postgresql://postgres:postgres@127.0.0.1:5432/postgres",
)
TASK_TRACKER_UI_PROJECT_KEY = (
    os.environ.get("TASK_TRACKER_UI_PROJECT_KEY", "demo").strip() or "demo"
)

ALLOWED_STATUSES = {"backlog", "ready", "in_progress", "done"}
ALLOWED_TRANSITIONS = {
    ("backlog", "ready"),
    ("ready", "in_progress"),
    ("in_progress", "done"),
    ("in_progress", "ready"),
    ("ready", "backlog"),
}
ATTENTION_BUCKETS = (
    "pending_approval",
    "awaiting_input",
    "blocked",
    "ready_unclaimed",
    "in_progress",
    "done_recent",
)


OPERATIONAL_UI_HTML_TEMPLATE = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Task Tracker Operations</title>
    <style>
      :root {
        color-scheme: light;
        --bg: radial-gradient(circle at 15% 15%, #f8f4e8 0, #f4efe1 28%, #ede8de 58%, #e6e1d8 100%);
        --panel: rgba(255, 255, 255, 0.86);
        --panel-border: rgba(27, 41, 59, 0.18);
        --text: #1b293b;
        --muted: #5d6d82;
        --primary: #3f6a8f;
        --primary-strong: #335875;
        --danger: #a63a3a;
        --ok: #2f7541;
        --chip: #eef2f6;
        --shadow: 0 14px 34px rgba(21, 33, 45, 0.14);
      }
      * {
        box-sizing: border-box;
      }
      body {
        margin: 0;
        min-height: 100vh;
        font-family: "Avenir Next", "Segoe UI", "Helvetica Neue", sans-serif;
        color: var(--text);
        background: var(--bg);
      }
      .wrap {
        width: min(1240px, 100%);
        margin: 0 auto;
        padding: 20px 16px 22px;
      }
      .header {
        border: 1px solid var(--panel-border);
        border-radius: 14px;
        background: var(--panel);
        box-shadow: var(--shadow);
        padding: 16px;
        display: grid;
        gap: 10px;
      }
      .header h1 {
        margin: 0;
        font-size: 24px;
        letter-spacing: 0.01em;
      }
      .toolbar {
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
        align-items: center;
      }
      .toolbar label {
        font-size: 13px;
        font-weight: 600;
      }
      .toolbar input, .toolbar button, .details input, .details textarea, .details select {
        border-radius: 10px;
        border: 1px solid rgba(33, 51, 73, 0.24);
        font-size: 14px;
        padding: 8px 10px;
        background: #fff;
        color: var(--text);
      }
      .toolbar input {
        min-width: 220px;
      }
      button {
        cursor: pointer;
        border: 1px solid transparent;
        transition: transform 120ms ease, background 140ms ease;
      }
      button:hover {
        transform: translateY(-1px);
      }
      .btn-primary {
        background: var(--primary);
        color: #fff;
      }
      .btn-primary:hover {
        background: var(--primary-strong);
      }
      .btn-secondary {
        background: #f2f4f7;
        color: var(--text);
      }
      .btn-danger {
        background: var(--danger);
        color: #fff;
      }
      .status-line {
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
        align-items: center;
        font-size: 13px;
      }
      .chip {
        border-radius: 999px;
        padding: 4px 10px;
        background: var(--chip);
        color: var(--muted);
        font-weight: 600;
      }
      .chip.ok {
        background: rgba(47, 117, 65, 0.12);
        color: var(--ok);
      }
      .chip.error {
        background: rgba(166, 58, 58, 0.14);
        color: var(--danger);
      }
      .grid {
        margin-top: 14px;
        display: grid;
        gap: 14px;
        grid-template-columns: minmax(0, 1.8fr) minmax(310px, 1fr);
      }
      .panel {
        border: 1px solid var(--panel-border);
        border-radius: 14px;
        background: var(--panel);
        box-shadow: var(--shadow);
      }
      .panel h2 {
        margin: 0;
        font-size: 18px;
      }
      .panel-head {
        border-bottom: 1px solid rgba(27, 41, 59, 0.14);
        padding: 12px 14px;
        display: flex;
        justify-content: space-between;
        align-items: center;
      }
      .panel-body {
        padding: 12px 14px;
      }
      .board {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 10px;
      }
      .queue {
        border: 1px solid rgba(27, 41, 59, 0.14);
        border-radius: 12px;
        padding: 8px;
        background: rgba(248, 248, 248, 0.74);
      }
      .queue-head {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 8px;
      }
      .queue-title {
        font-size: 13px;
        font-weight: 700;
        text-transform: uppercase;
        color: #2f435c;
      }
      .queue-count {
        font-size: 12px;
        color: var(--muted);
      }
      .task-list {
        display: grid;
        gap: 7px;
      }
      .task-card {
        width: 100%;
        text-align: left;
        border: 1px solid rgba(27, 41, 59, 0.15);
        background: #fff;
        border-radius: 10px;
        padding: 8px 9px;
        display: grid;
        gap: 4px;
      }
      .task-card.selected {
        border-color: var(--primary);
        box-shadow: 0 0 0 2px rgba(63, 106, 143, 0.2);
      }
      .task-title {
        font-weight: 700;
        font-size: 14px;
      }
      .task-meta {
        color: var(--muted);
        font-size: 12px;
      }
      .empty {
        color: var(--muted);
        font-size: 12px;
        padding: 6px;
      }
      .details {
        display: grid;
        gap: 10px;
      }
      .detail-block {
        border: 1px solid rgba(27, 41, 59, 0.12);
        border-radius: 10px;
        padding: 9px;
        background: rgba(255, 255, 255, 0.8);
        display: grid;
        gap: 8px;
      }
      .detail-title {
        font-size: 13px;
        font-weight: 700;
        text-transform: uppercase;
        color: #2f435c;
      }
      .kv {
        display: grid;
        grid-template-columns: 110px minmax(0, 1fr);
        gap: 5px;
        font-size: 13px;
      }
      .kv .k {
        color: var(--muted);
      }
      .detail-actions {
        display: flex;
        flex-wrap: wrap;
        gap: 7px;
      }
      .detail-grid {
        display: grid;
        gap: 7px;
      }
      textarea {
        min-height: 72px;
        resize: vertical;
      }
      @media (max-width: 1020px) {
        .grid {
          grid-template-columns: 1fr;
        }
      }
      @media (max-width: 700px) {
        .board {
          grid-template-columns: 1fr;
        }
      }
    </style>
  </head>
  <body>
    <main class="wrap">
      <section class="header">
        <h1>Task Tracker Operational UI</h1>
        <div class="toolbar">
          <span id="tt-project-label" class="chip">Project: <span id="tt-project-value"></span></span>
          <button id="tt-refresh" class="btn-secondary" type="button">Refresh</button>
        </div>
        <div class="status-line">
          <span id="tt-connection-state" class="chip">idle</span>
          <span id="tt-status-text" class="chip">Ready</span>
        </div>
      </section>

      <section class="grid">
        <section class="panel">
          <div class="panel-head">
            <h2>Board</h2>
            <small>Operational buckets from queue projection</small>
          </div>
          <div class="panel-body">
            <div id="tt-board" class="board"></div>
          </div>
        </section>

        <aside class="panel">
          <div class="panel-head">
            <h2>Details</h2>
            <small>Actions for approvals, questions, and blocked flow</small>
          </div>
          <div class="panel-body">
            <div id="tt-details" class="details"></div>
          </div>
        </aside>
      </section>
    </main>

    <script>
      const DEFAULT_PROJECT_KEY = __DEFAULT_PROJECT_KEY__;
      const BUCKETS = [
        { id: "pending_approval", label: "Pending Approval" },
        { id: "awaiting_input", label: "Awaiting Input" },
        { id: "blocked", label: "Blocked" },
        { id: "ready_unclaimed", label: "Ready Unclaimed" },
        { id: "in_progress", label: "In Progress" },
        { id: "done_recent", label: "Done Recent" },
      ];

      const state = {
        projectKey: DEFAULT_PROJECT_KEY || "",
        cursor: 0,
        selectedTaskId: null,
        snapshot: {
          cursor: 0,
          queues: {},
          tasks: [],
          pending_transitions: [],
          open_pauses: [],
        },
      };

      let pollToken = 0;

      function byId(id) {
        return document.getElementById(id);
      }

      function esc(value) {
        const text = value == null ? "" : String(value);
        return text
          .replaceAll("&", "&amp;")
          .replaceAll("<", "&lt;")
          .replaceAll(">", "&gt;")
          .replaceAll('"', "&quot;")
          .replaceAll("'", "&#39;");
      }

      function setStatus(message, level) {
        const chip = byId("tt-status-text");
        chip.textContent = message || "Ready";
        chip.className = "chip";
        if (level === "ok") {
          chip.classList.add("ok");
        } else if (level === "error") {
          chip.classList.add("error");
        }
      }

      function setConnectionState(value) {
        const chip = byId("tt-connection-state");
        chip.textContent = value;
        chip.className = "chip";
        if (value === "connected") {
          chip.classList.add("ok");
        }
      }

      function normalizeSnapshot(snapshot) {
        return {
          cursor: Number(snapshot.cursor || 0),
          queues: snapshot.queues || {},
          tasks: Array.isArray(snapshot.tasks) ? snapshot.tasks : [],
          pending_transitions: Array.isArray(snapshot.pending_transitions)
            ? snapshot.pending_transitions
            : [],
          open_pauses: Array.isArray(snapshot.open_pauses) ? snapshot.open_pauses : [],
        };
      }

      function activeTask() {
        return state.snapshot.tasks.find((task) => task.id === state.selectedTaskId) || null;
      }

      function pendingTransitionForTask(taskId) {
        return (
          state.snapshot.pending_transitions.find((transition) => transition.task_id === taskId) ||
          null
        );
      }

      function pauseForTask(taskId) {
        return state.snapshot.open_pauses.find((pause) => pause.task_id === taskId) || null;
      }

      function valueOf(id) {
        const element = byId(id);
        return element ? element.value.trim() : "";
      }

      function requiredValue(id, fieldName) {
        const value = valueOf(id);
        if (!value) {
          throw new Error(fieldName + " is required");
        }
        return value;
      }

      function renderBoard() {
        const board = byId("tt-board");
        const queues = state.snapshot.queues || {};
        const html = BUCKETS.map((bucket) => {
          const queue = queues[bucket.id] || { count: 0, tasks: [] };
          const tasks = Array.isArray(queue.tasks) ? queue.tasks : [];
          const cards = tasks.length
            ? tasks
                .map((task) => {
                  const selectedClass = task.task_id === state.selectedTaskId ? " selected" : "";
                  return (
                    '<button type="button" class="task-card' +
                    selectedClass +
                    '" data-task-id="' +
                    esc(task.task_id) +
                    '">' +
                    '<span class="task-title">' +
                    esc(task.title) +
                    "</span>" +
                    '<span class="task-meta">' +
                    esc(task.status) +
                    " | score " +
                    esc(task.priority_score) +
                    "</span>" +
                    "</button>"
                  );
                })
                .join("")
            : '<div class="empty">No tasks</div>';
          return (
            '<section class="queue">' +
            '<div class="queue-head">' +
            '<span class="queue-title">' +
            esc(bucket.label) +
            "</span>" +
            '<span class="queue-count">' +
            esc(queue.count || 0) +
            "</span>" +
            "</div>" +
            '<div class="task-list">' +
            cards +
            "</div>" +
            "</section>"
          );
        }).join("");
        board.innerHTML = html;
      }

      function renderPendingTransitionSection(transition) {
        if (!transition) {
          return "";
        }
        return (
          '<section class="detail-block">' +
          '<div class="detail-title">Pending Approval</div>' +
          '<div class="kv"><span class="k">Transition</span><span>' +
          esc(transition.from_status) +
          " -> " +
          esc(transition.to_status) +
          "</span></div>" +
          '<div class="kv"><span class="k">Requested by</span><span>' +
          esc(transition.requested_by || "n/a") +
          "</span></div>" +
          '<div class="kv"><span class="k">Reason</span><span>' +
          esc(transition.reason || "n/a") +
          "</span></div>" +
          '<div class="detail-grid">' +
          '<input id="tt-transition-actor" type="text" placeholder="actor">' +
          '<textarea id="tt-transition-comment" placeholder="comment (required for reject)"></textarea>' +
          '<div class="detail-actions">' +
          '<button type="button" class="btn-primary" data-action="approve-transition" data-attempt-id="' +
          esc(transition.id) +
          '">Approve</button>' +
          '<button type="button" class="btn-danger" data-action="reject-transition" data-attempt-id="' +
          esc(transition.id) +
          '">Reject</button>' +
          "</div>" +
          "</div>" +
          "</section>"
        );
      }

      function renderPauseSection(pause) {
        if (!pause) {
          return "";
        }
        const pauseMeta =
          '<div class="kv"><span class="k">Type</span><span>' +
          esc(pause.pause_type) +
          "</span></div>" +
          '<div class="kv"><span class="k">Opened by</span><span>' +
          esc(pause.opened_by || "n/a") +
          "</span></div>" +
          '<div class="kv"><span class="k">Reason</span><span>' +
          esc(pause.reason || "n/a") +
          "</span></div>" +
          '<div class="kv"><span class="k">Question</span><span>' +
          esc(pause.question || "n/a") +
          "</span></div>" +
          '<div class="kv"><span class="k">Requested from</span><span>' +
          esc(pause.requested_from || "n/a") +
          "</span></div>" +
          '<div class="kv"><span class="k">Due</span><span>' +
          esc(pause.due_at || "n/a") +
          "</span></div>";

        const answerSection =
          pause.pause_type === "awaiting_input"
            ? '<div class="detail-grid">' +
              '<input id="tt-answer-actor" type="text" placeholder="answer actor">' +
              '<textarea id="tt-answer-text" placeholder="answer"></textarea>' +
              '<button type="button" class="btn-secondary" data-action="add-answer" data-pause-id="' +
              esc(pause.id) +
              '">Add Answer</button>' +
              "</div>"
            : "";

        return (
          '<section class="detail-block">' +
          '<div class="detail-title">Open Pause</div>' +
          pauseMeta +
          answerSection +
          '<div class="detail-grid">' +
          '<input id="tt-resume-actor" type="text" placeholder="actor">' +
          '<textarea id="tt-resume-comment" placeholder="resume comment (optional)"></textarea>' +
          '<button type="button" class="btn-primary" data-action="resume-pause" data-pause-id="' +
          esc(pause.id) +
          '">Resume Pause</button>' +
          "</div>" +
          "</section>"
        );
      }

      function renderPauseOpeners(task, pause) {
        if (!task || pause || task.status === "done") {
          return "";
        }
        return (
          '<section class="detail-block">' +
          '<div class="detail-title">Open Pause</div>' +
          '<div class="detail-grid">' +
          '<input id="tt-blocked-actor" type="text" placeholder="actor (optional)">' +
          '<input id="tt-blocked-reason" type="text" placeholder="blocked reason">' +
          '<textarea id="tt-blocked-details" placeholder="blocked details (optional)"></textarea>' +
          '<button type="button" class="btn-secondary" data-action="open-blocked" data-task-id="' +
          esc(task.id) +
          '">Open blocked</button>' +
          "</div>" +
          '<div class="detail-grid">' +
          '<input id="tt-await-actor" type="text" placeholder="actor (optional)">' +
          '<textarea id="tt-await-question" placeholder="question for human input"></textarea>' +
          '<input id="tt-await-requested-from" type="text" placeholder="requested_from (optional)">' +
          '<input id="tt-await-due-at" type="text" placeholder="due_at RFC3339 (optional)">' +
          '<button type="button" class="btn-secondary" data-action="open-awaiting-input" data-task-id="' +
          esc(task.id) +
          '">Open awaiting_input</button>' +
          "</div>" +
          "</section>"
        );
      }

      function renderTransitionRequester(task) {
        if (!task || task.status === "done") {
          return "";
        }
        return (
          '<section class="detail-block">' +
          '<div class="detail-title">Request Transition</div>' +
          '<div class="detail-grid">' +
          '<select id="tt-transition-target">' +
          '<option value="backlog">backlog</option>' +
          '<option value="ready">ready</option>' +
          '<option value="in_progress">in_progress</option>' +
          '<option value="done">done</option>' +
          "</select>" +
          '<input id="tt-transition-request-actor" type="text" placeholder="actor (optional)">' +
          '<textarea id="tt-transition-request-reason" placeholder="reason (optional)"></textarea>' +
          '<button type="button" class="btn-secondary" data-action="request-transition" data-task-id="' +
          esc(task.id) +
          '">Submit transition request</button>' +
          "</div>" +
          "</section>"
        );
      }

      function renderDetails() {
        const details = byId("tt-details");
        const task = activeTask();
        if (!task) {
          details.innerHTML = '<div class="detail-block"><p class="empty">Select a task from the board.</p></div>';
          return;
        }

        const transition = pendingTransitionForTask(task.id);
        const pause = pauseForTask(task.id);
        details.innerHTML =
          '<section class="detail-block">' +
          '<div class="detail-title">Task</div>' +
          '<div class="kv"><span class="k">ID</span><span>' +
          esc(task.id) +
          "</span></div>" +
          '<div class="kv"><span class="k">Title</span><span>' +
          esc(task.title) +
          "</span></div>" +
          '<div class="kv"><span class="k">Status</span><span>' +
          esc(task.status) +
          "</span></div>" +
          '<div class="kv"><span class="k">Priority</span><span>' +
          esc(task.priority) +
          "</span></div>" +
          '<div class="kv"><span class="k">Assignee</span><span>' +
          esc(task.assignee || "n/a") +
          "</span></div>" +
          '<div class="kv"><span class="k">Description</span><span>' +
          esc(task.description || "n/a") +
          "</span></div>" +
          "</section>" +
          renderPendingTransitionSection(transition) +
          renderPauseSection(pause) +
          renderPauseOpeners(task, pause) +
          renderTransitionRequester(task);
      }

      async function requestJson(path, options) {
        const response = await fetch(path, options || {});
        const text = await response.text();
        let payload = {};
        if (text) {
          try {
            payload = JSON.parse(text);
          } catch (error) {
            payload = {};
          }
        }
        if (!response.ok) {
          const message =
            payload && payload.error && payload.error.message
              ? payload.error.message
              : "HTTP " + response.status;
          throw new Error(message);
        }
        return payload;
      }

      async function apiPost(path, payload) {
        return requestJson(path, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload || {}),
        });
      }

      function ensureSelectedTask() {
        const hasSelection = state.snapshot.tasks.some((task) => task.id === state.selectedTaskId);
        if (!hasSelection) {
          state.selectedTaskId = state.snapshot.tasks.length ? state.snapshot.tasks[0].id : null;
        }
      }

      async function refreshSnapshot(silent) {
        if (!state.projectKey) {
          throw new Error("project key is required");
        }
        const snapshot = await requestJson(
          "/api/v1/ui/snapshot?project_key=" + encodeURIComponent(state.projectKey)
        );
        state.snapshot = normalizeSnapshot(snapshot);
        state.cursor = state.snapshot.cursor;
        ensureSelectedTask();
        renderBoard();
        renderDetails();
        if (!silent) {
          setStatus("Snapshot loaded at cursor " + state.cursor, "ok");
        }
      }

      function wait(ms) {
        return new Promise((resolve) => setTimeout(resolve, ms));
      }

      async function pollLoop(token) {
        while (token === pollToken && state.projectKey) {
          try {
            const updates = await requestJson(
              "/api/v1/ui/updates?cursor=" + state.cursor + "&timeout=20"
            );
            if (token !== pollToken) {
              return;
            }
            if (updates.events && updates.events.length > 0) {
              state.cursor = Number(updates.cursor || state.cursor);
              await refreshSnapshot(true);
              setStatus("Received " + updates.events.length + " update(s)", "ok");
            }
          } catch (error) {
            if (token !== pollToken) {
              return;
            }
            setStatus("Polling error: " + error.message, "error");
            await wait(1500);
          }
        }
      }

      function restartPolling() {
        pollToken += 1;
        setConnectionState("connected");
        void pollLoop(pollToken);
      }

      function renderProjectLabel() {
        const projectValue = byId("tt-project-value");
        if (!projectValue) {
          return;
        }
        projectValue.textContent = state.projectKey || "n/a";
      }

      async function initializeConnection() {
        if (!state.projectKey) {
          setConnectionState("idle");
          setStatus("project key is not configured", "error");
          renderBoard();
          renderDetails();
          return;
        }
        try {
          await refreshSnapshot(false);
          restartPolling();
        } catch (error) {
          setConnectionState("idle");
          setStatus(error.message, "error");
        }
      }

      async function runAction(successMessage, handler) {
        try {
          await handler();
          await refreshSnapshot(true);
          setStatus(successMessage, "ok");
        } catch (error) {
          setStatus(error.message, "error");
        }
      }

      async function handleDetailsAction(action, button) {
        if (!state.projectKey) {
          throw new Error("project key is not configured");
        }

        if (action === "approve-transition") {
          const attemptId = button.dataset.attemptId;
          const actor = requiredValue("tt-transition-actor", "actor");
          const comment = valueOf("tt-transition-comment");
          await apiPost("/api/v1/transitions/" + encodeURIComponent(attemptId) + "/approve", {
            actor: actor,
            comment: comment || undefined,
          });
          return "Transition approved";
        }

        if (action === "reject-transition") {
          const attemptId = button.dataset.attemptId;
          const actor = requiredValue("tt-transition-actor", "actor");
          const comment = requiredValue("tt-transition-comment", "comment");
          await apiPost("/api/v1/transitions/" + encodeURIComponent(attemptId) + "/reject", {
            actor: actor,
            comment: comment,
          });
          return "Transition rejected";
        }

        if (action === "add-answer") {
          const pauseId = button.dataset.pauseId;
          const actor = requiredValue("tt-answer-actor", "actor");
          const answer = requiredValue("tt-answer-text", "answer");
          await apiPost("/api/v1/pauses/" + encodeURIComponent(pauseId) + "/answers", {
            actor: actor,
            answer: answer,
          });
          return "Answer added";
        }

        if (action === "resume-pause") {
          const pauseId = button.dataset.pauseId;
          const actor = requiredValue("tt-resume-actor", "actor");
          const comment = valueOf("tt-resume-comment");
          await apiPost("/api/v1/pauses/" + encodeURIComponent(pauseId) + "/resume", {
            actor: actor,
            comment: comment || undefined,
          });
          return "Pause resumed";
        }

        if (action === "open-blocked") {
          const taskId = button.dataset.taskId;
          const actor = valueOf("tt-blocked-actor");
          const reason = requiredValue("tt-blocked-reason", "reason");
          const details = valueOf("tt-blocked-details");
          await apiPost("/api/v1/tasks/" + encodeURIComponent(taskId) + "/pauses/blocked", {
            actor: actor || undefined,
            reason: reason,
            details: details || undefined,
          });
          return "Blocked pause opened";
        }

        if (action === "open-awaiting-input") {
          const taskId = button.dataset.taskId;
          const actor = valueOf("tt-await-actor");
          const question = requiredValue("tt-await-question", "question");
          const requestedFrom = valueOf("tt-await-requested-from");
          const dueAt = valueOf("tt-await-due-at");
          await apiPost(
            "/api/v1/tasks/" + encodeURIComponent(taskId) + "/pauses/awaiting_input",
            {
              actor: actor || undefined,
              question: question,
              requested_from: requestedFrom || undefined,
              due_at: dueAt || undefined,
            }
          );
          return "Awaiting input pause opened";
        }

        if (action === "request-transition") {
          const taskId = button.dataset.taskId;
          const targetSelect = byId("tt-transition-target");
          const targetStatus = targetSelect ? targetSelect.value : "";
          const reason = valueOf("tt-transition-request-reason");
          const actor = valueOf("tt-transition-request-actor");
          if (!targetStatus) {
            throw new Error("target_status is required");
          }
          await apiPost("/api/v1/tasks/" + encodeURIComponent(taskId) + "/transitions", {
            target_status: targetStatus,
            reason: reason || undefined,
            actor: actor || undefined,
          });
          return "Transition requested";
        }

        return null;
      }

      byId("tt-board").addEventListener("click", (event) => {
        const card = event.target.closest("[data-task-id]");
        if (!card) {
          return;
        }
        state.selectedTaskId = card.dataset.taskId;
        renderBoard();
        renderDetails();
      });

      byId("tt-details").addEventListener("click", (event) => {
        const button = event.target.closest("button[data-action]");
        if (!button) {
          return;
        }
        const action = button.dataset.action;
        void runAction("Action completed", async () => {
          const message = await handleDetailsAction(action, button);
          if (message) {
            setStatus(message, "ok");
          }
        });
      });

      byId("tt-refresh").addEventListener("click", () => {
        if (!state.projectKey) {
          setStatus("project key is not configured", "error");
          return;
        }
        void refreshSnapshot(false);
      });

      renderProjectLabel();
      void initializeConnection();
    </script>
  </body>
</html>
"""


def render_operational_ui_html(default_project_key=""):
    normalized = ""
    if isinstance(default_project_key, str):
        normalized = default_project_key.strip()
    default_key_payload = json.dumps(normalized)
    return OPERATIONAL_UI_HTML_TEMPLATE.replace(
        "__DEFAULT_PROJECT_KEY__",
        default_key_payload,
        1,
    )


def _empty_attention_queues():
    return {
        bucket: {"count": 0, "tasks": []}
        for bucket in ATTENTION_BUCKETS
    }


def _attention_bucket_for(status, assignee, pause_type, has_pending_approval):
    if has_pending_approval:
        return "pending_approval"
    if pause_type == "awaiting_input":
        return "awaiting_input"
    if pause_type == "blocked":
        return "blocked"
    if status == "ready" and not assignee:
        return "ready_unclaimed"
    if status == "in_progress":
        return "in_progress"
    if status == "done":
        return "done_recent"
    return None


def _attention_priority_score(status, assignee, pause_type, has_pending_approval, priority):
    score = int(priority or 0)
    if has_pending_approval:
        return score + 100
    if pause_type == "awaiting_input":
        return score + 80
    if pause_type == "blocked":
        return score + 60
    if status == "ready" and not assignee:
        return score + 40
    if status == "in_progress":
        return score + 20
    return score


def _build_attention_task_summary(
    task_id,
    title,
    status,
    assignee,
    pause_type,
    priority,
    updated_at,
    has_pending_approval,
):
    return {
        "task_id": str(task_id),
        "title": title,
        "status": status,
        "pause_type": pause_type,
        "priority_score": _attention_priority_score(
            status=status,
            assignee=assignee,
            pause_type=pause_type,
            has_pending_approval=has_pending_approval,
            priority=priority,
        ),
        "updated_at": updated_at,
        "closable": bool(
            status == "in_progress" and pause_type is None and not has_pending_approval
        ),
    }


def _finalize_attention_queues(queues):
    for queue in queues.values():
        queue["tasks"].sort(
            key=lambda task: (
                task["priority_score"],
                task.get("updated_at") or "",
                task["task_id"],
            ),
            reverse=True,
        )
        queue["count"] = len(queue["tasks"])
    return queues


class PostgresTaskStore:
    def __init__(self, dsn=None):
        self._dsn = dsn or TASK_TRACKER_DATABASE_URL

    def _connect(self):
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError("psycopg is required for PostgresTaskStore") from exc
        return psycopg.connect(self._dsn)

    def _row_to_task(self, row):
        if row is None:
            return None
        return {
            "id": str(row[0]),
            "project_key": row[1],
            "parent_task_id": str(row[2]) if row[2] is not None else None,
            "title": row[3],
            "description": row[4],
            "status": row[5],
            "priority": row[6],
            "assignee": row[7],
            "summary": row[8],
            "artifacts": [],
        }

    def _row_to_transition_attempt(self, row):
        if row is None:
            return None
        return {
            "id": str(row[0]),
            "task_id": str(row[1]),
            "from_status": row[2],
            "to_status": row[3],
            "gate_type": row[4],
            "status": row[5],
            "reason": row[6],
            "requested_by": row[7],
            "requested_at": row[8].isoformat() if row[8] else None,
            "resolved_by": row[9],
            "resolved_comment": row[10],
            "resolved_at": row[11].isoformat() if row[11] else None,
        }

    def _row_to_pause(self, row):
        if row is None:
            return None
        return {
            "id": str(row[0]),
            "task_id": str(row[1]),
            "pause_type": row[2],
            "reason": row[3],
            "details": row[4],
            "question": row[5],
            "requested_from": row[6],
            "due_at": row[7].isoformat() if row[7] else None,
            "opened_by": row[8],
            "opened_at": row[9].isoformat() if row[9] else None,
            "closed_by": row[10],
            "closed_comment": row[11],
            "closed_at": row[12].isoformat() if row[12] else None,
        }

    def _row_to_pause_answer(self, row):
        if row is None:
            return None
        return {
            "id": str(row[0]),
            "pause_id": str(row[1]),
            "actor": row[2],
            "answer": row[3],
            "created_at": row[4].isoformat() if row[4] else None,
        }

    def _row_to_event(self, row):
        if row is None:
            return None
        payload = row[5] if isinstance(row[5], dict) else {}
        return {
            "cursor": int(row[0]),
            "event_type": row[1],
            "project_key": row[2],
            "task_id": str(row[3]) if row[3] is not None else None,
            "occurred_at": row[4].isoformat() if row[4] else None,
            "payload": payload,
        }

    def _get_task_row(self, cur, task_id, for_update=False):
        lock_clause = "FOR UPDATE" if for_update else ""
        cur.execute(
            f"""
            SELECT id, project_key, parent_task_id, title, description,
                status, priority, assignee, result_summary, workflow_version_id
            FROM tasks
            WHERE id = %s
            {lock_clause}
            """,
            (uuid.UUID(task_id),),
        )
        return cur.fetchone()

    def _emit_event(self, cur, event_type, project_key, task_id, payload):
        cur.execute(
            """
            INSERT INTO events (event_type, project_key, task_id, payload)
            VALUES (%s, %s, %s, %s::jsonb)
            """,
            (
                event_type,
                project_key,
                uuid.UUID(task_id) if task_id else None,
                json.dumps(payload),
            ),
        )

    def _get_open_pause_for_task(self, cur, task_id, for_update=False):
        lock_clause = "FOR UPDATE" if for_update else ""
        cur.execute(
            f"""
            SELECT id, task_id, pause_type, reason, details, question,
                requested_from, due_at, opened_by, opened_at,
                closed_by, closed_comment, closed_at
            FROM pauses
            WHERE task_id = %s AND closed_at IS NULL
            {lock_clause}
            ORDER BY opened_at DESC
            LIMIT 1
            """,
            (uuid.UUID(task_id),),
        )
        return cur.fetchone()

    def _close_open_pause_if_any(self, cur, task_id, actor=None, comment=None):
        open_pause_row = self._get_open_pause_for_task(cur, task_id, for_update=True)
        if open_pause_row is None:
            return None

        cur.execute(
            """
            UPDATE pauses
            SET closed_by = %s,
                closed_comment = %s,
                closed_at = NOW()
            WHERE id = %s
            RETURNING id, task_id, pause_type, reason, details, question,
                requested_from, due_at, opened_by, opened_at,
                closed_by, closed_comment, closed_at
            """,
            (actor, comment, open_pause_row[0]),
        )
        return cur.fetchone()

    def create_task(self, task):
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO tasks (
                        id, project_key, workflow_version_id, parent_task_id, title,
                        description, status, priority, assignee, result_summary
                    ) VALUES (
                        %s,
                        %s,
                        (SELECT active_workflow_version_id FROM projects WHERE project_key = %s),
                        %s, %s, %s, %s, %s, %s, %s
                    )
                    RETURNING id, project_key, parent_task_id, title, description,
                        status, priority, assignee, result_summary
                    """,
                    (
                        uuid.UUID(task["id"]),
                        task["project_key"],
                        task["project_key"],
                        uuid.UUID(task["parent_task_id"]) if task.get("parent_task_id") else None,
                        task["title"],
                        task.get("description"),
                        task["status"],
                        task["priority"],
                        task.get("assignee"),
                        task.get("summary"),
                    ),
                )
                row = cur.fetchone()
                created = self._row_to_task(row)
                self._emit_event(
                    cur,
                    "task.created",
                    created["project_key"],
                    created["id"],
                    {},
                )
            conn.commit()
        return created

    def get_task(self, task_id):
        with self._connect() as conn:
            with conn.cursor() as cur:
                row = self._get_task_row(cur, task_id)
        return self._row_to_task(row)

    def update_task(self, task_id, changes):
        allowed = {
            "title",
            "description",
            "status",
            "priority",
            "assignee",
            "summary",
        }
        updates = {k: v for k, v in changes.items() if k in allowed}
        if not updates:
            return self.get_task(task_id)

        sets = []
        values = []

        for field in (
            "title",
            "description",
            "status",
            "priority",
            "assignee",
            "summary",
        ):
            if field not in updates:
                continue
            if field == "summary":
                sets.append("result_summary = %s")
                values.append(updates[field])
            else:
                sets.append(f"{field} = %s")
                values.append(updates[field])

        values.append(uuid.UUID(task_id))

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    UPDATE tasks
                    SET {", ".join(sets)}
                    WHERE id = %s
                    RETURNING id, project_key, parent_task_id, title, description,
                        status, priority, assignee, result_summary
                    """,
                    values,
                )
                row = cur.fetchone()
                updated = self._row_to_task(row)
                if updated is not None:
                    event_type = "task.updated"
                    if "summary" in updates:
                        event_type = "task.result_reported"
                    elif set(updates.keys()) == {"assignee"}:
                        event_type = "task.claimed"
                    self._emit_event(
                        cur,
                        event_type,
                        updated["project_key"],
                        updated["id"],
                        {"changes": updates},
                    )
            conn.commit()
        return updated

    def reset(self):
        return

    def request_transition(self, task_id, target_status, reason=None, requested_by=None):
        with self._connect() as conn:
            with conn.cursor() as cur:
                task_row = self._get_task_row(cur, task_id, for_update=True)
                if task_row is None:
                    return None

                from_status = task_row[5]
                project_key = task_row[1]
                workflow_version_id = task_row[9]
                if (from_status, target_status) not in ALLOWED_TRANSITIONS:
                    return {"error": "invalid_transition"}

                cur.execute(
                    """
                    SELECT gate_type
                    FROM workflow_transition_gates
                    WHERE workflow_version_id = %s
                        AND from_status = %s
                        AND to_status = %s
                    """,
                    (workflow_version_id, from_status, target_status),
                )
                gate = cur.fetchone()
                if gate is None:
                    return {"error": "invalid_transition"}

                gate_type = gate[0]
                cur.execute(
                    """
                    SELECT id, task_id, from_status, to_status, gate_type, status,
                        reason, requested_by, requested_at, resolved_by,
                        resolved_comment, resolved_at
                    FROM transition_attempts
                    WHERE task_id = %s
                        AND status = 'pending'
                    ORDER BY requested_at DESC, id DESC
                    LIMIT 1
                    """,
                    (uuid.UUID(task_id),),
                )
                pending_attempt_row = cur.fetchone()
                if pending_attempt_row is not None:
                    return {
                        "error": "pending_transition_exists",
                        "attempt": self._row_to_transition_attempt(pending_attempt_row),
                        "task": self._row_to_task(task_row[:9]),
                    }

                attempt_id = uuid.uuid4()
                if gate_type == "auto":
                    cur.execute(
                        """
                        INSERT INTO transition_attempts (
                            id, task_id, from_status, to_status, gate_type, status,
                            reason, requested_by, resolved_by, resolved_at
                        ) VALUES (
                            %s, %s, %s, %s, %s, 'approved',
                            %s, %s, %s, NOW()
                        )
                        RETURNING id, task_id, from_status, to_status, gate_type, status,
                            reason, requested_by, requested_at, resolved_by,
                            resolved_comment, resolved_at
                        """,
                        (
                            attempt_id,
                            uuid.UUID(task_id),
                            from_status,
                            target_status,
                            gate_type,
                            reason,
                            requested_by,
                            requested_by,
                        ),
                    )
                    attempt_row = cur.fetchone()
                    cur.execute(
                        """
                        UPDATE tasks
                        SET status = %s,
                            updated_at = NOW(),
                            completed_at = CASE
                                WHEN %s = 'done' THEN NOW()
                                ELSE completed_at
                            END
                        WHERE id = %s
                        RETURNING id, project_key, parent_task_id, title, description,
                            status, priority, assignee, result_summary
                        """,
                        (target_status, target_status, uuid.UUID(task_id)),
                    )
                    updated_task_row = cur.fetchone()
                    if target_status == "done":
                        closed_pause_row = self._close_open_pause_if_any(
                            cur,
                            task_id,
                            actor=requested_by,
                            comment="auto-closed on task completion",
                        )
                else:
                    cur.execute(
                        """
                        INSERT INTO transition_attempts (
                            id, task_id, from_status, to_status, gate_type, status,
                            reason, requested_by
                        ) VALUES (
                            %s, %s, %s, %s, %s, 'pending',
                            %s, %s
                        )
                        RETURNING id, task_id, from_status, to_status, gate_type, status,
                            reason, requested_by, requested_at, resolved_by,
                            resolved_comment, resolved_at
                        """,
                        (
                            attempt_id,
                            uuid.UUID(task_id),
                            from_status,
                            target_status,
                            gate_type,
                            reason,
                            requested_by,
                        ),
                    )
                    attempt_row = cur.fetchone()
                    updated_task_row = task_row[:9]

                attempt = self._row_to_transition_attempt(attempt_row)
                updated_task = self._row_to_task(updated_task_row)
                self._emit_event(
                    cur,
                    "transition.requested",
                    project_key,
                    task_id,
                    {
                        "transition_attempt_id": attempt["id"],
                        "from_status": from_status,
                        "to_status": target_status,
                        "gate_type": gate_type,
                    },
                )
                if attempt["status"] == "approved":
                    self._emit_event(
                        cur,
                        "transition.approved",
                        project_key,
                        task_id,
                        {"transition_attempt_id": attempt["id"]},
                    )
                    if target_status == "done":
                        if closed_pause_row is not None:
                            closed_pause = self._row_to_pause(closed_pause_row)
                            self._emit_event(
                                cur,
                                "pause.resumed",
                                project_key,
                                task_id,
                                {
                                    "pause_id": closed_pause["id"],
                                    "auto_closed": True,
                                },
                            )
                        self._emit_event(cur, "task.completed", project_key, task_id, {})

            conn.commit()
        return {"attempt": attempt, "task": updated_task}

    def get_transition_attempt(self, attempt_id):
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, task_id, from_status, to_status, gate_type, status,
                        reason, requested_by, requested_at, resolved_by,
                        resolved_comment, resolved_at
                    FROM transition_attempts
                    WHERE id = %s
                    """,
                    (uuid.UUID(attempt_id),),
                )
                row = cur.fetchone()
        return self._row_to_transition_attempt(row)

    def resolve_transition_attempt(self, attempt_id, decision, actor, comment=None):
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, task_id, from_status, to_status, gate_type, status,
                        reason, requested_by, requested_at, resolved_by,
                        resolved_comment, resolved_at
                    FROM transition_attempts
                    WHERE id = %s
                    FOR UPDATE
                    """,
                    (uuid.UUID(attempt_id),),
                )
                attempt_row = cur.fetchone()
                if attempt_row is None:
                    return None

                attempt = self._row_to_transition_attempt(attempt_row)
                if attempt["status"] != "pending":
                    return {"error": "already_resolved", "attempt": attempt}

                task_row = self._get_task_row(cur, attempt["task_id"], for_update=True)
                if task_row is None:
                    return {"error": "task_not_found"}

                project_key = task_row[1]
                if task_row[5] != attempt["from_status"]:
                    return {
                        "error": "stale_transition",
                        "attempt": attempt,
                        "task": self._row_to_task(task_row[:9]),
                    }

                if decision == "approve":
                    cur.execute(
                        """
                        UPDATE transition_attempts
                        SET status = 'approved',
                            resolved_by = %s,
                            resolved_comment = %s,
                            resolved_at = NOW()
                        WHERE id = %s
                        RETURNING id, task_id, from_status, to_status, gate_type, status,
                            reason, requested_by, requested_at, resolved_by,
                            resolved_comment, resolved_at
                        """,
                        (actor, comment, uuid.UUID(attempt_id)),
                    )
                    updated_attempt_row = cur.fetchone()
                    cur.execute(
                        """
                        UPDATE tasks
                        SET status = %s,
                            updated_at = NOW(),
                            completed_at = CASE
                                WHEN %s = 'done' THEN NOW()
                                ELSE completed_at
                            END
                        WHERE id = %s
                        RETURNING id, project_key, parent_task_id, title, description,
                            status, priority, assignee, result_summary
                        """,
                        (
                            attempt["to_status"],
                            attempt["to_status"],
                            uuid.UUID(attempt["task_id"]),
                        ),
                    )
                    updated_task_row = cur.fetchone()
                    if attempt["to_status"] == "done":
                        closed_pause_row = self._close_open_pause_if_any(
                            cur,
                            attempt["task_id"],
                            actor=actor,
                            comment="auto-closed on task completion",
                        )
                    self._emit_event(
                        cur,
                        "transition.approved",
                        project_key,
                        attempt["task_id"],
                        {"transition_attempt_id": attempt_id},
                    )
                    if attempt["to_status"] == "done":
                        if closed_pause_row is not None:
                            closed_pause = self._row_to_pause(closed_pause_row)
                            self._emit_event(
                                cur,
                                "pause.resumed",
                                project_key,
                                attempt["task_id"],
                                {
                                    "pause_id": closed_pause["id"],
                                    "auto_closed": True,
                                },
                            )
                        self._emit_event(
                            cur, "task.completed", project_key, attempt["task_id"], {}
                        )
                else:
                    cur.execute(
                        """
                        UPDATE transition_attempts
                        SET status = 'rejected',
                            resolved_by = %s,
                            resolved_comment = %s,
                            resolved_at = NOW()
                        WHERE id = %s
                        RETURNING id, task_id, from_status, to_status, gate_type, status,
                            reason, requested_by, requested_at, resolved_by,
                            resolved_comment, resolved_at
                        """,
                        (actor, comment, uuid.UUID(attempt_id)),
                    )
                    updated_attempt_row = cur.fetchone()
                    updated_task_row = task_row[:9]
                    self._emit_event(
                        cur,
                        "transition.rejected",
                        project_key,
                        attempt["task_id"],
                        {"transition_attempt_id": attempt_id},
                    )

            conn.commit()
        return {
            "attempt": self._row_to_transition_attempt(updated_attempt_row),
            "task": self._row_to_task(updated_task_row),
        }

    def create_pause(self, task_id, pause_type, payload):
        with self._connect() as conn:
            with conn.cursor() as cur:
                task_row = self._get_task_row(cur, task_id, for_update=True)
                if task_row is None:
                    return None
                if task_row[5] == "done":
                    return {"error": "task_done"}
                if self._get_open_pause_for_task(cur, task_id, for_update=True) is not None:
                    return {"error": "pause_exists"}

                cur.execute(
                    """
                    INSERT INTO pauses (
                        id, task_id, pause_type, reason, details, question,
                        requested_from, due_at, opened_by
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    RETURNING id, task_id, pause_type, reason, details, question,
                        requested_from, due_at, opened_by, opened_at,
                        closed_by, closed_comment, closed_at
                    """,
                    (
                        uuid.uuid4(),
                        uuid.UUID(task_id),
                        pause_type,
                        payload.get("reason"),
                        payload.get("details"),
                        payload.get("question"),
                        payload.get("requested_from"),
                        payload.get("due_at"),
                        payload.get("actor"),
                    ),
                )
                pause_row = cur.fetchone()
                pause = self._row_to_pause(pause_row)
                self._emit_event(
                    cur,
                    "pause.opened",
                    task_row[1],
                    task_id,
                    {"pause_id": pause["id"], "pause_type": pause["pause_type"]},
                )
            conn.commit()
        return pause

    def get_pause(self, pause_id):
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, task_id, pause_type, reason, details, question,
                        requested_from, due_at, opened_by, opened_at,
                        closed_by, closed_comment, closed_at
                    FROM pauses
                    WHERE id = %s
                    """,
                    (uuid.UUID(pause_id),),
                )
                row = cur.fetchone()
        return self._row_to_pause(row)

    def add_pause_answer(self, pause_id, actor, answer):
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, task_id, pause_type, reason, details, question,
                        requested_from, due_at, opened_by, opened_at,
                        closed_by, closed_comment, closed_at
                    FROM pauses
                    WHERE id = %s
                    FOR UPDATE
                    """,
                    (uuid.UUID(pause_id),),
                )
                pause_row = cur.fetchone()
                if pause_row is None:
                    return None
                pause = self._row_to_pause(pause_row)
                if pause["closed_at"] is not None:
                    return {"error": "pause_closed"}

                cur.execute(
                    """
                    INSERT INTO pause_answers (id, pause_id, actor, answer)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id, pause_id, actor, answer, created_at
                    """,
                    (uuid.uuid4(), uuid.UUID(pause_id), actor, answer),
                )
                answer_row = cur.fetchone()
                answer_record = self._row_to_pause_answer(answer_row)

                task_row = self._get_task_row(cur, pause["task_id"])
                self._emit_event(
                    cur,
                    "pause.answered",
                    task_row[1],
                    pause["task_id"],
                    {"pause_id": pause_id, "answer_id": answer_record["id"]},
                )
            conn.commit()
        return answer_record

    def resume_pause(self, pause_id, actor, comment=None):
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, task_id, pause_type, reason, details, question,
                        requested_from, due_at, opened_by, opened_at,
                        closed_by, closed_comment, closed_at
                    FROM pauses
                    WHERE id = %s
                    FOR UPDATE
                    """,
                    (uuid.UUID(pause_id),),
                )
                pause_row = cur.fetchone()
                if pause_row is None:
                    return None
                pause = self._row_to_pause(pause_row)
                if pause["closed_at"] is not None:
                    return {"error": "already_resolved", "pause": pause}

                if pause["pause_type"] == "awaiting_input":
                    cur.execute(
                        """
                        SELECT 1
                        FROM pause_answers
                        WHERE pause_id = %s
                        LIMIT 1
                        """,
                        (uuid.UUID(pause_id),),
                    )
                    if cur.fetchone() is None:
                        return {"error": "answers_required"}

                cur.execute(
                    """
                    UPDATE pauses
                    SET closed_by = %s,
                        closed_comment = %s,
                        closed_at = NOW()
                    WHERE id = %s
                    RETURNING id, task_id, pause_type, reason, details, question,
                        requested_from, due_at, opened_by, opened_at,
                        closed_by, closed_comment, closed_at
                    """,
                    (actor, comment, uuid.UUID(pause_id)),
                )
                updated_pause_row = cur.fetchone()
                updated_pause = self._row_to_pause(updated_pause_row)

                task_row = self._get_task_row(cur, updated_pause["task_id"])
                self._emit_event(
                    cur,
                    "pause.resumed",
                    task_row[1],
                    updated_pause["task_id"],
                    {"pause_id": updated_pause["id"], "auto_closed": False},
                )
            conn.commit()
        return updated_pause

    def _fetch_attention_rows(self, cur, project_key):
        cur.execute(
            """
            SELECT t.id, t.title, t.status, t.priority, t.assignee, t.updated_at,
                p.pause_type,
                EXISTS (
                    SELECT 1
                    FROM transition_attempts ta
                    WHERE ta.task_id = t.id
                        AND ta.status = 'pending'
                ) AS has_pending_approval
            FROM tasks t
            LEFT JOIN pauses p
                ON p.task_id = t.id
                AND p.closed_at IS NULL
            WHERE t.project_key = %s
            """,
            (project_key,),
        )
        return cur.fetchall()

    def _build_attention_queues_from_rows(self, rows):
        queues = _empty_attention_queues()
        for row in rows:
            task_id = row[0]
            title = row[1]
            status = row[2]
            priority = row[3]
            assignee = row[4]
            updated_at = row[5].isoformat() if row[5] is not None else None
            pause_type = row[6]
            has_pending_approval = bool(row[7])

            bucket = _attention_bucket_for(
                status=status,
                assignee=assignee,
                pause_type=pause_type,
                has_pending_approval=has_pending_approval,
            )
            if bucket is None:
                continue

            queues[bucket]["tasks"].append(
                _build_attention_task_summary(
                    task_id=task_id,
                    title=title,
                    status=status,
                    assignee=assignee,
                    pause_type=pause_type,
                    priority=priority,
                    updated_at=updated_at,
                    has_pending_approval=has_pending_approval,
                )
            )
        return _finalize_attention_queues(queues)

    def get_attention_queues(self, project_key):
        with self._connect() as conn:
            with conn.cursor() as cur:
                rows = self._fetch_attention_rows(cur, project_key)
        return self._build_attention_queues_from_rows(rows)

    def get_ui_snapshot(self, project_key):
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COALESCE(MAX(cursor), 0) FROM events")
                current_cursor = int(cur.fetchone()[0] or 0)

                attention_rows = self._fetch_attention_rows(cur, project_key)
                queues = self._build_attention_queues_from_rows(attention_rows)

                cur.execute(
                    """
                    SELECT id, project_key, parent_task_id, title, description,
                        status, priority, assignee, result_summary, updated_at
                    FROM tasks
                    WHERE project_key = %s
                    ORDER BY priority DESC, updated_at DESC, id DESC
                    """,
                    (project_key,),
                )
                task_rows = cur.fetchall()
                tasks = [
                    {
                        "id": str(row[0]),
                        "project_key": row[1],
                        "parent_task_id": str(row[2]) if row[2] is not None else None,
                        "title": row[3],
                        "description": row[4],
                        "status": row[5],
                        "priority": row[6],
                        "assignee": row[7],
                        "summary": row[8],
                        "artifacts": [],
                        "updated_at": row[9].isoformat() if row[9] is not None else None,
                    }
                    for row in task_rows
                ]

                cur.execute(
                    """
                    SELECT ta.id, ta.task_id, ta.from_status, ta.to_status, ta.gate_type,
                        ta.status, ta.reason, ta.requested_by, ta.requested_at,
                        ta.resolved_by, ta.resolved_comment, ta.resolved_at
                    FROM transition_attempts ta
                    JOIN tasks t ON t.id = ta.task_id
                    WHERE t.project_key = %s
                        AND ta.status = 'pending'
                    ORDER BY ta.requested_at ASC, ta.id ASC
                    """,
                    (project_key,),
                )
                pending_transition_rows = cur.fetchall()
                pending_transitions = [
                    self._row_to_transition_attempt(row)
                    for row in pending_transition_rows
                ]

                cur.execute(
                    """
                    SELECT p.id, p.task_id, p.pause_type, p.reason, p.details, p.question,
                        p.requested_from, p.due_at, p.opened_by, p.opened_at,
                        p.closed_by, p.closed_comment, p.closed_at
                    FROM pauses p
                    JOIN tasks t ON t.id = p.task_id
                    WHERE t.project_key = %s
                        AND p.closed_at IS NULL
                    ORDER BY p.opened_at ASC, p.id ASC
                    """,
                    (project_key,),
                )
                open_pause_rows = cur.fetchall()
                open_pauses = [self._row_to_pause(row) for row in open_pause_rows]

        return {
            "cursor": current_cursor,
            "queues": queues,
            "tasks": tasks,
            "pending_transitions": pending_transitions,
            "open_pauses": open_pauses,
        }

    def get_events_since(self, cursor, limit=200):
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT cursor, event_type, project_key, task_id, occurred_at, payload
                    FROM events
                    WHERE cursor > %s
                    ORDER BY cursor ASC
                    LIMIT %s
                    """,
                    (int(cursor), int(limit)),
                )
                rows = cur.fetchall()
        return [self._row_to_event(row) for row in rows]

    def wait_for_events(self, cursor, timeout_seconds, limit=200):
        deadline = time.monotonic() + float(timeout_seconds)
        while True:
            events = self.get_events_since(cursor, limit=limit)
            if events:
                return events
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return []
            time.sleep(min(0.5, remaining))


_RUNTIME_STORE = PostgresTaskStore()


def set_runtime_store(store):
    global _RUNTIME_STORE
    _RUNTIME_STORE = store


def get_runtime_store():
    return _RUNTIME_STORE


def reset_runtime_store():
    get_runtime_store().reset()


def reset_store():
    reset_runtime_store()


def _error(status, code, message):
    return status, {
        "error": {
            "code": code,
            "message": message,
        }
    }


def _task_copy(task):
    payload = dict(task)
    payload["artifacts"] = list(payload.get("artifacts") or [])
    if "priority" not in payload or payload["priority"] is None:
        payload["priority"] = 50
    return payload


def _new_task_id():
    return str(uuid.uuid4())


def _lookup_task(task_id):
    return get_runtime_store().get_task(task_id)


def create_task(payload):
    project_key = payload.get("project_key")
    title = payload.get("title")
    if not project_key or not title:
        return _error(
            HTTPStatus.BAD_REQUEST,
            "invalid_request",
            "project_key and title are required",
        )

    priority = payload.get("priority", 50)
    if not isinstance(priority, int) or priority < 0 or priority > 100:
        return _error(
            HTTPStatus.BAD_REQUEST,
            "invalid_request",
            "priority must be an integer between 0 and 100",
        )

    task = {
        "id": _new_task_id(),
        "project_key": project_key,
        "parent_task_id": payload.get("parent_task_id"),
        "title": title,
        "description": payload.get("description"),
        "status": "backlog",
        "priority": priority,
        "assignee": payload.get("assignee"),
        "summary": payload.get("summary"),
        "artifacts": list(payload.get("artifacts") or []),
    }
    created = get_runtime_store().create_task(task)
    return HTTPStatus.CREATED, {"task": _task_copy(created)}


def get_task(task_id):
    task = _lookup_task(task_id)
    if task is None:
        return _error(HTTPStatus.NOT_FOUND, "not_found", "task not found")
    return HTTPStatus.OK, {"task": _task_copy(task)}


def get_attention_queues(project_key):
    if not isinstance(project_key, str) or not project_key.strip():
        return _error(
            HTTPStatus.BAD_REQUEST,
            "invalid_request",
            "project_key query parameter is required",
        )

    normalized_project_key = project_key.strip()
    queues = get_runtime_store().get_attention_queues(normalized_project_key)
    return HTTPStatus.OK, {
        "project_key": normalized_project_key,
        "queues": queues,
    }


def get_ui_snapshot(project_key):
    if not isinstance(project_key, str) or not project_key.strip():
        return _error(
            HTTPStatus.BAD_REQUEST,
            "invalid_request",
            "project_key query parameter is required",
        )

    normalized_project_key = project_key.strip()
    snapshot = get_runtime_store().get_ui_snapshot(normalized_project_key)
    return HTTPStatus.OK, snapshot


def _parse_non_negative_int(value, field_name):
    if value is None:
        raise ValueError(f"{field_name} query parameter is required")
    try:
        parsed = int(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a non-negative integer") from exc
    if parsed < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return parsed


def _parse_timeout_seconds(value):
    if value is None:
        return 20
    try:
        parsed = int(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError("timeout must be an integer between 1 and 30") from exc
    if parsed < 1 or parsed > 30:
        raise ValueError("timeout must be an integer between 1 and 30")
    return parsed


def _wait_for_events(store, cursor, timeout_seconds, limit=200):
    if hasattr(store, "wait_for_events"):
        return store.wait_for_events(cursor, timeout_seconds, limit=limit)

    deadline = time.monotonic() + float(timeout_seconds)
    while True:
        events = store.get_events_since(cursor, limit=limit)
        if events:
            return events
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return []
        time.sleep(min(0.5, remaining))


def get_ui_updates(cursor, timeout=None):
    try:
        cursor_value = _parse_non_negative_int(cursor, "cursor")
        timeout_seconds = _parse_timeout_seconds(timeout)
    except ValueError as exc:
        return _error(
            HTTPStatus.BAD_REQUEST,
            "invalid_request",
            str(exc),
        )

    events = _wait_for_events(
        get_runtime_store(),
        cursor_value,
        timeout_seconds,
    )
    if not events:
        return HTTPStatus.OK, {"cursor": cursor_value, "events": []}
    return HTTPStatus.OK, {
        "cursor": int(events[-1]["cursor"]),
        "events": events,
    }


def patch_task(task_id, payload):
    task = _lookup_task(task_id)
    if task is None:
        return _error(HTTPStatus.NOT_FOUND, "not_found", "task not found")

    if "status" in payload:
        return _error(
            HTTPStatus.BAD_REQUEST,
            "invalid_request",
            "status cannot be updated via patch",
        )

    updates = {}
    for field in ("title", "description", "priority", "assignee"):
        if field in payload:
            updates[field] = payload[field]
    if "priority" in updates and (
        not isinstance(updates["priority"], int)
        or updates["priority"] < 0
        or updates["priority"] > 100
    ):
        return _error(
            HTTPStatus.BAD_REQUEST,
            "invalid_request",
            "priority must be an integer between 0 and 100",
        )

    updated = get_runtime_store().update_task(task_id, updates)
    return HTTPStatus.OK, {"task": _task_copy(updated)}


def create_child_task(parent_task_id, payload):
    parent = _lookup_task(parent_task_id)
    if parent is None:
        return _error(HTTPStatus.NOT_FOUND, "not_found", "parent task not found")

    child_payload = dict(payload)
    child_payload["project_key"] = parent["project_key"]
    child_payload["parent_task_id"] = parent_task_id
    return create_task(child_payload)


def claim_task(task_id, payload):
    task = _lookup_task(task_id)
    if task is None:
        return _error(HTTPStatus.NOT_FOUND, "not_found", "task not found")

    assignee = payload.get("assignee")
    if not assignee:
        return _error(
            HTTPStatus.BAD_REQUEST,
            "invalid_request",
            "assignee is required",
        )

    updated = get_runtime_store().update_task(task_id, {"assignee": assignee})
    return HTTPStatus.OK, {"task": _task_copy(updated)}


def start_work(task_id):
    return request_transition(
        task_id,
        {"target_status": "in_progress", "reason": "start_work"},
    )


def request_transition(task_id, payload):
    target_status = payload.get("target_status")
    if not target_status or target_status not in ALLOWED_STATUSES:
        return _error(
            HTTPStatus.BAD_REQUEST,
            "invalid_request",
            "target_status must be one of backlog, ready, in_progress, done",
        )

    outcome = get_runtime_store().request_transition(
        task_id,
        target_status,
        reason=payload.get("reason"),
        requested_by=payload.get("actor"),
    )
    if outcome is None:
        return _error(HTTPStatus.NOT_FOUND, "not_found", "task not found")
    if outcome.get("error") == "invalid_transition":
        return _error(
            HTTPStatus.CONFLICT,
            "invalid_transition",
            "requested transition is not allowed for current task status",
        )
    if outcome.get("error") == "pending_transition_exists":
        return HTTPStatus.CONFLICT, {
            "error": {
                "code": "pending_transition_exists",
                "message": "task already has a pending transition attempt",
            },
            "task": _task_copy(outcome["task"]),
            "transition_attempt": dict(outcome["attempt"]),
        }

    attempt = outcome["attempt"]
    task = outcome["task"]
    status = (
        HTTPStatus.ACCEPTED
        if attempt.get("status") == "pending"
        else HTTPStatus.OK
    )
    return status, {
        "task": _task_copy(task),
        "transition_attempt": dict(attempt),
    }


def get_transition_attempt(attempt_id):
    attempt = get_runtime_store().get_transition_attempt(attempt_id)
    if attempt is None:
        return _error(HTTPStatus.NOT_FOUND, "not_found", "transition attempt not found")
    return HTTPStatus.OK, {"transition_attempt": dict(attempt)}


def approve_transition_attempt(attempt_id, payload):
    actor = payload.get("actor")
    if not actor:
        return _error(
            HTTPStatus.BAD_REQUEST,
            "invalid_request",
            "actor is required",
        )
    outcome = get_runtime_store().resolve_transition_attempt(
        attempt_id,
        "approve",
        actor,
        comment=payload.get("comment"),
    )
    if outcome is None:
        return _error(HTTPStatus.NOT_FOUND, "not_found", "transition attempt not found")
    if outcome.get("error") == "already_resolved":
        return _error(
            HTTPStatus.CONFLICT,
            "already_resolved",
            "transition attempt is already resolved",
        )
    if outcome.get("error") == "stale_transition":
        return HTTPStatus.CONFLICT, {
            "error": {
                "code": "stale_transition",
                "message": "task status no longer matches the transition attempt source status",
            },
            "task": _task_copy(outcome["task"]),
            "transition_attempt": dict(outcome["attempt"]),
        }
    return HTTPStatus.OK, {
        "task": _task_copy(outcome["task"]),
        "transition_attempt": dict(outcome["attempt"]),
    }


def reject_transition_attempt(attempt_id, payload):
    actor = payload.get("actor")
    if not actor:
        return _error(
            HTTPStatus.BAD_REQUEST,
            "invalid_request",
            "actor is required",
        )
    comment = payload.get("comment")
    if not isinstance(comment, str) or not comment.strip():
        return _error(
            HTTPStatus.BAD_REQUEST,
            "invalid_request",
            "comment is required when rejecting a transition",
        )
    outcome = get_runtime_store().resolve_transition_attempt(
        attempt_id,
        "reject",
        actor,
        comment=comment.strip(),
    )
    if outcome is None:
        return _error(HTTPStatus.NOT_FOUND, "not_found", "transition attempt not found")
    if outcome.get("error") == "already_resolved":
        return _error(
            HTTPStatus.CONFLICT,
            "already_resolved",
            "transition attempt is already resolved",
        )
    if outcome.get("error") == "stale_transition":
        return HTTPStatus.CONFLICT, {
            "error": {
                "code": "stale_transition",
                "message": "task status no longer matches the transition attempt source status",
            },
            "task": _task_copy(outcome["task"]),
            "transition_attempt": dict(outcome["attempt"]),
        }
    return HTTPStatus.OK, {
        "task": _task_copy(outcome["task"]),
        "transition_attempt": dict(outcome["attempt"]),
    }


def report_result(task_id, payload):
    task = _lookup_task(task_id)
    if task is None:
        return _error(HTTPStatus.NOT_FOUND, "not_found", "task not found")

    updates = {}
    if "summary" in payload:
        updates["summary"] = payload["summary"]
    if "artifacts" in payload:
        updates["artifacts"] = list(payload.get("artifacts") or [])

    updated = get_runtime_store().update_task(task_id, updates)
    return HTTPStatus.OK, {"task": _task_copy(updated)}


def _parse_optional_rfc3339(value):
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("due_at must be a valid RFC3339 timestamp")
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError("due_at must be a valid RFC3339 timestamp") from exc
    return value.strip()


def open_blocked_pause(task_id, payload):
    reason = payload.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        return _error(
            HTTPStatus.BAD_REQUEST,
            "invalid_request",
            "reason is required",
        )
    reason = reason.strip()
    if len(reason) > 500:
        return _error(
            HTTPStatus.BAD_REQUEST,
            "invalid_request",
            "reason must be 500 characters or fewer",
        )

    details = payload.get("details")
    if details is not None:
        if not isinstance(details, str):
            return _error(
                HTTPStatus.BAD_REQUEST,
                "invalid_request",
                "details must be a string when provided",
            )
        if len(details) > 5000:
            return _error(
                HTTPStatus.BAD_REQUEST,
                "invalid_request",
                "details must be 5000 characters or fewer",
            )

    outcome = get_runtime_store().create_pause(
        task_id,
        "blocked",
        {
            "reason": reason,
            "details": details,
            "actor": payload.get("actor"),
        },
    )
    if outcome is None:
        return _error(HTTPStatus.NOT_FOUND, "not_found", "task not found")
    if outcome.get("error") == "task_done":
        return _error(
            HTTPStatus.CONFLICT,
            "invalid_state",
            "cannot open a pause for a task in done status",
        )
    if outcome.get("error") == "pause_exists":
        return _error(
            HTTPStatus.CONFLICT,
            "pause_already_open",
            "task already has an open pause",
        )
    return HTTPStatus.CREATED, {"pause": dict(outcome)}


def open_awaiting_input_pause(task_id, payload):
    question = payload.get("question")
    if not isinstance(question, str) or not question.strip():
        return _error(
            HTTPStatus.BAD_REQUEST,
            "invalid_request",
            "question is required",
        )
    question = question.strip()
    if len(question) > 1000:
        return _error(
            HTTPStatus.BAD_REQUEST,
            "invalid_request",
            "question must be 1000 characters or fewer",
        )

    requested_from = payload.get("requested_from")
    if requested_from is not None:
        if not isinstance(requested_from, str) or not requested_from.strip():
            return _error(
                HTTPStatus.BAD_REQUEST,
                "invalid_request",
                "requested_from must be a non-empty string when provided",
            )
        if len(requested_from.strip()) > 120:
            return _error(
                HTTPStatus.BAD_REQUEST,
                "invalid_request",
                "requested_from must be 120 characters or fewer",
            )
        requested_from = requested_from.strip()

    due_at = payload.get("due_at")
    try:
        due_at = _parse_optional_rfc3339(due_at)
    except ValueError as exc:
        return _error(HTTPStatus.BAD_REQUEST, "invalid_request", str(exc))

    outcome = get_runtime_store().create_pause(
        task_id,
        "awaiting_input",
        {
            "question": question,
            "requested_from": requested_from,
            "due_at": due_at,
            "actor": payload.get("actor"),
        },
    )
    if outcome is None:
        return _error(HTTPStatus.NOT_FOUND, "not_found", "task not found")
    if outcome.get("error") == "task_done":
        return _error(
            HTTPStatus.CONFLICT,
            "invalid_state",
            "cannot open a pause for a task in done status",
        )
    if outcome.get("error") == "pause_exists":
        return _error(
            HTTPStatus.CONFLICT,
            "pause_already_open",
            "task already has an open pause",
        )
    return HTTPStatus.CREATED, {"pause": dict(outcome)}


def answer_pause(pause_id, payload):
    actor = payload.get("actor")
    if not isinstance(actor, str) or not actor.strip():
        return _error(
            HTTPStatus.BAD_REQUEST,
            "invalid_request",
            "actor is required",
        )
    actor = actor.strip()
    answer = payload.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        return _error(
            HTTPStatus.BAD_REQUEST,
            "invalid_request",
            "answer is required",
        )
    answer = answer.strip()
    if len(answer) > 5000:
        return _error(
            HTTPStatus.BAD_REQUEST,
            "invalid_request",
            "answer must be 5000 characters or fewer",
        )

    outcome = get_runtime_store().add_pause_answer(pause_id, actor, answer)
    if outcome is None:
        return _error(HTTPStatus.NOT_FOUND, "not_found", "pause not found")
    if outcome.get("error") == "pause_closed":
        return _error(
            HTTPStatus.CONFLICT,
            "pause_closed",
            "cannot answer a closed pause",
        )
    return HTTPStatus.CREATED, {"answer": dict(outcome)}


def resume_pause(pause_id, payload):
    actor = payload.get("actor")
    if not isinstance(actor, str) or not actor.strip():
        return _error(
            HTTPStatus.BAD_REQUEST,
            "invalid_request",
            "actor is required",
        )
    actor = actor.strip()

    comment = payload.get("comment")
    if comment is not None and not isinstance(comment, str):
        return _error(
            HTTPStatus.BAD_REQUEST,
            "invalid_request",
            "comment must be a string when provided",
        )

    outcome = get_runtime_store().resume_pause(pause_id, actor, comment=comment)
    if outcome is None:
        return _error(HTTPStatus.NOT_FOUND, "not_found", "pause not found")
    if outcome.get("error") == "already_resolved":
        return _error(
            HTTPStatus.CONFLICT,
            "already_resolved",
            "pause is already resolved",
        )
    if outcome.get("error") == "answers_required":
        return _error(
            HTTPStatus.CONFLICT,
            "answers_required",
            "awaiting_input pause requires at least one answer before resume",
        )
    return HTTPStatus.OK, {"pause": dict(outcome)}


def _path_parts(path):
    parsed = urlparse(path)
    return [part for part in parsed.path.split("/") if part]


def route_operational_ui(path):
    parsed = urlparse(path)
    if parsed.path not in ("", "/", "/ui", "/ui/"):
        return None

    query = parse_qs(parsed.query, keep_blank_values=True)
    project_key = query.get("project_key", [TASK_TRACKER_UI_PROJECT_KEY])[0]
    if not isinstance(project_key, str) or not project_key.strip():
        project_key = TASK_TRACKER_UI_PROJECT_KEY
    return HTTPStatus.OK, render_operational_ui_html(project_key)


class TaskTrackerHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def _send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, status, body, content_type):
        if isinstance(body, str):
            payload = body.encode("utf-8")
        else:
            payload = body or b""
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}

        raw = self.rfile.read(length)
        if not raw:
            return {}

        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("invalid json body") from exc

    def do_GET(self):
        ui_response = route_operational_ui(self.path)
        if ui_response is not None:
            status, body = ui_response
            self._send_text(status, body, "text/html; charset=utf-8")
            return

        status, payload = route_get(self.path)
        self._send_json(status, payload)

    def do_POST(self):
        try:
            body = self._read_json_body()
        except ValueError:
            status, payload = _error(
                HTTPStatus.BAD_REQUEST,
                "invalid_json",
                "request body must be valid JSON",
            )
            self._send_json(status, payload)
            return

        status, payload = route_post(self.path, body)
        self._send_json(status, payload)

    def do_PATCH(self):
        try:
            body = self._read_json_body()
        except ValueError:
            status, payload = _error(
                HTTPStatus.BAD_REQUEST,
                "invalid_json",
                "request body must be valid JSON",
            )
            self._send_json(status, payload)
            return

        status, payload = route_patch(self.path, body)
        self._send_json(status, payload)


def create_server(host, port):
    return ThreadingHTTPServer((host, int(port)), TaskTrackerHandler)


def route_get(path):
    parsed = urlparse(path)
    if parsed.path == "/healthz":
        return HTTPStatus.OK, {"status": "ok"}
    if parsed.path == "/api/v1/ui/snapshot":
        query = parse_qs(parsed.query, keep_blank_values=True)
        project_key = query.get("project_key", [None])[0]
        return get_ui_snapshot(project_key)
    if parsed.path == "/api/v1/ui/updates":
        query = parse_qs(parsed.query, keep_blank_values=True)
        cursor = query.get("cursor", [None])[0]
        timeout = query.get("timeout", [None])[0]
        return get_ui_updates(cursor, timeout)
    if parsed.path == "/api/v1/queues/attention":
        query = parse_qs(parsed.query, keep_blank_values=True)
        project_key = query.get("project_key", [None])[0]
        return get_attention_queues(project_key)

    parts = _path_parts(path)
    if len(parts) == 4 and parts[:3] == ["api", "v1", "tasks"]:
        return get_task(parts[3])
    if len(parts) == 4 and parts[:3] == ["api", "v1", "transitions"]:
        return get_transition_attempt(parts[3])

    return HTTPStatus.NOT_FOUND, {
        "error": {
            "code": "not_found",
            "message": "route not found",
        }
    }


def route_post(path, payload):
    parts = _path_parts(path)
    if parts == ["api", "v1", "tasks"]:
        return create_task(payload)

    if len(parts) == 5 and parts[:3] == ["api", "v1", "tasks"] and parts[4] == "children":
        return create_child_task(parts[3], payload)

    if len(parts) == 5 and parts[:3] == ["api", "v1", "tasks"] and parts[4] == "transitions":
        return request_transition(parts[3], payload)

    if len(parts) == 6 and parts[:3] == ["api", "v1", "tasks"] and parts[4] == "actions":
        task_id = parts[3]
        action = parts[5]
        if action == "claim":
            return claim_task(task_id, payload)
        if action == "start_work":
            return start_work(task_id)
        if action == "report_result":
            return report_result(task_id, payload)

    if len(parts) == 6 and parts[:3] == ["api", "v1", "tasks"] and parts[4] == "pauses":
        task_id = parts[3]
        pause_type = parts[5]
        if pause_type == "blocked":
            return open_blocked_pause(task_id, payload)
        if pause_type == "awaiting_input":
            return open_awaiting_input_pause(task_id, payload)

    if len(parts) == 5 and parts[:3] == ["api", "v1", "pauses"]:
        pause_id = parts[3]
        action = parts[4]
        if action == "answers":
            return answer_pause(pause_id, payload)
        if action == "resume":
            return resume_pause(pause_id, payload)

    if len(parts) == 5 and parts[:3] == ["api", "v1", "transitions"]:
        attempt_id = parts[3]
        action = parts[4]
        if action == "approve":
            return approve_transition_attempt(attempt_id, payload)
        if action == "reject":
            return reject_transition_attempt(attempt_id, payload)

    return HTTPStatus.NOT_FOUND, {
        "error": {
            "code": "not_found",
            "message": "route not found",
        }
    }


def route_patch(path, payload):
    parts = _path_parts(path)
    if len(parts) == 4 and parts[:3] == ["api", "v1", "tasks"]:
        return patch_task(parts[3], payload)

    return HTTPStatus.NOT_FOUND, {
        "error": {
            "code": "not_found",
            "message": "route not found",
        }
    }


def main():
    server = create_server(TASK_TRACKER_HOST, TASK_TRACKER_PORT)
    print(
        "task-tracker listening on "
        f"http://{TASK_TRACKER_HOST}:{TASK_TRACKER_PORT}",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
