"""Pure decision logic for in-call guardrails (voicemail + silence/stall).

Extracted from the stream handler so the rules are unit-testable without a
live pipeline. The handler owns the timestamps and side effects; these
functions only decide.
"""

from dataclasses import dataclass
from typing import Optional

# Seconds the agent gets to say goodbye after a silence wind-down prompt
# before the call is force-disconnected.
SILENCE_WINDDOWN_GOODBYE_SECONDS = 10

# Lowercased fragments that identify an answering-machine greeting in the
# inbound transcription.
VOICEMAIL_PHRASES = (
    "leave a message",
    "leave your message",
    "leave me a message",
    "after the tone",
    "after the beep",
    "at the tone",
    "record your message",
    "voicemail",
    "voice mail",
    "mailbox",
    "not available to take your call",
    "unable to take your call",
    "is currently unavailable",
    "not reachable at the moment",
    "cannot be reached",
    "please try again later",
    "is busy on another call",
)

# Twilio AMD AnsweredBy values that mean a machine picked up.
TWILIO_MACHINE_ANSWERED_BY = frozenset(
    {"machine_start", "machine_end_beep", "machine_end_silence",
     "machine_end_other", "fax"}
)

# Synthetic tool the live model can call to hang up (voicemail or natural end).
END_CALL_TOOL = {
    "name": "end_call",
    "description": (
        "Ends the phone call immediately. Call this when you realize you have "
        "reached voicemail or an answering machine (reason='voicemail'), or "
        "when the conversation is finished and goodbyes have been said "
        "(reason='conversation_complete')."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "reason": {
                "type": "string",
                "enum": ["voicemail", "conversation_complete"],
                "description": "Why the call should end.",
            },
        },
        "required": ["reason"],
    },
}

END_CALL_SYSTEM_SUFFIX = (
    "\n\nIf you are CERTAIN you have reached voicemail or an answering machine "
    "— you heard a recorded greeting, an instruction to leave a message, or a "
    "beep — do not deliver your pitch; call the end_call tool with "
    "reason='voicemail'. Never do this while a live person is responding to "
    "you; a quiet or hesitant caller is NOT voicemail. If unsure, ask "
    "\"Hello, can you hear me?\" and wait before deciding."
)


def effective_agent_audio_at(
    now: float,
    last_sent_at: Optional[float],
    playback_until: float,
) -> Optional[float]:
    """Translate chunk-send time into perceived agent-speech time.

    The model generates audio far faster than real time: a 30s reply reaches
    the telephony provider in a ~2s burst and then plays from the provider's
    buffer. Silence must be measured against when the lead stops HEARING the
    agent (the playback horizon), not when we stopped sending.
    """
    candidates = [t for t in (last_sent_at, min(now, playback_until)) if t]
    return max(candidates) if candidates else None


def detect_voicemail_phrase(transcript_window: str) -> Optional[str]:
    """Return the matched voicemail phrase in a lowercased transcript window."""
    for phrase in VOICEMAIL_PHRASES:
        if phrase in transcript_window:
            return phrase
    return None


def is_twilio_machine(answered_by: Optional[str]) -> bool:
    """True when a Twilio AMD AnsweredBy value indicates a machine/fax."""
    return (answered_by or "").lower() in TWILIO_MACHINE_ANSWERED_BY


def parse_disposition(summary_text: str) -> Optional[str]:
    """Extract the DISPOSITION line from the post-call summary LLM output.

    Returns one of interested | not_interested | voicemail, or None when the
    line is missing, 'neutral', or garbage.
    """
    if not summary_text or "DISPOSITION" not in summary_text.upper():
        return None
    tail = summary_text.upper().split("DISPOSITION", 1)[1]
    # First recognizable token after the header wins
    for token in ("NOT_INTERESTED", "NOT INTERESTED", "INTERESTED", "VOICEMAIL", "NEUTRAL"):
        idx = tail.find(token)
        if idx != -1 and idx < 40:
            if token == "NEUTRAL":
                return None
            return token.replace(" ", "_").lower()
    return None


# Allowed values for the REASON line that follows a not_interested
# disposition in the summary output. Mirrored in campaign_calls.disposition_reason.
NOT_INTERESTED_REASONS = (
    "BUDGET_LOW",
    "NOT_SUITABLE",
    "NOT_INVESTING",
    "ALREADY_BOUGHT",
    "OTHER",
)


def parse_not_interested_reason(summary_text: str) -> Optional[str]:
    """Extract the REASON line (why the lead was not interested) from the
    post-call summary LLM output.

    Only meaningful when parse_disposition() returned not_interested; returns
    None when the line is missing, 'none', or garbage.
    """
    if not summary_text or "DISPOSITION" not in summary_text.upper():
        return None
    tail = summary_text.upper().split("DISPOSITION", 1)[1]
    if "REASON" not in tail:
        return None
    reason_tail = tail.split("REASON", 1)[1]
    for token in NOT_INTERESTED_REASONS:
        idx = reason_tail.find(token)
        if idx != -1 and idx < 40:
            return token.lower()
    return None


