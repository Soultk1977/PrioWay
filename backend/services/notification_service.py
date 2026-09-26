import json
import os
import threading

from services.database_service import (
    PROJECT_ROOT,
    database_service,
)


try:
    import firebase_admin

    from firebase_admin import (
        credentials,
        messaging,
    )

    FIREBASE_ADMIN_AVAILABLE = True
    FIREBASE_IMPORT_ERROR = None

except Exception as error:

    firebase_admin = None
    credentials = None
    messaging = None

    FIREBASE_ADMIN_AVAILABLE = False
    FIREBASE_IMPORT_ERROR = str(error)


DEFAULT_SERVICE_ACCOUNT_PATH = os.path.join(
    PROJECT_ROOT,
    "data",
    "firebase-service-account.json",
)


class NotificationService:

    def __init__(self):

        self._lock = threading.RLock()

        self._initialized = False

        self._credential_source = None

        self._last_error = None

    # =====================================================
    # DEVICE COUNT
    # =====================================================

    def registered_device_count(self):

        row = database_service.fetch_one(
            """
            SELECT COUNT(*) AS total
            FROM app_devices
            WHERE enabled = 1
            """
        )

        if not row:
            return 0

        return int(
            row.get(
                "total",
                0,
            )
        )

    # =====================================================
    # FIREBASE CONFIGURATION
    # =====================================================

    def _get_environment_json(self):

        raw_json = str(
            os.getenv(
                "FIREBASE_SERVICE_ACCOUNT_JSON",
                "",
            )
            or ""
        ).strip()

        if not raw_json:
            return None

        try:

            parsed = json.loads(
                raw_json
            )

            if not isinstance(
                parsed,
                dict,
            ):

                raise ValueError(
                    "Firebase credentials "
                    "must be a JSON object"
                )

            return parsed

        except Exception as error:

            self._last_error = (
                "Invalid "
                "FIREBASE_SERVICE_ACCOUNT_JSON: "
                f"{error}"
            )

            return None

    # =====================================================
    # INITIALIZE
    # =====================================================

    def initialize(self):

        with self._lock:

            if self._initialized:
                return True

            if not FIREBASE_ADMIN_AVAILABLE:

                self._last_error = (
                    "firebase-admin "
                    "is not installed"
                )

                return False

            try:

                # Reuse Firebase if another module
                # already initialized it.

                try:

                    firebase_admin.get_app()

                    self._initialized = True

                    self._credential_source = (
                        "EXISTING_FIREBASE_APP"
                    )

                    self._last_error = None

                    return True

                except ValueError:
                    pass

                # -----------------------------------------
                # 1. CLOUD / RAILWAY ENVIRONMENT SECRET
                # -----------------------------------------

                env_credentials = (
                    self._get_environment_json()
                )

                if env_credentials:

                    credential = (
                        credentials.Certificate(
                            env_credentials
                        )
                    )

                    firebase_admin.initialize_app(
                        credential
                    )

                    self._initialized = True

                    self._credential_source = (
                        "ENVIRONMENT_JSON"
                    )

                    self._last_error = None

                    return True

                # -----------------------------------------
                # 2. LOCAL DEVELOPMENT JSON FILE
                # -----------------------------------------

                if os.path.exists(
                    DEFAULT_SERVICE_ACCOUNT_PATH
                ):

                    credential = (
                        credentials.Certificate(
                            DEFAULT_SERVICE_ACCOUNT_PATH
                        )
                    )

                    firebase_admin.initialize_app(
                        credential
                    )

                    self._initialized = True

                    self._credential_source = (
                        "PROJECT_DATA_FILE"
                    )

                    self._last_error = None

                    return True

                # -----------------------------------------
                # 3. GOOGLE APPLICATION DEFAULT
                # -----------------------------------------

                google_credentials = str(
                    os.getenv(
                        "GOOGLE_APPLICATION_CREDENTIALS",
                        "",
                    )
                    or ""
                ).strip()

                if google_credentials:

                    firebase_admin.initialize_app()

                    self._initialized = True

                    self._credential_source = (
                        "GOOGLE_APPLICATION_CREDENTIALS"
                    )

                    self._last_error = None

                    return True

                self._last_error = (
                    "Firebase credentials "
                    "are not configured"
                )

                return False

            except Exception as error:

                self._last_error = str(error)

                return False

    # =====================================================
    # STATUS
    # =====================================================

    def status(self):

        if not FIREBASE_ADMIN_AVAILABLE:

            status = "DEPENDENCY_MISSING"

        elif self._initialized:

            status = "READY"

        elif (
            os.getenv(
                "FIREBASE_SERVICE_ACCOUNT_JSON"
            )
            or
            os.path.exists(
                DEFAULT_SERVICE_ACCOUNT_PATH
            )
            or
            os.getenv(
                "GOOGLE_APPLICATION_CREDENTIALS"
            )
        ):

            status = (
                "CONFIGURED_NOT_INITIALIZED"
            )

        else:

            status = "NOT_CONFIGURED"

        return {
            "success":
                status == "READY",

            "status":
                status,

            "firebase_admin_available":
                FIREBASE_ADMIN_AVAILABLE,

            "initialized":
                self._initialized,

            "credential_source":
                self._credential_source,

            "registered_devices":
                self.registered_device_count(),

            "error":
                (
                    self._last_error
                    or
                    FIREBASE_IMPORT_ERROR
                ),
        }

    # =====================================================
    # ACTIVE DEVICES
    # =====================================================

    def _active_devices(self):

        return database_service.fetch_all(
            """
            SELECT
                id,
                user_id,
                device_token,
                platform
            FROM app_devices
            WHERE
                enabled = 1
                AND
                device_token IS NOT NULL
                AND
                TRIM(device_token) != ''
            ORDER BY id ASC
            """
        )

    def _disable_token(
        self,
        token,
    ):

        database_service.execute(
            """
            UPDATE app_devices
            SET enabled = 0
            WHERE device_token = ?
            """,
            (token,),
        )

    # =====================================================
    # SEND PUSH
    # =====================================================

    def send_to_registered_devices(
        self,
        title,
        body,
        data=None,
    ):

        devices = self._active_devices()

        tokens = []
        seen = set()

        for device in devices:

            token = str(
                device.get(
                    "device_token",
                    "",
                )
                or ""
            ).strip()

            if (
                token
                and
                token not in seen
            ):

                seen.add(token)

                tokens.append(token)

        if not tokens:

            return {
                "success": False,
                "status":
                    "NO_REGISTERED_DEVICES",
                "registered_devices": 0,
                "sent": 0,
                "failed": 0,
                "disabled_invalid_tokens": 0,
            }

        if not self.initialize():

            current = self.status()

            return {
                "success": False,
                "status":
                    current["status"],
                "registered_devices":
                    len(tokens),
                "sent": 0,
                "failed":
                    len(tokens),
                "disabled_invalid_tokens": 0,
                "error":
                    current.get(
                        "error"
                    ),
            }

        safe_data = {}

        for key, value in (
            data or {}
        ).items():

            if value is None:
                continue

            safe_data[
                str(key)
            ] = str(value)

        sent = 0
        failed = 0
        disabled = 0

        errors = []

        for start in range(
            0,
            len(tokens),
            500,
        ):

            chunk = tokens[
                start:
                start + 500
            ]

            try:

                message = (
                    messaging.MulticastMessage(

                        tokens=chunk,

                        notification=
                            messaging.Notification(
                                title=str(title),
                                body=str(body),
                            ),

                        data=safe_data,

                        android=
                            messaging.AndroidConfig(
                                priority="high",

                                notification=
                                    messaging
                                    .AndroidNotification(
                                        sound="default",
                                    ),
                            ),
                    )
                )

                response = (
                    messaging
                    .send_each_for_multicast(
                        message
                    )
                )

                for index, item in enumerate(
                    response.responses
                ):

                    if item.success:

                        sent += 1

                        continue

                    failed += 1

                    exception = (
                        item.exception
                    )

                    error_name = (
                        exception
                        .__class__
                        .__name__
                        if exception
                        else
                        "UnknownError"
                    )

                    errors.append(
                        error_name
                    )

                    if error_name in {
                        "UnregisteredError",
                        "SenderIdMismatchError",
                    }:

                        self._disable_token(
                            chunk[index]
                        )

                        disabled += 1

            except Exception as error:

                failed += len(chunk)

                errors.append(
                    error
                    .__class__
                    .__name__
                )

        if (
            sent > 0
            and
            failed == 0
        ):

            status = "SENT"

        elif sent > 0:

            status = "PARTIAL"

        else:

            status = "FAILED"

        return {
            "success":
                sent > 0,

            "status":
                status,

            "registered_devices":
                len(tokens),

            "sent":
                sent,

            "failed":
                failed,

            "disabled_invalid_tokens":
                disabled,

            "errors":
                sorted(
                    set(errors)
                ),
        }


notification_service = NotificationService()
