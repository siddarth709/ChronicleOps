const API = ""; 

const envListEl = document.getElementById("environments-list");
const envTotalBadge = document.getElementById("env-total-badge");
const globalHealthEl = document.getElementById("global-health");
const activeEnvCountEl = document.getElementById("active-env-count");
const statusDot = document.getElementById("status-dot");
const statusLabelEl = document.getElementById("status-label");
const mttrEl = document.getElementById("mttr-readout");
const diagnosisEl = document.getElementById("diagnosis-output");
const canvas = document.getElementById("uptime-chart");
const ctx = canvas.getContext("2d");
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

const STATUS_LABELS = {
  ready: "ready",
  provisioning: "provisioning",
  error: "error",
  destroyed: "destroyed",
};

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}

let selectedEnvironmentId = null;
let timeline = [];
let showDestroyed = false;

const toggleDestroyedBtn = document.getElementById("toggle-destroyed-btn");
toggleDestroyedBtn.addEventListener("click", () => {
  showDestroyed = !showDestroyed;
  refreshEnvironments();
});

const judgeStatusEl = document.getElementById("judge-status");

document.getElementById("demo-quickstart-btn").addEventListener("click", async (e) => {
  e.target.disabled = true;
  judgeStatusEl.textContent = "Spawning demo environment and triggering a kill experiment…";
  try {
    const res = await fetch(`${API}/api/demo/quickstart`, { method: "POST" });
    const data = await res.json();
    selectedEnvironmentId = data.environment_id;
    timeline = [];
    judgeStatusEl.textContent = `Demo running against ${data.demo_repo} — watch the status panel below.`;
    await refreshEnvironments();
  } catch (err) {
    judgeStatusEl.textContent = "Demo quickstart failed — check that Zerops secrets are configured.";
  } finally {
    e.target.disabled = false;
  }
});

document.getElementById("seed-samples-btn").addEventListener("click", async (e) => {
  const res = await fetch(`${API}/api/demo/seed-samples`, { method: "POST" });
  const data = await res.json();
  judgeStatusEl.textContent = data.status === "already_seeded"
    ? `Sample incidents already loaded (${data.count}).`
    : `Loaded ${data.count} sample incidents for the matcher to compare against.`;
});

document.getElementById("reset-samples-btn").addEventListener("click", async () => {
  await fetch(`${API}/api/demo/reset-samples`, { method: "POST" });
  judgeStatusEl.textContent = "Sample incidents cleared.";
});

document.getElementById("spawn-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const repo_url = document.getElementById("repo-url").value.trim();
  if (!repo_url) return;
  await fetch(`${API}/api/environments`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ repo_url }),
  });
  document.getElementById("repo-url").value = "";
  await refreshEnvironments();
});

