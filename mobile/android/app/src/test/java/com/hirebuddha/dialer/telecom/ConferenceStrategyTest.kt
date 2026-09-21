package com.hirebuddha.dialer.telecom

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

private fun facts(
    id: String,
    state: CallState = CallState.ACTIVE,
    parentId: String? = null,
    conferenceable: Boolean = false,
    canMerge: Boolean = false,
    exists: Boolean = true,
) = ConferenceStrategy.CallFacts(id, exists, state, parentId, conferenceable, canMerge)

private fun snapshot(
    id: String,
    state: CallState = CallState.ACTIVE,
    parentId: String? = null,
    isConference: Boolean = false,
    childIds: List<String> = emptyList(),
) = CallSnapshot(id, null, state, outgoing = true, isConference = isConference, parentId = parentId, childIds = childIds)

class ConferenceStrategyTest {

    // ── choosing the request ────────────────────────────────────────────

    @Test
    fun `two separate calls are merged with conference()`() {
        val action = ConferenceStrategy.choose(facts("lead"), facts("ai", state = CallState.HOLDING))
        assertEquals(ConferenceStrategy.Action.CONFERENCE, action)
    }

    @Test
    fun `CAPABILITY_MERGE_CONFERENCE alone must not pick mergeConference`() {
        // The original bug: mergeConference() does nothing when no conference exists,
        // so the calls were never merged and the attempt timed out.
        val action = ConferenceStrategy.choose(
            facts("lead", canMerge = true),
            facts("ai", state = CallState.HOLDING, canMerge = true),
        )
        assertEquals(ConferenceStrategy.Action.CONFERENCE, action)
    }

    @Test
    fun `calls already in conference containers use mergeConference`() {
        val action = ConferenceStrategy.choose(
            facts("lead", parentId = "confA"),
            facts("ai", parentId = "confB"),
        )
        assertEquals(ConferenceStrategy.Action.MERGE_CONFERENCE, action)
    }

    @Test
    fun `sharing a parent means the work is done`() {
        val action = ConferenceStrategy.choose(facts("lead", parentId = "conf"), facts("ai", parentId = "conf"))
        assertEquals(ConferenceStrategy.Action.ALREADY_MERGED, action)
    }

    @Test
    fun `a disconnected or missing call cannot be merged`() {
        assertEquals(
            ConferenceStrategy.Action.IMPOSSIBLE,
            ConferenceStrategy.choose(facts("lead", state = CallState.DISCONNECTED), facts("ai")),
        )
        assertEquals(
            ConferenceStrategy.Action.IMPOSSIBLE,
            ConferenceStrategy.choose(facts("lead"), facts("ai", exists = false)),
        )
    }

    // ── recognising a merged call ───────────────────────────────────────

    @Test
    fun `shared parent is merged`() {
        val calls = listOf(
            snapshot("lead", parentId = "conf"),
            snapshot("ai", parentId = "conf"),
            snapshot("conf", isConference = true, childIds = listOf("lead", "ai")),
        )
        assertEquals("conf", ConferenceStrategy.mergedConferenceId(calls, "lead", "ai"))
    }

    @Test
    fun `conference listing one leg as a child is merged`() {
        val calls = listOf(
            snapshot("lead"),
            snapshot("ai", state = CallState.HOLDING),
            snapshot("conf", isConference = true, childIds = listOf("lead")),
        )
        assertEquals("conf", ConferenceStrategy.mergedConferenceId(calls, "lead", "ai"))
    }

    @Test
    fun `conference replacing both legs is merged`() {
        // VoLTE shape: the original calls are gone, only the conference remains.
        val calls = listOf(
            snapshot("lead", state = CallState.DISCONNECTED),
            snapshot("ai", state = CallState.DISCONNECTED),
            snapshot("conf", isConference = true),
        )
        assertEquals("conf", ConferenceStrategy.mergedConferenceId(calls, "lead", "ai"))
    }

    @Test
    fun `two separate live calls are not merged`() {
        val calls = listOf(snapshot("lead"), snapshot("ai", state = CallState.HOLDING))
        assertNull(ConferenceStrategy.mergedConferenceId(calls, "lead", "ai"))
    }

    @Test
    fun `an unrelated conference while our legs are still separate is not a merge`() {
        val calls = listOf(
            snapshot("lead"),
            snapshot("ai", state = CallState.HOLDING),
            snapshot("conf", isConference = true, childIds = listOf("other1", "other2")),
        )
        assertNull(ConferenceStrategy.mergedConferenceId(calls, "lead", "ai"))
    }
}
