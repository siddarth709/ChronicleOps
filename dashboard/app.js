const API = ""; 

const envListEl = document.getElementById("environments-list");
const statusDot = document.getElementById("status-dot");
const statusLabelEl = document.getElementById("status-label");
const mttrEl = document.getElementById("mttr-readout");
const diagnosisEl = document.getElementById("diagnosis-output");
const canvas = document.getElementById("uptime-chart");
const ctx = canvas.getContext("2d");
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

let selectedEnvironmentId = null;
let timeline = []; 

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
  const res = await fetch(`${API}/api/environments`);
  const envs = await res.json();
  envListEl.innerHTML = "";

  envs.forEach((env) => {
    const row = document.createElement("div");
    row.className = "env-row";
    row.innerHTML = `
      <span>${env.repo_url.replace("https://github.com/", "")}${env.is_demo ? " (demo)" : ""} — ${env.status}</span>
      <span>
        <button data-action="select" data-id="${env.id}">View</button>
        <button data-action="chaos" data-id="${env.id}" class="danger">Kill</button>
      </span>
    `;
    envListEl.appendChild(row);
  });

  envListEl.querySelectorAll("[data-action='select']").forEach((btn) =>
    btn.addEventListener("click", () => {
      selectedEnvironmentId = btn.dataset.id;
      timeline = [];
    })
  );

  envListEl.querySelectorAll("[data-action='chaos']").forEach((btn) =>
    btn.addEventListener("click", async () => {
      selectedEnvironmentId = btn.dataset.id;
      timeline = [];
      await fetch(`${API}/api/experiments`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ environment_id: selectedEnvironmentId, kind: "kill" }),
      });
    })
  );
}

async function pollLatestExperiment() {
  if (!selectedEnvironmentId) return;
  const res = await fetch(`${API}/api/environments/${selectedEnvironmentId}/experiments`);
  const experiments = await res.json();
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


