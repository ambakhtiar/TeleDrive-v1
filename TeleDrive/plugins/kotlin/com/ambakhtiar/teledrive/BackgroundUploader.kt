package com.ambakhtiar.teledrive

import android.content.Context
import android.net.Uri
import android.util.Log
import org.drinkless.tdlib.Client
import org.drinkless.tdlib.TdApi
import java.io.File
import java.io.FileOutputStream
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

data class WorkerUploadItem(
    val queueItemId: Long,
    val fileUri: String,
    val filename: String,
    val fileSize: Long,
    val chatId: Long,
    val topicId: Long,
    val caption: String,
    val tempPath: String? = null,
)

data class WorkerUploadResult(
    val queueItemId: Long,
    val success: Boolean,
    val messageLink: String?,
    val errorMessage: String?,
)

object BackgroundUploader {

    private const val TAG = "BackgroundUploader"

    fun performUploads(
        context: Context,
        items: List<WorkerUploadItem>,
    ): List<WorkerUploadResult> {
        if (items.isEmpty()) return emptyList()

        val results = mutableListOf<WorkerUploadResult>()

        // Reuse the already-authenticated TDLib client owned by the live
        // React Native app. Creating a fresh client here would land on
        // WaitPhoneNumber (no persisted session) and fail every upload.
        // Callers (UploadWorker) must check the client themselves; if it is
        // null we return failures WITHOUT writing to the DB so the worker can
        // reset the rows to 'pending' and retry instead of abandoning them.
        val client = TeleDriveModule.getLiveTdLibClient()
            ?: return items.map {
                WorkerUploadResult(
                    it.queueItemId,
                    false,
                    null,
                    "TDLib session unavailable in background — keep the app running for uploads",
                )
            }

        try {
            for (item in items) {
                try {
                    // Prefer the temp copy staged by the worker; fall back to
                    // copying the SAF URI on the fly if it is missing.
                    val sourcePath = item.tempPath?.takeIf { File(it).exists() }
                        ?: copyToTemp(context, item)
                    if (sourcePath == null) {
                        results.add(WorkerUploadResult(item.queueItemId, false, null, "Failed to copy file"))
                        updateDbState(context, item.queueItemId, "failed", "Failed to copy file")
                        continue
                    }

                    val message = sendDocument(client, item.chatId, item.topicId, sourcePath, item.caption)
                    if (message != null) {
                        val link = "https://t.me/c/${item.chatId}/${message.id}"
                        results.add(WorkerUploadResult(item.queueItemId, true, link, null))
                        updateDbState(context, item.queueItemId, "success", link)
                        // Temp copy is no longer needed once the upload succeeded.
                        item.tempPath?.let { path -> runCatching { File(path).delete() } }
                    } else {
                        results.add(WorkerUploadResult(item.queueItemId, false, null, "TDLib upload failed"))
                        updateDbState(context, item.queueItemId, "failed", "TDLib upload failed")
                    }
                } catch (e: Exception) {
                    Log.e(TAG, "performUploads item failed for ${item.queueItemId}", e)
                    results.add(WorkerUploadResult(item.queueItemId, false, null, e.message ?: "Unknown error"))
                    updateDbState(context, item.queueItemId, "failed", e.message ?: "Unknown error")
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "performUploads batch failed", e)
            results.addAll(
                items.drop(results.size).map {
                    WorkerUploadResult(it.queueItemId, false, null, e.message ?: "Background upload failed")
                }
            )
        }

        return results
    }

    private fun sendDocument(
        client: Client,
        chatId: Long,
        topicId: Long,
        filePath: String,
        caption: String,
    ): TdApi.Message? {
        val latch = CountDownLatch(1)
        val resultRef = AtomicReference<TdApi.Message?>()

        val inputFile = TdApi.InputFileLocal(filePath)
        val formattedCaption = TdApi.FormattedText(caption, null)
        // Pass the real caption (4th positional arg). Previously it was null,
        // silently dropping captions on the native upload path.
        val inputContent = TdApi.InputMessageDocument(inputFile, null, false, formattedCaption)
        val sendOptions = TdApi.MessageSendOptions(null, false, true, false, false, 0, false, null, 0, 0, false)
        val replyTo = if (topicId != 0L) TdApi.InputMessageReplyToMessage(topicId, null, 0) else null

        val request = TdApi.SendMessage(chatId, null, replyTo, sendOptions, null, inputContent)

        client.send(request, Client.ResultHandler { result ->
            when (result) {
                is TdApi.Message -> resultRef.set(result)
                is TdApi.Error -> resultRef.set(null)
                else -> resultRef.set(null)
            }
            latch.countDown()
        })

        try { latch.await(60, TimeUnit.SECONDS) } catch (e: InterruptedException) { Thread.currentThread().interrupt() }
        return resultRef.get()
    }

    private fun copyToTemp(context: Context, item: WorkerUploadItem): String? {
        return try {
            val uri = Uri.parse(item.fileUri)
            val cacheDir = File(context.cacheDir, "teledrive_uploads")
            if (!cacheDir.exists() && !cacheDir.mkdirs()) return null
            val safeName = item.filename.replace(Regex("[/\\\\:*?\"<>|]"), "_")
            val target = File(cacheDir, "${item.queueItemId}_bg_$safeName")
            if (target.exists() && !target.delete()) target.deleteOnExit()
            context.contentResolver.openInputStream(uri)?.use { input ->
                FileOutputStream(target).use { output ->
                    input.copyTo(output)
                }
            } ?: return null
            target.absolutePath
        } catch (e: Exception) {
            Log.e(TAG, "copyToTemp failed for ${item.queueItemId}", e)
            null
        }
    }

    private fun updateDbState(context: Context, queueItemId: Long, status: String, message: String?) {
        DatabaseHelper.updateStatus(context, queueItemId, status, message)
    }
}
