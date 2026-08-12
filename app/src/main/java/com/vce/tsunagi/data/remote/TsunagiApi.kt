package com.vce.tsunagi.data.remote

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.Header
import retrofit2.http.POST

@Serializable
data class RegisterRequest(
    @SerialName("device_name") val deviceName: String,
)

@Serializable
data class RegisterResponse(
    @SerialName("device_id") val deviceId: String,
    @SerialName("token") val token: String,
)

@Serializable
data class MessageUpload(
    @SerialName("id") val id: String,
    @SerialName("sender") val sender: String,
    @SerialName("body") val body: String,
    @SerialName("received_at") val receivedAt: String,
)

@Serializable
data class BatchRequest(
    @SerialName("messages") val messages: List<MessageUpload>,
)

@Serializable
data class BatchResponse(
    @SerialName("accepted") val accepted: Int,
    @SerialName("created") val created: Int,
    @SerialName("duplicates") val duplicates: Int,
)

@Serializable
data class IdentityResponse(
    @SerialName("kind") val kind: String,
    @SerialName("scope") val scope: String,
    @SerialName("name") val name: String? = null,
    @SerialName("id") val id: String? = null,
)

@Serializable
data class HealthResponse(
    @SerialName("status") val status: String,
    @SerialName("version") val version: String? = null,
)

/** Error envelope the backend returns for every non-2xx response. */
@Serializable
data class ApiErrorEnvelope(
    @SerialName("error") val error: ApiErrorDetail,
)

@Serializable
data class ApiErrorDetail(
    @SerialName("code") val code: String,
    @SerialName("message") val message: String,
)

interface TsunagiApi {

    @GET("health")
    suspend fun health(): HealthResponse

    @POST("api/v1/devices/register")
    suspend fun register(
        @Header("Authorization") authorization: String,
        @Body body: RegisterRequest,
    ): RegisterResponse

    /**
     * Authenticated no-op. The server refreshes the device's last_seen on any
     * authenticated call, so this is what lets an idle phone report that it is
     * still alive.
     */
    @GET("api/v1/me")
    suspend fun heartbeat(
        @Header("Authorization") authorization: String,
    ): IdentityResponse

    @POST("api/v1/messages/batch")
    suspend fun uploadBatch(
        @Header("Authorization") authorization: String,
        @Body body: BatchRequest,
    ): BatchResponse
}
