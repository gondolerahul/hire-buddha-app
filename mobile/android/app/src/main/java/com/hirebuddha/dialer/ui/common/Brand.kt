package com.hirebuddha.dialer.ui.common

import android.provider.Settings
import androidx.annotation.DrawableRes
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.LocalContentColor
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.em
import androidx.compose.ui.unit.sp
import com.hirebuddha.dialer.R
import com.hirebuddha.dialer.ui.theme.BrandType
import com.hirebuddha.dialer.ui.theme.HbTheme

/*
 * Brand primitives — each one a direct translation of a rule in
 * buddha-cognitive-lab-design-system/project/styles.css, sized for touch.
 * Screen-level composites live in Components.kt.
 */

// ══════════════════════════════════════════════════════════════════════ ICONS

/** Lucide-style outline icon; the drawables are generated from the mockups' symbol set. */
@Composable
fun HbIcon(
    @DrawableRes id: Int,
    modifier: Modifier = Modifier,
    size: Dp = 20.dp,
    tint: Color = LocalContentColor.current,
    contentDescription: String? = null,
) = Icon(painterResource(id), contentDescription, modifier.size(size), tint)

// ═══════════════════════════════════════════════════════════════════════ TYPE

/** Uppercase mono kicker — the brand's only decorative label. Gold by default. */
@Composable
fun Eyebrow(text: String, modifier: Modifier = Modifier, color: Color = HbTheme.colors.accent) =
    Text(text.uppercase(), modifier, color = color, style = BrandType.eyebrow)

@Composable
fun MonoText(
    text: String,
    modifier: Modifier = Modifier,
    color: Color = HbTheme.colors.fgSubtle,
    style: TextStyle = BrandType.mono,
    maxLines: Int = 1,
) = Text(text, modifier, color = color, style = style, maxLines = maxLines, overflow = TextOverflow.Ellipsis)

/** A figure that should read as a number first: tabular, tight, display face. */
@Composable
fun Numeral(
    text: String,
    modifier: Modifier = Modifier,
    style: TextStyle = BrandType.numeral,
    color: Color = HbTheme.colors.fg,
    gradient: Boolean = false,
) = Text(
    text, modifier,
    color = if (gradient) Color.Unspecified else color,
    style = if (gradient) style.copy(brush = HbTheme.colors.goldGradient) else style,
)

@Composable
fun CardBody(text: String, modifier: Modifier = Modifier, color: Color = HbTheme.colors.fgMuted) =
    Text(text, modifier, color = color, style = MaterialTheme.typography.bodyMedium)

@Composable
fun CardCaption(text: String, modifier: Modifier = Modifier, color: Color = HbTheme.colors.fgSubtle) =
    Text(text, modifier, color = color, style = MaterialTheme.typography.bodySmall)

@Composable
fun MicroText(text: String, modifier: Modifier = Modifier, color: Color = HbTheme.colors.fgFaint) =
    Text(text, modifier, color = color, style = MaterialTheme.typography.labelSmall)

// ═══════════════════════════════════════════════════════════════════ SURFACES

/**
 * The default card: a barely-there vertical gradient, so a column of them reads as separate
 * objects on a flat black canvas without needing heavier borders.
 */
@Composable
fun HbCard(
    modifier: Modifier = Modifier,
    padding: Dp = 16.dp,
    onClick: (() -> Unit)? = null,
    border: Color = HbTheme.colors.border,
    content: @Composable ColumnScope.() -> Unit,
) {
    val shape = RoundedCornerShape(HbTheme.dims.rLg)
    Column(
        modifier
            .clip(shape)
            .background(Brush.verticalGradient(listOf(Color(0xFF16130F), Color(0xFF121010))))
            .border(1.dp, border, shape)
            .then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier)
            .padding(padding),
        content = content,
    )
}

/** Marks the one live, brand-owned thing on a screen. At most one per screen. */
@Composable
fun GoldCard(
    modifier: Modifier = Modifier,
    padding: Dp = 20.dp,
    onClick: (() -> Unit)? = null,
    content: @Composable ColumnScope.() -> Unit,
) {
    val c = HbTheme.colors
    val shape = RoundedCornerShape(HbTheme.dims.rLg)
    Column(
        modifier
            .clip(shape)
            .background(
                Brush.verticalGradient(
                    0f to c.accent.copy(alpha = 0.09f),
                    0.62f to c.surface,
                    1f to c.surface,
                )
            )
            .border(1.dp, c.borderGold, shape)
            .then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier)
            .padding(padding),
        content = content,
    )
}

