import hashlib
import math
import os
from datetime import datetime, timezone

import firebase_admin
from firebase_admin import messaging

# Importing the existing notification service guarantees that the
# project's already-working Firebase Admin initialization path runs.
from services.notification_service import notification_service  # noqa: F401

from services.database_service import database_service


class NearbyNotificationService:

    ALERT_KEY_PREFIX = "corridor_device_sent:"
    ACTIVE_FLAG_KEY = "physical_corridor_active"

    def _now_iso(self):
        return datetime.now(timezone.utc).isoformat()

    def _parse_iso(self, value):
        try:
            return datetime.fromisoformat(
                str(value).replace("Z", "+00:00")
            )
        except Exception:
            return None

    def _distance_m(
        self,
        lat1,
        lon1,
        lat2,
        lon2,
    ):
        radius_m = 6371000.0

        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)

        delta_phi = math.radians(lat2 - lat1)
        delta_lambda = math.radians(lon2 - lon1)

        a = (
            math.sin(delta_phi / 2.0) ** 2
            +
            math.cos(phi1)
            *
            math.cos(phi2)
            *
            math.sin(delta_lambda / 2.0) ** 2
        )

        c = 2.0 * math.atan2(
            math.sqrt(a),
            math.sqrt(1.0 - a),
        )

        return radius_m * c

    # =====================================================
    # NOTIFICATION STATE
    # =====================================================

    def _state_get(self, key):
        row = database_service.fetch_one(
            """
            SELECT value
            FROM notification_state
            WHERE key = ?
            """,
            (key,),
        )

        if not row:
            return None

        return str(row.get("value", ""))

    def _state_set(self, key, value):
        now = self._now_iso()

        existing = database_service.fetch_one(
            """
            SELECT key
            FROM notification_state
            WHERE key = ?
            """,
            (key,),
        )

        if existing:
            database_service.execute(
                """
                UPDATE notification_state
                SET value = ?, updated_at = ?
                WHERE key = ?
                """,
                (
                    str(value),
                    now,
                    key,
                ),
            )
        else:
            database_service.insert(
                """
                INSERT INTO notification_state (
                    key,
                    value,
                    updated_at
                )
                VALUES (?, ?, ?)
                """,
                (
                    key,
                    str(value),
                    now,
                ),
            )

    def _clear_corridor_device_flags(self):
        database_service.execute(
            """
            DELETE FROM notification_state
            WHERE key LIKE ?
            """,
            (
                f"{self.ALERT_KEY_PREFIX}%",
            ),
        )

        database_service.execute(
            """
            DELETE FROM notification_state
            WHERE key = ?
            """,
            (
                self.ACTIVE_FLAG_KEY,
            ),
        )

    def _device_alert_key(self, token):
        digest = hashlib.sha256(
            str(token).encode("utf-8")
        ).hexdigest()

        return (
            self.ALERT_KEY_PREFIX
            +
            digest
        )

    # =====================================================
    # LIVE EMERGENCY VEHICLE GPS
    # =====================================================

    def _live_vehicle_coordinates(self):
        row = database_service.fetch_one(
            """
            SELECT
                vehicle_id,
                lat,
                lon,
                location_valid,
                last_seen
            FROM vehicles
            WHERE vehicle_id = ?
            """,
            (
                "VEH-001",
            ),
        )

        if not row:
            return {
                "available": False,
                "source": "LIVE_VEHICLE_GPS_UNAVAILABLE",
                "vehicle_id": "VEH-001",
                "lat": None,
                "lon": None,
                "age_seconds": None,
            }

        if (
            not bool(row.get("location_valid"))
            or
            row.get("lat") is None
            or
            row.get("lon") is None
        ):
            return {
                "available": False,
                "source": "LIVE_VEHICLE_GPS_NO_FIX",
                "vehicle_id": "VEH-001",
                "lat": None,
                "lon": None,
                "age_seconds": None,
            }

        max_age_seconds = float(
            os.getenv(
                "PRIOWAY_VEHICLE_GPS_MAX_AGE_SECONDS",
                "120",
            )
        )

        last_seen = row.get("last_seen")
        age_seconds = None

        if last_seen is not None:
            try:
                age_seconds = max(
                    0.0,
                    datetime.now(timezone.utc).timestamp()
                    - float(last_seen),
                )
            except Exception:
                age_seconds = None

        if (
            age_seconds is not None
            and
            age_seconds > max_age_seconds
        ):
            return {
                "available": False,
                "source": "LIVE_VEHICLE_GPS_STALE",
                "vehicle_id": "VEH-001",
                "lat": float(row["lat"]),
                "lon": float(row["lon"]),
                "age_seconds": round(age_seconds, 1),
            }

        return {
            "available": True,
            "source": "LIVE_VEHICLE_GPS",
            "vehicle_id": "VEH-001",
            "lat": float(row["lat"]),
            "lon": float(row["lon"]),
            "age_seconds": (
                round(age_seconds, 1)
                if age_seconds is not None
                else None
            ),
        }

    # =====================================================
    # PHONE SELECTION
    # =====================================================

    def _eligible_devices(self):
        center = self._live_vehicle_coordinates()

        radius_m = float(
            os.getenv(
                "PRIOWAY_CORRIDOR_RADIUS_M",
                "1000",
            )
        )

        max_age_seconds = float(
            os.getenv(
                "PRIOWAY_LOCATION_MAX_AGE_SECONDS",
                "180",
            )
        )

        result = {
            "devices": [],
            "center": center,
            "radius_m": radius_m,
            "max_age_seconds": max_age_seconds,
        }

        if not center["available"]:
            return result

        now = datetime.now(timezone.utc)

        rows = database_service.fetch_all(
            """
            SELECT
                user_id,
                device_token,
                platform,
                lat,
                lon,
                location_accuracy_m,
                location_updated_at
            FROM app_devices
            WHERE
                enabled = 1
                AND lat IS NOT NULL
                AND lon IS NOT NULL
                AND location_updated_at IS NOT NULL
            """
        )

        eligible = []

        for row in rows:
            updated_at = self._parse_iso(
                row.get("location_updated_at")
            )

            if updated_at is None:
                continue

            if updated_at.tzinfo is None:
                updated_at = updated_at.replace(
                    tzinfo=timezone.utc
                )

            age_seconds = (
                now
                -
                updated_at.astimezone(timezone.utc)
            ).total_seconds()

            if (
                age_seconds < 0
                or
                age_seconds > max_age_seconds
            ):
                continue

            distance_m = self._distance_m(
                center["lat"],
                center["lon"],
                float(row["lat"]),
                float(row["lon"]),
            )

            if distance_m > radius_m:
                continue

            item = dict(row)
            item["distance_m"] = round(
                distance_m,
                1,
            )
            item["age_seconds"] = round(
                age_seconds,
                1,
            )

            eligible.append(item)

        result["devices"] = eligible
        return result

    # =====================================================
    # STATUS
    # =====================================================

    def status(self):
        selection = self._eligible_devices()

        registered = (
            database_service.fetch_one(
                """
                SELECT COUNT(*) AS total
                FROM app_devices
                WHERE enabled = 1
                """
            )
            or {}
        ).get("total", 0)

        located = (
            database_service.fetch_one(
                """
                SELECT COUNT(*) AS total
                FROM app_devices
                WHERE
                    enabled = 1
                    AND lat IS NOT NULL
                    AND lon IS NOT NULL
                    AND location_updated_at IS NOT NULL
                """
            )
            or {}
        ).get("total", 0)

        return {
            "success": True,
            "target":
                "VEH-001",
            "coordinate_source":
                selection["center"]["source"],
            "vehicle_gps_available":
                selection["center"]["available"],
            "vehicle_lat":
                selection["center"]["lat"],
            "vehicle_lon":
                selection["center"]["lon"],
            "vehicle_gps_age_seconds":
                selection["center"]["age_seconds"],
            "radius_m":
                selection["radius_m"],
            "max_phone_location_age_seconds":
                selection["max_age_seconds"],
            "registered_devices":
                registered,
            "located_devices":
                located,
            "nearby_devices":
                len(selection["devices"]),
            "corridor_active":
                self._state_get(
                    self.ACTIVE_FLAG_KEY
                )
                == "1",
        }

    # =====================================================
    # SEND TO NEWLY NEARBY DEVICES
    # =====================================================

    def send_corridor_alerts(self):
        selection = self._eligible_devices()

        if not selection["center"]["available"]:
            return {
                "success": True,
                "status":
                    selection["center"]["source"],
                "eligible_devices": 0,
                "new_devices": 0,
                "sent": 0,
                "failed": 0,
            }

        devices = selection["devices"]

        if not devices:
            return {
                "success": True,
                "status": "NO_NEARBY_DEVICES",
                "eligible_devices": 0,
                "new_devices": 0,
                "sent": 0,
                "failed": 0,
            }

        try:
            firebase_admin.get_app()

        except ValueError as error:
            return {
                "success": False,
                "status": "FIREBASE_NOT_READY",
                "eligible_devices": len(devices),
                "new_devices": 0,
                "sent": 0,
                "failed": len(devices),
                "error": str(error),
            }

        sent = 0
        failed = 0
        new_devices = 0
        disabled_invalid_tokens = 0

        for device in devices:
            token = device.get("device_token")

            if not token:
                continue

            alert_key = self._device_alert_key(
                token
            )

            if self._state_get(alert_key) == "1":
                continue

            new_devices += 1

            message = messaging.Message(
                notification=messaging.Notification(
                    title=(
                        "PrioWay Emergency Corridor"
                    ),
                    body=(
                        "An emergency vehicle is nearby. "
                        "Please keep the priority route clear."
                    ),
                ),
                data={
                    "type":
                        "EMERGENCY_CORRIDOR_NEARBY",
                    "vehicle_id":
                        "VEH-001",
                    "distance_m":
                        str(
                            device.get(
                                "distance_m",
                                "",
                            )
                        ),
                },
                token=token,
            )

            try:
                messaging.send(message)
                sent += 1

                # One notification per phone per active
                # corridor cycle.
                self._state_set(
                    alert_key,
                    "1",
                )

            except Exception as error:
                failed += 1

                error_name = (
                    error.__class__.__name__
                )

                if error_name in {
                    "UnregisteredError",
                    "InvalidArgumentError",
                    "SenderIdMismatchError",
                }:
                    database_service.execute(
                        """
                        UPDATE app_devices
                        SET enabled = 0
                        WHERE device_token = ?
                        """,
                        (token,),
                    )

                    disabled_invalid_tokens += 1

        return {
            "success": True,
            "status": (
                "SENT"
                if sent > 0
                else (
                    "ALREADY_NOTIFIED"
                    if new_devices == 0
                    else "FAILED"
                )
            ),
            "eligible_devices": len(devices),
            "new_devices": new_devices,
            "sent": sent,
            "failed": failed,
            "disabled_invalid_tokens":
                disabled_invalid_tokens,
            "coordinate_source":
                selection["center"]["source"],
            "radius_m":
                selection["radius_m"],
        }

    # =====================================================
    # PHYSICAL CORRIDOR STATE
    # =====================================================

    def handle_snapshot(self, snapshot):
        state = str(
            snapshot.get(
                "state",
                "",
            )
        ).upper()

        if state != "ACTIVE_CORRIDOR":
            if (
                self._state_get(
                    self.ACTIVE_FLAG_KEY
                )
                == "1"
            ):
                self._clear_corridor_device_flags()

            return {
                "status": "IDLE",
                "state": state,
            }

        self._state_set(
            self.ACTIVE_FLAG_KEY,
            "1",
        )

        # This is intentionally checked repeatedly while the
        # corridor is active. A phone that becomes nearby later
        # can receive one alert, but each phone is notified only
        # once per corridor cycle.
        return self.send_corridor_alerts()


nearby_notification_service = NearbyNotificationService()
