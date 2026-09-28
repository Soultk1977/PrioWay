import os
import time
import threading

import requests
import serial

from services.display_service import (
    DisplayService
)

from services.camera_service import (
    CameraService
)


# =========================================================
# CONFIGURATION
# =========================================================

BACKEND_URL = os.getenv(

    "RESQSYNC_BACKEND_URL",

    "http://192.168.137.1:5000"
)

SERIAL_PORT = "/dev/serial0"

BAUD_RATE = 115200

VEHICLE_ID = "VEH-001"

JUNCTION_ID = "JNC-001"


# =========================================================
# RESET SAFETY
# =========================================================

RESET_RETRY_SECONDS = 5

RESET_FAILSAFE_SECONDS = 10


class TrafficNodeManager:

    def __init__(self):

        # =================================================
        # SERVICES
        # =================================================

        self.display = (
            DisplayService()
        )

        self.camera = (
            CameraService()
        )

        # =================================================
        # UART
        # =================================================

        self.esp32 = serial.Serial(

            SERIAL_PORT,

            BAUD_RATE,

            timeout=0.1
        )

        print(
            "UART Bridge to ESP32 Online."
        )

        # All threads share one UART.
        # Prevent command writes from interleaving.

        self.serial_write_lock = (
            threading.Lock()
        )

        # =================================================
        # LOCAL STATE
        # =================================================

        # 0 RED
        # 1 GREEN
        # 2 YELLOW

        self.current_light = 0

        self.gas = "NORMAL"

        # IMPORTANT:
        #
        # NORMAL
        # REQUESTED   = emergency waiting for approval
        # ACTIVATING  = approval sent
        # ACTIVE      = green corridor active
        # RESETTING   = hardware reset underway

        self.corridor_state = (
            "NORMAL"
        )

        self.countdown_running = (
            False
        )

        # =================================================
        # RESET WATCHDOG
        # =================================================

        self.reset_started_at = None

        self.reset_retry_sent = False

        # =================================================
        # BACKEND COMMAND TRACKING
        # =================================================

        self.handled_commands = set()

    # =====================================================
    # UART WRITE
    # =====================================================

    def write_uart(
        self,
        command,
        log=True
    ):

        try:

            with self.serial_write_lock:

                self.esp32.write(
                    (
                        command
                        +
                        "\n"
                    ).encode(
                        "utf-8"
                    )
                )

                self.esp32.flush()

            if log:

                print(
                    f"Sending to Junction: {command}"
                )

            return True

        except Exception as error:

            print(
                "UART write error:",
                error
            )

            return False

    # =====================================================
    # BACKEND - EMERGENCY
    # =====================================================

    def notify_emergency(self):

        try:

            response = requests.post(

                f"{BACKEND_URL}"
                "/api/emergency",

                json={

                    "vehicle_id":
                        VEHICLE_ID,

                    "junction_id":
                        JUNCTION_ID
                },

                timeout=5
            )

            print(
                "Emergency backend response:",
                response.status_code,
                response.text
            )

        except requests.RequestException as error:

            print(
                "Backend emergency error:",
                error
            )

    # =====================================================
    # BACKEND - REJECT PENDING
    # =====================================================

    def reject_backend(self):

        try:

            response = requests.post(

                f"{BACKEND_URL}"
                "/api/reject",

                timeout=5
            )

            print(
                "Reject backend response:",
                response.status_code,
                response.text
            )

        except requests.RequestException as error:

            print(
                "Backend reject error:",
                error
            )

    # =====================================================
    # BACKEND - RESET ACTIVE
    # =====================================================

    def reset_backend(self):

        try:

            response = requests.post(

                f"{BACKEND_URL}"
                "/api/reset",

                timeout=5
            )

            print(
                "Reset backend response:",
                response.status_code,
                response.text
            )

        except requests.RequestException as error:

            print(
                "Backend reset error:",
                error
            )

    # =====================================================
    # COMMAND ACK
    # =====================================================

    def acknowledge_command(
        self,
        command_id
    ):

        try:

            requests.post(

                f"{BACKEND_URL}"
                "/api/pi/ack",

                json={
                    "command_id":
                        command_id
                },

                timeout=5
            )

        except requests.RequestException as error:

            print(
                "Command ACK error:",
                error
            )

    # =====================================================
    # JUNCTION EVENT -> WINDOWS
    # =====================================================

    def notify_junction_event(
        self,
        message
    ):

        try:

            requests.post(

                f"{BACKEND_URL}"
                "/api/pi/junction-event",

                json={
                    "message":
                        message
                },

                timeout=2
            )

        except requests.RequestException as error:

            print(
                "Junction backend error:",
                error
            )

    # =====================================================
    # GPS -> WINDOWS
    # =====================================================

    def notify_vehicle_location(
        self,
        lat,
        lon
    ):

        try:

            requests.post(

                f"{BACKEND_URL}"
                "/api/pi/vehicle-location",

                json={

                    "lat":
                        lat,

                    "lon":
                        lon
                },

                timeout=2
            )

        except requests.RequestException:

            pass

    # =====================================================
    # COMPLETE LOCAL RESET
    # =====================================================

    def complete_local_reset(
        self,
        reason,
        notify_backend=True
    ):

        print(
            f"Reset complete: {reason}"
        )

        self.corridor_state = (
            "NORMAL"
        )

        self.reset_started_at = None

        self.reset_retry_sent = False

        self.display.draw_normal_state(

            self.current_light,

            self.gas
        )

        # If actual CORRIDOR:CLEARED was lost,
        # synthesize it so Windows also exits RESETTING.

        if notify_backend:

            threading.Thread(

                target=
                    self.notify_junction_event,

                args=(
                    "SYNC:CORRIDOR:CLEARED",
                ),

                daemon=True

            ).start()

    # =====================================================
    # ENTER RESETTING
    # =====================================================

    def enter_resetting(self):

        if (
            self.corridor_state
            !=
            "RESETTING"
        ):

            print(
                "Local state -> RESETTING"
            )

        self.corridor_state = (
            "RESETTING"
        )

        if (
            self.reset_started_at
            is None
        ):

            self.reset_started_at = (
                time.time()
            )

        self.reset_retry_sent = False

    # =====================================================
    # BACKEND COMMAND LOOP
    # =====================================================

    def command_loop(self):

        print(
            "Backend command loop started."
        )

        while True:

            try:

                response = requests.get(

                    f"{BACKEND_URL}"
                    "/api/pi/commands",

                    timeout=5
                )

                commands = (
                    response
                    .json()
                    .get(
                        "commands",
                        []
                    )
                )

                for item in commands:

                    command_id = (
                        item["id"]
                    )

                    command = (
                        item["command"]
                    )

                    if (
                        command_id
                        in
                        self.handled_commands
                    ):

                        continue

                    print(
                        f"Backend command: {command}"
                    )

                    # =====================================
                    # CANCEL PENDING
                    #
                    # Emergency was rejected BEFORE
                    # corridor approval.
                    #
                    # This is Pi-only.
                    # Do NOT send it to Junction ESP32.
                    # =====================================

                    if (
                        command
                        ==
                        "CMD:CANCEL_PENDING"
                    ):

                        print(
                            "Pending emergency "
                            "cancelled by operator."
                        )

                        self.corridor_state = (
                            "NORMAL"
                        )

                        self.reset_started_at = None

                        self.reset_retry_sent = False

                        self.display.draw_normal_state(

                            self.current_light,

                            self.gas
                        )

                        self.handled_commands.add(
                            command_id
                        )

                        self.acknowledge_command(
                            command_id
                        )

                        continue

                    # =====================================
                    # APPROVE
                    # =====================================

                    if (
                        command
                        ==
                        "CMD:APPROVE"
                    ):

                        # If reset already started,
                        # this is a stale approve.

                        if (
                            self.corridor_state
                            ==
                            "RESETTING"
                        ):

                            print(
                                "Ignoring stale "
                                "CMD:APPROVE during reset."
                            )

                            self.handled_commands.add(
                                command_id
                            )

                            self.acknowledge_command(
                                command_id
                            )

                            continue

                        self.corridor_state = (
                            "ACTIVATING"
                        )

                        sent = self.write_uart(
                            command
                        )

                        if sent:

                            self.handled_commands.add(
                                command_id
                            )

                            self.acknowledge_command(
                                command_id
                            )

                        continue

                    # =====================================
                    # RESET
                    # =====================================

                    if (
                        command
                        ==
                        "CMD:RESET"
                    ):

                        self.enter_resetting()

                        sent = self.write_uart(
                            command
                        )

                        if sent:

                            self.handled_commands.add(
                                command_id
                            )

                            self.acknowledge_command(
                                command_id
                            )

                        continue

                    # =====================================
                    # UNKNOWN/FUTURE COMMAND
                    # =====================================

                    sent = self.write_uart(
                        command
                    )

                    if sent:

                        self.handled_commands.add(
                            command_id
                        )

                        self.acknowledge_command(
                            command_id
                        )

            except requests.RequestException as error:

                print(
                    "Backend connection error:",
                    error
                )

            except Exception as error:

                print(
                    "Backend command error:",
                    error
                )

            time.sleep(
                0.5
            )

    # =====================================================
    # RESET WATCHDOG
    # =====================================================

    def reset_watchdog(self):

        while True:

            try:

                if (
                    self.corridor_state
                    ==
                    "RESETTING"
                ):

                    if (
                        self.reset_started_at
                        is None
                    ):

                        self.reset_started_at = (
                            time.time()
                        )

                    elapsed = (

                        time.time()

                        -

                        self.reset_started_at
                    )

                    # -------------------------------------
                    # Retry reset once.
                    # -------------------------------------

                    if (
                        elapsed
                        >=
                        RESET_RETRY_SECONDS
                        and
                        not self.reset_retry_sent
                    ):

                        print(
                            "Reset confirmation missing; "
                            "retrying CMD:RESET once."
                        )

                        self.write_uart(
                            "CMD:RESET"
                        )

                        self.reset_retry_sent = (
                            True
                        )

                    # -------------------------------------
                    # Absolute failsafe.
                    #
                    # We never remain RESETTING forever.
                    # -------------------------------------

                    if (
                        elapsed
                        >=
                        RESET_FAILSAFE_SECONDS
                    ):

                        print(
                            "RESET watchdog timeout."
                        )

                        self.complete_local_reset(

                            (
                                "watchdog timeout "
                                "recovery"
                            ),

                            notify_backend=True
                        )

            except Exception as error:

                print(
                    "Reset watchdog error:",
                    error
                )

            time.sleep(
                0.25
            )

    # =====================================================
    # SENSOR POLLING
    # =====================================================

    def request_sensor_data(self):

        while True:

            if (
                self.corridor_state
                ==
                "NORMAL"
            ):

                self.write_uart(

                    "CMD:SENSOR",

                    log=False
                )

            time.sleep(
                2
            )

    # =====================================================
    # OLED COUNTDOWN
    # =====================================================

    def handle_countdown(self):

        if self.countdown_running:

            return

        self.countdown_running = (
            True
        )

        try:

            for seconds in range(
                5,
                0,
                -1
            ):

                if (
                    self.corridor_state
                    !=
                    "ACTIVATING"
                ):

                    break

                self.display.draw_corridor_pending(
                    seconds
                )

                time.sleep(
                    1
                )

        finally:

            self.countdown_running = (
                False
            )

    # =====================================================
    # NMEA -> DECIMAL
    # =====================================================

    def nmea_to_decimal(
        self,
        value,
        direction
    ):

        if not value:

            return None

        try:

            raw = float(
                value
            )

            degrees = int(
                raw / 100
            )

            minutes = (

                raw

                -

                (
                    degrees
                    *
                    100
                )
            )

            decimal = (

                degrees

                +

                (
                    minutes
                    /
                    60
                )
            )

            if direction in [
                "S",
                "W"
            ]:

                decimal *= -1

            return decimal

        except Exception:

            return None

    # =====================================================
    # GPS
    # =====================================================

    def handle_gps(
        self,
        raw_data
    ):

        try:

            sentence = raw_data.replace(

                "GPS:",

                "",

                1
            )

            if not (

                sentence.startswith(
                    "$GPRMC"
                )

                or

                sentence.startswith(
                    "$GNRMC"
                )

            ):

                return

            parts = sentence.split(
                ","
            )

            if len(parts) < 7:

                return

            # A = valid
            # V = invalid

            if (
                parts[2]
                !=
                "A"
            ):

                return

            lat = self.nmea_to_decimal(

                parts[3],

                parts[4]
            )

            lon = self.nmea_to_decimal(

                parts[5],

                parts[6]
            )

            if (
                lat is None
                or
                lon is None
            ):

                return

            print(
                f"Vehicle GPS: "
                f"{lat:.6f}, "
                f"{lon:.6f}"
            )

            self.notify_vehicle_location(
                lat,
                lon
            )

        except Exception as error:

            print(
                "GPS processing error:",
                error
            )

    # =====================================================
    # SERIAL MESSAGE
    # =====================================================

    def handle_serial_message(
        self,
        raw_data
    ):

        # =================================================
        # FORWARD VALID HARDWARE STATUS TO WINDOWS
        # =================================================

        if (

            raw_data.startswith(
                "SYNC:"
            )

            or

            raw_data.startswith(
                "DATA:GAS:"
            )

        ):

            threading.Thread(

                target=
                    self.notify_junction_event,

                args=(
                    raw_data,
                ),

                daemon=True

            ).start()

        # =================================================
        # EMERGENCY REQUEST
        # =================================================

        if (
            raw_data
            ==
            "REQ:EMERGENCY"
        ):

            # Only create one request.

            if (
                self.corridor_state
                ==
                "NORMAL"
            ):

                print(
                    "\n>>> EMERGENCY REQUEST "
                    "RECEIVED <<<"
                )

                # IMPORTANT:
                #
                # REQUESTED is NOT the same as ACTIVATING.

                self.corridor_state = (
                    "REQUESTED"
                )

                threading.Thread(

                    target=
                        self.notify_emergency,

                    daemon=True

                ).start()

            else:

                print(
                    "Emergency request ignored; "
                    "local state:",
                    self.corridor_state
                )

            return

        # =================================================
        # PHYSICAL VEHICLE CANCEL
        # =================================================

        if (
            raw_data
            ==
            "REQ:CANCEL"
        ):

            # ---------------------------------------------
            # CANCEL BEFORE APPROVAL
            #
            # Nothing physical was activated.
            # DO NOT RESET JUNCTION.
            # ---------------------------------------------

            if (
                self.corridor_state
                ==
                "REQUESTED"
            ):

                print(
                    "\n>>> PENDING EMERGENCY "
                    "CANCELLED <<<"
                )

                self.corridor_state = (
                    "NORMAL"
                )

                self.display.draw_normal_state(

                    self.current_light,

                    self.gas
                )

                threading.Thread(

                    target=
                        self.reject_backend,

                    daemon=True

                ).start()

                return

            # ---------------------------------------------
            # CANCEL WHILE ACTIVATING OR ACTIVE
            #
            # Hardware reset IS required.
            # ---------------------------------------------

            if self.corridor_state in [

                "ACTIVATING",
                "ACTIVE"

            ]:

                print(
                    "\n>>> ACTIVE EMERGENCY "
                    "CANCELLED <<<"
                )

                self.enter_resetting()

                threading.Thread(

                    target=
                        self.reset_backend,

                    daemon=True

                ).start()

                return

            # Already resetting.
            # Do NOT start another reset.

            if (
                self.corridor_state
                ==
                "RESETTING"
            ):

                print(
                    "Cancel ignored; "
                    "reset already running."
                )

                return

            return

        # =================================================
        # TRAFFIC LIGHT SYNC
        # =================================================

        if raw_data.startswith(
            "SYNC:LIGHT:"
        ):

            try:

                light = int(
                    raw_data.split(
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
                # NORMAL
                # -----------------------------------------

                if (
                    self.corridor_state
                    ==
                    "NORMAL"
                ):

                    self.display.draw_normal_state(

                        self.current_light,

                        self.gas
                    )

                # -----------------------------------------
                # RESET FAILSAFE
                #
                # Any valid normal light sequence after
                # reset means Junction resumed normal
                # signal operation.
                # -----------------------------------------

                elif (
                    self.corridor_state
                    ==
                    "RESETTING"
                ):

                    self.complete_local_reset(

                        (
                            "normal traffic-light "
                            "sync resumed"
                        ),

                        notify_backend=True
                    )

            except Exception as error:

                print(
                    "Light sync error:",
                    error
                )

            return

        # =================================================
        # CORRIDOR PENDING
        # =================================================

        if (
            raw_data
            ==
            "SYNC:CORRIDOR:PENDING"
        ):

            # Ignore stale activation result after reset.

            if (
                self.corridor_state
                ==
                "RESETTING"
            ):

                print(
                    "Ignoring stale "
                    "CORRIDOR:PENDING during reset."
                )

                return

            print(
                "Junction corridor state: "
                "PENDING"
            )

            self.corridor_state = (
                "ACTIVATING"
            )

            threading.Thread(

                target=
                    self.handle_countdown,

                daemon=True

            ).start()

            return

        # =================================================
        # CORRIDOR ACTIVE
        # =================================================

        if (
            raw_data
            ==
            "SYNC:CORRIDOR:ACTIVE"
        ):

            # Race:
            #
            # APPROVE was sent then operator immediately
            # pressed reject.
            #
            # Do not let stale ACTIVE cancel RESETTING.

            if (
                self.corridor_state
                ==
                "RESETTING"
            ):

                print(
                    "Ignoring stale ACTIVE during reset."
                )

                # Reinforce reset once.

                self.write_uart(
                    "CMD:RESET"
                )

                return

            print(
                "Junction corridor state: ACTIVE"
            )

            self.corridor_state = (
                "ACTIVE"
            )

            self.current_light = 1

            self.display.draw_corridor_active()

            # Camera remains optional.

            def camera_task():

                try:

                    self.camera.capture_evidence()

                except Exception as error:

                    print(
                        "Camera skipped:",
                        error
                    )

            threading.Thread(

                target=
                    camera_task,

                daemon=True

            ).start()

            return

        # =================================================
        # RESET PENDING
        # =================================================

        if (
            raw_data
            ==
            "SYNC:RESET:PENDING"
        ):

            print(
                "Junction reset pending."
            )

            self.enter_resetting()

            return

        # =================================================
        # CORRIDOR CLEARED
        # =================================================

        if (
            raw_data
            ==
            "SYNC:CORRIDOR:CLEARED"
        ):

            print(
                "Junction corridor cleared."
            )

            self.current_light = 0

            # Event was already forwarded to Windows above,
            # so don't send a duplicate synthetic event.

            self.complete_local_reset(

                "junction confirmed clear",

                notify_backend=False
            )

            return

        # =================================================
        # GAS
        # =================================================

        if raw_data.startswith(
            "DATA:GAS:"
        ):

            try:

                raw_gas = int(
                    raw_data.split(
                        ":"
                    )[2]
                )

                if raw_gas < 600:

                    self.gas = (
                        "NORMAL"
                    )

                elif raw_gas < 1200:

                    self.gas = (
                        "POOR"
                    )

                else:

                    self.gas = (
                        "DANGER!"
                    )

                if (
                    self.corridor_state
                    ==
                    "NORMAL"
                ):

                    self.display.draw_normal_state(

                        self.current_light,

                        self.gas
                    )

            except Exception as error:

                print(
                    "Gas processing error:",
                    error
                )

            return

        # =================================================
        # GPS
        # =================================================

        if raw_data.startswith(
            "GPS:"
        ):

            threading.Thread(

                target=
                    self.handle_gps,

                args=(
                    raw_data,
                ),

                daemon=True

            ).start()

            return

        # =================================================
        # UNKNOWN UART DATA
        # =================================================

        print(
            f"Junction: {raw_data}"
        )

    # =====================================================
    # RUN
    # =====================================================

    def run(self):

        # Sensor polling

        threading.Thread(

            target=
                self.request_sensor_data,

            daemon=True

        ).start()

        # Backend command polling

        threading.Thread(

            target=
                self.command_loop,

            daemon=True

        ).start()

        # Reset watchdog

        threading.Thread(

            target=
                self.reset_watchdog,

            daemon=True

        ).start()

        print(
            "Traffic Node Control Loop Started."
        )

        print(
            f"Backend: {BACKEND_URL}"
        )

        print(
            f"Serial: {SERIAL_PORT}"
        )

        # =================================================
        # UART READ LOOP
        # =================================================

        while True:

            try:

                if (
                    self.esp32.in_waiting
                    >
                    0
                ):

                    raw_data = (

                        self.esp32

                        .readline()

                        .decode(
                            "utf-8",
                            errors="ignore"
                        )

                        .strip()
                    )

                    if raw_data:

                        self.handle_serial_message(
                            raw_data
                        )

                time.sleep(
                    0.01
                )

            except KeyboardInterrupt:

                print(
                    "\nStopping ResQSync "
                    "Traffic Node..."
                )

                break

            except Exception as error:

                print(
                    "Traffic loop error:",
                    error
                )

                time.sleep(
                    1
                )


# =========================================================
# START
# =========================================================

if __name__ == "__main__":

    node = TrafficNodeManager()

    node.run()
