package com.hirebuddha.dialer.ui.theme

import androidx.compose.runtime.Immutable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

/**
 * Buddha Cognitive Lab design tokens.
 *
 * Source of truth: `buddha-cognitive-lab-design-system/project/colors_and_type.css`.
 * Values are copied verbatim except the two lowest neutral steps — see [BrandColors.fgSubtle].
 * The rationale for every choice is in docs/mobile-dialer-app/11-ux-and-visual-design.md §5.
 */
@Immutable
data class BrandColors(
    // ── Gold: the only brand hue, sampled from the logo gradient ─────────────
    val accent: Color = Color(0xFFEDAB48),
    val accentHover: Color = Color(0xFFF4B65C),
    val accentPress: Color = Color(0xFFD2923A),
    /** Low-alpha gold wash behind active/brand surfaces. */
    val accentQuiet: Color = Color(0x1FEDAB48),
    val gold300: Color = Color(0xFFFDC871),
    /** Near-black text that sits on a gold fill. */
    val onAccent: Color = Color(0xFF2A1D08),

    // ── Warm near-black canvas; depth comes from surface steps, not colour ───
    val bg: Color = Color(0xFF0A0908),
    val surface: Color = Color(0xFF141210),
    val surface2: Color = Color(0xFF1C1916),
    val surface3: Color = Color(0xFF241F1B),

    // ── Text ─────────────────────────────────────────────────────────────────
    val fg: Color = Color(0xFFF6F1E9),
    val fgMuted: Color = Color(0xFFB3AAA0),
    /**
     * Shifted one step lighter than the desktop system (`#7c746b`, 4.06:1 on [surface]).
     * At the 11–13sp sizes a phone carries — outdoors, one-handed — the desktop value
     * fails WCAG AA. `#968d82` is 5.72:1; the four-level hierarchy is unchanged.
     */
    val fgSubtle: Color = Color(0xFF968D82),
    /** Was `#544d46` (2.25:1). `#8b8277` is 4.95:1 — see [fgSubtle]. */
    val fgFaint: Color = Color(0xFF8B8277),
    /** The old faint step, kept for things that never carry information. */
    val fgDisabled: Color = Color(0xFF544D46),

    // ── Lines ────────────────────────────────────────────────────────────────
    val border: Color = Color(0x14FFF0DC),
    val borderStrong: Color = Color(0x29FFF0DC),
    val borderGold: Color = Color(0x66EDAB48),

    // ── Semantic: deliberately desaturated so they never compete with gold ───
    val positive: Color = Color(0xFF7BB487),
    val negative: Color = Color(0xFFD4664F),
    val positiveQuiet: Color = Color(0x247BB487),
    val negativeQuiet: Color = Color(0x24D4664F),

    // ── Glass (the liquid-glass material, used only over moving content) ─────
    val glassTint: Color = Color(0x8C1A1714),
    val glassTintStrong: Color = Color(0xAD141110),
    val glassBorder: Color = Color(0x29FFF8EE),
) {
    val warning: Color get() = accent

    /** Reserved for the mark, key figures, hairlines and primary buttons. */
    val goldGradient: Brush
        get() = Brush.linearGradient(
            0.00f to Color(0xFFFDC871), 0.32f to Color(0xFFEDAB48),
            0.58f to Color(0xFFFFEFD8), 1.00f to Color(0xFFFDC871),
        )

    /** Richer metallic plate. Only two buttons in the app use it: Start run, Resume. */
    val goldMetallic: Brush
        get() = Brush.linearGradient(
            0.00f to Color(0xFFFFF1CF), 0.18f to Color(0xFFF6C96F), 0.42f to Color(0xFFE3A23D),
            0.56f to Color(0xFFB9791F), 0.78f to Color(0xFFF0BD5E), 1.00f to Color(0xFFFFE7B0),
        )

    /** Soft focal glow laid behind hero content. */
    fun glow(radius: Float): Brush = Brush.radialGradient(
        0.00f to Color(0x4DEDAB48), 0.42f to Color(0x14EDAB48), 0.70f to Color.Transparent,
        radius = radius,
    )
}

/** 4px grid, plus the two mobile-specific measures. */
@Immutable
data class BrandDims(
    val gutter: Dp = 20.dp,
    /** Android's minimum touch target; every interactive row honours it. */
    val tap: Dp = 48.dp,
    val tapLarge: Dp = 56.dp,
    val s1: Dp = 4.dp, val s2: Dp = 8.dp, val s3: Dp = 12.dp, val s4: Dp = 16.dp,
    val s5: Dp = 24.dp, val s6: Dp = 32.dp, val s7: Dp = 48.dp,
    val rXs: Dp = 4.dp, val rSm: Dp = 7.dp, val rMd: Dp = 11.dp,
    val rLg: Dp = 16.dp, val rXl: Dp = 22.dp, val r2Xl: Dp = 30.dp,
)

val LocalBrand = staticCompositionLocalOf { BrandColors() }
val LocalDims = staticCompositionLocalOf { BrandDims() }
