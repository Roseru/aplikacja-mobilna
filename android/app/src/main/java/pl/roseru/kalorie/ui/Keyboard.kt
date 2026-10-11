package pl.roseru.kalorie.ui

import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.runtime.Composable
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.platform.LocalSoftwareKeyboardController

/** Done finishes quantity entry; saving remains an explicit button action. */
@Composable internal fun doneKeyboardActions(): KeyboardActions {
    val focus = LocalFocusManager.current
    val keyboard = LocalSoftwareKeyboardController.current
    return KeyboardActions(onDone = {
        focus.clearFocus()
        keyboard?.hide()
    })
}
