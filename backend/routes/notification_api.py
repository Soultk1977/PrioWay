import os

from flask import (
    Blueprint,
    jsonify,
    request,
)

from services.notification_service import (
    notification_service,
)


notification_api = Blueprint(
    "notification_api",
    __name__,
    url_prefix="/api/v1/notifications",
)


def test_endpoint_allowed():

    return (
        os.getenv(
            "PRIOWAY_DEMO_MODE",
            "1",
        )
        == "1"
        or
        os.getenv(
            "PRIOWAY_ALLOW_NOTIFICATION_TEST",
            "0",
        )
        == "1"
    )


# =========================================================
# NOTIFICATION STATUS
# =========================================================

@notification_api.get("/status")
def notification_status():

    # Initialize here so opening this URL also checks
    # whether the Firebase credentials actually work.

    notification_service.initialize()

    return jsonify(
        notification_service.status()
    )


# =========================================================
# TEST PUSH NOTIFICATION
# =========================================================

@notification_api.post("/test")
def notification_test():

    if not test_endpoint_allowed():

        return jsonify({
            "success": False,
            "message":
                "Notification test endpoint disabled",
        }), 403

    data = (
        request.get_json(
            silent=True
        )
        or {}
    )

    title = str(
        data.get(
            "title",
            "PrioWay Test",
        )
    )

    body = str(
        data.get(
            "body",
            (
                "PrioWay Firebase "
                "notifications are connected."
            ),
        )
    )

    result = (
        notification_service
        .send_to_registered_devices(
            title=title,
            body=body,
            data={
                "type":
                    "PRIOWAY_TEST",
                "source":
                    "BACKEND",
            },
        )
    )

    status = result.get(
        "status"
    )

    if result.get("success"):

        code = 200

    elif status == (
        "NO_REGISTERED_DEVICES"
    ):

        code = 409

    elif status in {
        "DEPENDENCY_MISSING",
        "NOT_CONFIGURED",
        "CONFIGURED_NOT_INITIALIZED",
    }:

        code = 503

    else:

        code = 502

    return jsonify(
        result
    ), code