async function refreshEnvironments() {
  let envs;
  try {
    const res = await fetch(`${API}/api/environments`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    envs = await res.json();
  } catch (err) {
    envListEl.innerHTML = `<div class="error-state">Couldn't load environments — retrying…</div>`;
    return;
  }

  envTotalBadge.textContent = `${envs.length} TOTAL`;

  const activeCount = envs.filter((e) => e.status === "ready" || e.status === "provisioning").length;
  activeEnvCountEl.textContent = activeCount;

  const hasError = envs.some((e) => e.status === "error");
  if (envs.length === 0) {
    globalHealthEl.textContent = "IDLE";
    globalHealthEl.className = "stat-val val-muted";
  } else if (hasError) {
    globalHealthEl.textContent = "DEGRADED";
    globalHealthEl.className = "stat-val val-red";
  } else {
    globalHealthEl.textContent = "OPERATIONAL";
    globalHealthEl.className = "stat-val val-green";
  }

  if (envs.length === 0) {
    envListEl.innerHTML = `<div class="empty-state">No environments yet — spawn one above or run the demo.</div>`;
    toggleDestroyedBtn.style.display = "none";
    return;
  }

  const destroyedCount = envs.filter((e) => e.status === "destroyed").length;
  if (destroyedCount === 0) {
    toggleDestroyedBtn.style.display = "none";
  } else {
    toggleDestroyedBtn.style.display = "";
    toggleDestroyedBtn.textContent = showDestroyed
      ? `Hide destroyed (${destroyedCount})`
      : `Show destroyed (${destroyedCount})`;
  }

  const STATUS_ORDER = { ready: 0, provisioning: 1, error: 2, destroyed: 3 };
  const visibleEnvs = envs
    .filter((e) => showDestroyed || e.status !== "destroyed")
    .sort((a, b) => (STATUS_ORDER[a.status] ?? 9) - (STATUS_ORDER[b.status] ?? 9));

  if (visibleEnvs.length === 0) {
    envListEl.innerHTML = `<div class="empty-state">All ${destroyedCount} environments are destroyed — click "Show destroyed" to view them.</div>`;
    return;
  }

  envListEl.innerHTML = "";
  visibleEnvs.forEach((env) => {
    const repoLabel = escapeHtml(env.repo_url.replace("https://github.com/", ""));
    const statusText = STATUS_LABELS[env.status] || env.status;
    const card = document.createElement("div");
    card.className = "env-card" + (env.id === selectedEnvironmentId ? " active-selected" : "");
    card.innerHTML = `
      <div class="env-info">
        <span class="env-repo">${repoLabel}${env.is_demo ? " (demo)" : ""}</span>
        <div class="env-meta">
          <span class="status-badge badge-${env.status}">${statusText}</span>
          ${env.public_url ? `<a class="public-link" href="${escapeHtml(env.public_url)}" target="_blank" rel="noopener">${escapeHtml(env.public_url.replace("https://", ""))}</a>` : ""}
        </div>
      </div>
      <div class="env-actions">
        <button data-action="select" data-id="${env.id}" class="btn-secondary btn-sm">View</button>
        <button data-action="chaos" data-id="${env.id}" class="btn-danger btn-sm" ${env.status !== "ready" ? "disabled" : ""}>Kill</button>
        <button data-action="delete" data-id="${env.id}" class="btn-ghost btn-sm">Delete</button>
      </div>
    `;
    envListEl.appendChild(card);
  });

  envListEl.querySelectorAll("[data-action='select']").forEach((btn) =>
    btn.addEventListener("click", () => {
      selectedEnvironmentId = btn.dataset.id;
      timeline = [];
      envListEl.querySelectorAll(".env-card").forEach((c) => c.classList.remove("active-selected"));
      btn.closest(".env-card").classList.add("active-selected");
    })
  );

  envListEl.querySelectorAll("[data-action='chaos']").forEach((btn) =>
    btn.addEventListener("click", async () => {
      selectedEnvironmentId = btn.dataset.id;
      timeline = [];
      btn.disabled = true;
      try {
        await fetch(`${API}/api/experiments`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ environment_id: selectedEnvironmentId, kind: "kill" }),
        });
      } finally {
        btn.disabled = false;
      }
    })
  );

  envListEl.querySelectorAll("[data-action='delete']").forEach((btn) =>
    btn.addEventListener("click", async () => {
      const id = btn.dataset.id;
      btn.disabled = true;
      btn.textContent = "Deleting…";
      try {
        await fetch(`${API}/api/environments/${id}`, { method: "DELETE" });
        if (selectedEnvironmentId === id) {
          selectedEnvironmentId = null;
          timeline = [];
        }
        await refreshEnvironments();
      } catch (err) {
        console.error("Delete failed", err);
      } finally {
        btn.disabled = false;
        btn.textContent = "Delete";
      }
    })
  );
}

