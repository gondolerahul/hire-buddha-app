"""Unit tests for the in-call guardrail logic (Kanakia-Leads-01 fixes).

Covers voicemail phrase detection, Twilio AMD mapping, post-call disposition
parsing, and the activity-watchdog decision matrix in call_guards.py.
"""

from types import SimpleNamespace

import pytest

from src.voice.call_guards import (
    ActivityState,
    SILENCE_WINDDOWN_GOODBYE_SECONDS,
    detect_voicemail_phrase,
    effective_agent_audio_at,
    evaluate_activity,
    is_twilio_machine,
    parse_disposition,
    parse_not_interested_reason,
)


CFG = SimpleNamespace(
    VOICEMAIL_NO_SPEECH_SECONDS=15,
    VOICE_PIPELINE_STALL_SECONDS=10,
    VOICE_SILENCE_DISCONNECT_SECONDS=15,
    VOICE_SILENCE_GRACE_SECONDS=20,
    VOICE_AGENT_STALL_SECONDS=10,
    VOICE_AGENT_STALL_DISCONNECT=False,
)


def make_state(**kwargs) -> ActivityState:
    defaults = dict(now=100.0, direction="outbound")
    defaults.update(kwargs)
    return ActivityState(**defaults)


# ---------------------------------------------------------------------------
# Voicemail phrase detection
# ---------------------------------------------------------------------------

class TestDetectVoicemailPhrase:
    @pytest.mark.parametrize("window", [
        "hi you have reached rahul please leave a message after the tone",
        "the person you are calling is not available to take your call",
        "your call has been forwarded to voicemail",
        "please record your message after the beep",
        "the subscriber is busy on another call please try again later",
    ])
    def test_matches_common_greetings(self, window):
        assert detect_voicemail_phrase(window) is not None

    @pytest.mark.parametrize("window", [
        "hello who is this",
        "yes i am interested tell me more about the project",
        "",
    ])
    def test_no_false_positive_on_normal_speech(self, window):
        assert detect_voicemail_phrase(window) is None


class TestIsTwilioMachine:
    @pytest.mark.parametrize("value", [
        "machine_start", "machine_end_beep", "machine_end_silence",
        "machine_end_other", "fax", "MACHINE_START",
    ])
    def test_machine_values(self, value):
        assert is_twilio_machine(value) is True

    @pytest.mark.parametrize("value", ["human", "unknown", "", None])
    def test_non_machine_values(self, value):
        assert is_twilio_machine(value) is False


# ---------------------------------------------------------------------------
# Disposition parsing from LLM summary output
# ---------------------------------------------------------------------------

class TestParseDisposition:
    def test_interested(self):
        assert parse_disposition(
            "SUMMARY:\nGood call.\n\nNEXT ACTIONS:\n- Follow up\n\nDISPOSITION:\ninterested"
        ) == "interested"

    def test_not_interested(self):
        assert parse_disposition("DISPOSITION: not_interested") == "not_interested"

    def test_not_interested_with_space(self):
        assert parse_disposition("DISPOSITION: Not Interested") == "not_interested"

    def test_voicemail(self):
        assert parse_disposition("DISPOSITION:\nvoicemail") == "voicemail"

    def test_neutral_maps_to_none(self):
        assert parse_disposition("DISPOSITION: neutral") is None

    def test_missing_section(self):
        assert parse_disposition("SUMMARY: A call happened.") is None

    def test_garbage_after_header(self):
        assert parse_disposition("DISPOSITION:\n???") is None

    def test_empty(self):
        assert parse_disposition("") is None

    def test_interested_followed_by_reason_section(self):
        # The REASON header after the disposition value must not flip the result
        assert parse_disposition(
            "DISPOSITION:\ninterested\n\nREASON:\nnone"
        ) == "interested"


class TestParseNotInterestedReason:
    def test_budget_low(self):
        assert parse_not_interested_reason(
            "SUMMARY:\nCall done.\n\nDISPOSITION:\nnot_interested\n\nREASON:\nbudget_low"
        ) == "budget_low"

    def test_already_bought(self):
        assert parse_not_interested_reason(
            "DISPOSITION: not_interested\nREASON: already_bought"
        ) == "already_bought"

    def test_none_placeholder(self):
        assert parse_not_interested_reason(
            "DISPOSITION: interested\nREASON: none"
        ) is None

    def test_missing_reason_section(self):
        assert parse_not_interested_reason("DISPOSITION: not_interested") is None

    def test_missing_disposition_section(self):
        assert parse_not_interested_reason("REASON: budget_low") is None

    def test_garbage_reason(self):
        assert parse_not_interested_reason(
            "DISPOSITION: not_interested\nREASON: ???"
        ) is None

    def test_empty(self):
        assert parse_not_interested_reason("") is None


