import time
from datetime import (
    datetime,
    timezone,
)

from services.database_service import (
    database_service,
)

from services.health_service import (
    calculate_health,
)


ACTIVE_REQUEST_STATES = {
    "PENDING",
    "VERIFIED",
    "APPROVED",
    "ACTIVATING",
    "ACTIVE",
}


class PrioWayStore:

    # =====================================================
    # TIME
    # =====================================================

    def _now_iso(self):

        return datetime.now(
            timezone.utc
        ).isoformat()

    # =====================================================
    # VEHICLE CONVERSION
    # =====================================================

    def _vehicle_from_row(
        self,
        row,
    ):

        if row is None:
            return None

        return {
            "vehicle_id":
                row["vehicle_id"],

            "name":
                row["name"],

            "source":
                row["source"],

            "registration_number":
                row["registration_number"],

            "vehicle_type":
                row["vehicle_type"],

            "hospital_id":
                row["hospital_id"],

            "verified":
                bool(row["verified"]),

            "blacklisted":
                bool(row["blacklisted"]),

            "blacklist_reason":
                row["blacklist_reason"],

            "online":
                bool(row["online"]),

            "last_seen":
                row["last_seen"],

            "location": {
                "lat": row["lat"],
                "lon": row["lon"],
                "valid": bool(
                    row["location_valid"]
                ),
            },

            "history": {
                "completed_requests":
                    row[
                        "completed_requests"
                    ],

                "rejected_requests":
                    row[
                        "rejected_requests"
                    ],

                "suspicious_requests":
                    row[
                        "suspicious_requests"
                    ],

                "duplicate_requests":
                    row[
                        "duplicate_requests"
                    ],
            },
        }

    # =====================================================
    # JUNCTION CONVERSION
    # =====================================================

    def _junction_from_row(
        self,
        row,
    ):

        if row is None:
            return None

        health = calculate_health(
            row["last_seen"],
            row["forced_health"],
        )

        return {
            "junction_id":
                row["junction_id"],

            "name":
                row["name"],

            "source":
                row["source"],

            "lat":
                row["lat"],

            "lon":
                row["lon"],

            "last_seen":
                row["last_seen"],

            "forced_health":
                row["forced_health"],

            "health":
                health,

            "current_light":
                row["current_light"],

            "corridor_state":
                row["corridor_state"],

            "gas": {
                "value":
                    row["gas_value"],

                "status":
                    row["gas_status"],

                "source":
                    row["gas_source"],
            },

            "temperature": {
                "value":
                    row[
                        "temperature_value"
                    ],

                "source":
                    row[
                        "temperature_source"
                    ],
            },

            "camera": {
                "status":
                    row["camera_status"],

                "source":
                    row["camera_source"],
            },
        }

    # =====================================================
    # REQUEST CONVERSION
    # =====================================================

    def _request_from_row(
        self,
        row,
    ):

        if row is None:
            return None

        return {
            "request_id":
                row["request_id"],

            "vehicle_id":
                row["vehicle_id"],

            "junction_id":
                row["junction_id"],

            "hospital_id":
                row["hospital_id"],

            "priority":
                row["priority"],

            "status":
                row["status"],

            "verification_status":
                row[
                    "verification_status"
                ],

            "source":
                row["source"],

            "created_at":
                row["created_at"],

            "approved_at":
                row["approved_at"],

            "completed_at":
                row["completed_at"],
        }

    # =====================================================
    # EVENT CONVERSION
    # =====================================================

    def _event_from_row(
        self,
        row,
    ):

        return {
            "event_id":
                row["event_id"],

            "event_type":
                row["event_type"],

            "severity":
                row["severity"],

            "details":
                row["details"],

            "vehicle_id":
                row["vehicle_id"],

            "junction_id":
                row["junction_id"],

            "request_id":
                row["request_id"],

            "timestamp":
                row["timestamp"],
        }

    # =====================================================
    # EVENT LOG
    # =====================================================

    def _log_event(
        self,
        event_type,
        details,
        vehicle_id=None,
        junction_id=None,
        request_id=None,
        severity="INFO",
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
                severity,
                details,
                vehicle_id,
                junction_id,
                request_id,
                timestamp,
            ),
        )

        event_id = (
            f"EVT-{row_id:05d}"
        )

        database_service.execute(
            """
            UPDATE events
            SET event_id = ?
            WHERE id = ?
            """,
            (
                event_id,
                row_id,
            ),
        )

        return event_id

    # =====================================================
    # EXISTING PHYSICAL HARDWARE → DATABASE
    # =====================================================

    def sync_physical_state(
        self,
        snapshot,
    ):

        now = time.time()

        vehicle_online = bool(
            snapshot.get(
                "vehicle_recent",
                False,
            )
        )

        location = snapshot.get(
            "vehicle_location",
            {},
        )

        if vehicle_online:

            database_service.execute(
                """
                UPDATE vehicles
                SET
                    online = 1,
                    last_seen = ?
                WHERE vehicle_id = 'VEH-001'
                """,
                (now,),
            )

        else:

            database_service.execute(
                """
                UPDATE vehicles
                SET online = 0
                WHERE vehicle_id = 'VEH-001'
                """
            )

        if location.get(
            "valid",
            False,
        ):

            database_service.execute(
                """
                UPDATE vehicles
                SET
                    lat = ?,
                    lon = ?,
                    location_valid = 1
                WHERE vehicle_id = 'VEH-001'
                """,
                (
                    location.get("lat"),
                    location.get("lon"),
                ),
            )

        junction_online = bool(
            snapshot.get(
                "junction_online",
                False,
            )
        )

        if junction_online:

            database_service.execute(
                """
                UPDATE junctions
                SET last_seen = ?
                WHERE junction_id = 'JNC-001'
                """,
                (now,),
            )

        database_service.execute(
            """
            UPDATE junctions
            SET
                current_light = ?,
                corridor_state = ?,
                gas_status = ?
            WHERE junction_id = 'JNC-001'
            """,
            (
                snapshot.get(
                    "current_light",
                    0,
                ),

                snapshot.get(
                    "state",
                    "NORMAL",
                ),

                snapshot.get(
                    "gas",
                    "UNKNOWN",
                ),
            ),
        )

    # =====================================================
    # SIMULATED NODES → DATABASE
    # =====================================================

    def apply_simulation(
        self,
        updates,
    ):

        for (
            vehicle_id,
            values
        ) in updates.get(
            "vehicles",
            {},
        ).items():

            database_service.execute(
                """
                UPDATE vehicles
                SET
                    online = 1,
                    last_seen = ?,
                    lat = ?,
                    lon = ?,
                    location_valid = 1
                WHERE vehicle_id = ?
                """,
                (
                    values.get(
                        "last_seen"
                    ),

                    values.get(
                        "lat"
                    ),

                    values.get(
                        "lon"
                    ),

                    vehicle_id,
                ),
            )

        for (
            junction_id,
            values
        ) in updates.get(
            "junctions",
            {},
        ).items():

            database_service.execute(
                """
                UPDATE junctions
                SET
                    last_seen = ?,
                    current_light = ?,
                    gas_value = ?,
                    gas_status = ?,
                    gas_source = 'SIMULATED',
                    temperature_value = ?,
                    temperature_source = 'SIMULATED',
                    camera_status = ?,
                    camera_source = 'SIMULATED'
                WHERE junction_id = ?
                """,
                (
                    values.get(
                        "last_seen"
                    ),

                    values.get(
                        "current_light",
                        0,
                    ),

                    values.get(
                        "gas_value"
                    ),

                    values.get(
                        "gas_status",
                        "UNKNOWN",
                    ),

                    values.get(
                        "temperature"
                    ),

                    values.get(
                        "camera_status",
                        "SIMULATED_STREAM",
                    ),

                    junction_id,
                ),
            )

    # =====================================================
    # VEHICLES
    # =====================================================

    def list_vehicles(self):

        rows = database_service.fetch_all(
            """
            SELECT *
            FROM vehicles
            ORDER BY vehicle_id
            """
        )

        return [
            self._vehicle_from_row(
                row
            )
            for row in rows
        ]

    def get_vehicle(
        self,
        vehicle_id,
    ):

        row = database_service.fetch_one(
            """
            SELECT *
            FROM vehicles
            WHERE vehicle_id = ?
            """,
            (vehicle_id,),
        )

        return self._vehicle_from_row(
            row
        )

    def set_blacklist(
        self,
        vehicle_id,
        enabled,
        reason=None,
    ):

        vehicle = self.get_vehicle(
            vehicle_id
        )

        if vehicle is None:
            return None

        database_service.execute(
            """
            UPDATE vehicles
            SET
                blacklisted = ?,
                blacklist_reason = ?
            WHERE vehicle_id = ?
            """,
            (
                1 if enabled else 0,
                (
                    reason
                    if enabled
                    else None
                ),
                vehicle_id,
            ),
        )

        self._log_event(
            (
                "VEHICLE_BLACKLISTED"
                if enabled
                else "VEHICLE_RESTORED"
            ),
            (
                reason
                or (
                    "Vehicle blacklisted"
                    if enabled
                    else "Vehicle restored"
                )
            ),
            vehicle_id=vehicle_id,
            severity=(
                "WARNING"
                if enabled
                else "INFO"
            ),
        )

        return self.get_vehicle(
            vehicle_id
        )

    # =====================================================
    # JUNCTIONS
    # =====================================================

    def list_junctions(self):

        rows = database_service.fetch_all(
            """
            SELECT *
            FROM junctions
            ORDER BY junction_id
            """
        )

        return [
            self._junction_from_row(
                row
            )
            for row in rows
        ]

    def get_junction(
        self,
        junction_id,
    ):

        row = database_service.fetch_one(
            """
            SELECT *
            FROM junctions
            WHERE junction_id = ?
            """,
            (junction_id,),
        )

        return self._junction_from_row(
            row
        )

    def set_simulated_junction_health(
        self,
        junction_id,
        health,
    ):

        health = (
            str(health)
            .strip()
            .upper()
        )

        allowed = {
            "AUTO",
            "ONLINE",
            "DEGRADED",
            "OFFLINE",
            "FAILED",
        }

        if health not in allowed:
            return None

        junction = self.get_junction(
            junction_id
        )

        if junction is None:
            return None

        if (
            junction["source"]
            != "SIMULATED"
        ):
            return None

        forced = (
            None
            if health == "AUTO"
            else health
        )

        database_service.execute(
            """
            UPDATE junctions
            SET forced_health = ?
            WHERE junction_id = ?
            """,
            (
                forced,
                junction_id,
            ),
        )

        self._log_event(
            "JUNCTION_HEALTH_CHANGED",
            (
                f"{junction_id} "
                f"health changed to "
                f"{health}"
            ),
            junction_id=junction_id,
            severity=(
                "WARNING"
                if health in {
                    "DEGRADED",
                    "OFFLINE",
                    "FAILED",
                }
                else "INFO"
            ),
        )

        return self.get_junction(
            junction_id
        )

    # =====================================================
    # ACTIVE REQUEST LOOKUP
    # =====================================================

    def _find_active_request(
        self,
        vehicle_id,
    ):

        row = database_service.fetch_one(
            """
            SELECT *
            FROM emergency_requests
            WHERE
                vehicle_id = ?
                AND status IN (
                    'PENDING',
                    'VERIFIED',
                    'APPROVED',
                    'ACTIVATING',
                    'ACTIVE'
                )
            ORDER BY id DESC
            LIMIT 1
            """,
            (vehicle_id,),
        )

        return self._request_from_row(
            row
        )

    # =====================================================
    # CREATE REQUEST
    # =====================================================

    def create_request(
        self,
        vehicle_id,
        junction_id=None,
        hospital_id=None,
        priority="HIGH",
        source="API",
    ):

        vehicle = self.get_vehicle(
            vehicle_id
        )

        # -------------------------------------------------
        # UNKNOWN VEHICLE
        # -------------------------------------------------

        if vehicle is None:

            return self._insert_request(
                vehicle_id=vehicle_id,
                junction_id=junction_id,
                hospital_id=hospital_id,
                priority=priority,
                status="BLOCKED",
                verification_status=(
                    "UNKNOWN_VEHICLE"
                ),
                source=source,
                result="BLOCKED",
                event_type=(
                    "UNKNOWN_VEHICLE_REQUEST"
                ),
                event_severity="SECURITY",
            )

        # -------------------------------------------------
        # BLACKLISTED VEHICLE
        # -------------------------------------------------

        if vehicle[
            "blacklisted"
        ]:

            return self._insert_request(
                vehicle_id=vehicle_id,
                junction_id=junction_id,
                hospital_id=(
                    hospital_id
                    or vehicle[
                        "hospital_id"
                    ]
                ),
                priority=priority,
                status="BLOCKED",
                verification_status=(
                    "BLACKLISTED"
                ),
                source=source,
                result="BLOCKED",
                event_type=(
                    "BLACKLISTED_REQUEST_BLOCKED"
                ),
                event_severity="SECURITY",
            )

        # -------------------------------------------------
        # DUPLICATE REQUEST
        # -------------------------------------------------

        existing = (
            self._find_active_request(
                vehicle_id
            )
        )

        if existing is not None:

            database_service.execute(
                """
                UPDATE vehicles
                SET duplicate_requests =
                    duplicate_requests + 1
                WHERE vehicle_id = ?
                """,
                (vehicle_id,),
            )

            self._log_event(
                "DUPLICATE_REQUEST",
                (
                    "Duplicate emergency "
                    "request ignored"
                ),
                vehicle_id=vehicle_id,
                request_id=existing[
                    "request_id"
                ],
                severity="WARNING",
            )

            return {
                "result":
                    "DUPLICATE_REQUEST",

                "request":
                    existing,
            }

        # -------------------------------------------------
        # UNVERIFIED VEHICLE
        # -------------------------------------------------

        if not vehicle[
            "verified"
        ]:

            database_service.execute(
                """
                UPDATE vehicles
                SET suspicious_requests =
                    suspicious_requests + 1
                WHERE vehicle_id = ?
                """,
                (vehicle_id,),
            )

            return self._insert_request(
                vehicle_id=vehicle_id,
                junction_id=junction_id,
                hospital_id=(
                    hospital_id
                    or vehicle[
                        "hospital_id"
                    ]
                ),
                priority=priority,
                status="FLAGGED",
                verification_status=(
                    "UNVERIFIED"
                ),
                source=source,
                result="FLAGGED",
                event_type=(
                    "UNVERIFIED_REQUEST_FLAGGED"
                ),
                event_severity="WARNING",
            )

        # -------------------------------------------------
        # VERIFIED REQUEST
        # -------------------------------------------------

        return self._insert_request(
            vehicle_id=vehicle_id,
            junction_id=junction_id,
            hospital_id=(
                hospital_id
                or vehicle[
                    "hospital_id"
                ]
            ),
            priority=priority,
            status="PENDING",
            verification_status=(
                "VERIFIED"
            ),
            source=source,
            result="NEW_REQUEST",
            event_type=(
                "EMERGENCY_REQUEST_CREATED"
            ),
            event_severity="INFO",
        )

    # =====================================================
    # REQUEST INSERT
    # =====================================================

    def _insert_request(
        self,
        vehicle_id,
        junction_id,
        hospital_id,
        priority,
        status,
        verification_status,
        source,
        result,
        event_type,
        event_severity,
    ):

        created_at = self._now_iso()

        row_id = database_service.insert(
            """
            INSERT INTO emergency_requests (
                vehicle_id,
                junction_id,
                hospital_id,
                priority,
                status,
                verification_status,
                source,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                vehicle_id,
                junction_id,
                hospital_id,
                priority,
                status,
                verification_status,
                source,
                created_at,
            ),
        )

        request_id = (
            f"REQ-{row_id:05d}"
        )

        database_service.execute(
            """
            UPDATE emergency_requests
            SET request_id = ?
            WHERE id = ?
            """,
            (
                request_id,
                row_id,
            ),
        )

        self._log_event(
            event_type,
            (
                f"Emergency request "
                f"{request_id}: "
                f"{verification_status}"
            ),
            vehicle_id=vehicle_id,
            junction_id=junction_id,
            request_id=request_id,
            severity=event_severity,
        )

        return {
            "result": result,
            "request":
                self.get_request(
                    request_id
                ),
        }

    # =====================================================
    # REQUEST LIST / GET
    # =====================================================

    def list_requests(self):

        rows = database_service.fetch_all(
            """
            SELECT *
            FROM emergency_requests
            ORDER BY id DESC
            """
        )

        return [
            self._request_from_row(
                row
            )
            for row in rows
        ]

    def get_request(
        self,
        request_id,
    ):

        row = database_service.fetch_one(
            """
            SELECT *
            FROM emergency_requests
            WHERE request_id = ?
            """,
            (request_id,),
        )

        return self._request_from_row(
            row
        )

    # =====================================================
    # REQUEST ACTIONS
    # =====================================================

    def approve_request(
        self,
        request_id,
    ):

        item = self.get_request(
            request_id
        )

        if item is None:
            return None

        if item["status"] not in {
            "PENDING",
            "FLAGGED",
        }:
            return item

        approved_at = (
            self._now_iso()
        )

        database_service.execute(
            """
            UPDATE emergency_requests
            SET
                status = 'APPROVED',
                approved_at = ?
            WHERE request_id = ?
            """,
            (
                approved_at,
                request_id,
            ),
        )

        self._log_event(
            "REQUEST_APPROVED",
            (
                f"{request_id} approved"
            ),
            vehicle_id=item[
                "vehicle_id"
            ],
            junction_id=item[
                "junction_id"
            ],
            request_id=request_id,
        )

        return self.get_request(
            request_id
        )

    def reject_request(
        self,
        request_id,
    ):

        item = self.get_request(
            request_id
        )

        if item is None:
            return None

        if item["status"] in {
            "COMPLETED",
            "REJECTED",
            "BLOCKED",
        }:
            return item

        database_service.execute(
            """
            UPDATE emergency_requests
            SET status = 'REJECTED'
            WHERE request_id = ?
            """,
            (request_id,),
        )

        vehicle = self.get_vehicle(
            item["vehicle_id"]
        )

        if vehicle is not None:

            database_service.execute(
                """
                UPDATE vehicles
                SET rejected_requests =
                    rejected_requests + 1
                WHERE vehicle_id = ?
                """,
                (
                    item[
                        "vehicle_id"
                    ],
                ),
            )

        self._log_event(
            "REQUEST_REJECTED",
            (
                f"{request_id} rejected"
            ),
            vehicle_id=item[
                "vehicle_id"
            ],
            junction_id=item[
                "junction_id"
            ],
            request_id=request_id,
            severity="WARNING",
        )

        return self.get_request(
            request_id
        )

    def resolve_request(
        self,
        request_id,
    ):

        item = self.get_request(
            request_id
        )

        if item is None:
            return None

        if item["status"] == (
            "COMPLETED"
        ):
            return item

        completed_at = (
            self._now_iso()
        )

        database_service.execute(
            """
            UPDATE emergency_requests
            SET
                status = 'COMPLETED',
                completed_at = ?
            WHERE request_id = ?
            """,
            (
                completed_at,
                request_id,
            ),
        )

        vehicle = self.get_vehicle(
            item["vehicle_id"]
        )

        if vehicle is not None:

            database_service.execute(
                """
                UPDATE vehicles
                SET completed_requests =
                    completed_requests + 1
                WHERE vehicle_id = ?
                """,
                (
                    item[
                        "vehicle_id"
                    ],
                ),
            )

        self._log_event(
            "REQUEST_COMPLETED",
            (
                f"{request_id} completed"
            ),
            vehicle_id=item[
                "vehicle_id"
            ],
            junction_id=item[
                "junction_id"
            ],
            request_id=request_id,
        )

        return self.get_request(
            request_id
        )

    # =====================================================
    # HOSPITALS
    # =====================================================

    def list_hospitals(self):

        rows = database_service.fetch_all(
            """
            SELECT *
            FROM hospitals
            ORDER BY hospital_id
            """
        )

        return [
            {
                "hospital_id":
                    row["hospital_id"],

                "name":
                    row["name"],

                "lat":
                    row["lat"],

                "lon":
                    row["lon"],

                "emergency_available":
                    bool(
                        row[
                            "emergency_available"
                        ]
                    ),

                "source":
                    row["source"],
            }
            for row in rows
        ]

    def hospital_incoming(
        self,
        hospital_id,
    ):

        rows = database_service.fetch_all(
            """
            SELECT *
            FROM emergency_requests
            WHERE
                hospital_id = ?
                AND status IN (
                    'PENDING',
                    'VERIFIED',
                    'APPROVED',
                    'ACTIVATING',
                    'ACTIVE'
                )
            ORDER BY id DESC
            """,
            (hospital_id,),
        )

        return [
            self._request_from_row(
                row
            )
            for row in rows
        ]

    # =====================================================
    # EVENTS
    # =====================================================

    def list_events(
        self,
        limit=100,
    ):

        rows = database_service.fetch_all(
            """
            SELECT *
            FROM events
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )

        return [
            self._event_from_row(
                row
            )
            for row in rows
        ]


prioway_store = PrioWayStore()