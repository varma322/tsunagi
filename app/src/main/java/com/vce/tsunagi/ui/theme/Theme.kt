package com.vce.tsunagi.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable

/**
 * Tsunagi Core is a dark-only design system, and dynamic color would replace
 * the indigo/emerald accents that carry meaning here (emerald means synced),
 * so neither light mode nor dynamic color is offered.
 */
private val TsunagiColorScheme = darkColorScheme(
    primary = TsunagiPrimary,
    onPrimary = TsunagiOnPrimary,
    primaryContainer = TsunagiPrimaryContainer,
    onPrimaryContainer = TsunagiOnPrimaryContainer,
    secondary = TsunagiSecondary,
    onSecondary = TsunagiOnSecondary,
    secondaryContainer = TsunagiSecondaryContainer,
    onSecondaryContainer = TsunagiOnSecondaryContainer,
    tertiary = TsunagiTertiary,
    onTertiary = TsunagiOnTertiary,
    tertiaryContainer = TsunagiTertiaryContainer,
    onTertiaryContainer = TsunagiOnTertiaryContainer,
    error = TsunagiError,
    onError = TsunagiOnError,
    errorContainer = TsunagiErrorContainer,
    onErrorContainer = TsunagiOnErrorContainer,
    background = TsunagiBackground,
    onBackground = TsunagiOnBackground,
    surface = TsunagiSurface,
    onSurface = TsunagiOnSurface,
    surfaceVariant = TsunagiSurfaceVariant,
    onSurfaceVariant = TsunagiOnSurfaceVariant,
    surfaceContainerLow = TsunagiSurfaceContainerLow,
    surfaceContainer = TsunagiSurfaceContainer,
    surfaceContainerHigh = TsunagiSurfaceContainerHigh,
    outline = TsunagiOutline,
    outlineVariant = TsunagiOutlineVariant,
)

@Composable
fun TsunagiTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = TsunagiColorScheme,
        typography = Typography,
        content = content,
    )
}
