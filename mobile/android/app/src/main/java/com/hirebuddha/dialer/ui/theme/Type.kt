package com.hirebuddha.dialer.ui.theme

import androidx.compose.material3.Typography
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.em
import androidx.compose.ui.unit.sp
import com.hirebuddha.dialer.R

/**
 * Space Grotesk (display) · Hanken Grotesk (body/UI) · JetBrains Mono (data).
 *
 * These are the design system's documented substitutes, not the brand's real faces —
 * swap the files in `res/font` when the originals arrive. The wordmark needs no font at all: the
 * lockups ship as vector drawables (`ic_logo_*`).
 */
val SpaceGrotesk = FontFamily(
    Font(R.font.space_grotesk_medium, FontWeight.Medium),
    Font(R.font.space_grotesk_semibold, FontWeight.SemiBold),
    Font(R.font.space_grotesk_bold, FontWeight.Bold),
)

val HankenGrotesk = FontFamily(
    Font(R.font.hanken_grotesk_regular, FontWeight.Normal),
    Font(R.font.hanken_grotesk_medium, FontWeight.Medium),
    Font(R.font.hanken_grotesk_semibold, FontWeight.SemiBold),
    Font(R.font.hanken_grotesk_bold, FontWeight.Bold),
)

val JetBrainsMono = FontFamily(
    Font(R.font.jetbrains_mono_regular, FontWeight.Normal),
    Font(R.font.jetbrains_mono_medium, FontWeight.Medium),
)

/**
 * The mobile ramp. The desktop system's 48–84px display steps are not used; the largest
 * thing on a phone screen is a figure, and figures cap at 34sp.
 */
val BrandTypography = Typography(
    // Screen titles — Space Grotesk, tight tracking, balanced wrap
    headlineLarge = TextStyle(
        fontFamily = SpaceGrotesk, fontWeight = FontWeight.SemiBold,
        fontSize = 34.sp, lineHeight = 38.sp, letterSpacing = (-0.03).em,
    ),
    headlineMedium = TextStyle(
        fontFamily = SpaceGrotesk, fontWeight = FontWeight.SemiBold,
        fontSize = 27.sp, lineHeight = 31.sp, letterSpacing = (-0.025).em,
    ),
    headlineSmall = TextStyle(
        fontFamily = SpaceGrotesk, fontWeight = FontWeight.SemiBold,
        fontSize = 21.sp, lineHeight = 25.sp, letterSpacing = (-0.02).em,
    ),
    // Section / card headers
    titleLarge = TextStyle(
        fontFamily = SpaceGrotesk, fontWeight = FontWeight.SemiBold,
        fontSize = 17.sp, lineHeight = 22.sp, letterSpacing = (-0.015).em,
    ),
    titleMedium = TextStyle(
        fontFamily = HankenGrotesk, fontWeight = FontWeight.SemiBold,
        fontSize = 15.sp, lineHeight = 20.sp, letterSpacing = (-0.01).em,
    ),
    titleSmall = TextStyle(
        fontFamily = HankenGrotesk, fontWeight = FontWeight.SemiBold,
        fontSize = 13.5.sp, lineHeight = 18.sp,
    ),
    // Reading text
    bodyLarge = TextStyle(fontFamily = HankenGrotesk, fontSize = 15.sp, lineHeight = 22.sp),
    bodyMedium = TextStyle(fontFamily = HankenGrotesk, fontSize = 14.sp, lineHeight = 21.sp),
    bodySmall = TextStyle(fontFamily = HankenGrotesk, fontSize = 12.5.sp, lineHeight = 18.sp),
    // Controls and micro-copy
    labelLarge = TextStyle(
        fontFamily = HankenGrotesk, fontWeight = FontWeight.SemiBold,
        fontSize = 14.5.sp, lineHeight = 18.sp,
    ),
    labelMedium = TextStyle(fontFamily = HankenGrotesk, fontWeight = FontWeight.Medium, fontSize = 12.sp, lineHeight = 16.sp),
    labelSmall = TextStyle(fontFamily = HankenGrotesk, fontSize = 11.sp, lineHeight = 15.sp),
)

/** Type roles Material 3 has no slot for. */
object BrandType {
    /** Uppercase mono kicker, wide tracking. Always gold or subtle, never body-coloured. */
    val eyebrow = TextStyle(
        fontFamily = JetBrainsMono, fontWeight = FontWeight.Medium,
        fontSize = 10.sp, lineHeight = 14.sp, letterSpacing = 0.16.em,
    )

    /** Timers, phone numbers, IDs, counts — anything that must not jitter as it ticks. */
    val mono = TextStyle(
        fontFamily = JetBrainsMono, fontSize = 11.5.sp, lineHeight = 16.sp,
        fontFeatureSettings = "tnum",
    )
    val monoBody = mono.copy(fontSize = 13.sp, lineHeight = 18.sp)

    /** Big figures. Tabular so a counter does not shuffle its neighbours. */
    val numeral = TextStyle(
        fontFamily = SpaceGrotesk, fontWeight = FontWeight.SemiBold,
        fontSize = 30.sp, lineHeight = 32.sp, letterSpacing = (-0.03).em,
        fontFeatureSettings = "tnum", textAlign = TextAlign.Start,
    )
    val numeralSmall = numeral.copy(fontSize = 22.sp, lineHeight = 24.sp)
    val numeralLarge = numeral.copy(fontSize = 34.sp, lineHeight = 36.sp)
}
