package com.ambakhtiar.teledrive

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import androidx.work.*

class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action == Intent.ACTION_BOOT_COMPLETED) {
            val prefs = context.getSharedPreferences("teledrive", Context.MODE_PRIVATE)
            val wifiOnly = prefs.getBoolean("wifi_only", true)
            val chargingOnly = prefs.getBoolean("charging_only", false)

            val constraints = Constraints.Builder().apply {
                if (wifiOnly) setRequiredNetworkType(NetworkType.UNMETERED)
                else setRequiredNetworkType(NetworkType.CONNECTED)
                if (chargingOnly) setRequiresCharging(true)
            }.build()
            val syncRequest = PeriodicWorkRequestBuilder<UploadWorker>(15, TimeUnit.MINUTES)
                .setConstraints(constraints)
                .addTag("teledrive_continuous_backup")
                .build()
            WorkManager.getInstance(context).enqueueUniquePeriodicWork(
                "teledrive_continuous_backup",
                ExistingPeriodicWorkPolicy.KEEP,
                syncRequest
            )
        }
    }
}
