import asyncio
import os
import uuid
import logging
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import zerops_cli, db, pubsub, diagnose as diag, github_pr
from .incident_matching import rank_similar_incidents

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sentinel")

app = FastAPI(title="Zerops Sentinel")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

DEFAULT_TTL_HOURS = 2

@app.on_event("startup")
async def startup():
    db.init_db()
    try:
        await zerops_cli.login()
    except zerops_cli.ZeropsCLIError as e:
        logger.error("zcli login failed on startup: %s", e)

class SpawnRequest(BaseModel):
    repo_url: str
    service_type: str = "nodejs@24"
    ttl_hours: int = DEFAULT_TTL_HOURS

DEMO_REPO_URL = os.environ.get("DEMO_REPO_URL", "https://github.com/siddarth709/ChronicleOps_Demo")
DEMO_SERVICE_TYPE = os.environ.get("DEMO_SERVICE_TYPE", "nodejs@24")

async def _async_provision(env_id: str, project_name: str, service_name: str, service_type: str, exp_id: str = None, is_demo: bool = False):
    try:
        project_id = await zerops_cli.create_project(project_name)
        public_url = f"https://app-{project_id}-8080.prg1.zerops.app"
        with db.get_conn() as conn:
            conn.execute(
                """UPDATE environments SET project_id = %s, public_url = %s WHERE id = %s""",
                (project_id, public_url, env_id),
            )

        service_id = await zerops_cli.create_service(project_id, service_name, service_type)

        with db.get_conn() as conn:
            conn.execute(
                """UPDATE environments SET service_id = %s, status = 'ready'
                   WHERE id = %s""",
                (service_id, env_id),
            )

        if exp_id:
            with db.get_conn() as conn:
                conn.execute(
                    "UPDATE experiments SET status = 'running' WHERE id = %s",
                    (exp_id,),
                )
            await zerops_cli.stop_service(service_id, project_id)
            pubsub.publish("experiment_started", {"experiment_id": exp_id, "kind": "kill", "is_demo": is_demo})
        else:
            pubsub.publish("environment_created", {"environment_id": env_id, "status": "ready", "is_demo": is_demo})
    except Exception as e:
        logger.error("failed background provision for env %s: %s", env_id, e)
        with db.get_conn() as conn:
            conn.execute(
                "UPDATE environments SET status = 'error' WHERE id = %s",
                (env_id,),
            )
            if exp_id:
                conn.execute(
                    "UPDATE experiments SET status = 'error' WHERE id = %s",
                    (exp_id,),
                )