/**
 * Liquid glass. Only for chrome floating over moving content — the tab bar, the in-call dock,
 * sticky action bars. `backdrop-filter` has no Compose equivalent, so this is the design
 * system's documented fallback: a heavy translucent tint plus the lens edge.
 */
@Composable
fun GlassSurface(
    modifier: Modifier = Modifier,
    shape: RoundedCornerShape = RoundedCornerShape(HbTheme.dims.r2Xl),
    gold: Boolean = false,
    content: @Composable BoxScope.() -> Unit,
) {
    val c = HbTheme.colors
    Box(
        modifier
            .shadow(22.dp, shape, ambientColor = Color.Black, spotColor = Color.Black)
            .clip(shape)
            .background(c.glassTintStrong)
            .background(
                Brush.linearGradient(
                    0.00f to Color.White.copy(alpha = 0.10f),
                    0.24f to Color.White.copy(alpha = 0.02f),
                    0.50f to Color.Transparent,
                )
            )
            .border(1.dp, if (gold) c.borderGold else c.glassBorder, shape),
        content = content,
    )
}

@Composable
fun Hairline(modifier: Modifier = Modifier, color: Color = HbTheme.colors.border) =
    Box(modifier.fillMaxWidth().height(1.dp).background(color))

// ════════════════════════════════════════════════════════════════════ BUTTONS

enum class HbButtonStyle { Primary, Hero, Secondary, Ghost, Danger, DangerQuiet, Glass, Positive }

/** [Large] is reserved for the primary action on a screen; [Small] for dense rows. */
enum class HbButtonSize(val height: Dp, val hPadding: Dp, val fontSize: androidx.compose.ui.unit.TextUnit) {
    Small(40.dp, 15.dp, 13.sp),
    Medium(48.dp, 22.dp, 14.5.sp),
    Large(56.dp, 24.dp, 16.sp),
}

@Composable
fun HbButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    style: HbButtonStyle = HbButtonStyle.Primary,
    size: HbButtonSize = HbButtonSize.Medium,
    @DrawableRes icon: Int? = null,
    enabled: Boolean = true,
    content: @Composable (RowScope.() -> Unit)? = null,
) {
    val c = HbTheme.colors
    val shape = RoundedCornerShape(percent = 50)
    val fill: Brush? = when {
        !enabled -> SolidColor(c.surface2)
        style == HbButtonStyle.Primary -> SolidColor(c.accent)
        style == HbButtonStyle.Hero -> c.goldMetallic
        style == HbButtonStyle.Danger -> SolidColor(c.negative)
        style == HbButtonStyle.DangerQuiet -> SolidColor(c.negativeQuiet)
        style == HbButtonStyle.Positive -> SolidColor(c.positive)
        style == HbButtonStyle.Glass -> SolidColor(c.glassTint)
        else -> null
    }
    val fg = when {
        !enabled -> c.fgDisabled
        style == HbButtonStyle.Primary || style == HbButtonStyle.Hero -> c.onAccent
        style == HbButtonStyle.Danger -> Color(0xFF20100B)
        style == HbButtonStyle.Positive -> Color(0xFF0F2015)
        style == HbButtonStyle.DangerQuiet -> c.negative
        style == HbButtonStyle.Ghost -> c.fgMuted
        else -> c.fg
    }
    val stroke: BorderStroke? = when {
        !enabled -> BorderStroke(1.dp, c.border)
        style == HbButtonStyle.Secondary -> BorderStroke(1.dp, c.borderStrong)
        style == HbButtonStyle.DangerQuiet -> BorderStroke(1.dp, c.negative.copy(alpha = 0.32f))
        style == HbButtonStyle.Glass -> BorderStroke(1.dp, c.glassBorder)
        else -> null
    }
    // A gold shadow marks a primary moment; nothing else in the app casts a coloured shadow.
    val glow = enabled && (style == HbButtonStyle.Primary || style == HbButtonStyle.Hero)

    Row(
        modifier
            .then(if (glow) Modifier.shadow(16.dp, shape, spotColor = c.accent, ambientColor = c.accent) else Modifier)
            .clip(shape)
            .then(if (fill != null) Modifier.background(fill, shape) else Modifier)
            .then(if (stroke != null) Modifier.border(stroke, shape) else Modifier)
            .clickable(enabled = enabled, onClick = onClick)
            .height(size.height)
            .padding(horizontal = size.hPadding),
        horizontalArrangement = Arrangement.spacedBy(9.dp, Alignment.CenterHorizontally),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        CompositionLocalProvider(LocalContentColor provides fg) {
            if (content != null) {
                content()
            } else {
                icon?.let { HbIcon(it, size = if (size == HbButtonSize.Small) 16.dp else 19.dp) }
                Text(
                    text,
                    style = MaterialTheme.typography.labelLarge.copy(fontSize = size.fontSize),
                    maxLines = 1,
                )
            }
        }
    }
}

