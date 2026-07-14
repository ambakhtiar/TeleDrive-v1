package com.ambakhtiar.teledrive

import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.net.Uri
import android.util.Log
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File
import java.io.FileOutputStream

class UploadWorker(
    appContext: Context,
    params: WorkerParameters
) : CoroutineWorker(appContext, params) {

    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        val prefs = applicationContext.getSharedPreferences("teledrive", Context.MODE_PRIVATE)
        if (prefs.getBoolean("queue_paused", false)) {
            return@withContext Result.success()
        }

        // 1. Atomically claim the next batch of pending items. Setting them to
        //    'uploading' here prevents the JS upload path (runSync ->
        //    claimNextBatch) from grabbing the same rows and double-uploading.
        val claimedItems = mutableListOf<WorkerUploadItem>()
        val claimSuccess = java.util.concurrent.atomic.AtomicBoolean(false)
        DatabaseHelper.withWritable(applicationContext) { db ->
            try {
                db.beginTransaction()
                val cursor = db.rawQuery(
                    """SELECT q.id, q.file_uri, q.filename, q.file_size, f.chat_id, f.topic_id, q.temp_file_path
                       FROM upload_queue q
                       LEFT JOIN folder_sources f ON q.source_folder_id = f.id
                       WHERE q.status = 'pending' AND q.retry_count < 3
                       ORDER BY q.created_at ASC LIMIT 10""",
                    null
                )
                cursor.use {
                    while (it.moveToNext()) {
                        claimedItems.add(WorkerUploadItem(
                            queueItemId = it.getLong(0),
                            fileUri = it.getString(1),
                            filename = it.getString(2),
                            fileSize = it.getLong(3),
                            chatId = it.getLong(4),
                            topicId = it.getLong(5),
                            caption = "",
                            tempPath = it.getString(6),
                        ))
                    }
                }
                if (claimedItems.isNotEmpty()) {
                    val placeholders = claimedItems.joinToString(",") { "?" }
                    val ids = claimedItems.map { it.queueItemId }
                    db.execSQL(
                        "UPDATE upload_queue SET status = 'uploading', updated_at = ? WHERE id IN ($placeholders)",
                        arrayOf<Any>(System.currentTimeMillis(), *ids.toTypedArray()),
                    )
                }
                db.setTransactionSuccessful()
                claimSuccess.set(true)
            } catch (e: Exception) {
                Log.e("UploadWorker", "Failed to claim pending items", e)
            } finally {
                db.endTransaction()
            }
        }
        if (!claimSuccess.get()) return@withContext Result.retry()
        if (claimedItems.isEmpty()) return@withContext Result.success()

        // 2. Keep the app process (and thus the live TDLib client) alive for
        //    the duration of the backup by running inside the foreground
        //    service. If the client is unavailable (process was force-killed),
        //    reset the claimed rows and retry rather than permanently failing.
        val client = TeleDriveModule.getLiveTdLibClient()
        if (client == null) {
            Log.w("UploadWorker", "Live TDLib client unavailable — deferring upload")
            DatabaseHelper.resetToPending(applicationContext, claimedItems.map { it.queueItemId })
            return@withContext Result.retry()
        }

        // 3. Copy SAF URIs to temp (reuse an existing temp copy if still present),
        //    preserving the original SAF URI in file_uri.
        val stagedItems = claimedItems.mapNotNull { item ->
            val existing = item.tempPath?.takeIf { File(it).exists() }
            val tempPath = existing ?: copyToTemp(item)?.also {
                DatabaseHelper.updateTempPath(applicationContext, item.queueItemId, it)
            }
            if (tempPath != null) {
                item.copy(tempPath = tempPath)
            } else {
                markFailed(item.queueItemId, "Worker: could not copy file to temp")
                null
            }
        }

        if (stagedItems.isEmpty()) {
            return@withContext Result.success()
        }

        // 4. Build captions (filename + size + hashtags)
        val uploadItems = stagedItems.map { item ->
            val ext = item.filename.substringAfterLast('.', "").lowercase()
            val sizeStr = formatBytes(item.fileSize)
            val dateStr = java.text.SimpleDateFormat("MMM dd, yyyy", java.util.Locale.US)
                .format(java.util.Date())
            val caption = buildString {
                appendLine(item.filename)
                appendLine("$sizeStr · $dateStr")
                append("#$ext #${item.filename.replace(Regex("[^a-zA-Z0-9]"), "_")}")
            }
            item.copy(caption = caption)
        }

        // 5. Upload via the live TDLib client.
        val results = BackgroundUploader.performUploads(applicationContext, uploadItems)

        val successCount = results.count { it.success }
        val failCount = results.count { !it.success }

        if (failCount > 0 && successCount == 0) {
            return@withContext Result.retry()
        }

        return@withContext Result.success()
    }

    private fun copyToTemp(item: WorkerUploadItem): String? {
        return try {
            val uri = Uri.parse(item.fileUri)
            val cacheDir = File(applicationContext.cacheDir, "teledrive_uploads")
            cacheDir.mkdirs()
            val safeName = item.filename.replace(Regex("[/\\\\:*?\"<>|]"), "_")
            val target = File(cacheDir, "${item.queueItemId}_$safeName")
            if (target.exists()) target.delete()

            applicationContext.contentResolver.openInputStream(uri)?.use { input ->
                FileOutputStream(target).use { output ->
                    input.copyTo(output)
                }
            } ?: return null
            target.absolutePath
        } catch (e: Exception) {
            Log.e("UploadWorker", "copyToTemp failed for ${item.queueItemId}", e)
            null
        }
    }

    private fun markFailed(queueItemId: Long, error: String) {
        DatabaseHelper.markFailed(applicationContext, queueItemId, error)
    }

    private fun formatBytes(bytes: Long): String {
        return when {
            bytes >= 1_073_741_824 -> "%.1f GB".format(bytes.toDouble() / 1_073_741_824.0)
            bytes >= 1_048_576 -> "%.1f MB".format(bytes.toDouble() / 1_048_576.0)
            bytes >= 1_024 -> "%.1f KB".format(bytes.toDouble() / 1_024.0)
            else -> "$bytes B"
        }
    }
}
