"""
transcribe.py — Phase-1 Multimodal Audio Transcription using Gemini API.
"""

import logging

import httpx

from ..agent.cascade import GEMINI_KEYS, GEMINI_MODELS, get_next_gemini_key

log = logging.getLogger("helmis-transcribe")


async def transcribe_audio_base64(b64_data: str, mime_type: str = "audio/ogg") -> str | None:
    """
    Dedicated Phase-1 transcription using Gemini audio multimodal API with zero hallucinations.
    Uses temperature=0.0 and isolated instruction to extract verbatim speech.
    """
    clean_mime = mime_type.split(";")[0].strip() or "audio/ogg"
    payload = {
        "contents": [
            {
                "parts": [
                    {"inlineData": {"mimeType": clean_mime, "data": b64_data}},
                    {
                        "text": (
                            "Transcribe this audio verbatim in the original spoken language (Indonesian or English). "
                            "Output ONLY the exact words spoken without quotation marks, markdown, preamble, or commentary. "
                            "If the audio contains no discernible speech or only noise, output '[UNINTELLIGIBLE]'."
                        )
                    },
                ]
            }
        ],
        "generationConfig": {"temperature": 0.0, "maxOutputTokens": 250},
    }

    for model in GEMINI_MODELS:
        for _ in range(len(GEMINI_KEYS) or 1):
            api_key = get_next_gemini_key()
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            try:
                async with httpx.AsyncClient(timeout=5.0) as http_client:
                    resp = await http_client.post(url, json=payload)
                    if resp.status_code == 200:
                        data = resp.json()
                        candidates = data.get("candidates", [])
                        if candidates:
                            raw_text = (
                                candidates[0]
                                .get("content", {})
                                .get("parts", [{}])[0]
                                .get("text", "")
                            )
                            cleaned = str(raw_text).strip().strip('"').strip("'")
                            if cleaned and cleaned != "[UNINTELLIGIBLE]":
                                log.info("Audio transcribed successfully via %s: %s", model, cleaned)
                                return str(cleaned)
                            elif cleaned == "[UNINTELLIGIBLE]":
                                log.info("Audio was unintelligible or silent.")
                                return None
                        return None
                    elif resp.status_code == 429:
                        continue
                    elif resp.status_code == 404:
                        break
            except Exception as e:
                log.warning("Transcription attempt failed on %s: %s", model, e)
                continue
    return None
