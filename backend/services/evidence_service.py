import os
from datetime import datetime, timezone

from werkzeug.utils import secure_filename

from services.database_service import (
    PROJECT_ROOT,
    database_service,
)

from services.notification_service import (
    notification_service,
)


EVIDENCE_DIR = os.path.join(
    PROJECT_ROOT,
    "data",
    "evidence",
)

os.makedirs(
    EVIDENCE_DIR,
    exist_ok=True,
)


ALLOWED_EXTENSIONS = {
    "jpg",
    "jpeg",
    "png",
    "webp",
    "mp4",
    "mov",
    "avi",
}


class EvidenceService:

    def _now_iso(self):

        return datetime.now(
            timezone.utc
        ).isoformat()

    def _extension_allowed(
        self,
        filename,
    ):

        if "." not in filename:
            return False

        extension = (
            filename
            .rsplit(".", 1)[1]
            .lower()
        )

        return (
            extension
            in ALLOWED_EXTENSIONS
        )

    # =====================================================
    # SAVE PHOTO / VIDEO
    # =====================================================

    def save_upload(
        self,
        uploaded_file,
        request_id=None,
        vehicle_id=None,
        junction_id=None,
        evidence_type="PHOTO",
        description=None,
        source="APP",
    ):

        if (
            uploaded_file is None
            or
            not uploaded_file.filename
        ):

            return {
                "success": False,
                "message":
                    "No file uploaded",
            }, 400

        original_name = secure_filename(
            uploaded_file.filename
        )

        if not self._extension_allowed(
            original_name
        ):

            return {
                "success": False,
                "message":
                    "Unsupported file type",
            }, 400

        created_at = self._now_iso()

        row_id = database_service.insert(
            """
            INSERT INTO evidence (
                request_id,
                vehicle_id,
                junction_id,
                evidence_type,
                file_path,
                description,
                source,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                request_id,
                vehicle_id,
                junction_id,
                evidence_type,
                None,
                description,
                source,
                created_at,
            ),
        )

        evidence_id = (
            f"EVD-{row_id:05d}"
        )

        filename = (
            f"{evidence_id}_"
            f"{original_name}"
        )

        absolute_path = os.path.join(
            EVIDENCE_DIR,
            filename,
        )

        try:

            uploaded_file.save(
                absolute_path
            )

        except Exception as error:

            database_service.execute(
                """
                DELETE FROM evidence
                WHERE id = ?
                """,
                (row_id,),
            )

            return {
                "success": False,
                "message":
                    f"File save failed: {error}",
            }, 500

        relative_path = os.path.relpath(
            absolute_path,
            PROJECT_ROOT,
        ).replace(
            os.sep,
            "/"
        )

        database_service.execute(
            """
            UPDATE evidence
            SET
                evidence_id = ?,
                file_path = ?
            WHERE id = ?
            """,
            (
                evidence_id,
                relative_path,
                row_id,
            ),
        )

        # =================================================
        # EVENT LOG
        # =================================================

        event_row = database_service.insert(
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
                "EVIDENCE_UPLOADED",
                "INFO",
                (
                    f"Evidence {evidence_id} "
                    f"uploaded"
                ),
                vehicle_id,
                junction_id,
                request_id,
                created_at,
            ),
        )

        database_service.execute(
            """
            UPDATE events
            SET event_id = ?
            WHERE id = ?
            """,
            (
                f"EVT-{event_row:05d}",
                event_row,
            ),
        )

        # =================================================
        # FIREBASE PUSH NOTIFICATION
        # =================================================
        #
        # IMPORTANT:
        # Evidence storage does NOT fail if Firebase is
        # unavailable. Notification failure is reported
        # separately.
        # =================================================

        try:

            notification_result = (
                notification_service
                .send_to_registered_devices(

                    title=(
                        "PrioWay: New Evidence"
                    ),

                    body=(
                        f"Evidence {evidence_id} "
                        "was uploaded."
                    ),

                    data={
                        "type":
                            "EVIDENCE_UPLOADED",

                        "evidence_id":
                            evidence_id,

                        "request_id":
                            request_id,

                        "vehicle_id":
                            vehicle_id,

                        "junction_id":
                            junction_id,

                        "source":
                            source,
                    },
                )
            )

        except Exception as error:

            notification_result = {
                "success": False,
                "status":
                    "FAILED",
                "registered_devices": 0,
                "sent": 0,
                "failed": 0,
                "disabled_invalid_tokens": 0,
                "error":
                    str(error),
            }

        return {
            "success": True,

            "evidence": {

                "evidence_id":
                    evidence_id,

                "request_id":
                    request_id,

                "vehicle_id":
                    vehicle_id,

                "junction_id":
                    junction_id,

                "evidence_type":
                    evidence_type,

                "file_path":
                    relative_path,

                "description":
                    description,

                "source":
                    source,

                "created_at":
                    created_at,
            },

            "notification":
                notification_result,

        }, 201

    # =====================================================
    # LIST EVIDENCE
    # =====================================================

    def list_evidence(
        self,
        limit=100,
    ):

        rows = database_service.fetch_all(
            """
            SELECT *
            FROM evidence
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )

        return rows

    # =====================================================
    # REGISTER MOBILE DEVICE TOKEN
    # =====================================================

    def register_app_device(
        self,
        user_id,
        device_token,
        platform="android",
    ):

        device_token = str(
            device_token or ""
        ).strip()

        if not device_token:

            return {
                "success": False,
                "message":
                    "device_token required",
            }, 400

        now = self._now_iso()

        existing = database_service.fetch_one(
            """
            SELECT id
            FROM app_devices
            WHERE device_token = ?
            """,
            (device_token,),
        )

        if existing:

            database_service.execute(
                """
                UPDATE app_devices
                SET
                    user_id = ?,
                    platform = ?,
                    enabled = 1,
                    updated_at = ?
                WHERE device_token = ?
                """,
                (
                    user_id,
                    platform,
                    now,
                    device_token,
                ),
            )

        else:

            database_service.insert(
                """
                INSERT INTO app_devices (
                    user_id,
                    device_token,
                    platform,
                    enabled,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, 1, ?, ?)
                """,
                (
                    user_id,
                    device_token,
                    platform,
                    now,
                    now,
                ),
            )

        return {
            "success": True,
            "message":
                "App device registered",
        }, 200


    # =====================================================
    # UPDATE MOBILE DEVICE LOCATION
    # =====================================================

    def update_app_device_location(
        self,
        user_id,
        device_token,
        lat,
        lon,
        accuracy_m=None,
    ):

        user_id = str(
            user_id or ""
        ).strip()

        device_token = str(
            device_token or ""
        ).strip()

        if not user_id:

            return {
                "success": False,
                "message":
                    "user_id required",
            }, 400

        if not device_token:

            return {
                "success": False,
                "message":
                    "device_token required",
            }, 400

        try:

            lat = float(lat)
            lon = float(lon)

            if accuracy_m is not None:
                accuracy_m = float(
                    accuracy_m
                )

        except (
            TypeError,
            ValueError,
        ):

            return {
                "success": False,
                "message":
                    "Valid lat/lon required",
            }, 400

        if not (
            -90.0 <= lat <= 90.0
            and
            -180.0 <= lon <= 180.0
        ):

            return {
                "success": False,
                "message":
                    "Location outside valid range",
            }, 400

        now = self._now_iso()

        updated = database_service.execute(
            """
            UPDATE app_devices
            SET
                user_id = ?,
                enabled = 1,
                lat = ?,
                lon = ?,
                location_accuracy_m = ?,
                location_updated_at = ?,
                updated_at = ?
            WHERE device_token = ?
            """,
            (
                user_id,
                lat,
                lon,
                accuracy_m,
                now,
                now,
                device_token,
            ),
        )

        if not updated:

            database_service.insert(
                """
                INSERT INTO app_devices (
                    user_id,
                    device_token,
                    platform,
                    enabled,
                    lat,
                    lon,
                    location_accuracy_m,
                    location_updated_at,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    device_token,
                    "android",
                    lat,
                    lon,
                    accuracy_m,
                    now,
                    now,
                    now,
                ),
            )

        return {
            "success": True,
            "message":
                "Device location updated",
            "location": {
                "lat": lat,
                "lon": lon,
                "accuracy_m":
                    accuracy_m,
                "updated_at":
                    now,
            },
        }, 200

    # =====================================================
    # ADMIN EVIDENCE REMOVAL
    # =====================================================

    def _delete_rows(
        self,
        rows,
    ):

        deleted_ids = []

        evidence_root = os.path.abspath(
            EVIDENCE_DIR
        )

        for row in rows:

            relative_path = (
                row.get("file_path")
            )

            if relative_path:

                absolute_path = os.path.abspath(
                    os.path.join(
                        PROJECT_ROOT,
                        relative_path,
                    )
                )

                try:

                    inside_root = (
                        os.path.commonpath([
                            evidence_root,
                            absolute_path,
                        ])
                        == evidence_root
                    )

                except ValueError:

                    inside_root = False

                if not inside_root:

                    return {
                        "success": False,
                        "message":
                            "Invalid evidence path",
                    }, 500

                if os.path.isfile(
                    absolute_path
                ):

                    try:

                        os.remove(
                            absolute_path
                        )

                    except Exception as error:

                        return {
                            "success": False,
                            "message":
                                (
                                    "Evidence file could "
                                    f"not be removed: {error}"
                                ),
                        }, 500

            database_service.execute(
                """
                DELETE FROM evidence
                WHERE id = ?
                """,
                (
                    row["id"],
                ),
            )

            deleted_ids.append(
                row.get(
                    "evidence_id"
                )
            )

            event_row = (
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
                        "EVIDENCE_REMOVED",
                        "INFO",
                        (
                            "Evidence "
                            f"{row.get('evidence_id')} "
                            "removed by admin"
                        ),
                        row.get(
                            "vehicle_id"
                        ),
                        row.get(
                            "junction_id"
                        ),
                        row.get(
                            "request_id"
                        ),
                        self._now_iso(),
                    ),
                )
            )

            database_service.execute(
                """
                UPDATE events
                SET event_id = ?
                WHERE id = ?
                """,
                (
                    f"EVT-{event_row:05d}",
                    event_row,
                ),
            )

        return {
            "success": True,
            "deleted_count":
                len(deleted_ids),
            "deleted_evidence_ids":
                deleted_ids,
        }, 200

    def delete_by_request_id(
        self,
        request_id,
    ):

        request_id = str(
            request_id or ""
        ).strip()

        if not request_id:

            return {
                "success": False,
                "message":
                    "request_id required",
            }, 400

        rows = database_service.fetch_all(
            """
            SELECT *
            FROM evidence
            WHERE request_id = ?
            ORDER BY id DESC
            """,
            (
                request_id,
            ),
        )

        # Zero matches is intentionally successful.
        # This keeps moderation idempotent and also
        # supports older Firestore reports that were
        # created before report/evidence linking existed.
        return self._delete_rows(
            rows
        )

    def delete_by_evidence_id(
        self,
        evidence_id,
    ):

        evidence_id = str(
            evidence_id or ""
        ).strip()

        if not evidence_id:

            return {
                "success": False,
                "message":
                    "evidence_id required",
            }, 400

        rows = database_service.fetch_all(
            """
            SELECT *
            FROM evidence
            WHERE evidence_id = ?
            """,
            (
                evidence_id,
            ),
        )

        return self._delete_rows(
            rows
        )


evidence_service = EvidenceService()
