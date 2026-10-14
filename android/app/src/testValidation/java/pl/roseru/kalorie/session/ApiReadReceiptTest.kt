package pl.roseru.kalorie.session

import org.junit.Assert.*
import org.junit.Test
import java.time.Instant

class ApiReadReceiptTest {
    private val now = Instant.parse("2026-10-14T15:00:00Z")
    private val id = "12345678-1234-1234-1234-123456789abc"
    @Test fun acceptedHeadersProduceOnlyAllowlistedMetadata() {
        assertEquals("path=/api/v1/me utc=$now status=200 no_store=true request_id=$id",
            ApiReadReceipt.format("GET", "/api/v1/me", 200, "private, NO-STORE", id, now))
    }
    @Test fun malformedOrMissingHeadersNeverExposeTheirValues() {
        val value = "Bearer sensitive-value\nCookie: private"
        val receipt = ApiReadReceipt.format("GET", "/api/v1/me/motivation", 401, value, value, now)!!
        assertFalse(receipt.contains("sensitive-value")); assertFalse(receipt.contains("Cookie"))
        assertTrue(receipt.contains("no_store=false request_id=invalid"))
        assertTrue(ApiReadReceipt.format("GET", "/api/v1/me", 200, null, null, now)!!.endsWith("request_id=missing"))
    }
    @Test fun otherOperationsAndNoncanonicalIdsAreExcluded() {
        assertNull(ApiReadReceipt.format("POST", "/api/v1/me", 200, "no-store", id, now))
        assertNull(ApiReadReceipt.format("GET", "/api/v1/me?private=value", 200, "no-store", id, now))
        assertNull(ApiReadReceipt.format("GET", "/api/v1/ai/private-id", 200, "no-store", id, now))
        assertNull(ApiReadReceipt.format("GET", "/api/v1/me", 302, "no-store", id, now))
        assertTrue(ApiReadReceipt.format("GET", "/api/v1/me", 200, "x-no-store", id.uppercase(), now)!!.contains("no_store=false request_id=invalid"))
    }
}
