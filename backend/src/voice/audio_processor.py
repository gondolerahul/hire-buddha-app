"""
Audio processing utilities for format conversion.

Handles conversion between:
- mulaw (8kHz, 8-bit) - Twilio/Tata Tele format
- PCM16 (16kHz, 16-bit) - Gemini Live API input format
- PCM24 (24kHz, 16-bit) - Gemini Live API output format
"""
import logging
import audioop
import numpy as np

logger = logging.getLogger(__name__)


class AudioProcessor:
    """Audio format conversion utilities for streaming."""
    
    MULAW_SAMPLE_RATE = 8000
    PCM16_SAMPLE_RATE = 16000
    PCM24_SAMPLE_RATE = 24000
    SAMPLE_WIDTH = 2  # 16-bit = 2 bytes
    CHANNELS = 1  # Mono
    
    @staticmethod
    def mulaw_to_pcm16(mulaw_bytes: bytes) -> bytes:
        """
        Convert mulaw (8kHz, 8-bit) to PCM16 (16kHz, 16-bit).
        
        Twilio/Tata use mulaw, Gemini expects PCM16.
        
        Args:
            mulaw_bytes: Input mulaw audio data
            
        Returns:
            PCM16 audio data at 16kHz
        """
        try:
            # Decode mulaw to linear PCM (8kHz)
            pcm_8khz = audioop.ulaw2lin(mulaw_bytes, AudioProcessor.SAMPLE_WIDTH)
            
            # Resample 8kHz → 16kHz
            pcm_16khz, _ = audioop.ratecv(
                pcm_8khz,
                AudioProcessor.SAMPLE_WIDTH,  # sample width
                AudioProcessor.CHANNELS,      # channels (mono)
                AudioProcessor.MULAW_SAMPLE_RATE,   # input rate (8kHz)
                AudioProcessor.PCM16_SAMPLE_RATE,   # output rate (16kHz)
                None  # state
            )
            
            return pcm_16khz
            
        except Exception as e:
            logger.error(f"Error converting mulaw to PCM16: {e}")
            return b''
    
    @staticmethod
    def pcm24_to_mulaw(pcm24_bytes: bytes) -> bytes:
        """
        Convert PCM24 (24kHz, 16-bit) to mulaw (8kHz, 8-bit).
        
        Gemini outputs PCM24, Twilio/Tata expect mulaw.
        Output is aligned to 20ms frame boundaries (160 bytes at 8kHz)
        to prevent audible clicks and static at frame edges.
        
        Args:
            pcm24_bytes: Input PCM24 audio data
            
        Returns:
            mulaw audio data at 8kHz, frame-aligned
        """
        try:
            # Resample 24kHz → 8kHz
            pcm_8khz, _ = audioop.ratecv(
                pcm24_bytes,
                AudioProcessor.SAMPLE_WIDTH,
                AudioProcessor.CHANNELS,
                AudioProcessor.PCM24_SAMPLE_RATE,  # input rate (24kHz)
                AudioProcessor.MULAW_SAMPLE_RATE,   # output rate (8kHz)
                None
            )
            
            # Encode linear PCM to mulaw
            mulaw = audioop.lin2ulaw(pcm_8khz, AudioProcessor.SAMPLE_WIDTH)

            # Phase 2: Frame alignment — ensure output is a multiple of 160 bytes
            # (20ms at 8kHz mulaw). Misaligned chunks cause audible clicks/static.
            FRAME_SIZE = 160  # 20ms at 8kHz, 1 byte per mulaw sample
            remainder = len(mulaw) % FRAME_SIZE
            if remainder != 0:
                # Pad with mulaw silence (0xFF = zero-level in mu-law encoding)
                padding = FRAME_SIZE - remainder
                mulaw = mulaw + b'\xff' * padding

            return mulaw
            
        except Exception as e:
            logger.error(f"Error converting PCM24 to mulaw: {e}")
            return b''
    
    @staticmethod
    def pcm16_to_mulaw(pcm16_bytes: bytes) -> bytes:
        """
        Convert PCM16 (16kHz, 16-bit) to mulaw (8kHz, 8-bit).
        
        Used for mock responses.
        
        Args:
            pcm16_bytes: Input PCM16 audio data
            
        Returns:
            mulaw audio data at 8kHz
        """
        try:
            # Resample 16kHz → 8kHz
            pcm_8khz, _ = audioop.ratecv(
                pcm16_bytes,
                AudioProcessor.SAMPLE_WIDTH,
                AudioProcessor.CHANNELS,
                AudioProcessor.PCM16_SAMPLE_RATE,
                AudioProcessor.MULAW_SAMPLE_RATE,
                None
            )
            
            # Encode to mulaw
            mulaw = audioop.lin2ulaw(pcm_8khz, AudioProcessor.SAMPLE_WIDTH)
            
            return mulaw
            
        except Exception as e:
            logger.error(f"Error converting PCM16 to mulaw: {e}")
            return b''
    
    @staticmethod
    def ensure_chunk_size(audio_bytes: bytes, target_size: int = 160) -> list[bytes]:
        """
        Split audio into chunks of specific size.
        
        Tata Tele requires chunks in multiples of 160 bytes.
        
        Args:
            audio_bytes: Input audio data
            target_size: Chunk size in bytes (default 160)
            
        Returns:
            List of audio chunks
        """
        chunks = []
        
        for i in range(0, len(audio_bytes), target_size):
            chunk = audio_bytes[i:i+target_size]
            
            # Pad if necessary
            if len(chunk) < target_size:
                chunk += b'\x00' * (target_size - len(chunk))
            
            chunks.append(chunk)
        
        return chunks
    
    @staticmethod
    def generate_silence(duration_ms: int, sample_rate: int = 16000) -> bytes:
        """
        Generate silence (zeros) for a given duration.
        
        Useful for padding or when no audio is available.
        
        Args:
            duration_ms: Duration in milliseconds
            sample_rate: Sample rate in Hz
            
        Returns:
            PCM16 silence data
        """
        num_samples = int((duration_ms / 1000.0) * sample_rate)
        silence = np.zeros(num_samples, dtype=np.int16)
        return silence.tobytes()
    
    @staticmethod
    def calculate_duration_ms(audio_bytes: bytes, sample_rate: int = 16000) -> int:
        """
        Calculate audio duration in milliseconds.
        
        Args:
            audio_bytes: PCM16 audio data
            sample_rate: Sample rate in Hz
            
        Returns:
            Duration in milliseconds
        """
        num_samples = len(audio_bytes) // AudioProcessor.SAMPLE_WIDTH
        duration_ms = int((num_samples / sample_rate) * 1000)
        return duration_ms

    @staticmethod
    def generate_ringback_tone(duration_seconds: int = 4) -> bytes:
        """
        Generate a typical North American ringback tone (440Hz + 480Hz).
        Returns it as 8kHz mu-law bytes, suitable for Twilio/Tata playback
        while waiting for a slow TTS/LLM response.
        """
        import math
        import struct
        import audioop
        
        sample_rate = 8000
        total_samples = int(sample_rate * duration_seconds)
        
        pcm16_data = bytearray()
        # Typical pattern: 2 seconds on, 4 seconds off
        for i in range(total_samples):
            t = i / sample_rate
            # 2s on, 4s off pattern
            cycle_time = t % 6.0
            if cycle_time < 2.0:
                # Beep tone
                sample = int(8000 * (math.sin(2 * math.pi * 440 * t) + math.sin(2 * math.pi * 480 * t)))
            else:
                # Silence
                sample = 0
            pcm16_data.extend(struct.pack('<h', sample))
            
        # Convert linear PCM to mu-law
        mulaw_data = audioop.lin2ulaw(bytes(pcm16_data), 2)
        return mulaw_data
