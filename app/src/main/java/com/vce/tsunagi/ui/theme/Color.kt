package com.vce.tsunagi.ui.theme

import androidx.compose.ui.graphics.Color

/**
 * Tsunagi Core palette, shared with the web dashboard so both surfaces read as
 * one product. Values come from tmp/frontend/tsunagi_core/DESIGN.md.
 */

// Indigo: primary actions and active states.
val TsunagiPrimary = Color(0xFFC0C1FF)
val TsunagiOnPrimary = Color(0xFF1000A9)
val TsunagiPrimaryContainer = Color(0xFF8083FF)
val TsunagiOnPrimaryContainer = Color(0xFF0D0096)

val TsunagiSecondary = Color(0xFFB9C8DE)
val TsunagiOnSecondary = Color(0xFF233143)
val TsunagiSecondaryContainer = Color(0xFF39485A)
val TsunagiOnSecondaryContainer = Color(0xFFA7B6CC)

// Emerald: reserved for "connected" and "synced" states.
val TsunagiTertiary = Color(0xFF4EDEA3)
val TsunagiOnTertiary = Color(0xFF003824)
val TsunagiTertiaryContainer = Color(0xFF00885D)
val TsunagiOnTertiaryContainer = Color(0xFF000703)

val TsunagiError = Color(0xFFFFB4AB)
val TsunagiOnError = Color(0xFF690005)
val TsunagiErrorContainer = Color(0xFF93000A)
val TsunagiOnErrorContainer = Color(0xFFFFDAD6)

// Near-black neutrals; depth comes from tonal layering, not shadows.
val TsunagiBackground = Color(0xFF131315)
val TsunagiOnBackground = Color(0xFFE5E1E4)
val TsunagiSurface = Color(0xFF131315)
val TsunagiOnSurface = Color(0xFFE5E1E4)
val TsunagiSurfaceVariant = Color(0xFF353437)
val TsunagiOnSurfaceVariant = Color(0xFFC7C4D7)
val TsunagiSurfaceContainerLow = Color(0xFF1C1B1D)
val TsunagiSurfaceContainer = Color(0xFF201F22)
val TsunagiSurfaceContainerHigh = Color(0xFF2A2A2C)
val TsunagiOutline = Color(0xFF908FA0)
val TsunagiOutlineVariant = Color(0xFF464554)

// Amber: pending or rate-limited, per the design system's functional accents.
val TsunagiWarning = Color(0xFFFFCC80)
