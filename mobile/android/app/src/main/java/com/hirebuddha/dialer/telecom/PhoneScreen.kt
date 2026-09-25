package com.hirebuddha.dialer.telecom

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.provider.ContactsContract
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import com.hirebuddha.dialer.R
import com.hirebuddha.dialer.ui.common.Avatar
import com.hirebuddha.dialer.ui.common.CardBody
import com.hirebuddha.dialer.ui.common.CardCaption
import com.hirebuddha.dialer.ui.common.ChipRow
import com.hirebuddha.dialer.ui.common.HbButton
import com.hirebuddha.dialer.ui.common.HbButtonSize
import com.hirebuddha.dialer.ui.common.HbButtonStyle
import com.hirebuddha.dialer.ui.common.HbCard
import com.hirebuddha.dialer.ui.common.HbChip
import com.hirebuddha.dialer.ui.common.HbIcon
import com.hirebuddha.dialer.ui.common.HbIconButton
import com.hirebuddha.dialer.ui.common.HbTextField
import com.hirebuddha.dialer.ui.common.MicroText
import com.hirebuddha.dialer.ui.common.MonoText
import com.hirebuddha.dialer.ui.common.initialsOf
import com.hirebuddha.dialer.ui.theme.HbTheme
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/** One number of one contact, as the Phone screen lists it. */
data class PhoneContact(val name: String, val number: String, val label: String?)

/**
 * The rep's own phone: HireBuddha is the default dialer, so personal calls go through it
 * too, with no agent anywhere near them. Keypad and Contacts, the two ways people dial.
 */
@Composable
fun PhoneScreen(
    initial: String,
    callingFrom: String?,
    runLive: Boolean,
    onClose: () -> Unit,
    onCall: (String) -> Unit,
) {
    val c = HbTheme.colors
    val context = LocalContext.current
    var tab by rememberSaveable { mutableStateOf("keypad") }
    var number by rememberSaveable { mutableStateOf(initial) }
    var granted by remember { mutableStateOf(hasContactsPermission(context)) }
    val askContacts = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted = it }
    var contacts by remember { mutableStateOf<List<PhoneContact>?>(null) }
    LaunchedEffect(granted) {
        contacts = if (granted) withContext(Dispatchers.IO) { loadContacts(context) } else null
    }

    Column(
        Modifier.fillMaxSize().statusBarsPadding().padding(horizontal = HbTheme.dims.gutter).navigationBarsPadding(),
    ) {
        Row(Modifier.fillMaxWidth().height(56.dp), verticalAlignment = Alignment.CenterVertically) {
            HbIconButton(R.drawable.ic_back, onClose, contentDescription = "Close")
            Text("Phone", Modifier.weight(1f), style = MaterialTheme.typography.titleLarge, color = c.fg)
        }
        ChipRow {
            HbChip("Keypad", tab == "keypad", onClick = { tab = "keypad" })
            HbChip("Contacts", tab == "contacts", onClick = { tab = "contacts" })
        }
        Spacer(Modifier.height(12.dp))
        if (runLive) {
            Row(
                Modifier.fillMaxWidth().clip(RoundedCornerShape(HbTheme.dims.rSm))
                    .background(c.accentQuiet).padding(12.dp),
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                HbIcon(R.drawable.ic_pause, size = 16.dp, tint = c.accent)
                CardCaption(
                    "A campaign run is live on this phone. Pause it before making a personal call.",
                    Modifier.weight(1f),
                )
            }
            Spacer(Modifier.height(12.dp))
        }

        when (tab) {
            "contacts" -> ContactsPane(
                contacts = contacts,
                granted = granted,
                enabled = !runLive,
                onAllow = { askContacts.launch(Manifest.permission.READ_CONTACTS) },
                onCall = onCall,
                modifier = Modifier.weight(1f),
            )
            else -> DialPad(
                number = number,
                onNumber = { number = it },
                callingFrom = callingFrom,
                enabled = !runLive,
                onCall = onCall,
                modifier = Modifier.weight(1f),
                suggestions = {
                    // Typing digits finds the contact: the fastest way back to someone.
                    val matches = remember(number, contacts) { matchByDigits(contacts, number).take(3) }
                    matches.forEach { contact ->
                        ContactRow(contact, enabled = !runLive) { number = contact.number }
                    }
                },
            )
        }
    }
}

