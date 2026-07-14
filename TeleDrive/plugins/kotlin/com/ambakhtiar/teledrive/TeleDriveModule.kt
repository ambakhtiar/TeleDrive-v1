package com.ambakhtiar.teledrive

import android.app.Activity
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.Uri
import android.os.BatteryManager
import android.util.Log
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.provider.DocumentsContract
import androidx.core.app.NotificationCompat
import androidx.work.*
import com.facebook.react.bridge.*
import com.facebook.react.modules.core.DeviceEventManagerModule
import kotlinx.coroutines.*
import com.reactnativetdlib.tdlibclient.TdLibJson
import org.drinkless.tdlib.Client
import org.drinkless.tdlib.TdApi
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.TimeUnit

class TeleDriveModule(reactContext: ReactApplicationContext) : ReactContextBaseJavaModule(reactContext), ActivityEventListener {

    override fun getName(): String = "TeleDrive"

    companion object {
        const val NOTIFICATION_CHANNEL_ID = "teledrive_sync"
        const val NOTIFICATION_ID = 1001
        const val PREFS_PENDING_UPLOADS = "teledrive_pending_uploads"

        // Set in init; lets background workers reuse the already-authenticated
        // TDLib client instead of spinning up an unauthenticated one.
        var sharedReactContext: ReactApplicationContext? = null

        /**
         * Exposes the live, already-authenticated TDLib client to background
         * workers (UploadWorker -> BackgroundUploader). Returns null when the
         * React Native bridge / TdLibModule is not alive (e.g. app fully
         * killed), in which case background uploads cannot reuse the session.
         */
        @JvmStatic
        fun getLiveTdLibClient(): Client? {
            val ctx = sharedReactContext ?: return null
            return try {
                val tdlib = ctx.getNativeModule(
                    Class.forName("com.reactnativetdlib.tdlibclient.TdLibModule")
                ) ?: return null
                val clientField = tdlib.javaClass.getDeclaredField("client")
                clientField.isAccessible = true
                clientField.get(tdlib) as? Client
            } catch (e: Exception) {
                Log.e("TeleDriveModule", "getLiveTdLibClient reflection failed", e)
                null
            }
        }
    }

    private var folderPromise: Promise? = null
    private val REQUEST_FOLDER_TREE = 4102
    private val handler = Handler(Looper.getMainLooper())

    private val uploadScope = CoroutineScope(Dispatchers.IO + SupervisorJob())

    init {
        reactContext.addActivityEventListener(this)
        sharedReactContext = reactContext
        createNotificationChannel()
    }

    override fun onCatalystInstanceDestroy() {
        uploadScope.cancel()
        reactContext.removeActivityEventListener(this)
        super.onCatalystInstanceDestroy()
    }

