import os
import sqlite3
import threading


PROJECT_ROOT = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "..",
    )
)

DATA_DIR = os.path.join(
    PROJECT_ROOT,
    "data",
)

DB_PATH = os.path.join(
    DATA_DIR,
    "prioway.db",
)


class DatabaseService:

    def __init__(self):

        os.makedirs(
            DATA_DIR,
            exist_ok=True,
        )

        self.lock = threading.RLock()

        self.initialize()

    # =====================================================
    # CONNECTION
    # =====================================================

    def connect(self):

        connection = sqlite3.connect(
            DB_PATH,
            timeout=10,
        )

        connection.row_factory = (
            sqlite3.Row
        )

        connection.execute(
            "PRAGMA foreign_keys = ON"
        )

        return connection

    # =====================================================
    # INITIAL DATABASE
    # =====================================================

    def initialize(self):

        with self.lock:

            connection = self.connect()

            try:

                connection.execute(
                    "PRAGMA journal_mode = WAL"
                )

                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS vehicles (
                        vehicle_id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        source TEXT NOT NULL,
                        registration_number TEXT,
                        vehicle_type TEXT,
                        hospital_id TEXT,
                        verified INTEGER NOT NULL DEFAULT 0,
                        blacklisted INTEGER NOT NULL DEFAULT 0,
                        blacklist_reason TEXT,
                        online INTEGER NOT NULL DEFAULT 0,
                        last_seen REAL,
                        lat REAL,
                        lon REAL,
                        location_valid INTEGER NOT NULL DEFAULT 0,
                        completed_requests INTEGER NOT NULL DEFAULT 0,
                        rejected_requests INTEGER NOT NULL DEFAULT 0,
                        suspicious_requests INTEGER NOT NULL DEFAULT 0,
                        duplicate_requests INTEGER NOT NULL DEFAULT 0
                    );

                    CREATE TABLE IF NOT EXISTS junctions (
                        junction_id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        source TEXT NOT NULL,
                        lat REAL,
                        lon REAL,
                        last_seen REAL,
                        forced_health TEXT,
                        current_light INTEGER NOT NULL DEFAULT 0,
                        corridor_state TEXT NOT NULL DEFAULT 'NORMAL',
                        gas_value REAL,
                        gas_status TEXT NOT NULL DEFAULT 'UNKNOWN',
                        gas_source TEXT NOT NULL,
                        temperature_value REAL,
                        temperature_source TEXT NOT NULL,
                        camera_status TEXT NOT NULL,
                        camera_source TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS hospitals (
                        hospital_id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        lat REAL,
                        lon REAL,
                        emergency_available INTEGER NOT NULL DEFAULT 1,
                        source TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS emergency_requests (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        request_id TEXT UNIQUE,
                        vehicle_id TEXT NOT NULL,
                        junction_id TEXT,
                        hospital_id TEXT,
                        priority TEXT NOT NULL,
                        status TEXT NOT NULL,
                        verification_status TEXT NOT NULL,
                        source TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        approved_at TEXT,
                        completed_at TEXT
                    );

                    CREATE TABLE IF NOT EXISTS events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        event_id TEXT UNIQUE,
                        event_type TEXT NOT NULL,
                        severity TEXT NOT NULL,
                        details TEXT NOT NULL,
                        vehicle_id TEXT,
                        junction_id TEXT,
                        request_id TEXT,
                        timestamp TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS evidence (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        evidence_id TEXT UNIQUE,
                        request_id TEXT,
                        vehicle_id TEXT,
                        junction_id TEXT,
                        evidence_type TEXT,
                        file_path TEXT,
                        description TEXT,
                        source TEXT,
                        created_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS app_devices (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id TEXT,
                        device_token TEXT UNIQUE,
                        platform TEXT,
                        enabled INTEGER NOT NULL DEFAULT 1,
                        lat REAL,
                        lon REAL,
                        location_accuracy_m REAL,
                        location_updated_at TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS notification_state (
                        key TEXT PRIMARY KEY,
                        value TEXT,
                        updated_at TEXT NOT NULL
                    );
                    """
                )

                # Existing Railway databases already have app_devices,
                # so add the new location columns safely when missing.
                self._ensure_column(
                    connection,
                    "app_devices",
                    "lat",
                    "REAL",
                )
                self._ensure_column(
                    connection,
                    "app_devices",
                    "lon",
                    "REAL",
                )
                self._ensure_column(
                    connection,
                    "app_devices",
                    "location_accuracy_m",
                    "REAL",
                )
                self._ensure_column(
                    connection,
                    "app_devices",
                    "location_updated_at",
                    "TEXT",
                )

                self._seed_database(
                    connection
                )

                # Remove only the old demonstration coordinates from
                # existing persistent Railway databases. Future real
                # JNC-001 coordinates, if added from an actual source,
                # are preserved.
                connection.execute(
                    """
                    UPDATE junctions
                    SET
                        lat = NULL,
                        lon = NULL
                    WHERE
                        junction_id = 'JNC-001'
                        AND ABS(lat - 28.7370) < 0.000001
                        AND ABS(lon - 77.1120) < 0.000001
                    """
                )

                connection.commit()

            finally:

                connection.close()

    # =====================================================
    # SAFE SCHEMA MIGRATION
    # =====================================================

    def _ensure_column(
        self,
        connection,
        table_name,
        column_name,
        column_type,
    ):

        rows = connection.execute(
            f"PRAGMA table_info({table_name})"
        ).fetchall()

        existing = {
            row["name"]
            for row in rows
        }

        if column_name not in existing:

            connection.execute(
                f"ALTER TABLE {table_name} "
                f"ADD COLUMN {column_name} {column_type}"
            )

    # =====================================================
    # SEED DATA
    # =====================================================

    def _seed_database(
        self,
        connection,
    ):

        vehicles = [
            (
                "VEH-001",
                "Physical Emergency Vehicle",
                "PHYSICAL",
                "PRIOWAY-001",
                "AMBULANCE",
                "HOSP-001",
                1,
            ),
            (
                "VEH-SIM-002",
                "Simulated Ambulance 2",
                "SIMULATED",
                "SIM-002",
                "AMBULANCE",
                "HOSP-002",
                1,
            ),
            (
                "VEH-SIM-003",
                "Unverified Demo Vehicle",
                "SIMULATED",
                "SIM-003",
                "AMBULANCE",
                "HOSP-001",
                0,
            ),
        ]

        for item in vehicles:

            connection.execute(
                """
                INSERT OR IGNORE INTO vehicles (
                    vehicle_id,
                    name,
                    source,
                    registration_number,
                    vehicle_type,
                    hospital_id,
                    verified
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                item,
            )

        junctions = [
            (
                "JNC-001",
                "Physical Junction 1",
                "PHYSICAL",
                None,
                None,
                "PHYSICAL",
                "UNAVAILABLE",
                "UNAVAILABLE",
                "PHYSICAL",
            ),
            (
                "JNC-SIM-002",
                "Simulated Junction 2",
                "SIMULATED",
                28.7200,
                77.1450,
                "SIMULATED",
                "SIMULATED",
                "SIMULATED_STREAM",
                "SIMULATED",
            ),
            (
                "JNC-SIM-003",
                "Simulated Junction 3",
                "SIMULATED",
                28.7000,
                77.1750,
                "SIMULATED",
                "SIMULATED",
                "SIMULATED_STREAM",
                "SIMULATED",
            ),
            (
                "JNC-SIM-004",
                "Simulated Junction 4",
                "SIMULATED",
                28.6800,
                77.2050,
                "SIMULATED",
                "SIMULATED",
                "SIMULATED_STREAM",
                "SIMULATED",
            ),
        ]

        for item in junctions:

            connection.execute(
                """
                INSERT OR IGNORE INTO junctions (
                    junction_id,
                    name,
                    source,
                    lat,
                    lon,
                    gas_source,
                    temperature_source,
                    camera_status,
                    camera_source
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                item,
            )

        hospitals = [
            (
                "HOSP-001",
                "PrioWay Demo Hospital A",
                28.5672,
                77.2100,
                1,
                "DEMO",
            ),
            (
                "HOSP-002",
                "PrioWay Demo Hospital B",
                28.6304,
                77.2177,
                1,
                "DEMO",
            ),
        ]

        for item in hospitals:

            connection.execute(
                """
                INSERT OR IGNORE INTO hospitals (
                    hospital_id,
                    name,
                    lat,
                    lon,
                    emergency_available,
                    source
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                item,
            )

    # =====================================================
    # SIMPLE HELPERS
    # =====================================================

    def fetch_one(
        self,
        query,
        parameters=(),
    ):

        with self.lock:

            connection = self.connect()

            try:

                cursor = connection.execute(
                    query,
                    parameters,
                )

                row = cursor.fetchone()

                if row is None:
                    return None

                return dict(row)

            finally:

                connection.close()

    def fetch_all(
        self,
        query,
        parameters=(),
    ):

        with self.lock:

            connection = self.connect()

            try:

                cursor = connection.execute(
                    query,
                    parameters,
                )

                return [
                    dict(row)
                    for row in cursor.fetchall()
                ]

            finally:

                connection.close()

    def execute(
        self,
        query,
        parameters=(),
    ):

        with self.lock:

            connection = self.connect()

            try:

                cursor = connection.execute(
                    query,
                    parameters,
                )

                connection.commit()

                return cursor.rowcount

            finally:

                connection.close()

    def insert(
        self,
        query,
        parameters=(),
    ):

        with self.lock:

            connection = self.connect()

            try:

                cursor = connection.execute(
                    query,
                    parameters,
                )

                row_id = cursor.lastrowid

                connection.commit()

                return row_id

            finally:

                connection.close()


database_service = DatabaseService()