/** Circular action — call/end buttons and app-bar affordances. */
@Composable
fun HbIconButton(
    @DrawableRes icon: Int,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    size: Dp = 44.dp,
    iconSize: Dp = 21.dp,
    tint: Color = HbTheme.colors.fgMuted,
    background: Color = Color.Transparent,
    contentDescription: String? = null,
) = Box(
    modifier
        .size(size)
        .clip(RoundedCornerShape(percent = 50))
        .background(background)
        .clickable(onClick = onClick),
    contentAlignment = Alignment.Center,
) { HbIcon(icon, size = iconSize, tint = tint, contentDescription = contentDescription) }

// ══════════════════════════════════════════════════════════════ CHIPS & PILLS

/** Status marker. Mono, uppercase, tiny — never competes with what it labels. */
@Composable
fun Pill(
    text: String,
    modifier: Modifier = Modifier,
    color: Color = HbTheme.colors.fgMuted,
    background: Color = Color(0x0FFFF0DC),
    dot: Boolean = false,
) = Row(
    modifier.clip(RoundedCornerShape(percent = 50)).background(background)
        .padding(horizontal = 9.dp, vertical = 4.dp),
    horizontalArrangement = Arrangement.spacedBy(5.dp),
    verticalAlignment = Alignment.CenterVertically,
) {
    if (dot) Box(Modifier.size(6.dp).clip(RoundedCornerShape(percent = 50)).background(color))
    Text(text.uppercase(), color = color, style = BrandType.eyebrow.copy(letterSpacing = 0.08.em))
}

@Composable
fun PositivePill(text: String, modifier: Modifier = Modifier, dot: Boolean = true) =
    Pill(text, modifier, HbTheme.colors.positive, HbTheme.colors.positiveQuiet, dot)

@Composable
fun NegativePill(text: String, modifier: Modifier = Modifier, dot: Boolean = true) =
    Pill(text, modifier, HbTheme.colors.negative, HbTheme.colors.negativeQuiet, dot)

@Composable
fun GoldPill(text: String, modifier: Modifier = Modifier, dot: Boolean = false) =
    Pill(text, modifier, HbTheme.colors.gold300, HbTheme.colors.accentQuiet, dot)

@Composable
fun HbChip(text: String, selected: Boolean, onClick: () -> Unit, modifier: Modifier = Modifier) {
    val c = HbTheme.colors
    val shape = RoundedCornerShape(percent = 50)
    Box(
        modifier
            .height(34.dp)
            .clip(shape)
            .background(if (selected) c.accentQuiet else c.surface3)
            .border(1.dp, if (selected) c.borderGold else c.border, shape)
            .clickable(onClick = onClick)
            .padding(horizontal = 14.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text,
            color = if (selected) c.gold300 else c.fgMuted,
            style = MaterialTheme.typography.labelMedium,
            maxLines = 1,
        )
    }
}

// ═════════════════════════════════════════════════════════════════ INDICATORS

/**
 * The dotted-B motif reused as the app's only spinner: gold dots lighting in sequence.
 * Renders a static ramp when the device has animations turned off.
 */
@Composable
fun BrandDots(
    modifier: Modifier = Modifier,
    count: Int = 5,
    dotSize: Dp = 5.dp,
    color: Color = HbTheme.colors.accent,
) {
    val animate = animationsEnabled()
    val phase by rememberInfiniteTransition(label = "dots").animateFloat(
        initialValue = 0f, targetValue = count.toFloat(),
        animationSpec = infiniteRepeatable(tween(1_100, easing = LinearEasing), RepeatMode.Restart),
        label = "phase",
    )
    Row(modifier, horizontalArrangement = Arrangement.spacedBy(dotSize)) {
        repeat(count) { i ->
            val alpha = if (animate) {
                (1f - ((i - phase + count) % count) / count).coerceIn(0.18f, 1f)
            } else {
                (1f - i * 0.16f).coerceAtLeast(0.2f)
            }
            Box(Modifier.size(dotSize).clip(RoundedCornerShape(percent = 50)).background(color.copy(alpha = alpha)))
        }
    }
}

/** Honour the system "remove animations" setting — a pulsing run screen is distracting. */
@Composable
fun animationsEnabled(): Boolean {
    val resolver = LocalContext.current.contentResolver
    return remember(resolver) {
        runCatching {
            Settings.Global.getFloat(resolver, Settings.Global.ANIMATOR_DURATION_SCALE, 1f) != 0f
        }.getOrDefault(true)
    }
}

