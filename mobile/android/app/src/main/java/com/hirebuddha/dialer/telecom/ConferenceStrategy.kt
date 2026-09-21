package com.hirebuddha.dialer.telecom

/**
 * How to ask Android Telecom to merge two calls, and how to tell that it worked.
 *
 * Pure logic so the rules can be unit-tested without a device — the device-specific
 * behaviour here is exactly what broke merging on the first pilot build:
 *
 *  * `Call.conference(other)` is what merges two separate calls. `mergeConference()`
 *    only does something when a conference already exists, so preferring it (because
 *    `CAPABILITY_MERGE_CONFERENCE` was set) silently did nothing.
 *  * After a successful merge some stacks keep both calls as children of a new
 *    conference call; others (common on VoLTE/IMS) remove them and leave only the
 *    conference. Both shapes mean "merged".
 */
object ConferenceStrategy {

    enum class Action {
        /** `a.conference(b)` — merge two independent calls. */
        CONFERENCE,
        /** `parent.mergeConference()` — both legs are already inside a conference container. */
        MERGE_CONFERENCE,
        /** Nothing to do: telecom already reports them merged. */
        ALREADY_MERGED,
        /** One of the calls is gone. */
        IMPOSSIBLE,
    }

    data class CallFacts(
        val id: String,
        val exists: Boolean,
        val state: CallState,
        val parentId: String? = null,
        val isConferenceable: Boolean = false,
        val canMergeConference: Boolean = false,
    )

    fun choose(a: CallFacts, b: CallFacts): Action = when {
        !a.exists || !b.exists -> Action.IMPOSSIBLE
        a.state == CallState.DISCONNECTED || b.state == CallState.DISCONNECTED -> Action.IMPOSSIBLE
        a.parentId != null && a.parentId == b.parentId -> Action.ALREADY_MERGED
        // Both already sit in conference containers (CDMA / some IMS stacks): merge them.
        a.parentId != null && b.parentId != null -> Action.MERGE_CONFERENCE
        // The normal path: two separate calls. conference() works even when the
        // conferenceable list has not been published yet, so never gate on it.
        else -> Action.CONFERENCE
    }

    /**
     * Returns the id of the live conference when [leadCall] and [aiCall] are merged.
     *
     * Accepts every shape a merge can take: shared parent, a conference listing either
     * leg as a child, or an active conference while the original legs have disappeared
     * (the stack replaced them).
     */
    fun mergedConferenceId(calls: List<CallSnapshot>, leadCall: String, aiCall: String): String? {
        val legs = setOf(leadCall, aiCall)
        val lead = calls.firstOrNull { it.id == leadCall }
        val ai = calls.firstOrNull { it.id == aiCall }
        if (lead?.parentId != null && lead.parentId == ai?.parentId) return lead.parentId

        val conference = calls.firstOrNull {
            it.isConference && it.state in setOf(CallState.ACTIVE, CallState.HOLDING)
        } ?: return null
        if (conference.childIds.any { it in legs }) return conference.id

        // Legs replaced by the conference: neither is live any more, but a conference is.
        val legStillLive = calls.any { it.id in legs && it.state != CallState.DISCONNECTED }
        return if (!legStillLive) conference.id else null
    }
}
