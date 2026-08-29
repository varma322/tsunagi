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
    /**
     * Ask for a verdict per message rather than an all-or-nothing answer.
     *
     * Setting this is a promise to read [BatchResponse.results]: the server
     * stores what it can and names what it refused, so treating the 200 as
     * "everything landed" would drop exactly the message it is warning about.
     * A server too old to know the field ignores it and answers as before.
     */
    @SerialName("partial") val partial: Boolean = true,
)

@Serializable
data class MessageResult(
    @SerialName("index") val index: Int,
    /** Absent when the id was itself the unreadable part. */
    @SerialName("id") val id: String? = null,
    @SerialName("status") val status: String,
    @SerialName("error") val error: String? = null,
)

@Serializable
data class BatchResponse(
    @SerialName("accepted") val accepted: Int,
    @SerialName("created") val created: Int,
    @SerialName("duplicates") val duplicates: Int,
    @SerialName("rejected") val rejected: Int = 0,
    /**
     * One entry per message when the request opted in. Null from a server that
     * does not report per message, whose 200 means it took all of them.
     */
    @SerialName("results") val results: List<MessageResult>? = null,
)

@Serializable
data class IdentityResponse(
    @SerialName("kind") val kind: String,
    @SerialName("scope") val scope: String,
    @SerialName("name") val name: String? = null,
    @SerialName("id") val id: String? = null,
)

/**
 * What the phone reports about its own ability to capture SMS.
 *
 * The server can see that a phone is reachable; it cannot see whether the
 * platform will still hand that phone a message. Only these say so.
 */
@Serializable
data class CheckInRequest(
    @SerialName("capture_permitted") val capturePermitted: Boolean,
    @SerialName("inbox_readable") val inboxReadable: Boolean,
    @SerialName("battery_exempt") val batteryExempt: Boolean,
    @SerialName("last_captured_at") val lastCapturedAt: String? = null,
    @SerialName("last_swept_at") val lastSweptAt: String? = null,
)

@Serializable
data class DeviceStatusResponse(
    @SerialName("id") val id: String,
    @SerialName("name") val name: String,
    @SerialName("enabled") val enabled: Boolean,
    @SerialName("capture") val capture: String,
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

    /**
     * Reports capture health and refreshes presence in one call.
     *
     * Supersedes [heartbeat] on a server new enough to accept it; a 404 means
     * an older server, which is a reason to fall back rather than to fail.
     */
    @POST("api/v1/devices/checkin")
    suspend fun checkIn(
        @Header("Authorization") authorization: String,
        @Body body: CheckInRequest,
    ): DeviceStatusResponse

    @POST("api/v1/messages/batch")
    suspend fun uploadBatch(
        @Header("Authorization") authorization: String,
        @Body body: BatchRequest,
    ): BatchResponse
}
