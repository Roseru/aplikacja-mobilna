package pl.roseru.kalorie.energy

import kotlinx.coroutines.flow.StateFlow
import pl.roseru.kalorie.session.ApiSession
import pl.roseru.kalorie.session.SessionController
import pl.roseru.kalorie.session.SessionView

/** The adapter delegates to the single existing controller, including its refresh and commit fence. */
internal interface EnergySessionAccess {
    val view:StateFlow<SessionView>
    suspend fun session(scope:EnergyScope,forceRefresh:Boolean=false):ApiSession
    suspend fun <T> withSession(ticket:ApiSession,scope:EnergyScope,block:suspend ()->T):T
    suspend fun defer(ticket:ApiSession,scope:EnergyScope,until:Long)
}
internal class ControllerEnergySessionAccess(private val controller:SessionController):EnergySessionAccess {
    override val view get()=controller.view
    override suspend fun session(scope:EnergyScope,forceRefresh:Boolean)=controller.communitySession(scope.session,forceRefresh)
    override suspend fun <T> withSession(ticket:ApiSession,scope:EnergyScope,block:suspend ()->T)=controller.withCommunitySession(ticket,scope.session,block)
    override suspend fun defer(ticket:ApiSession,scope:EnergyScope,until:Long)=controller.deferCommunity(ticket,scope.session,until)
}
