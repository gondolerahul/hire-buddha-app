package com.hirebuddha.dialer.ui.calls

import com.hirebuddha.dialer.data.api.VoiceSessionDto
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class CallDetailTextTest {

    private fun session(id: String, file: String?) =
        VoiceSessionDto(id = id, status = "ended", recordingUrl = "/api/v1/artifacts/x/download", recordingFileName = file)

    @Test
    fun `next action markdown from the model is reduced to its words`() {
        // Verbatim from a live session on 2026-09-22.
        assertEquals(
            "Agent to call Saurabh tomorrow after 5 PM.",
            plainText("**\n*   Agent to call Saurabh tomorrow after 5 PM.\n\n**"),
        )
        assertEquals("Site visit Saturday", plainText("## **Site visit** Saturday"))
    }

    @Test
    fun `a recording named for another session is not this call's`() {
        val mine = "fdb6397f-5ed0-47de-9657-bca77ba40918"
        assertTrue(recordingBelongsTo(session(mine, "recording_$mine.wav")))
        // The live mismatch: session 172180a8 was served fdb6397f's recording.
        assertFalse(recordingBelongsTo(session("172180a8-afd7-45cb-aef3-b4cc3e2d4f72", "recording_$mine.wav")))
        // No session id in the name: nothing to contradict, so it is trusted.
        assertTrue(recordingBelongsTo(session(mine, "call.wav")))
        assertTrue(recordingBelongsTo(session(mine, null)))
    }
}
