package com.ambakhtiar.teledrive

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

object SecurePrefs {
    private const val PREFS_NAME = "teledrive_auth_encrypted"
    private const val KEY_API_ID = "api_id"
    private const val KEY_API_HASH = "api_hash"

    private var prefs: SharedPreferences? = null

    private fun get(context: Context): SharedPreferences {
        if (prefs == null) {
            val masterKey = MasterKey.Builder(context)
                .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
                .build()
            prefs = EncryptedSharedPreferences.create(
                context,
                PREFS_NAME,
                masterKey,
                EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
                EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
            )
        }
        return prefs!!
    }

    fun storeApiCredentials(context: Context, apiId: Long, apiHash: String) {
        get(context).edit()
            .putLong(KEY_API_ID, apiId)
            .putString(KEY_API_HASH, apiHash)
            .apply()
    }

    fun getApiId(context: Context): Long {
        return get(context).getLong(KEY_API_ID, 0L)
    }

    fun getApiHash(context: Context): String? {
        return get(context).getString(KEY_API_HASH, null)
    }

    fun clear(context: Context) {
        get(context).edit().clear().apply()
    }
}