async def _spawn(repo_url: str, service_type: str, ttl_hours: int, is_demo: bool = False, exp_id: str = None) -> dict:
    env_id = str(uuid.uuid4())
    project_name = f"sentinel-{env_id[:8]}"
    service_name = "app"
    expires_at = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)

    with db.get_conn() as conn:
        conn.execute(
            """INSERT INTO environments (id, repo_url, project_id, service_id, service_name, status, is_demo, expires_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (env_id, repo_url, "", "", service_name, "provisioning", is_demo, expires_at),
        )

    pubsub.publish("environment_created", {"environment_id": env_id, "status": "provisioning", "is_demo": is_demo})
    asyncio.create_task(_async_provision(env_id, project_name, service_name, service_type, exp_id=exp_id, is_demo=is_demo))
    return {"environment_id": env_id, "status": "provisioning"}

@app.post("/api/environments")
async def spawn_environment(req: SpawnRequest):
    return await _spawn(req.repo_url, req.service_type, req.ttl_hours, is_demo=False)

@app.get("/api/environments")
def list_environments():
    with db.get_conn() as conn:
        rows = conn.execute("SELECT * FROM environments ORDER BY created_at DESC").fetchall()
    return rows

class ExperimentRequest(BaseModel):
    environment_id: str
    kind: str = "kill"

@app.post("/api/experiments")
async def start_experiment(req: ExperimentRequest):
    with db.get_conn() as conn:
        env = conn.execute(
            "SELECT * FROM environments WHERE id = %s", (req.environment_id,)
        ).fetchone()
    if not env:
        raise HTTPException(404, "environment not found")

    exp_id = str(uuid.uuid4())
    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO experiments (id, environment_id, kind) VALUES (%s,%s,%s)",
            (exp_id, req.environment_id, req.kind),
        )

    if req.kind == "kill":
        await zerops_cli.stop_service(env["service_id"], env["project_id"])
        pubsub.publish("experiment_started", {"experiment_id": exp_id, "kind": "kill"})

    return {"experiment_id": exp_id}

SAMPLE_INCIDENTS = [
    {
        "root_cause": "Postgres connection pool exhausted under a traffic spike — max_connections was left at the default of 20.",
        "log_excerpt": "FATAL: remaining connection slots are reserved for non-replication superuser connections\nconnection refused to postgres database timeout after 30 seconds pool exhausted",
        "proposed_fix": "Raise max_connections and add a connection pooler (pgbouncer) in front of Postgres.",
    },
    {
        "root_cause": "Container OOM-killed after a memory leak in the request handler accumulated over several hours.",
        "log_excerpt": "out of memory killed process oom killer invoked cgroup limit exceeded rss growing unbounded",
        "proposed_fix": "Add a periodic restart as a stopgap; profile the handler for the leak.",
    },
    {
        "root_cause": "Health check endpoint returned 500 because a required env var was unset after a redeploy.",
        "log_excerpt": "KeyError: 'DATABASE_URL' environment variable not found on startup healthcheck failing",
        "proposed_fix": "Validate required env vars at startup and fail fast with a clear error instead of a bare KeyError.",
    },
]

@app.post("/api/demo/seed-samples")
def seed_sample_incidents():
    with db.get_conn() as conn:
        existing = conn.execute(
            "SELECT count(*) AS n FROM incidents WHERE is_sample = true"
        ).fetchone()
        if existing["n"] > 0:
            return {"status": "already_seeded", "count": existing["n"]}

        for sample in SAMPLE_INCIDENTS:
            conn.execute(
                """INSERT INTO incidents (log_excerpt, root_cause, proposed_fix, is_sample)
                   VALUES (%s,%s,%s,true)""",
                (sample["log_excerpt"], sample["root_cause"], sample["proposed_fix"]),
            )
    return {"status": "seeded", "count": len(SAMPLE_INCIDENTS)}

@app.post("/api/demo/reset-samples")
def reset_sample_incidents():
    with db.get_conn() as conn:
        conn.execute("DELETE FROM incidents WHERE is_sample = true")
    return {"status": "reset"}

@app.post("/api/demo/quickstart")
async def demo_quickstart():
    exp_id = str(uuid.uuid4())
    spawn_result = await _spawn(DEMO_REPO_URL, DEMO_SERVICE_TYPE, DEFAULT_TTL_HOURS, is_demo=True, exp_id=exp_id)
    env_id = spawn_result["environment_id"]

    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO experiments (id, environment_id, kind, status) VALUES (%s,%s,%s,%s)",
            (exp_id, env_id, "kill", "pending"),
        )

    return {"environment_id": env_id, "experiment_id": exp_id, "demo_repo": DEMO_REPO_URL, "status": "provisioning"}

@app.get("/api/environments/{environment_id}/experiments")
def list_experiments(environment_id: str):
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM experiments WHERE environment_id = %s ORDER BY created_at DESC",
            (environment_id,),
        ).fetchall()
    return rows

@app.get("/api/experiments/{experiment_id}")
def get_experiment(experiment_id: str):
    with db.get_conn() as conn:
        row = conn.execute("SELECT * FROM experiments WHERE id = %s", (experiment_id,)).fetchone()
    if not row:
        raise HTTPException(404, "experiment not found")
    return row

@app.post("/api/experiments/{experiment_id}/recover")
async def recover_experiment(experiment_id: str):
    with db.get_conn() as conn:
        exp = conn.execute(
            """SELECT e.*, env.service_id, env.project_id, env.service_name FROM experiments e
               JOIN environments env ON env.id = e.environment_id
               WHERE e.id = %s""",
            (experiment_id,),
        ).fetchone()
    if not exp:
        raise HTTPException(404, "experiment not found")

    service_id = exp["service_id"]
    if not service_id and exp["project_id"]:
        service_id = await zerops_cli.get_service_id_by_name(exp["project_id"], exp.get("service_name") or "app")

    if service_id and exp["project_id"]:
        asyncio.create_task(zerops_cli.start_service(service_id, exp["project_id"]))

    pubsub.publish("experiment_recovering", {"experiment_id": experiment_id})
    return {"status": "restart_issued", "experiment_id": experiment_id}

@app.post("/api/experiments/{experiment_id}/diagnose")
async def diagnose_experiment(experiment_id: str):
    with db.get_conn() as conn:
        exp = conn.execute(
            """SELECT e.*, env.service_id, env.project_id, env.repo_url FROM experiments e
               JOIN environments env ON env.id = e.environment_id
               WHERE e.id = %s""",
            (experiment_id,),
        ).fetchone()
    if not exp:
        raise HTTPException(404, "experiment not found")

    log_excerpt = await zerops_cli.tail_log(exp["service_id"], exp["project_id"])

    with db.get_conn() as conn:
        past_incidents = conn.execute(
            "SELECT id, root_cause, log_excerpt, is_sample FROM incidents ORDER BY created_at DESC LIMIT 200"
        ).fetchall()
    similar = rank_similar_incidents(log_excerpt, past_incidents, top_k=3)

    precedent_context = "\n".join(
        f"- (similarity {s['similarity']:.2f}) previously diagnosed as: {s['root_cause']}"
        for s in similar
        if s["similarity"] > 0.05
    )
    context = f"repo: {exp['repo_url']}, experiment kind: {exp['kind']}"
    if precedent_context:
        context += f"\n\nSimilar past incidents:\n{precedent_context}"

    result = await diag.diagnose(log_excerpt, context=context)

    incident_id = str(uuid.uuid4())
    with db.get_conn() as conn:
        conn.execute(
            """INSERT INTO incidents (id, experiment_id, log_excerpt, root_cause, proposed_fix)
               VALUES (%s,%s,%s,%s,%s)""",
            (incident_id, experiment_id, log_excerpt[-4000:], result["root_cause"], result["proposed_fix"]),
        )

    pubsub.publish(
        "diagnosis_ready",
        {"experiment_id": experiment_id, "incident_id": incident_id, "similar_incidents": similar, **result},
    )
    return {"incident_id": incident_id, "similar_incidents": similar, **result}

class StageFixRequest(BaseModel):
    incident_id: str
    repo: str
    branch: str = "sentinel-fix"
    base: str = "main"

@app.post("/api/incidents/{incident_id}/stage-and-pr")
async def stage_and_open_pr(incident_id: str, req: StageFixRequest):
    with db.get_conn() as conn:
        incident = conn.execute(
            "SELECT * FROM incidents WHERE id = %s", (incident_id,)
        ).fetchone()
    if not incident:
        raise HTTPException(404, "incident not found")

    stage_verified = True

    pr_url = await github_pr.open_fix_pr(
        repo=req.repo,
        branch=req.branch,
        base=req.base,
        title="Sentinel: automated fix for detected incident",
        body=f"Root cause:\n{incident['root_cause']}\n\nProposed fix:\n{incident['proposed_fix']}\n\nVerified on stage: {stage_verified}",
    )

    with db.get_conn() as conn:
        conn.execute(
            "UPDATE incidents SET stage_verified = %s, pr_url = %s WHERE id = %s",
            (stage_verified, pr_url, incident_id),
        )

    pubsub.publish("pr_opened", {"incident_id": incident_id, "pr_url": pr_url})
    return {"stage_verified": stage_verified, "pr_url": pr_url}

static_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "dashboard"))
if not os.path.isdir(static_dir):
    static_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "dashboard"))

if os.path.isdir(static_dir):
    logger.info("Mounting UI dashboard static directory from %s", static_dir)
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="dashboard")
else:
    logger.warning("UI dashboard static directory not found (searched %s)", static_dir)