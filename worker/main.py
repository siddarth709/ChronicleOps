import os
import time
import logging
import subprocess
from datetime import datetime, timezone

import httpx

import db
import pubsub
from chaos_logic import Action, ExperimentState, next_action, is_expired

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("worker")

ORCHESTRATOR_URL = os.environ.get("ORCHESTRATOR_URL", "http://orchestrator:8080")
POLL_INTERVAL_SECONDS = 1.0
LOOP_SLEEP_SECONDS = 2.0


def check_health(url: str) -> bool:
    try:
        r = httpx.get(url, timeout=2.0)
        return r.status_code < 500
    except httpx.HTTPError:
        return False


def run_kill_experiments():
    with db.get_conn() as conn:
        experiments = conn.execute(
            """SELECT e.*, env.public_url, env.service_id FROM experiments e
            JOIN environments env ON env.id = e.environment_id
            WHERE e.kind = 'kill' AND e.status = 'running'"""
        ).fetchall()

    for exp in experiments:
        if not exp["public_url"]:
            continue

        healthy = check_health(exp["public_url"])
        now_dt = datetime.now(timezone.utc)
        now = now_dt.timestamp()

        state = ExperimentState(
            healthy=healthy,
            down_at=exp["down_at"].timestamp() if exp["down_at"] else None,
            recovered_at=exp["recovered_at"].timestamp() if exp["recovered_at"] else None,
        )
        action, mttr = next_action(state, now)

        if action == Action.MARK_DOWN_AND_RESTART:
            with db.get_conn() as conn:
                conn.execute(
                    "UPDATE experiments SET down_at = %s WHERE id = %s", (now_dt, exp["id"])
                )
                conn.execute(
                    "INSERT INTO events (experiment_id, type) VALUES (%s, 'down')", (exp["id"],)
                )
            pubsub.publish("experiment_down", {"experiment_id": str(exp["id"])})
            logger.info("experiment %s: target went down, issuing restart", exp["id"])
            httpx.post(f"{ORCHESTRATOR_URL}/api/experiments/{exp['id']}/recover", timeout=10)

        elif action == Action.MARK_RECOVERED:
            with db.get_conn() as conn:
                conn.execute(
                    """UPDATE experiments SET recovered_at = %s, mttr_seconds = %s, status = 'done'
                    WHERE id = %s""",
                    (now_dt, mttr, exp["id"]),
                )
                conn.execute(
                    "INSERT INTO events (experiment_id, type, detail) VALUES (%s, 'up', %s)",
                    (exp["id"], f"mttr={mttr:.2f}s"),
                )
            pubsub.publish("experiment_recovered", {"experiment_id": str(exp["id"]), "mttr_seconds": mttr})
            logger.info("experiment %s: recovered, mttr=%.2fs", exp["id"], mttr)


def cleanup_expired_environments():
    with db.get_conn() as conn:
        candidates = conn.execute(
            "SELECT * FROM environments WHERE status != 'destroyed'"
        ).fetchall()

    now = datetime.now(timezone.utc).timestamp()
    
    expired = []
    for c in candidates:
        expires_at = c["expires_at"]
        if isinstance(expires_at, datetime):
            expires_at = expires_at.timestamp()
        
        if expires_at and is_expired(expires_at, now):
            expired.append(c)

    for env in expired:
        logger.info("environment %s past TTL, tearing down project %s", env["id"], env["project_id"])
        subprocess.run(["zcli", "project", "delete", env["project_id"], "--confirm"], check=False)
        with db.get_conn() as conn:
            conn.execute("UPDATE environments SET status = 'destroyed' WHERE id = %s", (env["id"],))
            pubsub.publish("environment_destroyed", {"environment_id": str(env["id"])})


def zcli_login():
    token = os.environ.get("Z_API_TOKEN", "") or os.environ.get("ZEROPS_API_TOKEN", "")
    result = subprocess.run(["zcli", "login", token], capture_output=True, text=True)
    if result.returncode != 0:
        logger.error("zcli login failed, TTL cleanup will not work: %s", result.stderr)


def main():
    logger.info("Sentinel worker starting, polling every %.1fs", LOOP_SLEEP_SECONDS)
    zcli_login()
    while True:
        try:
            run_kill_experiments()
            cleanup_expired_environments()
        except Exception:
            logger.exception("worker loop iteration failed")
        time.sleep(LOOP_SLEEP_SECONDS)


if __name__ == "__main__":
    main()