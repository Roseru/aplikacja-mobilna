package pl.roseru.kalorie.ui

import androidx.compose.foundation.layout.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.CloudOff
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import pl.roseru.kalorie.core.network.NetworkAccessState

/** For online screens; the diary remains usable without this notice taking its space. */
@Composable fun NetworkModeNotice(state:NetworkAccessState,onSettings:()->Unit) {
    if(state is NetworkAccessState.Allowed)return
    Surface(color=MaterialTheme.colorScheme.surfaceContainerHigh) {
        Row(Modifier.fillMaxWidth().statusBarsPadding().padding(horizontal=16.dp,vertical=4.dp).testTag("network-mode-notice"),
            verticalAlignment=Alignment.CenterVertically,horizontalArrangement=Arrangement.spacedBy(8.dp)) {
            Icon(Icons.Outlined.CloudOff,contentDescription=null)
            Text(if(state==NetworkAccessState.Blocked)"Tryb poligonowy · bez połączeń" else "Połączenia aplikacji wstrzymane",
                modifier=Modifier.weight(1f),style=MaterialTheme.typography.bodySmall)
            TextButton(onClick=onSettings,modifier=Modifier.testTag("network-mode-settings")){Text("Ustawienia")}
        }
    }
}
