import os
import tempfile
import threading
from typing import Optional, List

import azure.cognitiveservices.speech as speechsdk
from ..core.config import settings

def _mask(s: str, keep=6): return s[:keep] + "…" if s else ""

def _to_wav_pcm_16k_mono(src_path: str) -> Optional[str]:
    """Transcode to WAV PCM 16k mono via ffmpeg (pydub)."""
    try:
        from pydub import AudioSegment
    except Exception as e:
        print("[speech] pydub not available:", e)
        return None
    try:
        audio = AudioSegment.from_file(src_path)  # mp3/m4a/ogg/…
        audio = audio.set_frame_rate(16000).set_channels(1).set_sample_width(2)
        fd, out_path = tempfile.mkstemp(suffix=".wav"); os.close(fd)
        audio.export(out_path, format="wav")
        return out_path
    except Exception as e:
        print(f"[speech] ffmpeg/pydub conversion failed: {e}")
        return None

def _continuous_transcribe(wav_path: str, speech_config: "speechsdk.SpeechConfig") -> str:
    """Consume the full file with continuous recognition and join results."""
    audio_config = speechsdk.audio.AudioConfig(filename=wav_path)
    recognizer = speechsdk.SpeechRecognizer(speech_config=speech_config, audio_config=audio_config)

    done = threading.Event()
    lines: List[str] = []

    def on_recognized(evt: speechsdk.SpeechRecognitionEventArgs):
        if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech and evt.result.text:
            lines.append(evt.result.text)

    def on_stop(evt): done.set()

    recognizer.recognized.connect(on_recognized)
    recognizer.session_stopped.connect(on_stop)
    recognizer.canceled.connect(on_stop)

    recognizer.start_continuous_recognition()
    done.wait()           # wait until end-of-file
    recognizer.stop_continuous_recognition()
    return " ".join(lines).strip()

async def transcribe_wav(file_path: str) -> str:
    key = (settings.AZURE_SPEECH_KEY or "").strip()
    region = (settings.AZURE_SPEECH_REGION or "").strip()
    if not key or not region:
        print("[speech] Missing AZURE_SPEECH_KEY/REGION"); return ""
    if not os.path.exists(file_path):
        print(f"[speech] File not found: {file_path}"); return ""

    try:
        size = os.path.getsize(file_path)
        print(f"[speech] using region={region}, key={_mask(key)}, file_size={size} bytes, path={file_path}")
    except Exception:
        pass

    # 1) normalize to WAV 16k mono for stability
    wav_path = _to_wav_pcm_16k_mono(file_path) or file_path

    try:
        speech_config = speechsdk.SpeechConfig(subscription=key, region=region)
        # Optional: set language if your content is specific
        # speech_config.speech_recognition_language = "en-IN"

        text = _continuous_transcribe(wav_path, speech_config)
        if not text:
            print("[speech] continuous recognition produced empty text")
        return text
    except Exception as e:
        print(f"[speech] Exception during recognition: {e}")
        return ""
    finally:
        # remove temp wav if we created one
        if wav_path != file_path:
            try: os.remove(wav_path)
            except Exception: pass
