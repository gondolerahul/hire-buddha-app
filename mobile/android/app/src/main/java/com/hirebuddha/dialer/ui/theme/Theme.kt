package com.hirebuddha.dialer.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

private val Indigo = Color(0xFF3D5AFE)
private val IndigoDark = Color(0xFF1E2A78)

object StatusColors {
    val positive = Color(0xFF1B8A5A)
    val warning = Color(0xFFB26A00)
    val negative = Color(0xFFC62828)
    val neutral = Color(0xFF5F6B7A)
}

private val Light = lightColorScheme(
    primary = Indigo,
    onPrimary = Color.White,
    primaryContainer = Color(0xFFDDE1FF),
    onPrimaryContainer = IndigoDark,
    secondary = Color(0xFF5A5D72),
    background = Color(0xFFF7F8FA),
    surface = Color.White,
    surfaceVariant = Color(0xFFEEF0F4),
    outline = Color(0xFFC5C9D2),
)

private val Dark = darkColorScheme(
    primary = Color(0xFFB9C3FF),
    onPrimary = IndigoDark,
    primaryContainer = Color(0xFF2B3AA8),
    onPrimaryContainer = Color(0xFFDDE1FF),
    background = Color(0xFF121318),
    surface = Color(0xFF1A1C22),
    surfaceVariant = Color(0xFF2A2D35),
)

private val AppTypography = Typography(
    headlineSmall = TextStyle(fontSize = 22.sp, fontWeight = FontWeight.SemiBold),
    titleMedium = TextStyle(fontSize = 16.sp, fontWeight = FontWeight.SemiBold),
    labelSmall = TextStyle(fontSize = 11.sp, fontWeight = FontWeight.Medium, letterSpacing = 0.4.sp),
)

@Composable
fun HireBuddhaTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = if (isSystemInDarkTheme()) Dark else Light,
        typography = AppTypography,
        content = content,
    )
}
