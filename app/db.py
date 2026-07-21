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
            ("chat_id", "INTEGER"),   # which group/channel the file lives in
            ("duration", "REAL"),     # how long the upload took, seconds
            ("chunked", "INTEGER"),   # 1 if split across multiple messages
            ("total_parts", "INTEGER"),
            ("original_mtime", "REAL"),  # original file creation timestamp for download restore
        ):
            try:
                self.conn.execute(f"ALTER TABLE uploads ADD COLUMN {col} {decl}")
            except sqlite3.OperationalError:
                pass
        # Parts of a chunked (>Telegram-limit) file, one row per message.
        self.conn.execute(
            """CREATE TABLE IF NOT EXISTS file_chunks
            (file_hash TEXT, part_index INTEGER, message_id INTEGER,
             size INTEGER, sha256 TEXT,
             PRIMARY KEY (file_hash, part_index))"""
        )
        self.conn.commit()
        self.backfill_from_links()

    def is_uploaded(self, file_hash):
        with self._lock:
            return bool(
                self.conn.execute(
                    "SELECT 1 FROM uploads WHERE file_hash=?", (file_hash,)
                ).fetchone()
            )

    def mark_uploaded(self, file_hash, file_name, file_path, topic_id,
                      message_link=None, message_id=None, size=None, sha256=None,
                      chat_id=None, duration=None, chunked=0, total_parts=1,
                      original_mtime=None):
        with self._lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO uploads "
                "(file_hash, file_name, file_path, topic_id, message_link, "
                " message_id, size, sha256, chat_id, duration, chunked, total_parts, "
                " original_mtime) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (file_hash, file_name, file_path, topic_id, message_link,
                 message_id, size, sha256, chat_id, duration, chunked, total_parts,
                 original_mtime),
            )
            self.conn.commit()

    def get_upload(self, file_hash):
        """Full row for a single upload (used by download/restore)."""
        keys = ["file_hash", "file_name", "file_path", "topic_id", "message_link",
                "message_id", "size", "sha256", "chat_id", "duration",
                "chunked", "total_parts", "original_mtime"]
        with self._lock:
            row = self.conn.execute(
                f"SELECT {', '.join(keys)} FROM uploads WHERE file_hash=?",
                (file_hash,),
            ).fetchone()
        return dict(zip(keys, row)) if row else None

    # ---------- chunked-file parts ----------
    def add_chunk(self, file_hash, part_index, message_id, size, sha256):
        with self._lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO file_chunks "
                "(file_hash, part_index, message_id, size, sha256) VALUES (?,?,?,?,?)",
                (file_hash, part_index, message_id, size, sha256),
            )
            self.conn.commit()

    def get_chunks(self, file_hash):
        """Ordered list of a chunked file's parts."""
        with self._lock:
            rows = self.conn.execute(
                "SELECT part_index, message_id, size, sha256 FROM file_chunks "
                "WHERE file_hash=? ORDER BY part_index",
                (file_hash,),
            ).fetchall()
        return [{"part_index": r[0], "message_id": r[1], "size": r[2], "sha256": r[3]}
                for r in rows]

    def done_chunk_indices(self, file_hash):
        """Set of part indices already uploaded (for resume)."""
        with self._lock:
            rows = self.conn.execute(
                "SELECT part_index FROM file_chunks WHERE file_hash=?", (file_hash,)
            ).fetchall()
        return {r[0] for r in rows}

    @staticmethod
    def _parse_link(link):
        """A message link is https://t.me/c/<gid>/<topic>/<msg_id> (topic
        optional). Return (chat_id, message_id) or (None, None)."""
        try:
            parts = str(link).rstrip("/").split("/")
            i = parts.index("c")
            gid = parts[i + 1]
            msg_id = int(parts[-1])
            chat_id = int(f"-100{gid}")
            return chat_id, msg_id
        except (ValueError, IndexError, AttributeError):
            return None, None

    def backfill_from_links(self):
        """Populate message_id + chat_id for old rows from their message_link.
        Runs once at startup; a cheap no-op afterwards."""
        with self._lock:
            rows = self.conn.execute(
                "SELECT file_hash, message_link FROM uploads "
                "WHERE (message_id IS NULL OR chat_id IS NULL) "
                "AND message_link IS NOT NULL"
            ).fetchall()
            updated = 0
            for file_hash, link in rows:
                chat_id, mid = self._parse_link(link)
                if mid is None:
                    continue
                self.conn.execute(
                    "UPDATE uploads SET message_id=?, chat_id=? WHERE file_hash=?",
                    (mid, chat_id, file_hash),
                )
                updated += 1
            if updated:
                self.conn.commit()
        return updated

    def rows_missing_size(self):
        """(file_hash, message_id, chat_id) for downloadable rows lacking size."""
        with self._lock:
            return self.conn.execute(
                "SELECT file_hash, message_id, chat_id FROM uploads "
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
               f"size, duration FROM uploads {where} "
               f"ORDER BY uploaded_at {order} LIMIT ? OFFSET ?")
        with self._lock:
            rows = self.conn.execute(sql, (*params, limit, offset)).fetchall()
        return [{"name": r[0], "time": r[1], "link": r[2], "hash": r[3],
                 "downloadable": r[4] is not None, "size": r[5],
                 "duration": r[6]} for r in rows]

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

    def backup_to(self, dest_path):
        """Write a consistent copy of the live DB using SQLite's online backup
        API (safe even while the DB is in use). Returns metadata about it."""
        with self._lock:
            dest = sqlite3.connect(dest_path)
            try:
                self.conn.backup(dest)
            finally:
                dest.close()
            rows = self.conn.execute("SELECT COUNT(*) FROM uploads").fetchone()[0]
            last = self.conn.execute("SELECT MAX(uploaded_at) FROM uploads").fetchone()[0]
        return {"rows": rows, "last": last or ""}

    def stats_meta(self):
        with self._lock:
            rows = self.conn.execute("SELECT COUNT(*) FROM uploads").fetchone()[0]
            last = self.conn.execute("SELECT MAX(uploaded_at) FROM uploads").fetchone()[0]
        return {"rows": rows, "last": last or ""}

    def close(self):
        with self._lock:
            self.conn.close()


def generate_file_hash(file_path):
    """Dedup identity of a file: base NAME + size + mtime — NOT the full path.

    Using the basename (not the absolute path) means the same file uploaded
    from the browser twice — which lands in a different random staging dir each
    time — still produces the SAME id, so it's correctly detected as a
    duplicate. A different mtime (an edited/new version) yields a different id,
    so it uploads again. Matches: same name+size+mtime → skip; changed → upload.
    """
    try:
        stats = os.stat(file_path)
        name = os.path.basename(file_path)
        digest = hashlib.md5(
            f"{name}_{stats.st_size}_{int(stats.st_mtime)}".encode()
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
