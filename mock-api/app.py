import json
import logging
import os
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import psycopg
from psycopg.rows import dict_row


DATABASE_URL = os.environ["DATABASE_URL"]
SERVICE_LATENCY_SECONDS = int(os.environ.get("SERVICE_LATENCY_MS", "250")) / 1000

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
LOGGER = logging.getLogger("retry-lab-api")


def query_one(sql, parameters):
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, parameters)
            return cursor.fetchone()


class RequestHandler(BaseHTTPRequestHandler):
    server_version = "retry-lab-api/1.0"

    def do_GET(self):
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)

        if parsed.path == "/health":
            self._write_json(HTTPStatus.OK, {"status": "ok"})
            return

        if parsed.path == "/work":
            self._handle_work(query, coordinated=False)
            return

        if parsed.path == "/coordinated-work":
            self._handle_work(query, coordinated=True)
            return

        if parsed.path == "/metrics":
            self._handle_metrics(query)
            return

        self._write_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def _handle_work(self, query, coordinated):
        run_id = self._required_parameter(query, "run_id")
        client_id = self._required_parameter(query, "client_id")
        if run_id is None or client_id is None:
            return

        try:
            dispatch = None
            if coordinated:
                dispatch = query_one(
                    """
                    select dispatch_at, wait_ms
                    from retry_lab.reserve_dispatch_slot(%s)
                    """,
                    (run_id,),
                )
                time.sleep(dispatch["wait_ms"] / 1000)

            result = query_one(
                """
                select response_status, reason, requested_at
                from retry_lab.provider_request(%s, %s)
                """,
                (run_id, client_id),
            )
        except psycopg.Error as error:
            LOGGER.exception("provider request failed")
            self._write_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"error": "database_error", "detail": str(error)},
            )
            return

        time.sleep(SERVICE_LATENCY_SECONDS)
        status = HTTPStatus(result["response_status"])
        self._write_json(
            status,
            {
                "run_id": run_id,
                "client_id": client_id,
                "status": result["response_status"],
                "reason": result["reason"],
                "requested_at": result["requested_at"].isoformat(),
                "dispatch_at": (
                    dispatch["dispatch_at"].isoformat()
                    if dispatch is not None
                    else None
                ),
                "dispatch_wait_ms": (
                    dispatch["wait_ms"] if dispatch is not None else 0
                ),
            },
        )

    def _handle_metrics(self, query):
        run_id = self._required_parameter(query, "run_id")
        if run_id is None:
            return

        try:
            result = query_one(
                "select * from retry_lab.metrics(%s)",
                (run_id,),
            )
        except psycopg.Error as error:
            LOGGER.exception("metrics query failed")
            self._write_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"error": "database_error", "detail": str(error)},
            )
            return

        if result is None:
            self._write_json(HTTPStatus.NOT_FOUND, {"error": "unknown_run"})
            return

        self._write_json(HTTPStatus.OK, result)

    def _required_parameter(self, query, name):
        values = query.get(name)
        if values and values[0]:
            return values[0]

        self._write_json(
            HTTPStatus.BAD_REQUEST,
            {"error": "missing_parameter", "parameter": name},
        )
        return None

    def _write_json(self, status, body):
        encoded = json.dumps(body, default=str, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, message_format, *args):
        LOGGER.info(
            "%s - %s",
            self.client_address[0],
            message_format % args,
        )


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", 8080), RequestHandler)
    LOGGER.info("listening on port 8080")
    server.serve_forever()