/** Gold means volume or progress; sage means a completed good outcome. Nothing else. */
@Composable
fun HbProgress(
    fraction: Float,
    modifier: Modifier = Modifier,
    height: Dp = 5.dp,
    brush: Brush? = null,
) {
    val c = HbTheme.colors
    Box(
        modifier.fillMaxWidth().height(height)
            .clip(RoundedCornerShape(percent = 50))
            .background(Color(0x17FFF0DC))
    ) {
        Box(
            Modifier.fillMaxWidth(fraction.coerceIn(0f, 1f)).fillMaxHeight()
                .clip(RoundedCornerShape(percent = 50))
                .background(brush ?: c.goldGradient)
        )
    }
}

/** Progress ring — where the number matters as much as the proportion. */
@Composable
fun HbRing(
    fraction: Float,
    modifier: Modifier = Modifier,
    diameter: Dp = 84.dp,
    stroke: Dp = 6.dp,
    color: Color = HbTheme.colors.accent,
    track: Color = Color(0x17FFF0DC),
    content: @Composable () -> Unit = {},
) = Box(modifier.size(diameter), contentAlignment = Alignment.Center) {
    Box(
        Modifier.fillMaxSize().drawBehind {
            val w = stroke.toPx()
            val inset = w / 2
            val arcSize = Size(size.width - w, size.height - w)
            drawArc(track, 0f, 360f, false, Offset(inset, inset), arcSize, style = Stroke(w, cap = StrokeCap.Round))
            drawArc(
                color, -90f, 360f * fraction.coerceIn(0f, 1f), false,
                Offset(inset, inset), arcSize, style = Stroke(w, cap = StrokeCap.Round),
            )
        }
    )
    content()
}

// ════════════════════════════════════════════════════════════════ ATMOSPHERE

/** Radial gold glow behind hero content. Subtle: the canvas stays the brand. */
fun Modifier.goldGlow(
    radiusDp: Dp = 240.dp,
    center: Offset? = null,
    alpha: Float = 1f,
): Modifier = drawBehind {
    val r = radiusDp.toPx()
    val c = center ?: Offset(size.width / 2, size.height / 2)
    drawCircle(
        Brush.radialGradient(
            0.00f to Color(0xFFEDAB48).copy(alpha = 0.30f * alpha),
            0.42f to Color(0xFFEDAB48).copy(alpha = 0.08f * alpha),
            0.70f to Color.Transparent,
            center = c, radius = r,
        ),
        radius = r, center = c,
    )
}

/** The mark as a large, very low-opacity watermark bleeding off an edge. */
@Composable
fun MarkWatermark(modifier: Modifier = Modifier, height: Dp = 560.dp, alpha: Float = 0.055f) =
    Icon(
        painterResource(R.drawable.ic_logo_mark),
        contentDescription = null,
        modifier = modifier.height(height).width(height * 215.37f / 541.8f).alpha(alpha),
        tint = HbTheme.colors.accent,
    )

// ═══════════════════════════════════════════════════════════════════ LIST BITS

@Composable
fun Avatar(
    initials: String,
    modifier: Modifier = Modifier,
    size: Dp = 38.dp,
    gold: Boolean = false,
    shape: RoundedCornerShape = RoundedCornerShape(12.dp),
) {
    val c = HbTheme.colors
    Box(
        modifier.size(size).clip(shape)
            .background(if (gold) c.accentQuiet else c.surface3)
            .border(1.dp, if (gold) c.borderGold else c.border, shape),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            initials.take(2).uppercase(),
            color = if (gold) c.gold300 else c.fgMuted,
            style = MaterialTheme.typography.titleMedium.copy(fontSize = (size.value * 0.36f).sp),
        )
    }
}

/** Standard detail/settings row: icon, two lines, trailing slot; never under 48dp. */
@Composable
fun HbListRow(
    modifier: Modifier = Modifier,
    @DrawableRes icon: Int? = null,
    onClick: (() -> Unit)? = null,
    leading: @Composable (() -> Unit)? = null,
    trailing: @Composable (() -> Unit)? = null,
    content: @Composable ColumnScope.() -> Unit,
) = Row(
    modifier
        .fillMaxWidth()
        .then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier)
        .defaultMinSize(minHeight = HbTheme.dims.tap)
        .padding(vertical = 10.dp),
    horizontalArrangement = Arrangement.spacedBy(13.dp),
    verticalAlignment = Alignment.CenterVertically,
) {
    leading?.invoke()
    icon?.let { HbIcon(it, tint = HbTheme.colors.fgSubtle) }
    Column(Modifier.weight(1f), content = content)
    trailing?.invoke()
}