@dataclass
class ActivityState:
    """Snapshot of the handler's activity timestamps (time.time() floats)."""
    now: float
    direction: str                                  # "outbound" | "inbound"
    pipeline_started_at: Optional[float] = None
    greeting_sent_at: Optional[float] = None
    first_audio_received: bool = False
    first_agent_audio_sent_at: Optional[float] = None
    last_agent_audio_at: Optional[float] = None
    last_lead_speech_at: Optional[float] = None     # RMS energy VAD
    last_lead_transcript_at: Optional[float] = None  # model transcription
    user_speech_end_time: Optional[float] = None
    silence_winddown_at: Optional[float] = None
    agent_stall_nudge_at: Optional[float] = None
    voicemail_detection_enabled: bool = True


def evaluate_activity(state: ActivityState, cfg) -> Optional[str]:
    """Decide the next guardrail action for the current tick.

    Returns one of:
      'pipeline_stall'        — no agent audio ever arrived; tear down as failed
      'voicemail_no_speech'   — outbound, agent spoke, lead never transcribed
      'silence_winddown'      — both sides idle; prompt the agent to say goodbye
      'silence_disconnect'    — goodbye window elapsed, still silent; hang up
      'agent_stall_nudge'     — agent silent after lead's turn; nudge the model
      'agent_stall_disconnect'— nudge didn't help (only if enabled in cfg)
      None                    — all healthy

    ``cfg`` needs the VOICE_*/VOICEMAIL_* attributes from Settings.
    """
    now = state.now

    # 1. Pipeline stall: greeting was triggered but the model never produced
    # audio — the lead is hearing dead air (or our ringback). Kill fast.
    if state.greeting_sent_at and not state.first_audio_received:
        if now - state.greeting_sent_at > cfg.VOICE_PIPELINE_STALL_SECONDS:
            return "pipeline_stall"
        return None  # nothing else applies before first audio

    # 2. Voicemail heuristic: on an outbound call the agent has been talking
    # and the line produced NEITHER a transcript NOR any speech energy.
    # A human listening politely to the pitch still said "hello" at pickup
    # (energy), so requiring both signals absent avoids cutting live calls
    # mid-pitch (observed false positives with transcript-only detection).
    if (
        state.voicemail_detection_enabled
        and state.direction == "outbound"
        and state.first_agent_audio_sent_at
        and state.last_lead_transcript_at is None
        and state.last_lead_speech_at is None
        and now - state.first_agent_audio_sent_at > cfg.VOICEMAIL_NO_SPEECH_SECONDS
    ):
        return "voicemail_no_speech"

    # 3. Both-sides silence (after a startup grace window).
    if (
        state.pipeline_started_at
        and now - state.pipeline_started_at > cfg.VOICE_SILENCE_GRACE_SECONDS
    ):
        if state.silence_winddown_at is not None:
            # Waiting out the goodbye window; lead speech resets it (handler
            # clears silence_winddown_at when that happens).
            if (
                (state.last_lead_speech_at or 0) <= state.silence_winddown_at
                and now - state.silence_winddown_at > SILENCE_WINDDOWN_GOODBYE_SECONDS
            ):
                return "silence_disconnect"
        else:
            anchors = [
                t
                for t in (
                    state.last_agent_audio_at,
                    state.last_lead_speech_at,
                    state.pipeline_started_at,
                )
                if t
            ]
            if now - max(anchors) > cfg.VOICE_SILENCE_DISCONNECT_SECONDS:
                return "silence_winddown"

    # 4. Agent stall mid-conversation: the lead was speaking and the agent
    # has produced no audio since they stopped. Keyed on speech ENERGY as
    # well as transcripts — a wedged model session (observed: greeting
    # interrupted at t≈0 left Gemini mute, never transcribing the lead's
    # "hello, hello") delivers no transcripts at all, and the nudge is what
    # rescues it. Nudge first; disconnecting is opt-in because tool calls
    # legitimately take longer than the stall window.
    lead_last_active = max(
        (t for t in (state.user_speech_end_time, state.last_lead_speech_at) if t),
        default=None,
    )
    if (
        lead_last_active
        and (state.last_agent_audio_at or 0) < lead_last_active
    ):
        stall = now - lead_last_active
        if state.agent_stall_nudge_at is None:
            if stall > cfg.VOICE_AGENT_STALL_SECONDS:
                return "agent_stall_nudge"
        elif (
            cfg.VOICE_AGENT_STALL_DISCONNECT
            and stall > 2 * cfg.VOICE_AGENT_STALL_SECONDS
        ):
            return "agent_stall_disconnect"

    # 4b. Agent silent while the lead keeps talking: a lead repeating
    # "hello? hello?" never goes quiet, so the stall clock above never
    # starts — yet the agent has been dead air the whole time (observed
    # 26s of it). A brief "I'm still here" nudge is the right recovery.
    if (
        state.first_audio_received
        and state.agent_stall_nudge_at is None
        and state.last_agent_audio_at
        and state.last_lead_speech_at
        and now - state.last_lead_speech_at < 5
        and now - state.last_agent_audio_at > cfg.VOICE_AGENT_STALL_SECONDS
    ):
        return "agent_stall_nudge"

    return None
