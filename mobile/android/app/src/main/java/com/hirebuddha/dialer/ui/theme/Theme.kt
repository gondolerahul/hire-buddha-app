package com.hirebuddha.dialer.ui.theme

import android.app.Activity
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.SideEffect
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalView
import androidx.core.view.WindowCompat

/**
 * Shorthand for the brand tokens: `Brand.accent`, `Dims.gutter`.
 * Material 3's scheme carries what it has slots for; [BrandColors] carries the rest.
 */
object HbTheme {
    val colors: BrandColors
        @Composable get() = LocalBrand.current
    val dims: BrandDims
        @Composable get() = LocalDims.current
}

private val brand = BrandColors()

/**
 * Every Material 3 role is mapped onto a brand token, so stock components
 * (`Card`, `TextField`, `Slider`, `NavigationBar`) land on-brand without being rewritten.
 */
private val BrandScheme = darkColorScheme(
    primary = brand.accent,
    onPrimary = brand.onAccent,
    primaryContainer = Color(0xFF2A2116),
    onPrimaryContainer = brand.gold300,
    inversePrimary = brand.gold300,

    secondary = brand.fgMuted,
    onSecondary = brand.bg,
    secondaryContainer = brand.surface3,
    onSecondaryContainer = brand.fg,

    tertiary = brand.gold300,
    onTertiary = brand.onAccent,
    tertiaryContainer = Color(0xFF2A2116),
    onTertiaryContainer = brand.gold300,

    background = brand.bg,
    onBackground = brand.fg,
    surface = brand.surface,
    onSurface = brand.fg,
    surfaceVariant = brand.surface2,
    onSurfaceVariant = brand.fgMuted,
    surfaceTint = brand.accent,
    inverseSurface = brand.fg,
    inverseOnSurface = brand.bg,

    // Card / sheet / menu containers all step through the warm charcoals.
    surfaceContainerLowest = brand.bg,
    surfaceContainerLow = Color(0xFF100E0C),
    surfaceContainer = brand.surface,
    surfaceContainerHigh = brand.surface2,
    surfaceContainerHighest = brand.surface2,
    surfaceBright = brand.surface3,
    surfaceDim = brand.bg,

    error = brand.negative,
    onError = Color(0xFF20100B),
    errorContainer = Color(0xFF3A1F18),
    onErrorContainer = Color(0xFFF0B4A5),

    outline = Color(0xFF4A443E),
    outlineVariant = Color(0xFF2A2522),
    scrim = Color(0xFF000000),
)

/** Retained so semantic colour call-sites keep reading the same way. */
object StatusColors {
    val positive = brand.positive
    val warning = brand.accent
    val negative = brand.negative
    val neutral = brand.fgSubtle
}

@Composable
fun HireBuddhaTheme(
    @Suppress("UNUSED_PARAMETER") darkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit,
) {
    // Deliberately not system-dependent: the canvas is the brand, and a sales rep in
    // sunlight is better served by one tuned dark theme than two half-tuned ones.
    val view = LocalView.current
    if (!view.isInEditMode) {
        SideEffect {
            (LocalContextActivity(view))?.let { activity ->
                WindowCompat.getInsetsController(activity.window, view).apply {
                    isAppearanceLightStatusBars = false
                    isAppearanceLightNavigationBars = false
                }
            }
        }
    }
    CompositionLocalProvider(
        LocalBrand provides brand,
        LocalDims provides BrandDims(),
    ) {
        MaterialTheme(colorScheme = BrandScheme, typography = BrandTypography, content = content)
    }
}

private fun LocalContextActivity(view: android.view.View): Activity? {
    var ctx = view.context
    while (ctx is android.content.ContextWrapper) {
        if (ctx is Activity) return ctx
        ctx = ctx.baseContext
    }
    return null
}

/** Convenience for composables that only need the context's activity. */
@Composable
fun currentActivity(): Activity? = LocalContextActivity(LocalView.current) ?: (LocalContext.current as? Activity)