# ---------------------------------------------------------------------------
# Activity watchdog decision matrix
# ---------------------------------------------------------------------------

class TestPipelineStall:
    def test_stall_after_threshold(self):
        state = make_state(greeting_sent_at=85.0, first_audio_received=False)
        assert evaluate_activity(state, CFG) == "pipeline_stall"

    def test_no_stall_within_threshold(self):
        state = make_state(greeting_sent_at=95.0, first_audio_received=False)
        assert evaluate_activity(state, CFG) is None

    def test_no_stall_after_first_audio(self):
        state = make_state(
            greeting_sent_at=50.0,
            first_audio_received=True,
            pipeline_started_at=99.0,
        )
        assert evaluate_activity(state, CFG) is None


class TestVoicemailNoSpeech:
    def test_outbound_totally_silent_line_after_threshold(self):
        state = make_state(
            first_audio_received=True,
            first_agent_audio_sent_at=80.0,
            pipeline_started_at=99.0,
        )
        assert evaluate_activity(state, CFG) == "voicemail_no_speech"

    def test_transcribed_lead_prevents_detection(self):
        state = make_state(
            first_audio_received=True,
            first_agent_audio_sent_at=80.0,
            last_lead_transcript_at=90.0,
            pipeline_started_at=99.0,
        )
        assert evaluate_activity(state, CFG) is None

    def test_speech_energy_prevents_detection(self):
        # Lead said "hello" at pickup (RMS energy) but nothing was transcribed
        # while the agent pitched — must NOT be classified voicemail.
        state = make_state(
            first_audio_received=True,
            first_agent_audio_sent_at=80.0,
            last_agent_audio_at=99.0,  # agent mid-pitch
            last_lead_speech_at=81.0,
            pipeline_started_at=99.0,
        )
        assert evaluate_activity(state, CFG) is None

    def test_inbound_never_triggers(self):
        state = make_state(
            direction="inbound",
            first_audio_received=True,
            first_agent_audio_sent_at=80.0,
            pipeline_started_at=99.0,
        )
        assert evaluate_activity(state, CFG) is None

    def test_disabled_flag(self):
        state = make_state(
            first_audio_received=True,
            first_agent_audio_sent_at=80.0,
            voicemail_detection_enabled=False,
            pipeline_started_at=99.0,
        )
        assert evaluate_activity(state, CFG) is None


class TestSilence:
    def _idle_state(self, **overrides):
        base = dict(
            first_audio_received=True,
            pipeline_started_at=10.0,
            first_agent_audio_sent_at=12.0,
            last_agent_audio_at=70.0,
            last_lead_speech_at=80.0,
            last_lead_transcript_at=80.0,
        )
        base.update(overrides)
        return make_state(**base)

    def test_winddown_when_both_idle(self):
        # last activity at 80, now 100 → 20s idle > 15s threshold
        assert evaluate_activity(self._idle_state(), CFG) == "silence_winddown"

    def test_no_winddown_during_grace(self):
        state = self._idle_state(pipeline_started_at=90.0)
        state.last_agent_audio_at = None
        state.last_lead_speech_at = None
        assert evaluate_activity(state, CFG) is None

    def test_no_winddown_when_recently_active(self):
        state = self._idle_state(last_lead_speech_at=95.0)
        assert evaluate_activity(state, CFG) is None

    def test_disconnect_after_goodbye_window(self):
        state = self._idle_state(
            silence_winddown_at=100.0 - SILENCE_WINDDOWN_GOODBYE_SECONDS - 1
        )
        assert evaluate_activity(state, CFG) == "silence_disconnect"

    def test_no_disconnect_when_lead_spoke_after_winddown(self):
        state = self._idle_state(
            silence_winddown_at=85.0,
            last_lead_speech_at=97.0,
        )
        # Lead re-engaged: never disconnect; a nudge to respond is fine
        assert evaluate_activity(state, CFG) in (None, "agent_stall_nudge")


