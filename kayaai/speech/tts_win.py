"""Windows'ta çevrim dışı konuşma sentezi (ölçüm için): OneCore sesleri (WinRT; Türkçe "Tolga" burada) → yoksa System.Speech
(SAPI). Yalnızca kontrol/ölçüm betikleri kullanır (kullanıcıya sesli okuma tarayıcıda, yerel seslerle yapılır)."""

from __future__ import annotations

from pathlib import Path


def synth_wav_onecore(text: str, culture: str, out: Path) -> str | None:
    """Windows OneCore sesleri (WinRT, çevrim dışı; Türkçe "Tolga" burada olur). Ses yoksa None."""
    import asyncio

    try:
        from winrt.windows.media.speechsynthesis import SpeechSynthesizer
        from winrt.windows.storage.streams import DataReader
    except ImportError:
        return None

    async def run() -> str | None:
        voices = [v for v in SpeechSynthesizer.all_voices if v.language.lower() == culture.lower()]
        if not voices:
            return None
        synth = SpeechSynthesizer()
        synth.voice = voices[0]
        stream = await synth.synthesize_text_to_stream_async(text)
        size = int(stream.size)
        reader = DataReader(stream.get_input_stream_at(0))
        await reader.load_async(size)
        buf = bytearray(size)
        reader.read_bytes(buf)
        out.write_bytes(bytes(buf))
        return voices[0].display_name

    try:
        return asyncio.run(run())
    except Exception as exc:  # noqa: BLE001
        print(f"  (OneCore ses hatası: {exc})")
        return None


def synth_wav(text: str, culture: str, out: Path) -> str | None:
    """Önce OneCore (WinRT), yoksa System.Speech (SAPI) ile WAV (çevrim dışı). Ses yoksa None."""
    name = synth_wav_onecore(text, culture, out)
    if name:
        return name
    import subprocess

    ps = (
        "Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        f"$v = $s.GetInstalledVoices() | Where-Object {{ $_.VoiceInfo.Culture.Name -eq '{culture}' -and $_.Enabled }} | "
        "Select-Object -First 1; if (-not $v) { exit 3 }; $s.SelectVoice($v.VoiceInfo.Name); "
        f"$s.SetOutputToWaveFile('{out}'); $s.Speak($env:KAYA_TTS_TEXT); $s.Dispose(); Write-Output $v.VoiceInfo.Name"
    )
    import os

    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                       env={**os.environ, "KAYA_TTS_TEXT": text}, timeout=60)
    return r.stdout.strip() if r.returncode == 0 and out.is_file() else None


def wer(ref: str, hyp: str) -> float:
    import re

    norm = lambda t: re.findall(r"\w+", t.lower().replace("İ", "i").replace("I", "ı"))  # noqa: E731
    r, h = norm(ref), norm(hyp)
    d = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(h) + 1):
            cur = min(d[j] + 1, d[j - 1] + 1, prev + (r[i - 1] != h[j - 1]))
            prev, d[j] = d[j], cur
    return round(d[len(h)] / max(1, len(r)), 3)