    // ── Notification Channel ─────────────────────────────────────

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                NOTIFICATION_CHANNEL_ID,
                "TeleDrive Sync",
                NotificationManager.IMPORTANCE_LOW,
            ).apply {
                description = "Shows when TeleDrive is scanning or uploading files"
            }
            val nm = reactApplicationContext.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            nm.createNotificationChannel(channel)
        }
    }

    // ── Folder Picker (SAF) ──────────────────────────────────────

    @ReactMethod
    fun pickFolder(promise: Promise) {
        val activity = currentActivity
        if (activity == null) {
            promise.reject("NO_ACTIVITY", "No current activity")
            return
        }

        folderPromise = promise
        val intent = Intent(Intent.ACTION_OPEN_DOCUMENT_TREE).apply {
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION)
            addFlags(Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION)
            addFlags(Intent.FLAG_GRANT_PREFIX_URI_PERMISSION)
        }
        activity.startActivityForResult(intent, REQUEST_FOLDER_TREE)
    }

    override fun onActivityResult(activity: Activity, requestCode: Int, resultCode: Int, data: Intent?) {
        if (requestCode != REQUEST_FOLDER_TREE) return
        val promise = folderPromise ?: return
        folderPromise = null

        if (resultCode != Activity.RESULT_OK || data?.data == null) {
            promise.resolve(null)
            return
        }

        val treeUri = data.data ?: return
        val flags = data.flags and (Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION)
        try {
            reactApplicationContext.contentResolver.takePersistableUriPermission(treeUri, flags)
            val docId = DocumentsContract.getTreeDocumentId(treeUri)
            val displayName = docId.substringAfterLast(':').ifBlank { "Selected folder" }
            val result = Arguments.createMap().apply {
                putString("treeUri", treeUri.toString())
                putString("displayName", displayName)
            }
            promise.resolve(result)
        } catch (error: SecurityException) {
            promise.reject("FOLDER_PERMISSION_FAILED", "Could not keep access to this folder.", error)
        }
    }

    override fun onNewIntent(intent: Intent) = Unit

    // ── Folder Scanning (SAF recursive) ──────────────────────────

    @ReactMethod
    fun scanFolder(treeUri: String, promise: Promise) {
        uploadScope.launch {
            withContext(Dispatchers.IO) {
                try {
                    val uri = Uri.parse(treeUri)
                    val result = Arguments.createArray()
                    scanDirectory(uri, result)
                    handler.post { promise.resolve(result) }
                } catch (e: Exception) {
                    handler.post { promise.reject("SCAN_ERROR", e.message, e) }
                }
            }
        }
    }

    private fun scanDirectory(uri: Uri, result: WritableArray) {
        val resolver = reactApplicationContext.contentResolver
        // Use the *current node's* document id (not the tree root id) so nested
        // subfolders are enumerated correctly instead of re-listing the root.
        val documentId = DocumentsContract.getDocumentId(uri)
        val childrenUri = DocumentsContract.buildChildDocumentsUriUsingTree(uri, documentId)

        resolver.query(
            childrenUri,
            arrayOf(
                DocumentsContract.Document.COLUMN_DOCUMENT_ID,
                DocumentsContract.Document.COLUMN_DISPLAY_NAME,
                DocumentsContract.Document.COLUMN_SIZE,
                DocumentsContract.Document.COLUMN_MIME_TYPE,
                DocumentsContract.Document.COLUMN_LAST_MODIFIED,
            ),
            null, null, null,
        )?.use { cursor ->
            while (cursor.moveToNext()) {
                val docId = cursor.getString(0)
                val name = cursor.getString(1)
                val size = cursor.getLong(2)
                val mimeType = cursor.getString(3)
                val lastModified = cursor.getLong(4)

                if (mimeType == DocumentsContract.Document.MIME_TYPE_DIR) {
                    val childUri = DocumentsContract.buildDocumentUriUsingTree(uri, docId)
                    scanDirectory(childUri, result)
                } else {
                    val fileUri = DocumentsContract.buildDocumentUriUsingTree(uri, docId)
                    val file = Arguments.createMap().apply {
                        putString("uri", fileUri.toString())
                        putString("name", name)
                        putDouble("size", size.toDouble())
                        putString("mimeType", mimeType)
                        putDouble("lastModified", lastModified.toDouble())
                        putBoolean("isDirectory", false)
                    }
                    result.pushMap(file)
                }
            }
        }
    }

    // ── TDLib Client Access via TdLibModule ─────────────────────

    private fun getTdLibClient(): Client? {
        return try {
            val tdlib = reactApplicationContext.getNativeModule(
                Class.forName("com.reactnativetdlib.tdlibclient.TdLibModule")
            ) ?: return null
            val clientField = tdlib.javaClass.getDeclaredField("client")
            clientField.isAccessible = true
            clientField.get(tdlib) as? Client
        } catch (e: Exception) {
            Log.e("TeleDriveModule", "getTdLibClient reflection failed", e)
            null
        }
    }

    // ── Chat Loading (via TDLib Client directly) ────────────────

    @ReactMethod
    fun loadChats(promise: Promise) {
        uploadScope.launch {
            try {
                val client = getTdLibClient()
                if (client == null) {
                    handler.post { promise.reject("TDLIB_UNAVAILABLE", "TdLibModule client not available") }
                    return@launch
                }
                client.send(TdApi.LoadChats(null, 100)) { }
                handler.post { promise.resolve(true) }
            } catch (e: Exception) {
                Log.e("TeleDriveModule", "loadChats failed", e)
                handler.post { promise.reject("LOAD_CHATS_FAILED", e.message) }
            }
        }
    }

    @ReactMethod
    fun getChats(promise: Promise) {
        uploadScope.launch {
            try {
                val client = getTdLibClient()
                if (client == null) {
                    handler.post { promise.reject("TDLIB_UNAVAILABLE", "TdLibModule client not available") }
                    return@launch
                }
                client.send(TdApi.GetChats(null, 100)) { result ->
                    handler.post {
                        if (result is TdApi.Chats) {
                            promise.resolve(TdLibJson.GSON.toJson(result))
                        } else if (result is TdApi.Error) {
                            promise.reject("GET_CHATS_ERROR", result.message)
                        } else {
                            promise.resolve("[]")
                        }
                    }
                }
            } catch (e: Exception) {
                Log.e("TeleDriveModule", "getChats failed", e)
                handler.post { promise.reject("GET_CHATS_FAILED", e.message) }
            }
        }
    }

    @ReactMethod
    fun getForumTopics(chatId: Double, promise: Promise) {
        uploadScope.launch {
            try {
                val client = getTdLibClient()
                if (client == null) {
                    handler.post { promise.reject("TDLIB_UNAVAILABLE", "TdLibModule client not available") }
                    return@launch
                }
                client.send(TdApi.GetForumTopics(chatId.toLong(), "", 0, 0, 0, 50)) { result ->
                    handler.post {
                        if (result is TdApi.ForumTopics) {
                            promise.resolve(TdLibJson.GSON.toJson(result))
                        } else if (result is TdApi.Error) {
                            promise.reject("GET_FORUM_TOPICS_ERROR", result.message)
                        } else {
                            promise.resolve("{}")
                        }
                    }
                }
            } catch (e: Exception) {
                Log.e("TeleDriveModule", "getForumTopics failed", e)
                handler.post { promise.reject("GET_FORUM_TOPICS_FAILED", e.message) }
            }
        }
    }

    @ReactMethod
    fun createForumTopic(chatId: Double, name: String, promise: Promise) {
        uploadScope.launch {
            try {
                val client = getTdLibClient()
                if (client == null) {
                    handler.post { promise.reject("TDLIB_UNAVAILABLE", "TdLibModule client not available") }
                    return@launch
                }
                client.send(TdApi.CreateForumTopic(chatId.toLong(), name, false, null)) { result ->
                    handler.post {
                        if (result is TdApi.ForumTopicInfo) {
                            promise.resolve(TdLibJson.GSON.toJson(result))
                        } else if (result is TdApi.Error) {
                            promise.reject("CREATE_FORUM_TOPIC_ERROR", result.message)
                        } else {
                            promise.resolve("{}")
                        }
                    }
                }
            } catch (e: Exception) {
                Log.e("TeleDriveModule", "createForumTopic failed", e)
                handler.post { promise.reject("CREATE_FORUM_TOPIC_FAILED", e.message) }
            }
        }
    }

    // ── Foreground Service ───────────────────────────────────────

    @ReactMethod
    fun startForegroundService(promise: Promise) {
        try {
            val intent = Intent(reactApplicationContext, TeleDriveForegroundService::class.java).apply {
                action = TeleDriveForegroundService.ACTION_SYNC
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                reactApplicationContext.startForegroundService(intent)
            } else {
                reactApplicationContext.startService(intent)
            }
            promise.resolve(null)
        } catch (e: Exception) {
            Log.e("TeleDriveModule", "startForegroundService failed", e)
            promise.reject("START_SERVICE_FAILED", e.message)
        }
    }

    @ReactMethod
    fun stopForegroundService(promise: Promise) {
        try {
            val intent = Intent(reactApplicationContext, TeleDriveForegroundService::class.java).apply {
                action = TeleDriveForegroundService.ACTION_STOP
            }
            reactApplicationContext.startService(intent)
            promise.resolve(null)
        } catch (e: Exception) {
            Log.e("TeleDriveModule", "stopForegroundService failed", e)
            promise.reject("STOP_SERVICE_FAILED", e.message)
        }
    }

    // ── Queue Control ────────────────────────────────────────────

    @ReactMethod
    fun syncNow(promise: Promise) {
        try {
            val prefs = reactApplicationContext.getSharedPreferences("teledrive", Context.MODE_PRIVATE)
            val wifiOnly = prefs.getBoolean("wifi_only", true)
            val chargingOnly = prefs.getBoolean("charging_only", false)

            // Give immediate feedback when a constraint the user enabled is not
            // met, instead of silently enqueuing a worker that never runs.
            if (wifiOnly && !isWifiConnectedSync()) {
                promise.reject("WIFI_REQUIRED", "Sync is set to Wi-Fi only and you're not on Wi-Fi.")
                return
            }
            if (chargingOnly && !isChargingSync()) {
                promise.reject("CHARGING_REQUIRED", "Sync is set to charging only and the device is not charging.")
                return
            }

            // Run the upload inside the foreground service so the app process
            // (and the live, already-authenticated TDLib client) stays alive
            // for the whole backup. The service enqueues the worker honouring
            // the Wi-Fi / charging constraints.
            val intent = Intent(reactApplicationContext, TeleDriveForegroundService::class.java).apply {
                action = TeleDriveForegroundService.ACTION_SYNC
                putExtra("wifi_only", wifiOnly)
                putExtra("charging_only", chargingOnly)
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                reactApplicationContext.startForegroundService(intent)
            } else {
                reactApplicationContext.startService(intent)
            }
            promise.resolve(null)
        } catch (e: Exception) {
            Log.e("TeleDriveModule", "syncNow failed", e)
            promise.reject("SYNC_FAILED", e.message)
        }
    }

    private fun isWifiConnectedSync(): Boolean {
        return try {
            val cm = reactApplicationContext.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
            val network = cm.activeNetwork ?: return false
            val caps = cm.getNetworkCapabilities(network) ?: return false
            caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)
        } catch (e: Exception) {
            Log.e("TeleDriveModule", "isWifiConnectedSync failed", e)
            false
        }
    }

    private fun isChargingSync(): Boolean {
        return try {
            val bm = reactApplicationContext.getSystemService(Context.BATTERY_SERVICE) as BatteryManager
            bm.isCharging
        } catch (e: Exception) {
            Log.e("TeleDriveModule", "isChargingSync failed", e)
            false
        }
    }

    @ReactMethod
    fun pauseQueue(promise: Promise) {
        val prefs = reactApplicationContext.getSharedPreferences("teledrive", Context.MODE_PRIVATE)
        prefs.edit().putBoolean("queue_paused", true).apply()
        promise.resolve(null)
    }

    @ReactMethod
    fun resumeQueue(promise: Promise) {
        val prefs = reactApplicationContext.getSharedPreferences("teledrive", Context.MODE_PRIVATE)
        prefs.edit().putBoolean("queue_paused", false).apply()
        promise.resolve(null)
    }

    // ── API Credentials (for Worker access) ─────────────────────

    @ReactMethod
    fun storeApiCredentials(apiId: Double, apiHash: String, promise: Promise) {
        SecurePrefs.storeApiCredentials(reactApplicationContext, apiId.toLong(), apiHash)
        promise.resolve(null)
    }

    // ── Batch Upload (coroutine semaphore) ──────────────────────

    @ReactMethod
    fun batchUpload(uploadsJson: String, maxConcurrent: Int, promise: Promise) {
        uploadScope.launch {
            try {
                val arr = JSONArray(uploadsJson)
                val items = mutableListOf<UploadItem>()
                for (i in 0 until arr.length()) {
                    val obj = arr.getJSONObject(i)
                    items.add(UploadItem(
                        queueItemId = obj.getLong("queueItemId"),
                        fileUri = obj.getString("fileUri"),
                        chatId = obj.getLong("chatId"),
                        topicId = obj.getLong("topicId"),
                        caption = obj.optString("caption", ""),
                        filename = obj.getString("filename"),
                        fileSize = obj.getLong("fileSize"),
                    ))
                }

                val uploader = NativeUploader(reactApplicationContext)
                val results = uploader.uploadBatch(items, maxConcurrent)

                handler.post {
                    val json = JSONArray().apply {
                        results.forEach { r ->
                            put(JSONObject().apply {
                                put("queueItemId", r.queueItemId)
                                put("success", r.success)
                                put("messageLink", r.messageLink ?: JSONObject.NULL)
                                put("errorMessage", r.errorMessage ?: JSONObject.NULL)
                            })
                        }
                    }
                    promise.resolve(json.toString())
                }
            } catch (e: Exception) {
                Log.e("TeleDriveModule", "batchUpload failed", e)
                handler.post { promise.reject("BATCH_UPLOAD_FAILED", e.message) }
            }
        }
    }

    // ── File Operations ──────────────────────────────────────────

    @ReactMethod
    fun deleteFile(uri: String, promise: Promise) {
        try {
            reactApplicationContext.contentResolver.delete(Uri.parse(uri), null, null)
            promise.resolve(true)
        } catch (e: Exception) {
            Log.e("TeleDriveModule", "deleteFile failed: $uri", e)
            promise.resolve(false)
        }
        }

    /**
     * Copies a SAF (content://) URI to a local cache file so TDLib's
     * InputFileLocal can read it. The fallback JS upload path sends files
     * directly; passing a content:// URI to TDLib fails, so it must be
     * staged locally first.
     */
    @ReactMethod
    fun copyUriToTemp(uri: String, queueItemId: Double, promise: Promise) {
        uploadScope.launch {
            try {
                val parsed = Uri.parse(uri)
                val cacheDir = File(reactApplicationContext.cacheDir, "teledrive_uploads")
                if (!cacheDir.exists() && !cacheDir.mkdirs()) {
                    promise.resolve(null)
                    return@launch
                }
                val target = File(cacheDir, "fb_${queueItemId.toLong()}.tmp")
                if (target.exists() && !target.delete()) target.deleteOnExit()
                reactApplicationContext.contentResolver.openInputStream(parsed)?.use { input ->
                    FileOutputStream(target).use { output -> input.copyTo(output) }
                } ?: run {
                    promise.resolve(null)
                    return@launch
                }
                promise.resolve(target.absolutePath)
            } catch (e: Exception) {
                Log.e("TeleDriveModule", "copyUriToTemp failed: $uri", e)
                promise.resolve(null)
            }
        }
    }

    // ── Network & Battery ────────────────────────────────────────

    @ReactMethod
    fun isWifiConnected(promise: Promise) {
        try {
            val cm = reactApplicationContext.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
            val network = cm.activeNetwork
            if (network == null) { promise.resolve(false); return }
            val caps = cm.getNetworkCapabilities(network)
            promise.resolve(caps != null && caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI))
        } catch (e: Exception) {
            Log.e("TeleDriveModule", "isWifiConnected failed", e)
            promise.resolve(false)
        }
    }

    @ReactMethod
    fun isDeviceCharging(promise: Promise) {
        try {
            val bm = reactApplicationContext.getSystemService(Context.BATTERY_SERVICE) as BatteryManager
            promise.resolve(bm.isCharging)
        } catch (e: Exception) {
            Log.e("TeleDriveModule", "isDeviceCharging failed", e)
            promise.resolve(false)
        }
    }

    // ── Settings Sync ────────────────────────────────────────────

    @ReactMethod
    fun syncSettings(settings: ReadableMap, promise: Promise) {
        val prefs = reactApplicationContext.getSharedPreferences("teledrive", Context.MODE_PRIVATE)
        prefs.edit()
            .putBoolean("wifi_only", settings.getBoolean("wifiOnly"))
            .putBoolean("charging_only", settings.getBoolean("chargingOnly"))
            .putBoolean("auto_delete", settings.getBoolean("autoDelete"))
            .putInt("max_concurrent_uploads", settings.getInt("maxConcurrentUploads"))
            .putInt("upload_speed_limit_kbps", if (settings.hasKey("uploadSpeedLimitKBps")) settings.getInt("uploadSpeedLimitKBps") else 0)
            .apply()
        promise.resolve(null)
    }

    // ── WorkManager Scheduling ───────────────────────────────────

    @ReactMethod
    fun scheduleContinuousBackup(promise: Promise) {
        try {
            val prefs = reactApplicationContext.getSharedPreferences("teledrive", Context.MODE_PRIVATE)
            val wifiOnly = prefs.getBoolean("wifi_only", true)
            val chargingOnly = prefs.getBoolean("charging_only", false)

            val constraints = buildConstraints(wifiOnly, chargingOnly)
            val data = workDataOf("action" to "scan")
            val workRequest = PeriodicWorkRequestBuilder<UploadWorker>(15, TimeUnit.MINUTES)
                .setConstraints(constraints)
                .setInputData(data)
                .build()
            WorkManager.getInstance(reactApplicationContext)
                .enqueueUniquePeriodicWork(
                    "teledrive_continuous_backup",
                    ExistingPeriodicWorkPolicy.UPDATE,
                    workRequest,
                )
            promise.resolve(null)
        } catch (e: Exception) {
            Log.e("TeleDriveModule", "scheduleContinuousBackup failed", e)
            promise.reject("SCHEDULE_FAILED", e.message)
        }
    }

    @ReactMethod
    fun cancelContinuousBackup(promise: Promise) {
        WorkManager.getInstance(reactApplicationContext)
            .cancelUniqueWork("teledrive_continuous_backup")
        promise.resolve(null)
    }

    // ── Event Emitter ────────────────────────────────────────────

    private fun emitEvent(eventName: String, params: WritableMap) {
        reactApplicationContext
            .getJSModule(DeviceEventManagerModule.RCTDeviceEventEmitter::class.java)
            .emit(eventName, params)
    }

    // ── Helpers ──────────────────────────────────────────────────

    private fun buildConstraints(wifiOnly: Boolean, chargingOnly: Boolean): Constraints {
        return Constraints.Builder().apply {
            if (wifiOnly) setRequiredNetworkType(NetworkType.UNMETERED)
            else setRequiredNetworkType(NetworkType.CONNECTED)
            if (chargingOnly) setRequiresCharging(true)
        }.build()
    }
}
