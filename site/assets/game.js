const GRID_SIZE = 18;
const CELL_SIZE = 20;
const LOOP_MS = 140;
const UPDATE_CHECK_MS = 30_000;

const board = document.getElementById("game-board");
const context = board.getContext("2d");
const scoreNode = document.getElementById("score");
const statusNode = document.getElementById("status");
const currentVersionNode = document.getElementById("current-version");
const serverBestNode = document.getElementById("server-best");
const updateBannerNode = document.getElementById("update-banner");
const updateVersionNode = document.getElementById("update-version");
const restartButton = document.getElementById("restart-button");
const refreshButton = document.getElementById("refresh-button");
const currentVersion = document.body.dataset.appVersion || "0.0.0";

const state = {
  snake: [],
  direction: { x: 1, y: 0 },
  nextDirection: { x: 1, y: 0 },
  food: { x: 0, y: 0 },
  score: 0,
  tickHandle: null,
  isGameOver: false,
  hasUpdateNotice: false,
  remoteBestScore: null,
  statusText: "Running",
};

function sameCell(left, right) {
  return left.x === right.x && left.y === right.y;
}

function updateHud(statusText) {
  if (statusText) {
    state.statusText = statusText;
  }

  scoreNode.textContent = String(state.score);
  statusNode.textContent = state.statusText;
  currentVersionNode.textContent = currentVersion;
  serverBestNode.textContent =
    state.remoteBestScore === null ? "--" : String(state.remoteBestScore);
}

function randomCell() {
  return {
    x: Math.floor(Math.random() * GRID_SIZE),
    y: Math.floor(Math.random() * GRID_SIZE),
  };
}

function spawnFood() {
  let candidate = randomCell();

  while (state.snake.some((segment) => sameCell(segment, candidate))) {
    candidate = randomCell();
  }

  state.food = candidate;
}

function drawGrid() {
  context.strokeStyle = "rgba(153, 255, 153, 0.08)";
  context.lineWidth = 1;

  for (let i = 1; i < GRID_SIZE; i += 1) {
    const lineOffset = i * CELL_SIZE;

    context.beginPath();
    context.moveTo(lineOffset, 0);
    context.lineTo(lineOffset, board.height);
    context.stroke();

    context.beginPath();
    context.moveTo(0, lineOffset);
    context.lineTo(board.width, lineOffset);
    context.stroke();
  }
}

function drawCell(cell, fillStyle) {
  const x = cell.x * CELL_SIZE;
  const y = cell.y * CELL_SIZE;
  const inset = 2;

  context.fillStyle = fillStyle;
  context.fillRect(
    x + inset,
    y + inset,
    CELL_SIZE - inset * 2,
    CELL_SIZE - inset * 2,
  );
}

function drawGameOver() {
  context.fillStyle = "rgba(4, 11, 20, 0.74)";
  context.fillRect(0, board.height / 2 - 38, board.width, 76);

  context.fillStyle = "#eef7f2";
  context.font = 'bold 18px "Avenir Next Condensed", "Trebuchet MS", sans-serif';
  context.textAlign = "center";
  context.fillText("Crash detected", board.width / 2, board.height / 2 - 4);

  context.fillStyle = "#9db1ab";
  context.font = '14px "Cascadia Mono", "SFMono-Regular", monospace';
  context.fillText("Press restart or space", board.width / 2, board.height / 2 + 20);
}

function draw() {
  context.clearRect(0, 0, board.width, board.height);

  context.fillStyle = "rgba(6, 12, 22, 0.94)";
  context.fillRect(0, 0, board.width, board.height);

  drawGrid();
  drawCell(state.food, "#ffd36a");

  state.snake.forEach((segment, index) => {
    const color = index === 0 ? "#c7ff7b" : "#6df04e";
    drawCell(segment, color);
  });

  if (state.isGameOver) {
    drawGameOver();
  }
}

function stopLoop() {
  if (state.tickHandle !== null) {
    window.clearInterval(state.tickHandle);
    state.tickHandle = null;
  }
}

function endGame() {
  stopLoop();
  state.isGameOver = true;
  updateHud("Crashed");
  draw();
  void syncRemoteBestScore();
}

