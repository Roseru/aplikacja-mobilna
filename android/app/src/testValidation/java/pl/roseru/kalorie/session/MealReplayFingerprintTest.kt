package pl.roseru.kalorie.session

import org.junit.Assert.*
import org.junit.Test

class MealReplayFingerprintTest {
    private fun value(table: String, id: String?, column: String, text: String?) =
        MealReplayFingerprint.normalize(table,id,column,text,"meal","operation","batch")

    @Test fun onlySelectedMealServerRevisionMayChange() {
        assertEquals("0",value("meals","meal","serverRevision","1"))
        assertEquals("1",value("meals","other","serverRevision","1"))
        assertEquals("2",value("meals","meal","localRevision","2"))
    }
    @Test fun selectedQueueStatusIsNormalizedButItsOperationAndPayloadAreNot() {
        assertEquals("pending",value("outbox","operation","status","acked"))
        assertEquals("acked",value("outbox","other","status","acked"))
        assertEquals("changed",value("outbox","operation","wireJson","changed"))
        assertEquals("changed",value("outbox","operation","payload","changed"))
    }
    @Test fun onlyThreeMutableSelectedBatchFieldsAreNormalized() {
        assertEquals("0",value("sync_push_batches","batch","attempted","1"))
        assertNull(value("sync_push_batches","batch","responseJson","ACK"))
        assertEquals("pending",value("sync_push_batches","batch","state","complete"))
        for(column in listOf("requestJson","requestHash","wireContext","ownerScope","snapshotRunId","createdAt","retryAtMillis"))
            assertEquals("changed",value("sync_push_batches","batch",column,"changed"))
    }
    @Test fun OtherRowsAndTablesPreserveEvenSimilarColumnNames() {
        for(table in listOf("profiles","goals","meal_items","photo_analysis_requests"))
            for(column in listOf("status","serverRevision","attempted","state"))assertEquals("original",value(table,"meal",column,"original"))
        assertEquals("ACK",value("sync_push_batches","other","responseJson","ACK"))
    }
    @Test fun UnknownValuesRemainMissingAndContentMutationsRemainDetectable() {
        assertNull(value("meals","meal","wirePayload",null))
        assertNotEquals(value("meals","meal","wirePayload","before"),value("meals","meal","wirePayload","after"))
        assertNotEquals(value("sync_push_batches","batch","requestJson","before"),value("sync_push_batches","batch","requestJson","after"))
    }
}
