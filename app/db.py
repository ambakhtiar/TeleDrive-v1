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
        # Additive schema migrations (safe to run every startup).
        for col, decl in (
            ("message_link", "TEXT"),
            ("message_id", "INTEGER"),
            ("size", "INTEGER"),
            ("sha256", "TEXT"),
        ):
            try:
                self.conn.execute(f"ALTER TABLE uploads ADD COLUMN {col} {decl}")
            except sqlite3.OperationalError:
                pass
        self.conn.commit()
        self.backfill_message_ids()

    def is_uploaded(self, file_hash):
        with self._lock:
            return bool(
                self.conn.execute(
                    "SELECT 1 FROM uploads WHERE file_hash=?", (file_hash,)
                ).fetchone()
            )

    def mark_uploaded(self, file_hash, file_name, file_path, topic_id,
                      message_link=None, message_id=None, size=None, sha256=None):
        with self._lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO uploads "
                "(file_hash, file_name, file_path, topic_id, message_link, "
                " message_id, size, sha256) VALUES (?,?,?,?,?,?,?,?)",
                (file_hash, file_name, file_path, topic_id, message_link,
                 message_id, size, sha256),
            )
            self.conn.commit()

    def get_upload(self, file_hash):
        """Full row for a single upload (used by download/restore)."""
        with self._lock:
            row = self.conn.execute(
                "SELECT file_hash, file_name, file_path, topic_id, message_link, "
                "message_id, size, sha256 FROM uploads WHERE file_hash=?",
                (file_hash,),
            ).fetchone()
        if not row:
            return None
        keys = ["file_hash", "file_name", "file_path", "topic_id", "message_link",
                "message_id", "size", "sha256"]
        return dict(zip(keys, row))

    def backfill_message_ids(self):
        """Populate message_id for old rows from the trailing id in message_link
        (…/c/<gid>/<topic>/<msg_id>). Runs once; cheap no-op after that."""
        with self._lock:
            rows = self.conn.execute(
                "SELECT file_hash, message_link FROM uploads "
                "WHERE message_id IS NULL AND message_link IS NOT NULL"
            ).fetchall()
            updated = 0
            for file_hash, link in rows:
                try:
                    mid = int(str(link).rstrip("/").split("/")[-1])
                except (ValueError, AttributeError, IndexError):
                    continue
                self.conn.execute(
                    "UPDATE uploads SET message_id=? WHERE file_hash=?",
                    (mid, file_hash),
                )
                updated += 1
            if updated:
                self.conn.commit()
        return updated

    def rows_missing_size(self):
        """(file_hash, message_id) for downloadable rows that have no size yet."""
        with self._lock:
            return self.conn.execute(
                "SELECT file_hash, message_id FROM uploads "
                "WHERE message_id IS NOT NULL AND (size IS NULL OR size=0)"
            ).fetchall()

    def set_size(self, file_hash, size):
        with self._lock:
            self.conn.execute(
                "UPDATE uploads SET size=? WHERE file_hash=?", (size, file_hash)
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
        sql = (f"SELECT file_name, uploaded_at, message_link, file_hash, message_id, "
               f"size FROM uploads {where} ORDER BY uploaded_at {order} LIMIT ? OFFSET ?")
        with self._lock:
            rows = self.conn.execute(sql, (*params, limit, offset)).fetchall()
        return [{"name": r[0], "time": r[1], "link": r[2], "hash": r[3],
                 "downloadable": r[4] is not None, "size": r[5]} for r in rows]

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


def file_sha256(file_path, chunk=1024 * 1024):
    """Streaming content hash for integrity verification."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while True:
            block = f.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()