function step() {
  state.direction = { ...state.nextDirection };

  const head = state.snake[0];
  const nextHead = {
    x: head.x + state.direction.x,
    y: head.y + state.direction.y,
  };
  const willGrow = sameCell(nextHead, state.food);
  const occupiedCells = willGrow ? state.snake : state.snake.slice(0, -1);

  const crashed =
    nextHead.x < 0 ||
    nextHead.x >= GRID_SIZE ||
    nextHead.y < 0 ||
    nextHead.y >= GRID_SIZE ||
    occupiedCells.some((segment) => sameCell(segment, nextHead));

  if (crashed) {
    endGame();
    return;
  }

  state.snake.unshift(nextHead);

  if (willGrow) {
    state.score += 1;
    updateHud("Running");
    spawnFood();
    void syncRemoteBestScore();
  } else {
    state.snake.pop();
  }

  draw();
}

function startGame() {
  stopLoop();

  const center = Math.floor(GRID_SIZE / 2);

  state.snake = [
    { x: center, y: center },
    { x: center - 1, y: center },
    { x: center - 2, y: center },
  ];
  state.direction = { x: 1, y: 0 };
  state.nextDirection = { x: 1, y: 0 };
  state.score = 0;
  state.isGameOver = false;

  spawnFood();
  updateHud("Running");
  draw();

  state.tickHandle = window.setInterval(step, LOOP_MS);
}

function queueDirection(nextDirection) {
  const reversing =
    nextDirection.x === state.direction.x * -1 &&
    nextDirection.y === state.direction.y * -1;

  if (!reversing) {
    state.nextDirection = nextDirection;
  }
}

function revealUpdateNotice(nextVersion) {
  if (state.hasUpdateNotice) {
    return;
  }

  state.hasUpdateNotice = true;
  updateVersionNode.textContent = nextVersion;
  updateBannerNode.hidden = false;
}

async function checkForUpdate() {
  try {
    // Keep default caching so the browser reuses validators and respects nginx TTL.
    const response = await window.fetch("/version.json", {
      headers: { Accept: "application/json" },
    });

    if (!response.ok) {
      return;
    }

    const payload = await response.json();

    if (payload.version && payload.version !== currentVersion) {
      revealUpdateNotice(payload.version);
    }
  } catch (error) {
    console.debug("Version check failed", error);
  }
}

async function loadRemoteState() {
  try {
    const response = await window.fetch("/api/state", {
      headers: { Accept: "application/json" },
    });

    if (!response.ok) {
      return;
    }

    const payload = await response.json();

    if (typeof payload.bestScore === "number") {
      state.remoteBestScore = payload.bestScore;
      updateHud();
    }
  } catch (error) {
    console.debug("State bootstrap failed", error);
  }
}

async function syncRemoteBestScore() {
  const candidate = state.score;

  if (
    state.remoteBestScore !== null &&
    candidate <= state.remoteBestScore
  ) {
    return;
  }

  try {
    const response = await window.fetch("/api/state", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify({ bestScore: candidate }),
    });

    if (!response.ok) {
      return;
    }

    const payload = await response.json();

    if (typeof payload.bestScore === "number") {
      state.remoteBestScore = payload.bestScore;
      updateHud();
    }
  } catch (error) {
    console.debug("State sync failed", error);
  }
}

document.addEventListener("keydown", (event) => {
  const directionMap = {
    ArrowUp: { x: 0, y: -1 },
    ArrowDown: { x: 0, y: 1 },
    ArrowLeft: { x: -1, y: 0 },
    ArrowRight: { x: 1, y: 0 },
  };

  if (event.code === "Space" && state.isGameOver) {
    event.preventDefault();
    startGame();
    return;
  }

  const nextDirection = directionMap[event.key];

  if (!nextDirection) {
    return;
  }

  event.preventDefault();
  queueDirection(nextDirection);
});

restartButton.addEventListener("click", startGame);
refreshButton.addEventListener("click", () => window.location.reload());

startGame();
void loadRemoteState();
window.setTimeout(checkForUpdate, 5_000);
window.setInterval(checkForUpdate, UPDATE_CHECK_MS);
