"""SQLite persistence for upload history and dedup tracking."""
import sqlite3
import hashlib
import os
import threading


class Database:
    def __init__(self, db_path):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self._lock = threading.Lock()
        self.conn.execute(
            """CREATE TABLE IF NOT EXISTS uploads
            (file_hash TEXT PRIMARY KEY, file_name TEXT, file_path TEXT,
             topic_id INTEGER, uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"""
        )
        try:
            self.conn.execute("ALTER TABLE uploads ADD COLUMN message_link TEXT")
        except sqlite3.OperationalError:
            pass
        self.conn.commit()

    def is_uploaded(self, file_hash):
        with self._lock:
            return bool(
                self.conn.execute(
                    "SELECT 1 FROM uploads WHERE file_hash=?", (file_hash,)
                ).fetchone()
            )

    def mark_uploaded(self, file_hash, file_name, file_path, topic_id, message_link=None):
        with self._lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO uploads "
                "(file_hash, file_name, file_path, topic_id, message_link) "
                "VALUES (?,?,?,?,?)",
                (file_hash, file_name, file_path, topic_id, message_link),
            )
            self.conn.commit()

    def total_count(self):
        with self._lock:
            return self.conn.execute("SELECT COUNT(*) FROM uploads").fetchone()[0]

    def recent(self, limit=5):
        with self._lock:
            rows = self.conn.execute(
                "SELECT file_name, uploaded_at, message_link FROM uploads "
                "ORDER BY uploaded_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [{"name": r[0], "time": r[1], "link": r[2]} for r in rows]

    def history(self, query="", limit=20, offset=0, ext="", date_from="",
                date_to="", sort="desc"):
        clauses, params = [], []
        if query:
            clauses.append("file_name LIKE ?")
            params.append(f"%{query}%")
        if ext:
            clauses.append("LOWER(file_name) LIKE ?")
            params.append(f"%.{ext.lower().lstrip('.')}")
        if date_from:
            clauses.append("date(uploaded_at, 'localtime') >= ?")
            params.append(date_from)
        if date_to:
            clauses.append("date(uploaded_at, 'localtime') <= ?")
            params.append(date_to)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        order = "ASC" if str(sort).lower() == "asc" else "DESC"
        sql = (f"SELECT file_name, uploaded_at, message_link FROM uploads "
               f"{where} ORDER BY uploaded_at {order} LIMIT ? OFFSET ?")
        with self._lock:
            rows = self.conn.execute(sql, (*params, limit, offset)).fetchall()
        return [{"name": r[0], "time": r[1], "link": r[2]} for r in rows]

    def distinct_extensions(self):
        with self._lock:
            rows = self.conn.execute("SELECT file_name FROM uploads").fetchall()
        exts = {}
        for (name,) in rows:
            if "." in name:
                e = name.rsplit(".", 1)[1].lower()
                if e and len(e) <= 8:
                    exts[e] = exts.get(e, 0) + 1
        return sorted(({"ext": k, "count": v} for k, v in exts.items()),
                      key=lambda x: -x["count"])

    def daily_reports(self, days=30):
        with self._lock:
            rows = self.conn.execute(
                "SELECT date(uploaded_at, 'localtime') as dt, COUNT(*) FROM uploads "
                "GROUP BY dt ORDER BY dt DESC LIMIT ?",
                (days,),
            ).fetchall()
        return [{"date": r[0], "count": r[1]} for r in rows]

    def count_on(self, day_expr="date('now', 'localtime')"):
        with self._lock:
            return self.conn.execute(
                f"SELECT COUNT(*) FROM uploads "
                f"WHERE date(uploaded_at, 'localtime') = {day_expr}"
            ).fetchone()[0]

    def close(self):
        with self._lock:
            self.conn.close()


def generate_file_hash(file_path):
    try:
        stats = os.stat(file_path)
        digest = hashlib.md5(
            f"{file_path}_{stats.st_size}_{stats.st_mtime}".encode()
        ).hexdigest()
        return digest, stats
    except Exception:
        return None, None
