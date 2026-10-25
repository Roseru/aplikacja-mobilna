package pl.roseru.kalorie

import kotlinx.coroutines.*
import kotlinx.coroutines.flow.collect
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.network.*

class NetworkAccessGenerationTest {
    private class Gate:ObservableNetworkAccessGate() {
        init {publish(NetworkAccessState.Allowed(7))}
        fun aba() {publish(NetworkAccessState.Blocked);publish(NetworkAccessState.Allowed(7))}
        fun reread() {publish(NetworkAccessState.Allowed(7))}
    }
    @Test fun conflatedSameRevisionAbaStillPublishesDifferentIssuance()=runBlocking<Unit> {
        val gate=Gate();val old=gate.captureAllowed();var states=0;var changes=0
        val state=launch(start=CoroutineStart.UNDISPATCHED){gate.state.collect {states++}}
        val frames=launch(start=CoroutineStart.UNDISPATCHED){gate.changes.collect {changes++}}
        gate.aba();yield()
        assertEquals(1,states);assertEquals(2,changes)
        assertEquals(old.revision,gate.captureAllowed().revision)
        assertNotEquals(old.issuance,gate.captureAllowed().issuance)
        try{gate.requireCurrent(old);fail("A revoked permit must stay revoked")}catch(_:NetworkAccessDenied){}
        state.cancelAndJoin();frames.cancelAndJoin()
    }
    @Test fun distinctInstancesAndOldGenerationNeverAuthorizeEachOther() {
        val first=Gate();val second=Gate();val permit=first.captureAllowed()
        assertNotEquals(permit.issuance,second.captureAllowed().issuance)
        try{second.requireCurrent(permit);fail("Wrong instance must reject permit")}catch(_:NetworkAccessDenied){}
        first.aba()
        assertEquals(permit.issuance.generation+2,first.captureAllowed().issuance.generation)
    }
    @Test fun identicalRereadDoesNotRevokeUninterruptedGrantAndDefaultIsClosed() {
        val gate=Gate();val permit=gate.captureAllowed();gate.reread()
        gate.requireCurrent(permit);assertEquals(permit.issuance,gate.captureAllowed().issuance)
        assertEquals(NetworkAccessState.Unavailable,ClosedNetworkAccessGate.changes.value.state)
        try{ClosedNetworkAccessGate.captureAllowed();fail("Default must be closed")}catch(_:NetworkAccessDenied){}
    }
}
