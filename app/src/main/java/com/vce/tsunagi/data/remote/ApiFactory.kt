package com.vce.tsunagi.data.remote

import com.vce.tsunagi.BuildConfig
import java.util.concurrent.TimeUnit
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.kotlinx.serialization.asConverterFactory

/**
 * Builds [TsunagiApi] clients. The server URL is user-supplied and can change
 * at runtime, so clients are created per base URL rather than held as a
 * singleton; the underlying OkHttp client (and its connection pool) is shared.
 */
object ApiFactory {

    private val json = Json {
        ignoreUnknownKeys = true
        encodeDefaults = true
    }

    private val httpClient: OkHttpClient by lazy {
        OkHttpClient.Builder()
            .connectTimeout(15, TimeUnit.SECONDS)
            .readTimeout(30, TimeUnit.SECONDS)
            .writeTimeout(30, TimeUnit.SECONDS)
            .retryOnConnectionFailure(true)
            .apply {
                if (BuildConfig.DEBUG) {
                    addInterceptor(
                        HttpLoggingInterceptor().apply {
                            // BODY would print message contents to logcat.
                            level = HttpLoggingInterceptor.Level.BASIC
                        }
                    )
                }
            }
            .build()
    }

    fun create(serverUrl: String): TsunagiApi =
        Retrofit.Builder()
            .baseUrl(normalizeBaseUrl(serverUrl))
            .client(httpClient)
            .addConverterFactory(json.asConverterFactory("application/json".toMediaType()))
            .build()
            .create(TsunagiApi::class.java)

    /** Retrofit requires a trailing slash, which users routinely omit. */
    fun normalizeBaseUrl(serverUrl: String): String {
        val trimmed = serverUrl.trim()
        return if (trimmed.endsWith("/")) trimmed else "$trimmed/"
    }

    fun bearer(token: String): String = "Bearer $token"
}
