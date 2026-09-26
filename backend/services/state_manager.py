import csv
import os
import threading
import time
from collections import deque
from datetime import datetime, timezone


# =========================================================
# PATHS
# =========================================================

PROJECT_ROOT = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        ".."
    )
)

CSV_PATH = os.path.join(
    PROJECT_ROOT,
    "data",
    "signal_events.csv"
)


# =========================================================
# TIMINGS
# =========================================================

PI_ONLINE_SECONDS = 5
JUNCTION_ONLINE_SECONDS = 5
VEHICLE_RECENT_SECONDS = 10

# Absolute protection against an endless RESETTING state.
RESET_TIMEOUT_SECONDS = 12


class StateManager:

    def __init__(self):

        self.lock = threading.RLock()

        # -------------------------------------------------
        # SYSTEM STATE
        # -------------------------------------------------

        self.state = "NORMAL"

        self.emergency = None

        self.latest_event = None

        # -------------------------------------------------
        # COMMAND QUEUE
        # -------------------------------------------------

        self.commands = []

        self.next_command_id = 1

        # -------------------------------------------------
        # HARDWARE
        # -------------------------------------------------

        self.current_light = 0

        self.gas = "UNKNOWN"

        # -------------------------------------------------
        # HEARTBEATS
        # -------------------------------------------------

        self.pi_last_seen = 0

        self.junction_last_seen = 0

        self.vehicle_last_seen = 0

        # -------------------------------------------------
        # GPS
        # -------------------------------------------------

        self.vehicle_lat = None

        self.vehicle_lon = None

        self.vehicle_gps_last_seen = 0

        # -------------------------------------------------
        # RESET WATCHDOG
        # -------------------------------------------------

        self.reset_started_at = None

        self.reset_reason = None

        # -------------------------------------------------
        # EVENT MEMORY
        # -------------------------------------------------

        self.events = deque(
            maxlen=100
        )

        self._ensure_csv()

    # =====================================================
    # TIME
    # =====================================================

    def _now_iso(self):

        return (
            datetime.now(
                timezone.utc
            )
            .astimezone()
            .isoformat(
                timespec="seconds"
            )
        )

    # =====================================================
    # CSV
    # =====================================================

    def _ensure_csv(self):

        os.makedirs(
            os.path.dirname(
                CSV_PATH
            ),
            exist_ok=True
        )

        if (
            not os.path.exists(
                CSV_PATH
            )
            or
            os.path.getsize(
                CSV_PATH
            ) == 0
        ):

            with open(
                CSV_PATH,
                "w",
                newline="",
                encoding="utf-8"
            ) as file:

                writer = csv.writer(
                    file
                )

                writer.writerow([
                    "timestamp",
                    "event_type",
                    "state",
                    "source",
                    "details"
                ])

    # =====================================================
    # EVENT LOG
    # =====================================================

    def _log_locked(
        self,
        event_type,
        source,
        details
    ):

        event = {

            "timestamp":
                self._now_iso(),

            "event_type":
                event_type,

            "state":
                self.state,

            "source":
                source,

            "details":
                details
        }

        self.latest_event = event

        self.events.appendleft(
            event
        )

        try:

            with open(
                CSV_PATH,
                "a",
                newline="",
                encoding="utf-8"
            ) as file:

                writer = csv.writer(
                    file
                )

                writer.writerow([
                    event["timestamp"],
                    event["event_type"],
                    event["state"],
                    event["source"],
                    event["details"]
                ])

        except OSError as error:

            print(
                "CSV logging error:",
                error
            )

    # =====================================================
    # COMMAND QUEUE HELPERS
    # =====================================================

    def _remove_command_locked(
        self,
        command
    ):

        self.commands = [

            item

            for item in self.commands

            if item["command"] != command
        ]

    # -----------------------------------------------------

    def _queue_command_locked(
        self,
        command
    ):

        # Never have duplicate pending commands.

        for item in self.commands:

            if (
                item["command"]
                ==
                command
            ):

                return item["id"]

        command_id = (
            self.next_command_id
        )

        self.next_command_id += 1

        self.commands.append({

            "id":
                command_id,

            "command":
                command,

            "created_at":
                time.time()
        })

        return command_id

    # =====================================================
    # RESET COMPLETION
    # =====================================================

    def _complete_reset_locked(
        self,
        source,
        details,
        event_type="CORRIDOR_CLEARED"
    ):

        self.state = "NORMAL"

        self.emergency = None

        self.reset_started_at = None

        self.reset_reason = None

        # Clear stale commands from old cycle.

        self._remove_command_locked(
            "CMD:RESET"
        )

        self._remove_command_locked(
            "CMD:APPROVE"
        )

        self._log_locked(
            event_type,
            source,
            details
        )

    # =====================================================
    # START HARDWARE RESET
    # =====================================================

    def _begin_reset_locked(
        self,
        source,
        reason
    ):

        # -------------------------------------------------
        # IDEMPOTENT RESET
        #
        # Pressing resolve repeatedly must NOT create
        # multiple reset cycles.
        # -------------------------------------------------

        if (
            self.state
            !=
            "RESETTING"
        ):

            self.state = (
                "RESETTING"
            )

            self.reset_started_at = (
                time.time()
            )

            self.reset_reason = reason

            self._log_locked(
                "RESET_REQUEST",
                source,
                reason
            )

        elif (
            self.reset_started_at
            is None
        ):

            self.reset_started_at = (
                time.time()
            )

        # -------------------------------------------------
        # IMPORTANT RACE FIX
        #
        # If APPROVE is still queued when operator presses
        # reject, remove it BEFORE sending reset.
        # -------------------------------------------------

        self._remove_command_locked(
            "CMD:APPROVE"
        )

        # Queue only one reset.

        self._queue_command_locked(
            "CMD:RESET"
        )

    # =====================================================
    # RESET WATCHDOG
    # =====================================================

    def _check_reset_timeout_locked(
        self
    ):

        if (
            self.state
            !=
            "RESETTING"
        ):

            return

        if (
            self.reset_started_at
            is None
        ):

            return

        elapsed = (
            time.time()
            -
            self.reset_started_at
        )

        if (
            elapsed
            >=
            RESET_TIMEOUT_SECONDS
        ):

            self._complete_reset_locked(

                "BACKEND_WATCHDOG",

                (
                    "Reset confirmation timeout. "
                    "Software state recovered to NORMAL."
                ),

                event_type=(
                    "RESET_TIMEOUT_RECOVERY"
                )
            )

    # =====================================================
    # PI HEARTBEAT
    # =====================================================

    def mark_pi_seen(self):

        with self.lock:

            self.pi_last_seen = (
                time.time()
            )

            self._check_reset_timeout_locked()

    # =====================================================
    # GPS
    # =====================================================

    def update_vehicle_location(
        self,
        lat,
        lon
    ):

        with self.lock:

            now = time.time()

            self.vehicle_lat = lat

            self.vehicle_lon = lon

            self.vehicle_gps_last_seen = now

            self.vehicle_last_seen = now

    # =====================================================
    # EMERGENCY REQUEST
    # =====================================================

    def emergency_request(
        self,
        vehicle_id,
        junction_id
    ):

        with self.lock:

            self._check_reset_timeout_locked()

            # Same emergency received again over LoRa.

            if (
                self.state
                ==
                "EMERGENCY_PENDING"
            ):

                return {

                    "success":
                        True,

                    "message":
                        "Emergency already pending."
                }

            if (
                self.state
                !=
                "NORMAL"
            ):

                return {

                    "success":
                        False,

                    "message":
                        (
                            "Cannot accept emergency "
                            f"while state is {self.state}."
                        )
                }

            self.state = (
                "EMERGENCY_PENDING"
            )

            now = time.time()

            self.vehicle_last_seen = now

            self.emergency = {

                "vehicle":
                    vehicle_id,

                "junction":
                    junction_id,

                "timestamp":
                    self._now_iso()
            }

            # Remove stale commands from previous cycle.

            self._remove_command_locked(
                "CMD:RESET"
            )

            self._remove_command_locked(
                "CMD:CANCEL_PENDING"
            )

            self._log_locked(

                "EMERGENCY_REQUEST",

                vehicle_id,

                (
                    "Emergency request received "
                    f"for junction {junction_id}."
                )
            )

            return {

                "success":
                    True,

                "message":
                    "Emergency request accepted."
            }

    # =====================================================
    # APPROVE
    # =====================================================

    def approve(self):

        with self.lock:

            self._check_reset_timeout_locked()

            if (
                self.state
                !=
                "EMERGENCY_PENDING"
            ):

                return {

                    "success":
                        False,

                    "message":
                        (
                            "No emergency is waiting "
                            "for approval."
                        )
                }

            self.state = (
                "CORRIDOR_PENDING"
            )

            self._queue_command_locked(
                "CMD:APPROVE"
            )

            self._log_locked(

                "APPROVED",

                "CONTROL_ROOM",

                "Green corridor approved."
            )

            return {

                "success":
                    True,

                "message":
                    (
                        "Corridor approval "
                        "command queued."
                    )
            }

    # =====================================================
    # REJECT
    # =====================================================

    def reject(self):

        with self.lock:

            self._check_reset_timeout_locked()

            # =================================================
            # CASE 1
            #
            # REJECT BEFORE APPROVAL
            #
            # Hardware never entered corridor mode.
            # Therefore DO NOT enter RESETTING.
            # =================================================

            if (
                self.state
                ==
                "EMERGENCY_PENDING"
            ):

                self._remove_command_locked(
                    "CMD:APPROVE"
                )

                self._remove_command_locked(
                    "CMD:RESET"
                )

                self.state = "NORMAL"

                self.emergency = None

                self.reset_started_at = None

                self.reset_reason = None

                # This command is consumed by the Pi only.
                # It is NOT sent to the Junction ESP32.

                self._queue_command_locked(
                    "CMD:CANCEL_PENDING"
                )

                self._log_locked(

                    "REJECTED",

                    "CONTROL_ROOM",

                    (
                        "Emergency rejected before "
                        "corridor activation."
                    )
                )

                return {

                    "success":
                        True,

                    "message":
                        (
                            "Emergency rejected. "
                            "No hardware reset required."
                        )
                }

            # =================================================
            # CASE 2
            #
            # Corridor may already be activating/active.
            # Real hardware reset is required.
            # =================================================

            if self.state in [

                "CORRIDOR_PENDING",
                "ACTIVE_CORRIDOR"

            ]:

                self._begin_reset_locked(

                    "CONTROL_ROOM",

                    (
                        "Operator rejected/resolved "
                        "an activating or active corridor."
                    )
                )

                return {

                    "success":
                        True,

                    "message":
                        "Reset command queued."
                }

            # =================================================
            # CASE 3
            #
            # Already resetting.
            # Do nothing.
            # =================================================

            if (
                self.state
                ==
                "RESETTING"
            ):

                return {

                    "success":
                        True,

                    "message":
                        "Reset already in progress."
                }

            if (
                self.state
                ==
                "NORMAL"
            ):

                return {

                    "success":
                        True,

                    "message":
                        "System already normal."
                }

            return {

                "success":
                    False,

                "message":
                    (
                        "Reject unavailable "
                        f"while state is {self.state}."
                    )
            }

    # =====================================================
    # RESET
    # =====================================================

    def reset(self):

        with self.lock:

            self._check_reset_timeout_locked()

            # -------------------------------------------------
            # Already normal.
            # -------------------------------------------------

            if (
                self.state
                ==
                "NORMAL"
            ):

                return {

                    "success":
                        True,

                    "message":
                        "System already normal."
                }

            # -------------------------------------------------
            # Pending emergency has NOT activated hardware.
            # Treat reset as reject.
            # -------------------------------------------------

            if (
                self.state
                ==
                "EMERGENCY_PENDING"
            ):

                self._remove_command_locked(
                    "CMD:APPROVE"
                )

                self._remove_command_locked(
                    "CMD:RESET"
                )

                self.state = "NORMAL"

                self.emergency = None

                self.reset_started_at = None

                self.reset_reason = None

                self._queue_command_locked(
                    "CMD:CANCEL_PENDING"
                )

                self._log_locked(

                    "PENDING_CANCELLED",

                    "CONTROL_ROOM",

                    (
                        "Pending emergency cleared "
                        "without hardware reset."
                    )
                )

                return {

                    "success":
                        True,

                    "message":
                        "Pending emergency cleared."
                }

            # -------------------------------------------------
            # Real corridor reset.
            # -------------------------------------------------

            self._begin_reset_locked(

                "CONTROL_ROOM",

                "Reset requested."
            )

            return {

                "success":
                    True,

                "message":
                    "Reset command queued."
            }

    # =====================================================
    # JUNCTION EVENT
    # =====================================================

    def junction_event(
        self,
        message
    ):

        with self.lock:

            self.junction_last_seen = (
                time.time()
            )

            self._check_reset_timeout_locked()

            # =================================================
            # TRAFFIC LIGHT SYNC
            # =================================================

            if message.startswith(
                "SYNC:LIGHT:"
            ):

                try:

                    light = int(
                        message.split(
                            ":"
                        )[2]
                    )

                    if light not in [
                        0,
                        1,
                        2
                    ]:

                        return

                    self.current_light = light

                    # -----------------------------------------
                    # RESET FAILSAFE
                    #
                    # If normal traffic signal messages have
                    # resumed, the Junction is no longer
                    # holding the green corridor.
                    # -----------------------------------------

                    if (
                        self.state
                        ==
                        "RESETTING"
                    ):

                        self._complete_reset_locked(

                            "JUNCTION",

                            (
                                "Normal traffic-light sync "
                                "resumed after reset."
                            ),

                            event_type=(
                                "RESET_CONFIRMED_BY_LIGHT"
                            )
                        )

                except (
                    ValueError,
                    IndexError
                ):

                    pass

                return

            # =================================================
            # GAS
            # =================================================

            if message.startswith(
                "DATA:GAS:"
            ):

                try:

                    raw_gas = int(
                        message.split(
                            ":"
                        )[2]
                    )

                    if raw_gas < 600:

                        self.gas = "NORMAL"

                    elif raw_gas < 1200:

                        self.gas = "POOR"

                    else:

                        self.gas = "DANGER"

                except (
                    ValueError,
                    IndexError
                ):

                    pass

                return

            # =================================================
            # CORRIDOR PENDING
            # =================================================

            if (
                message
                ==
                "SYNC:CORRIDOR:PENDING"
            ):

                # Ignore old activation message if reset
                # has already started.

                if (
                    self.state
                    !=
                    "RESETTING"
                ):

                    self.state = (
                        "CORRIDOR_PENDING"
                    )

                return

            # =================================================
            # CORRIDOR ACTIVE
            # =================================================

            if (
                message
                ==
                "SYNC:CORRIDOR:ACTIVE"
            ):

                # Never allow stale ACTIVE message to
                # cancel a reset operation.

                if (
                    self.state
                    ==
                    "RESETTING"
                ):

                    return

                self.state = (
                    "ACTIVE_CORRIDOR"
                )

                self.current_light = 1

                self._log_locked(

                    "CORRIDOR_ACTIVE",

                    "JUNCTION",

                    "Green corridor active."
                )

                return

            # =================================================
            # RESET PENDING
            # =================================================

            if (
                message
                ==
                "SYNC:RESET:PENDING"
            ):

                if (
                    self.state
                    !=
                    "NORMAL"
                ):

                    self.state = (
                        "RESETTING"
                    )

                    if (
                        self.reset_started_at
                        is None
                    ):

                        self.reset_started_at = (
                            time.time()
                        )

                return

            # =================================================
            # CORRIDOR CLEARED
            # =================================================

            if (
                message
                ==
                "SYNC:CORRIDOR:CLEARED"
            ):

                self.current_light = 0

                self._complete_reset_locked(

                    "JUNCTION",

                    (
                        "Junction confirmed "
                        "corridor cleared."
                    )
                )

                return

    # =====================================================
    # COMMANDS
    # =====================================================

    def get_commands(self):

        with self.lock:

            self._check_reset_timeout_locked()

            return [

                dict(item)

                for item in self.commands
            ]

    # -----------------------------------------------------

    def acknowledge(
        self,
        command_id
    ):

        with self.lock:

            self.commands = [

                item

                for item in self.commands

                if item["id"] != command_id
            ]

    # Compatibility with older app.py

    def acknowledge_command(
        self,
        command_id
    ):

        self.acknowledge(
            command_id
        )

    # =====================================================
    # EVENTS
    # =====================================================

    def get_recent_events(
        self,
        limit=20
    ):

        with self.lock:

            return list(
                self.events
            )[:limit]

    # =====================================================
    # DASHBOARD SNAPSHOT
    # =====================================================

    def snapshot(self):

        with self.lock:

            self._check_reset_timeout_locked()

            now = time.time()

            gps_valid = (

                self.vehicle_lat
                is not None

                and

                self.vehicle_lon
                is not None
            )

            if (
                self.vehicle_gps_last_seen
                >
                0
            ):

                gps_age = (

                    now
                    -
                    self.vehicle_gps_last_seen
                )

            else:

                gps_age = None

            if (
                self.reset_started_at
                is not None
            ):

                reset_age = (

                    now
                    -
                    self.reset_started_at
                )

            else:

                reset_age = None

            return {

                "state":
                    self.state,

                "emergency":
                    self.emergency,

                "latest_event":
                    self.latest_event,

                "current_light":
                    self.current_light,

                "gas":
                    self.gas,

                "pi_online":
                    (
                        self.pi_last_seen > 0
                        and
                        (
                            now
                            -
                            self.pi_last_seen
                        )
                        <=
                        PI_ONLINE_SECONDS
                    ),

                "junction_online":
                    (
                        self.junction_last_seen > 0
                        and
                        (
                            now
                            -
                            self.junction_last_seen
                        )
                        <=
                        JUNCTION_ONLINE_SECONDS
                    ),

                "vehicle_recent":
                    (
                        self.vehicle_last_seen > 0
                        and
                        (
                            now
                            -
                            self.vehicle_last_seen
                        )
                        <=
                        VEHICLE_RECENT_SECONDS
                    ),

                "vehicle_location": {

                    "lat":
                        self.vehicle_lat,

                    "lon":
                        self.vehicle_lon,

                    "valid":
                        gps_valid,

                    "age_seconds":
                        (
                            round(
                                gps_age,
                                1
                            )
                            if gps_age
                            is not None
                            else None
                        )
                },

                "reset": {

                    "active":
                        (
                            self.state
                            ==
                            "RESETTING"
                        ),

                    "reason":
                        self.reset_reason,

                    "age_seconds":
                        (
                            round(
                                reset_age,
                                1
                            )
                            if reset_age
                            is not None
                            else None
                        )
                }
            }


# =========================================================
# SINGLE SHARED INSTANCE
# =========================================================

state_manager = StateManager()