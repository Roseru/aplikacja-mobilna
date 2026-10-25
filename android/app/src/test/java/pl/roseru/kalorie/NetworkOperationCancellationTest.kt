package pl.roseru.kalorie

import kotlinx.coroutines.*
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.network.NetworkOperationCancellation
import java.util.concurrent.CountDownLatch
import java.util.concurrent.atomic.AtomicInteger

class NetworkOperationCancellationTest {
    @Test fun closeCallbackFailureCannotInterruptCancellationOrFinally()=runBlocking<Unit> {
        val entered=CompletableDeferred<Unit>();val finished=CompletableDeferred<Unit>()
        val scope=CoroutineScope(SupervisorJob()+Dispatchers.Default)
        val work=scope.async {
            withContext(NetworkOperationCancellation(currentCoroutineContext().job)) {
                val handle=NetworkOperationCancellation.subscribeOnCancelling {throw IllegalStateException("Synthetic close failure")}
                try{entered.complete(Unit);awaitCancellation()}finally{handle?.dispose();finished.complete(Unit)}
            }
        }
        try{entered.await();work.cancelAndJoin();assertTrue(work.isCancelled);assertTrue(finished.isCompleted)}
        finally{work.cancelAndJoin();scope.coroutineContext.job.cancelAndJoin()}
    }
    @Test fun parentCancellationClosesConnectionRegisteredByAlreadyFinishedIoChild()=runBlocking<Unit> {
        val entered=CompletableDeferred<Unit>();val finished=CompletableDeferred<Unit>();val closed=CountDownLatch(1)
        val scope=CoroutineScope(SupervisorJob()+Dispatchers.Default)
        val work=scope.async {
            withContext(NetworkOperationCancellation(currentCoroutineContext().job)) {
                // open() and read() need not use the same short-lived child Job.
                val handle=withContext(Dispatchers.IO){NetworkOperationCancellation.subscribeOnCancelling {closed.countDown()}}
                withContext(Dispatchers.IO){try{entered.complete(Unit);closed.await()}finally{handle?.dispose();finished.complete(Unit)}}
            }
        }
        try {
            entered.await();work.cancel()
            withTimeout(3000){finished.await();work.join()}
            assertEquals(0L,closed.count);assertTrue(work.isCancelled)
        }finally{closed.countDown();work.cancelAndJoin();scope.coroutineContext.job.cancelAndJoin()}
    }
    @Test fun disposedOldSubscriptionCannotCloseNewOperationAndThreadContextDoesNotLeak()=runBlocking<Unit> {
        val firstReady=CompletableDeferred<Unit>();val secondReady=CompletableDeferred<Unit>()
        val oldCloses=AtomicInteger();val newCloses=AtomicInteger()
        val scope=CoroutineScope(SupervisorJob()+Dispatchers.Default)
        val first=scope.async {
            withContext(NetworkOperationCancellation(currentCoroutineContext().job)) {
                withContext(Dispatchers.IO){NetworkOperationCancellation.subscribeOnCancelling {oldCloses.incrementAndGet()}!!.dispose()}
                firstReady.complete(Unit);awaitCancellation()
            }
        }
        var second:Deferred<Nothing>?=null
        try {
            firstReady.await()
            second=scope.async {
                withContext(NetworkOperationCancellation(currentCoroutineContext().job)) {
                    val handle=withContext(Dispatchers.IO){NetworkOperationCancellation.subscribeOnCancelling {newCloses.incrementAndGet()}}
                    try{secondReady.complete(Unit);awaitCancellation()}finally{handle?.dispose()}
                }
            }
            secondReady.await();first.cancelAndJoin()
            assertEquals(0,oldCloses.get());assertEquals(0,newCloses.get());assertTrue(second.isActive)
            second.cancelAndJoin();assertEquals(1,newCloses.get())
            withContext(Dispatchers.IO){assertNull(NetworkOperationCancellation.subscribeOnCancelling {fail("No operation outside context")} )}
        }finally{first.cancelAndJoin();second?.cancelAndJoin();scope.coroutineContext.job.cancelAndJoin()}
    }
}
