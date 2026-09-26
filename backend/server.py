import os

from app import app

from routes.api_v1 import api_v1
from routes.device_api import device_api
from routes.notification_api import (
    notification_api,
)


# =========================================================
# PRIOWAY SERVER LAUNCHER
# =========================================================
#
# MAIN START COMMAND:
#
#     python backend\server.py
#
# =========================================================


# ---------------------------------------------------------
# REGISTER MAIN V1 API
# ---------------------------------------------------------

if "api_v1" not in app.blueprints:

    app.register_blueprint(
        api_v1
    )


# ---------------------------------------------------------
# REGISTER DEVICE API
# ---------------------------------------------------------

if "device_api" not in app.blueprints:

    app.register_blueprint(
        device_api
    )


# ---------------------------------------------------------
# REGISTER NOTIFICATION API
# ---------------------------------------------------------

if "notification_api" not in app.blueprints:

    app.register_blueprint(
        notification_api
    )


# ---------------------------------------------------------
# FILE UPLOAD LIMIT
# ---------------------------------------------------------

app.config[
    "MAX_CONTENT_LENGTH"
] = 20 * 1024 * 1024


# ---------------------------------------------------------
# BASIC SERVER INFORMATION
# ---------------------------------------------------------

@app.get("/api/server-info")
def server_info():

    registered_blueprints = sorted(
        list(
            app.blueprints.keys()
        )
    )

    return {
        "success": True,
        "project": "PrioWay",
        "server":
            "PrioWay Main Server",
        "api_version": "v1",
        "blueprints":
            registered_blueprints,
    }


# ---------------------------------------------------------
# START SERVER
# ---------------------------------------------------------

if __name__ == "__main__":

    print()
    print("=" * 60)
    print("PRIOWAY MAIN SERVER")
    print("=" * 60)

    print(
        "API:"
        " http://127.0.0.1:5000/api/v1/health"
    )

    print(
        "Device API:"
        " http://127.0.0.1:5000/api/v1/device/ping"
    )

    print(
        "Notification Status:"
        " http://127.0.0.1:5000"
        "/api/v1/notifications/status"
    )

    print(
        "Server Info:"
        " http://127.0.0.1:5000/api/server-info"
    )

    print("=" * 60)
    print()

    print(
        "Registered blueprints:",
        sorted(
            app.blueprints.keys()
        )
    )

    print()

    app.run(
        host="0.0.0.0",
        port=int(
            os.getenv(
                "PORT",
                "5000"
            )
        ),
        debug=True,
        use_reloader=False,
    )
