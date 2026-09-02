"""
ocr.py — Multimodal Vision OCR Engine using Google Gemini for Scanned Documents & Images.
"""

import base64
import logging

import httpx

from ..agent.cascade import GEMINI_KEYS, GEMINI_MODELS, get_next_gemini_key

log = logging.getLogger("helmis-vision-ocr")

DEFAULT_OCR_PROMPT = (
    "You are an expert high-precision document OCR and visual analyzer.\n"
    "Extract and transcribe all content from this document/page image verbatim into clean Markdown:\n"
    "1. Text & Headers: Transcribe verbatim preserving hierarchy.\n"
    "2. Mathematical Formulas & Equations: Format using standard LaTeX notation ($...$ or $$...$$).\n"
    "3. Graphs & Plots: Transcribe title, axis labels, legends, key data points, trends, and min/max values.\n"
    "4. Diagrams, Flowcharts & Architectures: Describe all nodes, connections, labels, and relationships in structured bullet points.\n"
    "5. Tables & Matrices: Format in standard Markdown tables.\n"
    "6. Screenshots of Code / Functions: Output in fenced code blocks with appropriate language tags.\n"
    "7. Forms & Receipts: Transcribe all line items, dates, prices, stamps, and signatures.\n"
    "Output ONLY the extracted structured content without pleasantries, conversational filler, or preamble."
)


def perform_vision_ocr(
    image_bytes: bytes,
    mime_type: str = "image/png",
    prompt_hint: str = "",
) -> str | None:
    """
    Synchronous Vision OCR using Gemini API.
    Encodes image to base64, invokes Gemini Vision cascade, and returns structured markdown text.
    """
    if not image_bytes:
        return None

    clean_mime = mime_type.split(";")[0].strip() or "image/png"
    b64_data = base64.b64encode(image_bytes).decode("ascii")

    prompt = prompt_hint if prompt_hint.strip() else DEFAULT_OCR_PROMPT
    payload = {
        "contents": [
            {
                "parts": [
                    {"inlineData": {"mimeType": clean_mime, "data": b64_data}},
                    {"text": prompt},
                ]
            }
        ],
        "generationConfig": {"temperature": 0.0, "maxOutputTokens": 2048},
    }

    models_to_try = [m for m in GEMINI_MODELS if "flash" in m or "pro" in m]
    if not models_to_try:
        models_to_try = ["gemini-flash-latest", "gemini-2.5-flash", "gemini-2.5-flash-lite"]

    keys_count = len(GEMINI_KEYS) or 1
    for model in models_to_try:
        for _ in range(min(keys_count, 3)):
            api_key = get_next_gemini_key()
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            try:
                with httpx.Client(timeout=15.0) as client:
                    resp = client.post(url, json=payload)
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
                            cleaned = str(raw_text).strip()
                            if cleaned:
                                log.info("Vision OCR extracted %d chars via %s", len(cleaned), model)
                                return cleaned
                    elif resp.status_code == 429:
                        log.warning("Rate limit (429) during Vision OCR on %s, rotating key...", model)
                        continue
                    elif resp.status_code == 404:
                        break
                    else:
                        log.warning("Vision OCR API error %d on %s: %s", resp.status_code, model, resp.text[:200])
            except Exception as e:
                log.warning("Vision OCR connection/timeout on %s: %s", model, e)
                continue

    return None


async def async_perform_vision_ocr(
    image_bytes: bytes,
    mime_type: str = "image/png",
    prompt_hint: str = "",
) -> str | None:
    """Async variant of perform_vision_ocr."""
    if not image_bytes:
        return None

    clean_mime = mime_type.split(";")[0].strip() or "image/png"
    b64_data = base64.b64encode(image_bytes).decode("ascii")

    prompt = prompt_hint if prompt_hint.strip() else DEFAULT_OCR_PROMPT
    payload = {
        "contents": [
            {
                "parts": [
                    {"inlineData": {"mimeType": clean_mime, "data": b64_data}},
                    {"text": prompt},
                ]
            }
        ],
        "generationConfig": {"temperature": 0.0, "maxOutputTokens": 2048},
    }

    models_to_try = [m for m in GEMINI_MODELS if "flash" in m or "pro" in m]
    if not models_to_try:
        models_to_try = ["gemini-flash-latest", "gemini-2.5-flash", "gemini-2.5-flash-lite"]

    keys_count = len(GEMINI_KEYS) or 1
    for model in models_to_try:
        for _ in range(min(keys_count, 3)):
            api_key = get_next_gemini_key()
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.post(url, json=payload)
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
                            cleaned = str(raw_text).strip()
                            if cleaned:
                                log.info("Async Vision OCR extracted %d chars via %s", len(cleaned), model)
                                return cleaned
                    elif resp.status_code == 429:
                        continue
                    elif resp.status_code == 404:
                        break
            except Exception as e:
                log.warning("Async Vision OCR error on %s: %s", model, e)
                continue

    return None
