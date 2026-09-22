package com.hirebuddha.dialer.ui.splash

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.unit.dp
import com.hirebuddha.dialer.ui.common.BrandDots
import com.hirebuddha.dialer.ui.common.BuddhaLabLockup
import com.hirebuddha.dialer.ui.common.Eyebrow
import com.hirebuddha.dialer.ui.common.HireBuddhaLockup
import com.hirebuddha.dialer.ui.common.MarkWatermark
import com.hirebuddha.dialer.ui.common.MicroText
import com.hirebuddha.dialer.ui.common.goldGlow
import com.hirebuddha.dialer.ui.theme.HbTheme

/**
 * The in-app splash (docs 11, screen 01).
 *
 * Shown while the refresh token is checked — work that already happened, just against a
 * blank surface. For an APK a rep sideloads from a link this is the whole first
 * impression, so both brands appear in the right order: Hire Buddha owns the centre,
 * Buddha Cognitive Lab signs the bottom.
 *
 * The system splash (`Theme.HireBuddha.Splash`, the same mark on the same canvas) hands
 * off to this one, so there is no visible seam.
 */
@Composable
fun SplashScreen(modifier: Modifier = Modifier) {
    val c = HbTheme.colors
    Box(modifier.fillMaxSize()) {
        Box(Modifier.fillMaxSize().goldGlow(radiusDp = 260.dp, center = Offset(170f, 900f)))
        MarkWatermark(
            Modifier.align(Alignment.CenterEnd).offset(x = 70.dp),
            height = 580.dp,
            alpha = 0.05f,
        )
        Column(
            Modifier.fillMaxSize().padding(horizontal = 24.dp),
            verticalArrangement = Arrangement.Top,
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Spacer(Modifier.weight(1f))
            HireBuddhaLockup(width = 244.dp)
            Spacer(Modifier.height(20.dp))
            Eyebrow("Conference dialer", color = c.fgSubtle)
            Spacer(Modifier.height(32.dp))
            // The dotted-B motif doubles as the app's only loading indicator.
            BrandDots(dotSize = 7.dp)
            Spacer(Modifier.weight(1f))
            Signature()
            Spacer(Modifier.height(30.dp))
        }
    }
}

/** "A product of Buddha Cognitive Lab" — the parent brand, quietly. */
@Composable
fun Signature(modifier: Modifier = Modifier) = Column(
    modifier,
    verticalArrangement = Arrangement.spacedBy(10.dp),
    horizontalAlignment = Alignment.CenterHorizontally,
) {
    MicroText("A product of")
    BuddhaLabLockup(width = 138.dp)
    Eyebrow("Towards digital enlightenment", color = HbTheme.colors.fgDisabled)
}