class TestEffectiveAgentAudioAt:
    def test_playing_from_buffer_counts_as_now(self):
        # Chunks were burst-sent at t=80 but play until t=110; at t=100 the
        # lead is still hearing the agent.
        assert effective_agent_audio_at(100.0, 80.0, 110.0) == 100.0

    def test_after_buffer_drains_horizon_is_the_anchor(self):
        # Playback ended at t=90; at t=100 the agent has been silent 10s.
        assert effective_agent_audio_at(100.0, 80.0, 90.0) == 90.0

    def test_no_audio_ever(self):
        assert effective_agent_audio_at(100.0, None, 0.0) is None

    def test_regression_no_winddown_during_agent_monologue(self):
        # The 07:48 test call: agent's 30s reply burst-sent at t=72, playback
        # horizon t=102; lead listening quietly since "hello" at t=75. At
        # t=95 the old send-time accounting saw 23s of "mutual silence" and
        # killed the call mid-sentence; playback-aware time must not.
        agent_at = effective_agent_audio_at(95.0, 72.0, 102.0)
        state = ActivityState(
            now=95.0,
            direction="outbound",
            pipeline_started_at=70.0,
            first_audio_received=True,
            first_agent_audio_sent_at=72.0,
            last_agent_audio_at=agent_at,
            last_lead_speech_at=75.0,
            last_lead_transcript_at=75.0,
        )
        assert evaluate_activity(state, CFG) is None


class TestAgentStall:
    def _stall_state(self, **overrides):
        base = dict(
            first_audio_received=True,
            pipeline_started_at=10.0,
            first_agent_audio_sent_at=12.0,
            last_agent_audio_at=80.0,
            last_lead_speech_at=85.0,
            last_lead_transcript_at=85.0,
            user_speech_end_time=85.0,
        )
        base.update(overrides)
        return make_state(**base)

    def test_nudge_after_threshold(self):
        # lead's turn ended at 85, agent last spoke at 80 (before) → 15s stall
        assert evaluate_activity(self._stall_state(), CFG) == "agent_stall_nudge"

    def test_no_stall_while_lead_still_talking(self):
        # Lead speech energy 1s ago and the agent spoke recently — the
        # stall/disconnect clock must not run
        state = self._stall_state(last_lead_speech_at=99.0, last_agent_audio_at=95.0)
        assert evaluate_activity(state, CFG) is None

    def test_nudge_while_lead_keeps_talking_and_agent_silent(self):
        # Regression: lead said "hello" continuously for 26s (never went
        # quiet) while the agent produced nothing — clause 4b must nudge.
        state = self._stall_state(
            user_speech_end_time=None,
            last_lead_transcript_at=None,
            last_lead_speech_at=99.5,   # still talking right now
            last_agent_audio_at=85.0,   # agent dead air for 15s
        )
        assert evaluate_activity(state, CFG) == "agent_stall_nudge"

    def test_no_nudge_while_lead_talks_and_agent_recently_spoke(self):
        state = self._stall_state(
            user_speech_end_time=None,
            last_lead_transcript_at=None,
            last_lead_speech_at=99.5,
            last_agent_audio_at=95.0,   # agent spoke 5s ago — normal listening
        )
        assert evaluate_activity(state, CFG) is None

    def test_nudge_from_energy_alone_when_model_is_mute(self):
        # Wedged-session case: lead keeps saying "hello" (energy) but the
        # model never transcribes or answers — nudge must still fire.
        state = self._stall_state(
            user_speech_end_time=None,
            last_lead_transcript_at=None,
            last_agent_audio_at=80.0,
            last_lead_speech_at=85.0,
        )
        assert evaluate_activity(state, CFG) == "agent_stall_nudge"

    def test_no_nudge_when_agent_responded(self):
        state = self._stall_state(last_agent_audio_at=90.0)
        assert evaluate_activity(state, CFG) is None

    def test_disconnect_disabled_by_default(self):
        # Lead quiet 12s (below the silence threshold), nudge already sent,
        # agent still silent — without the opt-in flag nothing happens
        state = self._stall_state(
            agent_stall_nudge_at=90.0, user_speech_end_time=88.0,
            last_lead_speech_at=88.0, last_lead_transcript_at=88.0,
            last_agent_audio_at=70.0,
        )
        assert evaluate_activity(state, CFG) is None

    def test_disconnect_when_enabled(self):
        # Stall thresholds shortened so 2x stall (10s) trips before the
        # silence winddown (15s) — with the flag on, disconnect fires
        cfg = SimpleNamespace(**{
            **CFG.__dict__,
            "VOICE_AGENT_STALL_SECONDS": 5,
            "VOICE_AGENT_STALL_DISCONNECT": True,
        })
        state = self._stall_state(
            agent_stall_nudge_at=90.0, user_speech_end_time=88.0,
            last_lead_speech_at=88.0, last_lead_transcript_at=88.0,
            last_agent_audio_at=70.0,
        )
        assert evaluate_activity(state, cfg) == "agent_stall_disconnect"
