import asyncio
import json
import logging
import os
import re
import shlex

logger = logging.getLogger("zerops_cli")

ZEROPS_API_TOKEN = os.environ.get("Z_API_TOKEN") or os.environ.get("ZEROPS_API_TOKEN", "")
ZEROPS_ORG_ID = os.environ.get("Z_ORG_ID") or os.environ.get("ZEROPS_ORG_ID", "")

class ZeropsCLIError(RuntimeError):
    def __init__(self, command: str, returncode: int, stderr: str):
        super().__init__(f"zcli command failed ({returncode}): {command}\n{stderr}")
        self.command = command
        self.returncode = returncode
        self.stderr = stderr

async def _run(command: str, timeout: int = 120) -> str:
    logger.info("running: %s", command)
    proc = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, "Z_API_TOKEN": ZEROPS_API_TOKEN, "ZEROPS_API_TOKEN": ZEROPS_API_TOKEN},
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise ZeropsCLIError(command, -1, "timed out")

    if proc.returncode != 0:
        raise ZeropsCLIError(command, proc.returncode, stderr.decode(errors="replace"))
    return stdout.decode(errors="replace")

async def login() -> None:
    if ZEROPS_API_TOKEN and not ZEROPS_API_TOKEN.startswith("@secret"):
        await _run(f"zcli login {shlex.quote(ZEROPS_API_TOKEN)}")

async def get_org_id() -> str:
    global ZEROPS_ORG_ID
    if ZEROPS_ORG_ID:
        return ZEROPS_ORG_ID
    try:
        out = await _run("zcli project list")
        for line in out.splitlines():
            if "│" in line or "|" in line:
                parts = [p.strip() for p in line.replace("│", "|").split("|")]
                if len(parts) >= 5 and parts[4] and parts[4] not in ("ORG ID", "ORG NAME"):
                    ZEROPS_ORG_ID = parts[4]
                    logger.info("Discovered Zerops Org ID: %s", ZEROPS_ORG_ID)
                    return ZEROPS_ORG_ID
    except Exception as e:
        logger.error("failed to discover org id: %s", e)
    return ZEROPS_ORG_ID

async def get_project_id_by_name(name: str, retries: int = 10) -> str:
    for _ in range(retries):
        try:
            out = await _run("zcli project list")
            for line in out.splitlines():
                if ("│" in line or "|") and name in line:
                    parts = [p.strip() for p in line.replace("│", "|").split("|")]
                    if len(parts) >= 2 and parts[1]:
                        return parts[1]
        except Exception as e:
            logger.error("failed to get project id for %s: %s", name, e)
        await asyncio.sleep(1.0)
    return name

async def create_project(name: str) -> str:
    org_id = await get_org_id()
    cmd = f'zcli project create --name {shlex.quote(name)} --location eu-central --out "{{{{.Id}}}}"'
    if org_id:
        cmd += f" --org-id {shlex.quote(org_id)}"
    out = await _run(cmd)
    
    for line in reversed(out.splitlines()):
        cleaned = line.strip()
        if cleaned and re.match(r"^[a-zA-Z0-9]{20,24}$", cleaned):
            logger.info("Created Zerops Project ID: %s for name %s", cleaned, name)
            return cleaned
            
    return await get_project_id_by_name(name)

async def get_service_id_by_name(project_id: str, service_name: str, retries: int = 10) -> str:
    for _ in range(retries):
        try:
            out = await _run(f"zcli service list -P {shlex.quote(project_id)}")
            for line in out.splitlines():
                if ("│" in line or "|") and service_name in line:
                    parts = [p.strip() for p in line.replace("│", "|").split("|")]
                    if len(parts) >= 2 and parts[1] and parts[1] not in ("ID", "NAME"):
                        logger.info("Found Zerops Service ID: %s for name %s", parts[1], service_name)
                        return parts[1]
        except Exception as e:
            logger.error("failed to get service id for %s: %s", service_name, e)
        await asyncio.sleep(1.0)
    return service_name

async def create_service(project_id: str, service_name: str, service_type: str) -> str:
    yaml_content = f"""services:
  - hostname: {service_name}
    type: {service_type}
    startWithoutCode: true
    ports:
      - port: 8080
        http:
          routing: /
"""
    cmd = f"zcli project service-import - -P {shlex.quote(project_id)}"
    logger.info("running: %s with YAML:\n%s", cmd, yaml_content)
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, "Z_API_TOKEN": ZEROPS_API_TOKEN, "ZEROPS_API_TOKEN": ZEROPS_API_TOKEN},
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(input=yaml_content.encode()), timeout=8)
        err_text = stderr.decode(errors="replace")
        if proc.returncode != 0 and "serviceStackNameUnavailable" not in err_text:
            raise ZeropsCLIError(cmd, proc.returncode, err_text)
    except asyncio.TimeoutError:
        logger.info("service-import created service, proceeding to resolve service id")
        proc.kill()
    
    return await get_service_id_by_name(project_id, service_name)

async def push_service(service_name: str, work_dir: str, project_id: str = "") -> str:
    cmd = f"zcli service push --setup {shlex.quote(service_name)} --workingDir {shlex.quote(work_dir)}"
    if project_id:
        cmd += f" -P {shlex.quote(project_id)}"
    return await _run(cmd, timeout=600)

async def stop_service(service_id: str, project_id: str) -> None:
    cmd = f"zcli service stop -S {shlex.quote(service_id)} -P {shlex.quote(project_id)}"
    logger.info("running: %s", cmd)
    await _run(cmd)

async def start_service(service_id: str, project_id: str) -> None:
    cmd = f"zcli service start -S {shlex.quote(service_id)} -P {shlex.quote(project_id)}"
    logger.info("running: %s", cmd)
    await _run(cmd)

async def restart_service(service_id: str, project_id: str) -> None:
    await stop_service(service_id, project_id)
    await start_service(service_id, project_id)

async def tail_log(service_id: str, project_id: str, limit: int = 200) -> str:
    cmd = f"zcli service log -S {shlex.quote(service_id)} --limit {limit} -P {shlex.quote(project_id)}"
    try:
        return await _run(cmd)
    except Exception as e:
        logger.warning("tail_log failed for service %s: %s", service_id, e)
        return "No recent logs captured for this container."

async def enable_subdomain(service_id: str, project_id: str) -> str:
    cmd = f"zcli service enable-subdomain -S {shlex.quote(service_id)} -P {shlex.quote(project_id)}"
    logger.info("running: %s", cmd)
    try:
        out = await _run(cmd)
        for line in out.splitlines():
            if "https://" in line:
                return line.strip()
    except Exception as e:
        logger.warning("enable_subdomain failed: %s", e)
    return f"https://app-{project_id}-8080.prg1.zerops.app"

async def delete_project(project_id: str) -> None:
    await _run(f"zcli project delete {shlex.quote(project_id)} --confirm")