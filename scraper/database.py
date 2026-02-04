import json
import sqlite3
from datetime import datetime
from typing import Optional

from .utils import load_config


class Database:
    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            config = load_config()
            db_path = config.get("database", {}).get("path", "restaurants.db")
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self):
        """Create tables if they don't exist."""
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS restaurants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                michelin_id TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                address TEXT,
                city TEXT,
                region TEXT,
                stars INTEGER DEFAULT 0,
                bib_gourmand INTEGER DEFAULT 0,
                price_range TEXT,
                cuisine_types TEXT,
                description TEXT,
                latitude REAL,
                longitude REAL,
                phone TEXT,
                website TEXT,
                michelin_url TEXT,
                image_url TEXT,
                content_hash TEXT,
                created_at TEXT,
                updated_at TEXT
            );

            CREATE TABLE IF NOT EXISTS restaurant_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                restaurant_id INTEGER NOT NULL,
                content_hash TEXT NOT NULL,
                snapshot_json TEXT NOT NULL,
                changed_at TEXT NOT NULL,
                FOREIGN KEY (restaurant_id) REFERENCES restaurants(id)
            );

            CREATE INDEX IF NOT EXISTS idx_restaurants_michelin_id ON restaurants(michelin_id);
            CREATE INDEX IF NOT EXISTS idx_restaurants_content_hash ON restaurants(content_hash);
            CREATE INDEX IF NOT EXISTS idx_history_restaurant_id ON restaurant_history(restaurant_id);
        """)
        self.conn.commit()

    def get_by_michelin_id(self, michelin_id: str) -> Optional[dict]:
        """Get restaurant by michelin_id."""
        cursor = self.conn.execute(
            "SELECT * FROM restaurants WHERE michelin_id = ?", (michelin_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def upsert_restaurant(self, data: dict) -> tuple[int, str]:
        """
        Insert or update restaurant. Returns (id, action) where action is 'added', 'modified', or 'unchanged'.
        """
        now = datetime.utcnow().isoformat()
        existing = self.get_by_michelin_id(data["michelin_id"])

        if existing is None:
            # Insert new restaurant
            data["created_at"] = now
            data["updated_at"] = now
            columns = ", ".join(data.keys())
            placeholders = ", ".join("?" * len(data))
            cursor = self.conn.execute(
                f"INSERT INTO restaurants ({columns}) VALUES ({placeholders})",
                list(data.values()),
            )
            self.conn.commit()
            return cursor.lastrowid, "added"

        # Check if content changed
        if existing["content_hash"] == data.get("content_hash"):
            return existing["id"], "unchanged"

        # Save history before update
        self._save_history(existing["id"], existing)

        # Update restaurant
        data["updated_at"] = now
        set_clause = ", ".join(f"{k} = ?" for k in data.keys() if k != "michelin_id")
        values = [v for k, v in data.items() if k != "michelin_id"]
        values.append(data["michelin_id"])

        self.conn.execute(
            f"UPDATE restaurants SET {set_clause} WHERE michelin_id = ?", values
        )
        self.conn.commit()
        return existing["id"], "modified"

    def _save_history(self, restaurant_id: int, data: dict):
        """Save restaurant snapshot to history."""
        now = datetime.utcnow().isoformat()
        snapshot = json.dumps(dict(data), ensure_ascii=False)
        self.conn.execute(
            """INSERT INTO restaurant_history (restaurant_id, content_hash, snapshot_json, changed_at)
               VALUES (?, ?, ?, ?)""",
            (restaurant_id, data.get("content_hash", ""), snapshot, now),
        )

    def get_all_hashes(self) -> dict[str, str]:
        """Get mapping of michelin_id -> content_hash for all restaurants."""
        cursor = self.conn.execute("SELECT michelin_id, content_hash FROM restaurants")
        return {row["michelin_id"]: row["content_hash"] for row in cursor}

    def count(self) -> int:
        """Return total restaurant count."""
        cursor = self.conn.execute("SELECT COUNT(*) FROM restaurants")
        return cursor.fetchone()[0]

    def close(self):
        """Close database connection."""
        self.conn.close()
