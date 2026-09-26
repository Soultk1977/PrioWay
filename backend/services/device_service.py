import hmac
import os
import time

from services.database_service import database_service
from services.state_manager import state_manager


class DeviceService:
    """
    Internet-facing physical-device layer.

    LOCAL DEFAULT KEYS ARE ONLY FOR DEVELOPMENT.
    Before public deployment these will be replaced
    by secrets stored in server environment variables.
    """

    def _expected_key(self, device_id):

        keys = {
            "VEH-001": os.getenv(
                "PRIOWAY_VEH001_KEY",
                "LOCAL-VEH-001-CHANGE-ME",
            ),
            "JNC-001": os.getenv(
                "PRIOWAY_JNC001_KEY",
                "LOCAL-JNC-001-CHANGE-ME",
            ),
        }

        return keys.get(device_id)

    def authenticate(self, device_id, provided_key):

        device_id = str(device_id or "").strip()
        provided_key = str(provided_key or "").strip()

        expected = self._expected_key(device_id)

        if expected is None:
            return False, "UNKNOWN_DEVICE"

        if not provided_key:
            return False, "MISSING_DEVICE_KEY"

        if not hmac.compare_digest(
            provided_key,
            expected,
        ):
            return False, "INVALID_DEVICE_KEY"

        return True, "AUTHENTICATED"

    # =====================================================
    # HEARTBEAT
    # =====================================================

    def heartbeat(self, device_id):

        now = time.time()

        vehicle = database_service.fetch_one(
            """
            SELECT vehicle_id
            FROM vehicles
            WHERE vehicle_id = ?
            """,
            (device_id,),
        )

        if vehicle:

            database_service.execute(
                """
                UPDATE vehicles
                SET
                    online = 1,
                    last_seen = ?
                WHERE vehicle_id = ?
                """,
                (
                    now,
                    device_id,
                ),
            )

            return {
                "success": True,
                "device_id": device_id,
                "device_type": "VEHICLE",
                "server_time": now,
            }

        junction = database_service.fetch_one(
            """
            SELECT junction_id
            FROM junctions
            WHERE junction_id = ?
            """,
            (device_id,),
        )

        if junction:

            database_service.execute(
                """
                UPDATE junctions
                SET last_seen = ?
                WHERE junction_id = ?
                """,
                (
                    now,
                    device_id,
                ),
            )

            return {
                "success": True,
                "device_id": device_id,
                "device_type": "JUNCTION",
                "server_time": now,
            }

        return {
            "success": False,
            "message": "Unknown device",
        }

    # =====================================================
    # VEHICLE GPS
    # =====================================================

    def update_vehicle_location(
        self,
        vehicle_id,
        lat,
        lon,
    ):

        try:
            lat = float(lat)
            lon = float(lon)

        except (TypeError, ValueError):
            return {
                "success": False,
                "message": "Invalid latitude/longitude",
            }

        if not -90 <= lat <= 90:
            return {
                "success": False,
                "message": "Latitude out of range",
            }

        if not -180 <= lon <= 180:
            return {
                "success": False,
                "message": "Longitude out of range",
            }

        exists = database_service.fetch_one(
            """
            SELECT vehicle_id
            FROM vehicles
            WHERE vehicle_id = ?
            """,
            (vehicle_id,),
        )

        if not exists:
            return {
                "success": False,
                "message": "Vehicle not registered",
            }

        now = time.time()

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
                now,
                lat,
                lon,
                vehicle_id,
            ),
        )

        # Keep old physical dashboard/state machine alive.
        if vehicle_id == "VEH-001":
            try:
                state_manager.update_vehicle_location(
                    lat,
                    lon,
                )
            except Exception:
                pass

        return {
            "success": True,
            "vehicle_id": vehicle_id,
            "location": {
                "lat": lat,
                "lon": lon,
            },
            "server_time": now,
        }

    # =====================================================
    # JUNCTION TELEMETRY
    # =====================================================

    def update_junction_telemetry(
        self,
        junction_id,
        payload,
    ):

        row = database_service.fetch_one(
            """
            SELECT *
            FROM junctions
            WHERE junction_id = ?
            """,
            (junction_id,),
        )

        if row is None:
            return {
                "success": False,
                "message": "Junction not registered",
            }

        current_light = payload.get(
            "current_light",
            row["current_light"],
        )

        try:
            current_light = int(current_light)
        except (TypeError, ValueError):
            current_light = row["current_light"]

        if current_light not in (0, 1, 2):
            current_light = row["current_light"]

        gas_value = payload.get(
            "gas_value",
            row["gas_value"],
        )

        if gas_value is not None:
            try:
                gas_value = float(gas_value)
            except (TypeError, ValueError):
                gas_value = row["gas_value"]

        gas_status = payload.get(
            "gas_status"
        )

        if not gas_status:

            if gas_value is None:
                gas_status = row["gas_status"]

            elif gas_value < 600:
                gas_status = "NORMAL"

            elif gas_value < 1200:
                gas_status = "POOR"

            else:
                gas_status = "DANGER"

        temperature = payload.get(
            "temperature",
            row["temperature_value"],
        )

        if temperature is not None:
            try:
                temperature = float(
                    temperature
                )
            except (TypeError, ValueError):
                temperature = row[
                    "temperature_value"
                ]

        corridor_state = str(
            payload.get(
                "corridor_state",
                row["corridor_state"],
            )
        )

        camera_status = str(
            payload.get(
                "camera_status",
                row["camera_status"],
            )
        )

        now = time.time()

        database_service.execute(
            """
            UPDATE junctions
            SET
                last_seen = ?,
                current_light = ?,
                corridor_state = ?,
                gas_value = ?,
                gas_status = ?,
                gas_source = 'PHYSICAL',
                temperature_value = ?,
                temperature_source = ?,
                camera_status = ?,
                camera_source = 'PHYSICAL'
            WHERE junction_id = ?
            """,
            (
                now,
                current_light,
                corridor_state,
                gas_value,
                gas_status,
                temperature,
                (
                    "PHYSICAL"
                    if temperature is not None
                    else "UNAVAILABLE"
                ),
                camera_status,
                junction_id,
            ),
        )

        # Feed existing legacy state machine too.
        if junction_id == "JNC-001":

            try:
                state_manager.junction_event(
                    f"SYNC:LIGHT:{current_light}"
                )
            except Exception:
                pass

            if gas_value is not None:

                try:
                    state_manager.junction_event(
                        f"DATA:GAS:{int(gas_value)}"
                    )
                except Exception:
                    pass

        return {
            "success": True,
            "junction_id": junction_id,
            "server_time": now,
        }


device_service = DeviceService()
