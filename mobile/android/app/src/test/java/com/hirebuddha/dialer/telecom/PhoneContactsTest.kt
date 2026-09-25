package com.hirebuddha.dialer.telecom

import org.junit.Assert.assertEquals
import org.junit.Test

class PhoneContactsTest {
    private val book = listOf(
        PhoneContact("Asha Patil", "+91 98765 43210", "Mobile"),
        PhoneContact("Asha Patil", "098765 43210", "Home"),       // the same number saved twice
        PhoneContact("Ravi Kumar", "+91 88000 00037", "Work"),
    )

    @Test
    fun `the same number saved twice shows once`() {
        assertEquals(2, dedupe(book).size)
    }

    @Test
    fun `search matches names and digits`() {
        assertEquals(listOf("Ravi Kumar"), filterContacts(dedupe(book), "ravi").map { it.name })
        assertEquals(listOf("Ravi Kumar"), filterContacts(dedupe(book), "0003").map { it.name })
        assertEquals(2, filterContacts(dedupe(book), "").size)
    }

    @Test
    fun `typing on the keypad suggests contacts from three digits`() {
        assertEquals(emptyList<PhoneContact>(), matchByDigits(book, "98"))
        assertEquals("Asha Patil", matchByDigits(dedupe(book), "987").single().name)
    }
}
