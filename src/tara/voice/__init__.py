from __future__ import annotations

from tara.config import settings


def get_elevenlabs_base_url() -> str:
    """Get the ElevenLabs API base URL, auto-detecting data residency from API key."""
    if settings.elevenlabs_base_url:
        return settings.elevenlabs_base_url
    key = settings.elevenlabs_api_key
    if "_residency_in" in key:
        return "https://api.in.residency.elevenlabs.io"
    elif "_residency_eu" in key:
        return "https://api.eu.residency.elevenlabs.io"
    return "https://api.elevenlabs.io"
