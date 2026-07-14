package com.ambakhtiar.teledrive

import android.content.Context
import android.net.Uri
import android.provider.DocumentsContract
import android.util.Log
import com.facebook.react.bridge.Arguments
import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.bridge.WritableMap
import com.facebook.react.modules.core.DeviceEventManagerModule
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.semaphore.Semaphore
import kotlinx.coroutines.semaphore.withPermit
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import org.drinkless.tdlib.Client
import org.drinkless.tdlib.TdApi
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.lang.reflect.Field
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.coroutines.resume

data class UploadItem(
    val queueItemId: Long,
    val fileUri: String,
    val chatId: Long,
    val topicId: Long,
    val caption: String,
    val filename: String,
    val fileSize: Long,
)

data class UploadResult(
    val queueItemId: Long,
    val success: Boolean,
    val messageLink: String?,
    val errorMessage: String?,
)

class NativeUploader(private val reactContext: ReactApplicationContext) {

    companion object {
        private var clientField: Field? = null
    }

    private fun getClient(): Client? {
        try {
            val tdlib = reactContext.getNativeModule(
                Class.forName("com.reactnativetdlib.tdlibclient.TdLibModule")
            ) ?: return null
            if (clientField == null) {
                val f = tdlib.javaClass.getDeclaredField("client")
                f.isAccessible = true
                clientField = f
            }
            return clientField?.get(tdlib) as? Client
        } catch (e: Exception) {
            Log.e("NativeUploader", "Failed to get TDLib client", e)
            return null
        }
    }

    suspend fun uploadBatch(
        items: List<UploadItem>,
        maxConcurrent: Int,
    ): List<UploadResult> = withContext(Dispatchers.IO) {
        val client = getClient() ?: return@withContext items.map {
            UploadResult(it.queueItemId, false, null, "TDLib not initialized")
        }

        val semaphore = Semaphore(maxConcurrent.coerceIn(1, 4))

        coroutineScope {
            items.map { item ->
                async {
                    semaphore.withPermit {
                        uploadOne(client, item)
                    }
                }
            }.awaitAll()
        }
    }

    private suspend fun uploadOne(client: Client, item: UploadItem): UploadResult {
        emitProgress(item.queueItemId, 0, item.fileSize, 0)
        val tempPath = copySafToTemp(item) ?: return UploadResult(
            item.queueItemId, false, null, "Failed to copy file to temp"
        )
        emitProgress(item.queueItemId, 0, item.fileSize, 0)

        val result = try {
            val message = sendDocument(client, item.chatId, item.topicId, tempPath, item.caption)
            if (message != null) {
                val link = "https://t.me/c/${item.chatId}/${message.id}"
                // NOTE: do NOT write to the DB here. The JS caller
                // (services/upload.ts) owns the authoritative status write via
                // markUploaded/markFailed; the worker path uses
                // BackgroundUploader.updateStatus instead. Writing here too
                // double-counts daily_upload_summaries.
                emitProgress(item.queueItemId, item.fileSize, item.fileSize, 0)
                emitEvent("uploadFinished", Arguments.createMap().apply {
                    putDouble("queueItemId", item.queueItemId.toDouble())
                    putString("status", "uploaded")
                    putString("messageLink", link)
                })
                UploadResult(item.queueItemId, true, link, null)
            } else {
                UploadResult(item.queueItemId, false, null, "TDLib send failed")
            }
        } finally {
            // Temp copy is no longer needed (the SAF URI is preserved as the
            // source of truth, so a retry re-stages from it). Prevents unbounded
            // cache growth.
            runCatching { File(tempPath).delete() }
        }
        return result
    }

    private suspend fun sendDocument(
        client: Client,
        chatId: Long,
        topicId: Long,
        filePath: String,
        caption: String,
    ): TdApi.Message? {
        val inputFile = TdApi.InputFileLocal(filePath)
        val formattedCaption = TdApi.FormattedText(caption, null)
        // Pass the real caption (4th positional arg). Previously null, which
        // silently dropped captions on this upload path.
        val inputContent = TdApi.InputMessageDocument(inputFile, null, false, formattedCaption)
        val sendOptions = TdApi.MessageSendOptions(null, false, false, false, false, 0, false, null, 0, 0, false)
        val replyTo = if (topicId != 0L) TdApi.InputMessageReplyToMessage(topicId, null, 0) else null
        val request = TdApi.SendMessage(chatId, null, replyTo, sendOptions, null, inputContent)

        // Bound the wait: if TDLib never replies (network drop, auth failure,
        // disposed client) the batch promise must still resolve, not hang.
        return withTimeoutOrNull(60_000) {
            suspendCancellableCoroutine { continuation ->
                val resumed = AtomicBoolean(false)
                client.send(request, Client.ResultHandler { result ->
                    if (resumed.compareAndSet(false, true)) {
                        try {
                            continuation.resume((result as? TdApi.Message))
                        } catch (e: Exception) {
                            Log.e("NativeUploader", "Continuation resume failed after cancellation", e)
                        }
                    }
                })
                continuation.invokeOnCancellation {
                    // TDLib has no cheap way to abort an in-flight send; the
                    // late result (if any) is dropped via the resumed guard.
                }
            }
        }
    }

    private fun copySafToTemp(item: UploadItem): String? {
        try {
            val uri = Uri.parse(item.fileUri)
            val cacheDir = File(reactContext.cacheDir, "teledrive_uploads")
            if (!cacheDir.exists() && !cacheDir.mkdirs()) return null
            val safeName = item.filename.replace(Regex("[/\\\\:*?\"<>|]"), "_")
            val target = File(cacheDir, "${item.queueItemId}_$safeName")
            if (target.exists()) return target.absolutePath

            reactContext.contentResolver.openInputStream(uri)?.use { input ->
                FileOutputStream(target).use { output ->
                    input.copyTo(output)
                }
            }
            return target.absolutePath
        } catch (e: Exception) {
            Log.e("NativeUploader", "copySafToTemp failed for ${item.queueItemId}", e)
            return null
        }
    }

    private fun emitProgress(queueItemId: Long, transferred: Long, total: Long, speed: Long) {
        emitEvent("uploadProgress", Arguments.createMap().apply {
            putDouble("queueItemId", queueItemId.toDouble())
            putDouble("bytesTransferred", transferred.toDouble())
            putDouble("totalBytes", total.toDouble())
            putDouble("bytesPerSecond", speed.toDouble())
            putString("state", if (transferred >= total) "success" else "uploading")
        })
    }

    private fun emitEvent(eventName: String, params: WritableMap) {
        try {
            reactContext
                .getJSModule(DeviceEventManagerModule.RCTDeviceEventEmitter::class.java)
                .emit(eventName, params)
        } catch (e: Exception) {
            Log.e("NativeUploader", "emitEvent failed: $eventName", e)
        }
    }
}
