package pl.roseru.kalorie.session

import org.junit.Assert.*
import org.junit.Test

class MealReplayFingerprintTest {
    @Test fun supportedSchemasIncludeEveryNewBusinessLedgerAndRejectUnknownMigrations() {
        assertEquals(21,MealReplayFingerprint.tables(17).size)
        assertEquals(23,MealReplayFingerprint.tables(18).size)
        assertEquals(32,MealReplayFingerprint.tables(19).size)
        val tables=MealReplayFingerprint.tables(20)
        assertEquals(33,tables.size);assertEquals(tables.size,tables.toSet().size)
        assertTrue(tables.containsAll(listOf("diary_days","canonical_domains","canonical_goal_timelines",
            "import_origins","import_decisions","reconciliation_batches","reconciliation_evidence","reconciliation_pulls")))
        assertThrows(IllegalArgumentException::class.java){MealReplayFingerprint.tables(16)}
        assertThrows(IllegalArgumentException::class.java){MealReplayFingerprint.tables(21)}
        assertThrows(IllegalArgumentException::class.java){MealReplayFingerprint.tables(23)}
        assertThrows(IllegalArgumentException::class.java){MealReplayFingerprint.tables(24)}
        assertThrows(IllegalArgumentException::class.java){MealReplayFingerprint.tables(25, runtimeIsolated = true)}
        assertEquals(39,MealReplayFingerprint.tables(24, runtimeIsolated = true).size)
        assertEquals(35,MealReplayFingerprint.tables(21, runtimeIsolated = true).size)
        assertEquals(36,MealReplayFingerprint.tables(22, runtimeIsolated = true).size)
        val latest=MealReplayFingerprint.tables(23, runtimeIsolated = true)
        assertEquals(39,latest.size);assertEquals(latest.size,latest.toSet().size)
        assertEquals(listOf("snapshot_archive_receipts","sync_work_state","reconciliation_completions",
            "community_cache","community_attempts","community_backoff"), latest.drop(tables.size))
    }
    private fun value(table: String, id: String?, column: String, text: String?) =
        MealReplayFingerprint.normalize(table,id,column,text,"meal","operation","batch")

    @Test fun onlySelectedMealServerRevisionMayChange() {
        assertEquals("0",value("meals","meal","serverRevision","1"))
        assertEquals("1",value("meals","other","serverRevision","1"))
        assertEquals("2",value("meals","meal","localRevision","2"))
        assertEquals("exact-estimate",value("goals","meal","estimateJson","exact-estimate"))
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
        for(table in MealReplayFingerprint.tables(23, runtimeIsolated = true).filterNot{it in setOf("meals","outbox","sync_push_batches")})
            for(column in listOf("status","serverRevision","attempted","state","wireContext","leaseGeneration","requestJson",
                "responseJson","requestedVersion","activeVersion","handledVersion","retryAtMillis","reconciliationBaseline"))
                assertEquals("original",value(table,"meal",column,"original"))
        assertEquals("ACK",value("sync_push_batches","other","responseJson","ACK"))
    }
    @Test fun UnknownValuesRemainMissingAndContentMutationsRemainDetectable() {
        assertNull(value("meals","meal","wirePayload",null))
        assertNotEquals(value("meals","meal","wirePayload","before"),value("meals","meal","wirePayload","after"))
        assertNotEquals(value("sync_push_batches","batch","requestJson","before"),value("sync_push_batches","batch","requestJson","after"))
    }
}
