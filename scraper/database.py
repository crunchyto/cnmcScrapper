import sqlite3
from datetime import datetime, timezone
from typing import Optional

from .utils import load_config


class Database:
    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            config = load_config()
            db_path = str(config.get("database", {}).get("path", "cnmc.db"))
        self.db_path: str = db_path
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self) -> None:
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS portability (
                phone TEXT PRIMARY KEY,
                operator TEXT,
                query_date TEXT,
                scraped_at TEXT
            );

            CREATE TABLE IF NOT EXISTS progress (
                csv_file TEXT PRIMARY KEY,
                last_line INTEGER,
                updated_at TEXT
            );
        """)
        self.conn.commit()

    def upsert_result(self, phone: str, operator: str, query_date: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """INSERT INTO portability (phone, operator, query_date, scraped_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(phone) DO UPDATE SET
                 operator = excluded.operator,
                 query_date = excluded.query_date,
                 scraped_at = excluded.scraped_at""",
            (phone, operator, query_date, now),
        )
        self.conn.commit()

    def get_progress(self, csv_file: str) -> int:
        cursor = self.conn.execute(
            "SELECT last_line FROM progress WHERE csv_file = ?", (csv_file,)
        )
        row = cursor.fetchone()
        return row["last_line"] if row else 0

    def update_progress(self, csv_file: str, last_line: int) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """INSERT INTO progress (csv_file, last_line, updated_at)
               VALUES (?, ?, ?)
               ON CONFLICT(csv_file) DO UPDATE SET
                 last_line = excluded.last_line,
                 updated_at = excluded.updated_at""",
            (csv_file, last_line, now),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
