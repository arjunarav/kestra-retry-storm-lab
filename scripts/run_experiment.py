#!/usr/bin/env python3
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FLOW_DIRECTORY = ROOT / "flows"
RESULT_PATH = ROOT / "results" / "latest-run.json"
KESTRA_URL = os.environ.get("KESTRA_URL", "http://127.0.0.1:8082")
KESTRA_USERNAME = os.environ.get("KESTRA_USERNAME", "admin@kestra.io")
KESTRA_PASSWORD = os.environ.get("KESTRA_PASSWORD", "Admin1234")
AUTHORIZATION = "Basic " + base64.b64encode(
    f"{KESTRA_USERNAME}:{KESTRA_PASSWORD}".encode()
).decode()
TERMINAL_STATES = {"SUCCESS", "WARNING", "FAILED", "KILLED", "CANCELLED"}

SCENARIOS = (
    ("independent", "run-independent-retries"),
    ("bounded", "run-bounded-concurrency"),
    ("global-budget", "run-global-retry-budget"),
)


def request(path, method="GET", body=None, headers=None, timeout=30):
    request_headers = {"Authorization": AUTHORIZATION}
    request_headers.update(headers or {})
    target = urllib.request.Request(
        KESTRA_URL + path,
        data=body,
        headers=request_headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(target, timeout=timeout) as response:
            payload = response.read()
            if not payload:
                return None
            return json.loads(payload)
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")
        raise RuntimeError(
            f"{method} {path} returned HTTP {error.code}: {detail}"
        ) from error


def wait_for_kestra():
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        try:
            target = urllib.request.Request(
                KESTRA_URL + "/ui/",
                headers={"Authorization": AUTHORIZATION},
            )
            with urllib.request.urlopen(target, timeout=5) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(2)
    raise RuntimeError("Kestra did not become ready within 180 seconds")


def import_flow(flow_path):
    source = flow_path.read_bytes()
    flow_id = next(
        line.split(":", 1)[1].strip()
        for line in source.decode().splitlines()
        if line.startswith("id:")
    )
    namespace = "retry-storm-lab"
    try:
        request(f"/api/v1/main/flows/{namespace}/{flow_id}", timeout=10)
        method = "PUT"
        path = f"/api/v1/main/flows/{namespace}/{flow_id}"
    except RuntimeError as error:
        if "HTTP 404" not in str(error):
            raise
        method = "POST"
        path = "/api/v1/main/flows"

    request(
        path,
        method=method,
        body=source,
        headers={"Content-Type": "application/x-yaml"},
    )
    print(f"Imported {flow_path.name}")


def multipart(fields):
    boundary = f"----kestra-retry-lab-{uuid.uuid4().hex}"
    chunks = []
    for name, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                (
                    f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                ).encode(),
                str(value).encode(),
                b"\r\n",
            ]
        )
    chunks.append(f"--{boundary}--\r\n".encode())
    return boundary, b"".join(chunks)


def trigger(flow_id, run_id):
    boundary, body = multipart({"run_id": run_id})
    execution = request(
        f"/api/v1/main/executions/retry-storm-lab/{flow_id}",
        method="POST",
        body=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    return execution["id"]


def wait_for_execution(execution_id):
    deadline = time.monotonic() + 360
    last_state = None
    while time.monotonic() < deadline:
        execution = request(f"/api/v1/main/executions/{execution_id}")
        state = execution["state"]["current"]
        if state != last_state:
            print(f"{execution_id}: {state}")
            last_state = state
        if state in TERMINAL_STATES:
            return execution
        time.sleep(2)
    raise RuntimeError(f"execution {execution_id} exceeded six minutes")


def main():
    wait_for_kestra()
    for flow_path in sorted(FLOW_DIRECTORY.glob("*.yml")):
        import_flow(flow_path)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    results = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "kestra_url": KESTRA_URL,
        "scenarios": [],
    }

    for label, flow_id in SCENARIOS:
        run_id = f"{label}-{timestamp}"
        execution_id = trigger(flow_id, run_id)
        print(f"Started {label}: {execution_id}")
        execution = wait_for_execution(execution_id)
        state = execution["state"]["current"]
        if state not in {"SUCCESS", "WARNING"}:
            raise RuntimeError(
                f"{label} execution {execution_id} ended in {state}"
            )
        results["scenarios"].append(
            {
                "label": label,
                "run_id": run_id,
                "execution_id": execution_id,
                "state": state,
                "duration": execution["state"].get("duration"),
                "metrics": execution["outputs"]["metrics"],
            }
        )

    RESULT_PATH.write_text(
        json.dumps(results, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {RESULT_PATH}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
