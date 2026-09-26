import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone

from services.database_service import database_service
from services.prioway_store import prioway_store


REQUEST_WINDOW_SECONDS = 60
MAX_REQUEST_ATTEMPTS = 8


class VerificationService:

    def __init__(self):

        self.lock = threading.RLock()

        self.recent_attempts = defaultdict(
            deque
        )

    def _now_iso(self):

        return datetime.now(
            timezone.utc
        ).isoformat()

    def _log_security_event(
        self,
        event_type,
        details,
        vehicle_id=None,
    ):

        timestamp = self._now_iso()

        row_id = database_service.insert(
            """
            INSERT INTO events (
                event_type,
                severity,
                details,
                vehicle_id,
                junction_id,
                request_id,
                timestamp
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_type,
                "SECURITY",
                details,
                vehicle_id,
                None,
                None,
                timestamp,
            ),
        )

        database_service.execute(
            """
            UPDATE events
            SET event_id = ?
            WHERE id = ?
            """,
            (
                f"EVT-{row_id:05d}",
                row_id,
            ),
        )

    # =====================================================
    # REQUEST RATE CHECK
    # =====================================================

    def _allow_request(
        self,
        vehicle_id,
    ):

        now = time.time()

        with self.lock:

            attempts = self.recent_attempts[
                vehicle_id
            ]

            while (
                attempts
                and
                now - attempts[0]
                > REQUEST_WINDOW_SECONDS
            ):
                attempts.popleft()

            attempts.append(now)

            return (
                len(attempts)
                <= MAX_REQUEST_ATTEMPTS
            )

    # =====================================================
    # MAIN VERIFICATION
    # =====================================================

    def submit_emergency(
        self,
        payload,
        source="API",
    ):

        payload = payload or {}

        vehicle_id = str(
            payload.get(
                "vehicle_id",
                ""
            )
        ).strip()

        if not vehicle_id:

            return {
                "success": False,
                "result": "INVALID_REQUEST",
                "message":
                    "vehicle_id is required",
            }, 400

        priority = str(
            payload.get(
                "priority",
                "HIGH"
            )
        ).upper()

        allowed_priorities = {
            "LOW",
            "MEDIUM",
            "HIGH",
            "CRITICAL",
        }

        if priority not in allowed_priorities:
            priority = "HIGH"

        # ---------------------------------------------
        # BASIC RATE / SPAM PROTECTION
        # ---------------------------------------------

        if not self._allow_request(
            vehicle_id
        ):

            database_service.execute(
                """
                UPDATE vehicles
                SET suspicious_requests =
                    suspicious_requests + 1
                WHERE vehicle_id = ?
                """,
                (vehicle_id,),
            )

            self._log_security_event(
                "REQUEST_RATE_LIMITED",
                (
                    f"Too many emergency "
                    f"requests from {vehicle_id}"
                ),
                vehicle_id=vehicle_id,
            )

            return {
                "success": False,
                "result": "RATE_LIMITED",
                "message":
                    "Too many emergency requests",
            }, 429

        # ---------------------------------------------
        # STORE HANDLES:
        #
        # unknown vehicle
        # blacklist
        # duplicate request
        # unverified request
        # normal verified request
        # ---------------------------------------------

        result = prioway_store.create_request(
            vehicle_id=vehicle_id,

            junction_id=payload.get(
                "junction_id"
            ),

            hospital_id=payload.get(
                "hospital_id"
            ),

            priority=priority,

            source=source,
        )

        response_code = 201

        if result["result"] == (
            "DUPLICATE_REQUEST"
        ):
            response_code = 200

        elif result["result"] == (
            "FLAGGED"
        ):
            response_code = 202

        elif result["result"] == (
            "BLOCKED"
        ):
            response_code = 403

        return {
            "success":
                result["result"]
                != "BLOCKED",
            **result,
        }, response_code


verification_service = VerificationService()
