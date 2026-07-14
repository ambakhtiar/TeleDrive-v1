package com.ambakhtiar.teledrive

import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.util.Log

object DatabaseHelper {
    private const val TAG = "DatabaseHelper"

    // Single shared connection to teledrive.db. expo-sqlite (JS) opens its own
    // connection; keeping the native side on ONE cached, WAL + busy_timeout
    // connection avoids SQLITE_BUSY races and duplicate-handle corruption.
    private var db: SQLiteDatabase? = null
    private val lock = Any()

    private fun getDb(context: Context): SQLiteDatabase {
        synchronized(lock) {
            if (db == null || !db!!.isOpen) {
                val dbFile = context.getDatabasePath("teledrive.db")
                dbFile.parentFile?.mkdirs()
                db = SQLiteDatabase.openDatabase(
                    dbFile.absolutePath, null,
                    SQLiteDatabase.OPEN_READWRITE or SQLiteDatabase.CREATE_IF_NOT_EXISTS,
                )
                // Match expo-sqlite's WAL mode and wait on locks instead of
                // failing immediately with SQLITE_BUSY.
                db!!.execSQL("PRAGMA journal_mode=WAL")
                db!!.execSQL("PRAGMA busy_timeout=5000")
                db!!.execSQL("PRAGMA foreign_keys=ON")
            }
            return db!!
        }
    }

    fun withWritable(context: Context, block: (SQLiteDatabase) -> Unit) {
        synchronized(lock) {
            try {
                block(getDb(context))
            } catch (e: Exception) {
                Log.e(TAG, "DB write error", e)
            }
        }
    }

    fun withReadable(context: Context, block: (SQLiteDatabase) -> Unit) {
        synchronized(lock) {
            try {
                block(getDb(context))
            } catch (e: Exception) {
                Log.e(TAG, "DB read error", e)
            }
        }
    }

    fun updateStatus(context: Context, queueItemId: Long, status: String, message: String? = null) {
        withWritable(context) { db ->
            val now = System.currentTimeMillis()
            if (status == "success" && message != null) {
                db.execSQL(
                    "UPDATE upload_queue SET status = 'success', telegram_msg_link = ?, updated_at = ? WHERE id = ?",
                    arrayOf(message, now, queueItemId)
                )
                val cursor = db.rawQuery(
                    "SELECT file_size FROM upload_queue WHERE id = ?", arrayOf(queueItemId.toString())
                )
                cursor.use {
                    if (it.moveToFirst()) {
                        val size = it.getLong(0)
                        val day = java.text.SimpleDateFormat("yyyy-MM-dd", java.util.Locale.US)
                            .format(java.util.Date(now))
                        db.execSQL(
                            """INSERT INTO daily_upload_summaries (day, file_count, total_bytes, updated_at)
                               VALUES (?, 1, ?, ?)
                               ON CONFLICT(day) DO UPDATE SET
                                 file_count = file_count + 1,
                                 total_bytes = total_bytes + excluded.total_bytes,
                                 updated_at = excluded.updated_at""",
                            arrayOf(day, size, now)
                        )
                    }
                }
            } else if (status == "failed") {
                db.execSQL(
                    "UPDATE upload_queue SET status = 'failed', error_message = ?, retry_count = retry_count + 1, updated_at = ? WHERE id = ?",
                    arrayOf(message ?: "Upload failed", now, queueItemId)
                )
            }
        }
    }

    /**
     * Records the local temp copy path WITHOUT overwriting the original SAF
     * [file_uri]. The SAF URI is the source of truth and must survive so a
     * retry can re-stage the file if the temp copy is later evicted.
     */
    fun updateTempPath(context: Context, queueItemId: Long, tempPath: String) {
        withWritable(context) { db ->
            val now = System.currentTimeMillis()
            db.execSQL(
                "UPDATE upload_queue SET temp_file_path = ?, updated_at = ? WHERE id = ?",
                arrayOf(tempPath, now, queueItemId)
            )
        }
    }

    /**
     * Returns items claimed by the worker back to 'pending' so they can be
     * retried later instead of being abandoned when the live TDLib client is
     * temporarily unavailable.
     */
    fun resetToPending(context: Context, queueItemIds: List<Long>) {
        if (queueItemIds.isEmpty()) return
        withWritable(context) { db ->
            val placeholders = queueItemIds.joinToString(",") { "?" }
            db.execSQL(
                "UPDATE upload_queue SET status = 'pending', updated_at = ? WHERE id IN ($placeholders)",
                arrayOf<Any>(System.currentTimeMillis(), *queueItemIds.toTypedArray()),
            )
        }
    }

    fun markFailed(context: Context, queueItemId: Long, error: String) {
        withWritable(context) { db ->
            val now = System.currentTimeMillis()
            db.execSQL(
                "UPDATE upload_queue SET status = 'failed', error_message = ?, retry_count = retry_count + 1, updated_at = ? WHERE id = ?",
                arrayOf(error, now, queueItemId)
            )
        }
    }
}
