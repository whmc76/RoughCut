from __future__ import annotations

import wave
from dataclasses import dataclass
from pathlib import Path


@dataclass
class SilenceSegment:
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


def detect_silence(
    wav_path: Path,
    *,
    aggressiveness: int = 2,
    frame_duration_ms: int = 30,
    min_silence_duration_ms: int = 300,
    padding_ms: int = 50,
) -> list[SilenceSegment]:
    """
    Detect silence segments in a WAV file using webrtcvad.

    aggressiveness: 0-3, higher = more aggressive filtering
    frame_duration_ms: 10, 20, or 30 ms
    min_silence_duration_ms: minimum silence duration to report
    padding_ms: padding added around speech frames
    """
    try:
        import webrtcvad
    except ImportError:
        raise RuntimeError("webrtcvad is not installed. Run: pip install webrtcvad-wheels")

    vad = webrtcvad.Vad(aggressiveness)

    with wave.open(str(wav_path), "rb") as wf:
        sample_rate = wf.getframerate()
        num_channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        total_frames = wf.getnframes()
        audio_data = wf.readframes(total_frames)

    if sample_rate not in (8000, 16000, 32000, 48000):
        raise ValueError(f"VAD requires 8/16/32/48 kHz audio, got {sample_rate} Hz")
    if num_channels != 1:
        raise ValueError("VAD requires mono audio")
    if sample_width != 2:
        raise ValueError("VAD requires 16-bit audio")

    frame_size = int(sample_rate * frame_duration_ms / 1000) * 2  # bytes (16-bit)
    frames = []
    for i in range(0, len(audio_data) - frame_size + 1, frame_size):
        frame = audio_data[i : i + frame_size]
        frames.append(frame)

    # Mark each frame as speech or silence
    is_speech = []
    for frame in frames:
        try:
            is_speech.append(vad.is_speech(frame, sample_rate))
        except Exception:
            is_speech.append(False)

    # Apply padding: extend speech regions by padding_ms
    padding_frames = padding_ms // frame_duration_ms
    padded = list(is_speech)
    for i, speech in enumerate(is_speech):
        if speech:
            for j in range(max(0, i - padding_frames), min(len(padded), i + padding_frames + 1)):
                padded[j] = True

    # Collect silence segments
    silences: list[SilenceSegment] = []
    in_silence = not padded[0] if padded else False
    start_idx = 0

    for i, speech in enumerate(padded):
        if not speech and not in_silence:
            in_silence = True
            start_idx = i
        elif speech and in_silence:
            in_silence = False
            start_sec = start_idx * frame_duration_ms / 1000
            end_sec = i * frame_duration_ms / 1000
            dur_ms = (i - start_idx) * frame_duration_ms
            if dur_ms >= min_silence_duration_ms:
                silences.append(SilenceSegment(start=start_sec, end=end_sec))

    # Handle trailing silence
    if in_silence:
        start_sec = start_idx * frame_duration_ms / 1000
        end_sec = len(padded) * frame_duration_ms / 1000
        dur_ms = (len(padded) - start_idx) * frame_duration_ms
        if dur_ms >= min_silence_duration_ms:
            silences.append(SilenceSegment(start=start_sec, end=end_sec))

    return silences