async function pollLatestExperiment() {
  if (!selectedEnvironmentId) return;
  let experiments;
  try {
    const res = await fetch(`${API}/api/environments/${selectedEnvironmentId}/experiments`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    experiments = await res.json();
  } catch (err) {
    return;
  }
  if (!experiments.length) return;

  const latest = experiments[0];
  const up = !latest.down_at || !!latest.recovered_at;
  timeline.push({ t: Date.now(), up });
  if (timeline.length > 120) timeline.shift();

  statusDot.className = "dot " + (up ? "up" : "down");
  statusLabelEl.textContent = up ? "signal healthy" : "signal lost — recovering";

  if (latest.mttr_seconds) {
    mttrEl.textContent = `Last recovery: ${latest.mttr_seconds.toFixed(2)}s`;
    if (!latest._diagnosed) {
      latest._diagnosed = true;
      const diagRes = await fetch(`${API}/api/experiments/${latest.id}/diagnose`, { method: "POST" });
      const diag = await diagRes.json();
      let text = `Root cause: ${diag.root_cause}\n\nConfidence: ${diag.confidence}\n\nProposed fix:\n${diag.proposed_fix}`;
      if (diag.similar_incidents && diag.similar_incidents.length) {
        text += `\n\nSimilar past incidents:\n` + diag.similar_incidents
          .map((s) => `- (${(s.similarity * 100).toFixed(0)}% match${s.is_sample ? ", sample data" : ""}) ${s.root_cause}`)
          .join("\n");
      }
      diagnosisEl.innerHTML = "";
      diagnosisEl.className = "diagnosis-content";
      diagnosisEl.textContent = text;
    }
  } else {
    mttrEl.textContent = "";
  }

  drawTimeline();
}

function drawTimeline() {
  const dpr = window.devicePixelRatio || 1;
  if (canvas.width !== canvas.clientWidth * dpr) {
    canvas.width = canvas.clientWidth * dpr;
    canvas.height = canvas.clientHeight * dpr;
    ctx.scale(dpr, dpr);
  }
  const w = canvas.clientWidth;
  const h = canvas.clientHeight;

  ctx.clearRect(0, 0, w, h);

  ctx.strokeStyle = "rgba(53, 224, 184, 0.08)";
  ctx.lineWidth = 1;
  for (let gx = 0; gx < w; gx += 24) {
    ctx.beginPath();
    ctx.moveTo(gx, 0);
    ctx.lineTo(gx, h);
    ctx.stroke();
  }
  ctx.strokeStyle = "#1c2b27";
  ctx.strokeRect(0, 0, w, h);

  if (timeline.length < 2) return;

  const step = w / Math.max(timeline.length - 1, 1);
  const upY = h * 0.28;
  const downY = h * 0.72;

  const traceColor = timeline[timeline.length - 1].up ? "#35e0b8" : "#ff6b5b";
  ctx.lineWidth = 2;
  ctx.lineJoin = "round";
  if (!reducedMotion) {
    ctx.shadowColor = traceColor;
    ctx.shadowBlur = 8;
  }
  ctx.strokeStyle = traceColor;
  ctx.beginPath();
  timeline.forEach((point, i) => {
    const x = i * step;
    const y = point.up ? upY : downY;
    ctx.strokeStyle = point.up ? "#35e0b8" : "#ff6b5b";
    if (i === 0) {
      ctx.moveTo(x, y);
    } else {
      const prev = timeline[i - 1];
      if (prev.up !== point.up) {
        const midX = i * step - step / 2;
        ctx.lineTo(midX, prev.up ? upY : downY);
        ctx.lineTo(midX, point.up ? upY : downY);
      }
      ctx.lineTo(x, y);
    }
  });
  ctx.stroke();
  ctx.shadowBlur = 0;
  const last = timeline[timeline.length - 1];
  const lastX = (timeline.length - 1) * step;
  const lastY = last.up ? upY : downY;
  ctx.fillStyle = last.up ? "#35e0b8" : "#ff6b5b";
  ctx.beginPath();
  ctx.arc(lastX, lastY, 3.5, 0, Math.PI * 2);
  ctx.fill();
}

setInterval(refreshEnvironments, 4000);
setInterval(pollLatestExperiment, 1000);
refreshEnvironments();