/** Section label above a group of cards. */
@Composable
fun SectionLabel(text: String, modifier: Modifier = Modifier, trailing: @Composable (() -> Unit)? = null) =
    Row(modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Eyebrow(text, Modifier.weight(1f), color = HbTheme.colors.fgSubtle)
        trailing?.invoke()
    }

// ═══════════════════════════════════════════════════════════════════ INPUTS

/**
 * Text field. Built on Material 3 so selection, IME, autofill and TalkBack all
 * come for free; only the skin is ours. The label sits above the box rather than
 * floating, which keeps a column of fields on a consistent baseline.
 */
@Composable
fun HbTextField(
    value: String,
    onValueChange: (String) -> Unit,
    modifier: Modifier = Modifier,
    label: String? = null,
    placeholder: String? = null,
    @DrawableRes leadingIcon: Int? = null,
    trailing: @Composable (() -> Unit)? = null,
    singleLine: Boolean = true,
    minLines: Int = 1,
    enabled: Boolean = true,
    isError: Boolean = false,
    keyboardOptions: androidx.compose.foundation.text.KeyboardOptions =
        androidx.compose.foundation.text.KeyboardOptions.Default,
    visualTransformation: androidx.compose.ui.text.input.VisualTransformation =
        androidx.compose.ui.text.input.VisualTransformation.None,
) {
    val c = HbTheme.colors
    Column(modifier) {
        label?.let {
            Text(
                it,
                color = c.fgSubtle,
                style = MaterialTheme.typography.labelMedium,
                modifier = Modifier.padding(bottom = 7.dp),
            )
        }
        androidx.compose.material3.OutlinedTextField(
            value = value,
            onValueChange = onValueChange,
            modifier = Modifier.fillMaxWidth(),
            enabled = enabled,
            isError = isError,
            singleLine = singleLine,
            minLines = minLines,
            textStyle = MaterialTheme.typography.bodyLarge.copy(color = c.fg),
            placeholder = placeholder?.let { { Text(it, color = c.fgDisabled, style = MaterialTheme.typography.bodyLarge) } },
            leadingIcon = leadingIcon?.let { { HbIcon(it, size = 18.dp, tint = c.fgSubtle) } },
            trailingIcon = trailing,
            shape = RoundedCornerShape(HbTheme.dims.rMd),
            keyboardOptions = keyboardOptions,
            visualTransformation = visualTransformation,
            colors = androidx.compose.material3.OutlinedTextFieldDefaults.colors(
                focusedContainerColor = c.surface2,
                unfocusedContainerColor = c.surface2,
                disabledContainerColor = c.surface,
                errorContainerColor = c.surface2,
                focusedBorderColor = c.borderGold,
                unfocusedBorderColor = c.border,
                errorBorderColor = c.negative,
                cursorColor = c.accent,
                focusedTextColor = c.fg,
                unfocusedTextColor = c.fg,
            ),
        )
    }
}

// ═════════════════════════════════════════════════════════════════ BRANDING

/** The Hire Buddha lockup (mark + wordmark). Aspect 728.69 : 396.08. */
@Composable
fun HireBuddhaLockup(modifier: Modifier = Modifier, width: Dp = 240.dp) =
    androidx.compose.foundation.Image(
        painter = painterResource(R.drawable.ic_logo_hire_buddha),
        contentDescription = "Hire Buddha",
        modifier = modifier.width(width).height(width * 396.08f / 728.69f),
    )

/** The parent-brand lockup. Signs the splash and settings; never the hero. */
@Composable
fun BuddhaLabLockup(modifier: Modifier = Modifier, width: Dp = 132.dp, alpha: Float = 0.9f) =
    androidx.compose.foundation.Image(
        painter = painterResource(R.drawable.ic_logo_bcl),
        contentDescription = "Buddha Cognitive Lab",
        modifier = modifier.width(width).height(width * 365.14f / 614.09f).alpha(alpha),
    )

/** The dotted-B mark on its own. Aspect 215.37 : 541.8 — tall and narrow. */
@Composable
fun BrandMark(modifier: Modifier = Modifier, height: Dp = 120.dp) =
    androidx.compose.foundation.Image(
        painter = painterResource(R.drawable.ic_logo_mark),
        contentDescription = null,
        modifier = modifier.height(height).width(height * 215.37f / 541.8f),
    )