@Composable
private fun ContactsPane(
    contacts: List<PhoneContact>?,
    granted: Boolean,
    enabled: Boolean,
    onAllow: () -> Unit,
    onCall: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    val c = HbTheme.colors
    var query by rememberSaveable { mutableStateOf("") }
    Column(modifier.fillMaxWidth()) {
        if (!granted) {
            HbCard(Modifier.fillMaxWidth()) {
                Text("Your contacts", style = MaterialTheme.typography.titleMedium, color = c.fg)
                Spacer(Modifier.height(6.dp))
                CardBody("Allow access to call the people saved on this phone. They stay on the phone; nothing is uploaded.")
                Spacer(Modifier.height(12.dp))
                HbButton("Allow contacts", onAllow, Modifier.fillMaxWidth(), HbButtonStyle.Primary, HbButtonSize.Small)
            }
            return@Column
        }
        HbTextField(query, { query = it }, placeholder = "Search name or number", leadingIcon = R.drawable.ic_search)
        Spacer(Modifier.height(10.dp))
        val shown = remember(contacts, query) { filterContacts(contacts.orEmpty(), query) }
        when {
            contacts == null -> MicroText("Loading contacts…")
            shown.isEmpty() -> MicroText(if (query.isBlank()) "No contacts on this phone." else "No one matches that.")
            else -> LazyColumn(Modifier.fillMaxWidth()) {
                items(shown, key = { it.name + it.number }) { contact ->
                    ContactRow(contact, enabled) { onCall(contact.number) }
                }
            }
        }
    }
}

@Composable
private fun ContactRow(contact: PhoneContact, enabled: Boolean, onTap: () -> Unit) {
    val c = HbTheme.colors
    Row(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(HbTheme.dims.rSm))
            .clickable(enabled = enabled, onClick = onTap).padding(vertical = 9.dp, horizontal = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Avatar(initialsOf(contact.name), size = 36.dp)
        Column(Modifier.weight(1f)) {
            Text(contact.name, style = MaterialTheme.typography.bodyLarge, color = c.fg, maxLines = 1, overflow = TextOverflow.Ellipsis)
            MonoText(listOfNotNull(contact.number, contact.label).joinToString(" · "))
        }
        Box(
            Modifier.size(36.dp).clip(CircleShape).background(if (enabled) c.accentQuiet else c.surface2),
            contentAlignment = Alignment.Center,
        ) { HbIcon(R.drawable.ic_phone, size = 16.dp, tint = if (enabled) c.accent else c.fgFaint) }
    }
}

private fun hasContactsPermission(context: Context) =
    ContextCompat.checkSelfPermission(context, Manifest.permission.READ_CONTACTS) == PackageManager.PERMISSION_GRANTED

/** Every phone number of every contact, sorted by name, one row per distinct number. */
internal fun loadContacts(context: Context): List<PhoneContact> = runCatching {
    val projection = arrayOf(
        ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME_PRIMARY,
        ContactsContract.CommonDataKinds.Phone.NUMBER,
        ContactsContract.CommonDataKinds.Phone.TYPE,
        ContactsContract.CommonDataKinds.Phone.LABEL,
    )
    val out = mutableListOf<PhoneContact>()
    context.contentResolver.query(
        ContactsContract.CommonDataKinds.Phone.CONTENT_URI, projection, null, null,
        "${ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME_PRIMARY} COLLATE NOCASE ASC",
    )?.use { cur ->
        while (cur.moveToNext()) {
            val name = cur.getString(0) ?: continue
            val number = cur.getString(1)?.trim() ?: continue
            val label = ContactsContract.CommonDataKinds.Phone.getTypeLabel(
                context.resources, cur.getInt(2), cur.getString(3),
            )?.toString()
            out += PhoneContact(name, number, label)
        }
    }
    dedupe(out)
}.getOrDefault(emptyList())

/** The same number saved twice ("+91 98…", "098…") shows once per contact. */
internal fun dedupe(contacts: List<PhoneContact>): List<PhoneContact> =
    contacts.distinctBy { it.name to it.number.filter(Char::isDigit).takeLast(10) }

internal fun filterContacts(contacts: List<PhoneContact>, query: String): List<PhoneContact> {
    val q = query.trim()
    if (q.isEmpty()) return contacts
    val digits = q.filter(Char::isDigit)
    return contacts.filter {
        it.name.contains(q, ignoreCase = true) || (digits.length >= 2 && it.number.filter(Char::isDigit).contains(digits))
    }
}

internal fun matchByDigits(contacts: List<PhoneContact>?, typed: String): List<PhoneContact> {
    val digits = typed.filter(Char::isDigit)
    if (contacts == null || digits.length < 3) return emptyList()
    return contacts.filter { it.number.filter(Char::isDigit).contains(digits) }
}
