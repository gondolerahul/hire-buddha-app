package com.hirebuddha.dialer.ui.common

import com.hirebuddha.dialer.ui.campaigns.statusBucket
import org.junit.Assert.assertEquals
import org.junit.Test

class CampaignTextTest {

    @Test
    fun `console agent names split into a name and what the agent does`() {
        // Both from live mobile campaigns.
        assertEquals("Seema" to "Sales Representative", agentNameAndRole("Seema - Sales Representative"))
        assertEquals("Bangla-Saathi" to "Information", agentNameAndRole("Bangla-Saathi - Information"))
        assertEquals("Ananya" to null, agentNameAndRole("Ananya"))
        assertEquals(null to null, agentNameAndRole(null))
    }

    @Test
    fun `draft and pending campaigns are both not started`() {
        assertEquals("not_started", statusBucket("draft"))
        assertEquals("not_started", statusBucket("pending"))
        assertEquals("running", statusBucket("running"))
        assertEquals("completed", statusBucket("completed"))
    }

    @Test
    fun `created dates are shown as day and month`() {
        assertEquals("14 Sep", shortDate("2026-09-14T10:02:11.123"))
        assertEquals(null, shortDate(null))
    }
}
