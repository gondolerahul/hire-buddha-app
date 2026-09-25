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

class InsightsTextTest {
    @Test
    fun `period comparison reads as a signed percentage`() {
        assertEquals("+18% vs last week", com.hirebuddha.dialer.ui.analytics.changeCaption(118, 100, 7))
        assertEquals("-50% vs yesterday", com.hirebuddha.dialer.ui.analytics.changeCaption(5, 10, 1))
        assertEquals("0% vs the previous 14 days", com.hirebuddha.dialer.ui.analytics.changeCaption(10, 10, 14))
        // Nothing to compare against: say nothing rather than "+∞%".
        assertEquals(null, com.hirebuddha.dialer.ui.analytics.changeCaption(10, 0, 7))
        assertEquals(null, com.hirebuddha.dialer.ui.analytics.changeCaption(10, null, 7))
    }
}
