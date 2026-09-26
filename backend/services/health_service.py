import threading
import time
from datetime import (
    datetime,
    timezone,
)

from services.database_service import (
    database_service,
)

from services.simulation_service import (
    build_simulation_updates,
)

from services.state_manager import (
    state_manager,
)


# =========================================================
# HEALTH TIMINGS
# =========================================================

ONLINE_SECONDS = 10
DEGRADED_SECONDS = 25
OFFLINE_SECONDS = 40

MONITOR_INTERVAL_SECONDS = 3


VALID_FORCED_STATES = {
    "ONLINE",
    "DEGRADED",
    "OFFLINE",
    "FAILED",
}


# =========================================================
# BASIC HEALTH CALCULATION
# =========================================================

def calculate_health(
    last_seen,
    forced_status=None,
):

    if forced_status in VALID_FORCED_STATES:

        return {
            "status":
                forced_status,

            "age_seconds":
                (
                    None
                    if last_seen is None
                    else round(
                        max(
                            0,
                            time.time()
                            - last_seen,
                        ),
                        1,
                    )
                ),
        }

    if last_seen is None:

        return {
            "status": "OFFLINE",
            "age_seconds": None,
        }

    age = max(
        0,
        time.time()
        - last_seen,
    )

    if age <= ONLINE_SECONDS:

        status = "ONLINE"

    elif age <= DEGRADED_SECONDS:

        status = "DEGRADED"

    else:

        status = "OFFLINE"

    return {
        "status": status,
        "age_seconds": round(
            age,
            1,
        ),
    }


# =========================================================
# BACKGROUND HEALTH MONITOR
# =========================================================

class HealthMonitorService:

    def __init__(self):

        self._thread = None

        self._started = False

        self._lock = (
            threading.RLock()
        )

        self._last_junction_health = {}

        self._last_vehicle_health = {}

    # =====================================================
    # TIME
    # =====================================================

    def _now_iso(self):

        return datetime.now(
            timezone.utc
        ).isoformat()

    # =====================================================
    # EVENT WRITER
    # =====================================================

    def _log_event(
        self,
        event_type,
        details,
        severity="INFO",
        vehicle_id=None,
        junction_id=None,
    ):

        timestamp = (
            self._now_iso()
        )

        row_id = (
            database_service.insert(
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
                    None,
                    timestamp,
                ),
            )
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

    # =====================================================
    # REAL PHYSICAL HARDWARE SYNC
    # =====================================================

    def _sync_physical_nodes(
        self,
    ):

        snapshot = (
            state_manager.snapshot()
        )

        now = time.time()

        # -------------------------------------------------
        # PHYSICAL VEHICLE
        # -------------------------------------------------

        vehicle_online = bool(
            snapshot.get(
                "vehicle_recent",
                False,
            )
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

        vehicle_location = (
            snapshot.get(
                "vehicle_location",
                {},
            )
        )

        if vehicle_location.get(
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
                    vehicle_location.get(
                        "lat"
                    ),

                    vehicle_location.get(
                        "lon"
                    ),
                ),
            )

        # -------------------------------------------------
        # PHYSICAL JUNCTION
        # -------------------------------------------------

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
    # SIMULATION HEARTBEATS
    # =====================================================

    def _sync_simulated_nodes(
        self,
    ):

        updates = (
            build_simulation_updates()
        )

        # -------------------------------------------------
        # SIMULATED VEHICLES
        # -------------------------------------------------

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

        # -------------------------------------------------
        # SIMULATED JUNCTIONS
        # -------------------------------------------------

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
    # JUNCTION HEALTH CHECK
    # =====================================================

    def _check_junction_health(
        self,
    ):

        rows = (
            database_service.fetch_all(
                """
                SELECT
                    junction_id,
                    name,
                    source,
                    last_seen,
                    forced_health
                FROM junctions
                ORDER BY junction_id
                """
            )
        )

        for row in rows:

            junction_id = (
                row["junction_id"]
            )

            health = calculate_health(
                row["last_seen"],
                row["forced_health"],
            )

            current_status = (
                health["status"]
            )

            previous_status = (
                self
                ._last_junction_health
                .get(
                    junction_id
                )
            )

            # First scan is baseline only.
            # Do not fill the log with startup noise.

            if previous_status is None:

                self._last_junction_health[
                    junction_id
                ] = current_status

                continue

            if (
                previous_status
                ==
                current_status
            ):

                continue

            self._last_junction_health[
                junction_id
            ] = current_status

            severity = "INFO"

            if current_status == (
                "DEGRADED"
            ):

                severity = "WARNING"

            elif current_status in {
                "OFFLINE",
                "FAILED",
            }:

                severity = "CRITICAL"

            self._log_event(
                event_type=(
                    "JUNCTION_HEALTH_TRANSITION"
                ),

                details=(
                    f"{junction_id} changed "
                    f"from {previous_status} "
                    f"to {current_status}"
                ),

                severity=severity,

                junction_id=
                    junction_id,
            )

    # =====================================================
    # VEHICLE HEALTH CHECK
    # =====================================================

    def _check_vehicle_health(
        self,
    ):

        rows = (
            database_service.fetch_all(
                """
                SELECT
                    vehicle_id,
                    name,
                    source,
                    last_seen
                FROM vehicles
                ORDER BY vehicle_id
                """
            )
        )

        for row in rows:

            vehicle_id = (
                row["vehicle_id"]
            )

            health = calculate_health(
                row["last_seen"]
            )

            current_status = (
                health["status"]
            )

            previous_status = (
                self
                ._last_vehicle_health
                .get(
                    vehicle_id
                )
            )

            if previous_status is None:

                self._last_vehicle_health[
                    vehicle_id
                ] = current_status

                continue

            if (
                previous_status
                ==
                current_status
            ):

                continue

            self._last_vehicle_health[
                vehicle_id
            ] = current_status

            severity = "INFO"

            if current_status == (
                "DEGRADED"
            ):

                severity = "WARNING"

            elif current_status in {
                "OFFLINE",
                "FAILED",
            }:

                severity = "CRITICAL"

            self._log_event(
                event_type=(
                    "VEHICLE_HEALTH_TRANSITION"
                ),

                details=(
                    f"{vehicle_id} changed "
                    f"from {previous_status} "
                    f"to {current_status}"
                ),

                severity=severity,

                vehicle_id=
                    vehicle_id,
            )

    # =====================================================
    # ONE MONITOR CYCLE
    # =====================================================

    def _monitor_once(
        self,
    ):

        self._sync_physical_nodes()

        self._sync_simulated_nodes()

        self._check_junction_health()

        self._check_vehicle_health()

    # =====================================================
    # THREAD LOOP
    # =====================================================

    def _run(
        self,
    ):

        while True:

            try:

                self._monitor_once()

            except Exception as error:

                print(
                    "PrioWay health monitor error:",
                    error,
                )

            time.sleep(
                MONITOR_INTERVAL_SECONDS
            )

    # =====================================================
    # START
    # =====================================================

    def start(
        self,
    ):

        with self._lock:

            if self._started:

                return

            self._started = True

            self._thread = (
                threading.Thread(
                    target=self._run,
                    daemon=True,
                    name=(
                        "PrioWayHealthMonitor"
                    ),
                )
            )

            self._thread.start()

            print(
                "PrioWay health monitor started."
            )


# =========================================================
# START AUTOMATICALLY
# =========================================================

health_monitor_service = (
    HealthMonitorService()
)

health_monitor_service.start()