package com.ambakhtiar.teledrive

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.net.wifi.WifiManager
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import androidx.core.app.NotificationCompat
import androidx.lifecycle.Observer
import androidx.work.WorkInfo

class TeleDriveForegroundService : Service() {

    companion object {
        const val ACTION_SYNC = "com.ambakhtiar.teledrive.SYNC"
        const val ACTION_STOP = "com.ambakhtiar.teledrive.STOP"
    }

    private var wakeLock: PowerManager.WakeLock? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                TeleDriveModule.NOTIFICATION_CHANNEL_ID,
                "TeleDrive Sync",
                NotificationManager.IMPORTANCE_LOW,
            ).apply {
                description = "Shows when TeleDrive is scanning or uploading files"
            }
            val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            nm.createNotificationChannel(channel)
        }
    }

    private fun buildNotification(statusText: String): Notification {
        val launchIntent = packageManager.getLaunchIntentForPackage(packageName)
        val pendingIntent = PendingIntent.getActivity(
            this, 0, launchIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )

        return NotificationCompat.Builder(this, TeleDriveModule.NOTIFICATION_CHANNEL_ID)
            .setContentTitle("TeleDrive")
            .setContentText(statusText)
            .setSmallIcon(android.R.drawable.stat_sys_upload)
            .setContentIntent(pendingIntent)
            .setOngoing(true)
            .setSilent(true)
            .build()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_SYNC -> {
                acquireWakeLock()
                startForeground(TeleDriveModule.NOTIFICATION_ID, buildNotification("Scanning folders…"))

                val wifiOnly = intent?.getBooleanExtra("wifi_only", true) ?: true
                val chargingOnly = intent?.getBooleanExtra("charging_only", false) ?: false

                val constraints = androidx.work.Constraints.Builder().apply {
                    if (wifiOnly) setRequiredNetworkType(androidx.work.NetworkType.UNMETERED)
                    else setRequiredNetworkType(androidx.work.NetworkType.CONNECTED)
                    if (chargingOnly) setRequiresCharging(true)
                }.build()

                val wm = androidx.work.WorkManager.getInstance(this)
                val workRequest = androidx.work.OneTimeWorkRequestBuilder<UploadWorker>()
                    .setConstraints(constraints)
                    .setInputData(androidx.work.workDataOf("action" to "scan"))
                    .build()
                wm.enqueue(workRequest)

                val liveData = wm.getWorkInfoByIdLiveData(workRequest.id)
                val observer = Observer<WorkInfo> { info ->
                    if (info?.state?.isFinished == true) {
                        liveData.removeObserver(observer)
                        stopForeground(STOP_FOREGROUND_REMOVE)
                        stopSelf()
                        releaseWakeLock()
                    }
                }
                liveData.observeForever(observer)
            }
            ACTION_STOP -> {
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf()
                releaseWakeLock()
            }
        }
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        super.onDestroy()
        releaseWakeLock()
    }

    private fun acquireWakeLock() {
        if (wakeLock == null) {
            val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
            wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "teledrive::sync").apply {
                acquire(30 * 60 * 1000L) // 30 minutes max
            }
        }
    }

    private fun releaseWakeLock() {
        wakeLock?.let {
            if (it.isHeld) it.release()
        }
        wakeLock = null
    }
}
