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


evidence_service = EvidenceService()
