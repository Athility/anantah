"""
ai_services/voice_cataloger.py
================================
Multilingual Auto-Cataloger pipeline for Anantah.
Fully hosted — no local AI inference anywhere.

Pipeline:
    audio file  →  transcribe_and_translate()  (Groq Whisper primary → HF Whisper fallback)
                →  generate_catalog_entry()    (Groq LLaMA → bilingual SEO title + description)
                →  {title_en, title_hi, description_en, description_hi}

All external API calls are isolated here so providers can be swapped without
touching views or serializers.

Stage annotations:
  # [GROQ WHISPER]   – primary ASR+translation path (Groq hosted Whisper-large-v3)
  # [HF FALLBACK]    – secondary ASR path (Hugging Face Inference API)
  # [GROQ LLM]       – bilingual SEO description generation (Groq LLaMA)
"""

import io
import json
import logging
import time
import requests
from decouple import config, UndefinedValueError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config — read from .env via python-decouple (same pattern as the rest of the project)
# ---------------------------------------------------------------------------

def _get_cfg(key, default=None):
    """Return a config value without raising if the key is absent."""
    try:
        return config(key)
    except UndefinedValueError:
        return default


GROQ_API_KEY = _get_cfg('GROQ_API_KEY')
HF_API_TOKEN = _get_cfg('HF_API_TOKEN')
LLM_API_KEY  = _get_cfg('LLM_API_KEY')   # Also used for Groq LLM; can be same as GROQ_API_KEY

# HuggingFace Inference API endpoint for Whisper-large-v3 (automatic speech recognition)
HF_WHISPER_URL = "https://api-inference.huggingface.co/models/openai/whisper-large-v3"

# Groq API endpoints
GROQ_TRANS_URL = "https://api.groq.com/openai/v1/audio/translations"
GROQ_CHAT_URL  = "https://api.groq.com/openai/v1/chat/completions"

# Timeout constants (seconds)
GROQ_TIMEOUT = 90   # Groq Whisper is fast but audio upload takes time
HF_TIMEOUT   = 120  # HF cold-start can be slow; first call after idle takes ~20-30s


# ===========================================================================
# PUBLIC API — called by listings/views.py
# ===========================================================================

def transcribe_and_translate(audio_file) -> str:
    """
    Transcribe an audio file and translate to English in a single operation.

    Uses Groq Whisper-large-v3 with task="translate" as the primary path.
    Falls back to Hugging Face Inference API on Groq failure/rate-limit/timeout.
    If both fail, raises RuntimeError with a user-friendly message.

    Args:
        audio_file: A Django InMemoryUploadedFile or any file-like object.
                    Must support .read() and .name attributes.

    Returns:
        English transcript as a plain string.

    Raises:
        RuntimeError: with a human-readable message surfaced to the artisan.
    """
    audio_file.seek(0)
    audio_bytes = audio_file.read()
    filename    = getattr(audio_file, 'name', 'audio.webm')

    # ------------------------------------------------------------------
    # [GROQ WHISPER] — Primary path
    # Groq hosts Whisper-large-v3. The translations endpoint transcribes audio
    # in any language AND translates the output to English in one API call.
    # ------------------------------------------------------------------
    groq_error = None
    if GROQ_API_KEY:
        try:
            logger.info("[GROQ WHISPER] Attempting transcription + translation via Groq Whisper-large-v3")
            english_text = _transcribe_groq(audio_bytes, filename)
            logger.info("[GROQ WHISPER] Success: %d chars", len(english_text))
            return english_text
        except RuntimeError as e:
            groq_error = str(e)
            logger.warning("[GROQ WHISPER] Failed: %s — trying HF fallback", groq_error)
    else:
        groq_error = "GROQ_API_KEY not set in environment."
        logger.warning("[GROQ WHISPER] Skipped: %s", groq_error)

    # ------------------------------------------------------------------
    # [HF FALLBACK] — Secondary path
    # Only triggered when Groq fails. Uses Hugging Face Inference API
    # running whisper-large-v3 for transcription.
    # HF Whisper returns English text when the model auto-detects language.
    # ------------------------------------------------------------------
    if HF_API_TOKEN:
        try:
            logger.info("[HF FALLBACK] Attempting transcription via HuggingFace Inference API")
            english_text = _transcribe_hf(audio_bytes)
            logger.info("[HF FALLBACK] Success: %d chars", len(english_text))
            return english_text
        except RuntimeError as e:
            hf_error = str(e)
            logger.error("[HF FALLBACK] Failed: %s", hf_error)
            raise RuntimeError(
                "Voice processing is temporarily unavailable, please try again in a moment. "
                f"(Groq: {groq_error} | HF: {hf_error})"
            )
    else:
        logger.error("[HF FALLBACK] Skipped: HF_API_TOKEN not set in environment.")

    # ------------------------------------------------------------------
    # [GRACEFUL FAILURE] — Both providers failed or unconfigured
    # We do NOT crash the upload flow (the caller already saved the audio).
    # Return a clear error the frontend can display to the artisan.
    # ------------------------------------------------------------------
    raise RuntimeError(
        "Voice processing is temporarily unavailable, please try again in a moment."
    )


def generate_catalog_entry(
    english_transcript: str,
    category_name: str = '',
    existing_title_en: str = '',
    source_language: str = 'hi',
) -> dict:
    """
    Use Groq LLM to rewrite an English transcript into a professional,
    SEO-friendly product listing in both English and the selected regional language.

    Args:
        english_transcript: The English text from transcribe_and_translate().
        category_name: Product category (e.g. "Pottery", "Textile") for context.
        existing_title_en: If the artisan already entered a title, we preserve it
                           and only generate title_hi + descriptions.
        source_language: BCP-47 language code of regional translation (default 'hi').

    Returns:
        Dict with keys: title_en, title_hi, description_en, description_hi

    Raises:
        RuntimeError: with a human-readable message if generation fails.
    """
    # Use LLM_API_KEY if set, else fall back to GROQ_API_KEY (they can be the same key)
    api_key = LLM_API_KEY or GROQ_API_KEY
    if not api_key:
        raise RuntimeError(
            "Description generation failed: neither LLM_API_KEY nor GROQ_API_KEY is set in .env. "
            "Add your Groq API key to enable this feature."
        )

    return _generate_groq_llm(english_transcript, category_name, existing_title_en, api_key, source_language)


# ===========================================================================
# INTERNAL HELPERS
# ===========================================================================

# Language code to Name and Description map for LLM prompting
LANG_MAP = {
    'hi': ('Hindi', 'Hindi (Devanagari script)'),
    'mr': ('Marathi', 'Marathi (Devanagari script)'),
    'gu': ('Gujarati', 'Gujarati (Gujarati script)'),
    'ta': ('Tamil', 'Tamil (Tamil script)'),
}

def _transcribe_groq(audio_bytes: bytes, filename: str) -> str:
    """
    [GROQ WHISPER] Call Groq's hosted Whisper-large-v3 translations endpoint.
    This performs ASR + English translation in a single API call — no separate
    translation step needed.
    Docs: https://console.groq.com/docs/speech-text
    """
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is not configured.")

    # Groq audio API accepts multipart/form-data — same interface as OpenAI Whisper
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
    }

    # Determine a sensible MIME type for the upload
    fname_lower = filename.lower()
    if fname_lower.endswith('.mp3'):
        mime = 'audio/mpeg'
    elif fname_lower.endswith('.m4a'):
        mime = 'audio/mp4'
    elif fname_lower.endswith('.ogg'):
        mime = 'audio/ogg'
    elif fname_lower.endswith('.flac'):
        mime = 'audio/flac'
    elif fname_lower.endswith('.wav'):
        mime = 'audio/wav'
    else:
        mime = 'audio/webm'  # Default for browser MediaRecorder output

    files = {
        'file': (filename, audio_bytes, mime),
    }
    data = {
        'model':           'whisper-large-v3',
        'response_format': 'text',             # Plain text response (not JSON)
        'temperature':     '0',                # Deterministic output
    }

    try:
        response = requests.post(
            GROQ_TRANS_URL,
            headers=headers,
            files=files,
            data=data,
            timeout=GROQ_TIMEOUT,
        )

        if response.status_code == 429:
            # Rate limited — trigger HF fallback
            raise RuntimeError(f"Groq rate limit hit (429). Retry-After: {response.headers.get('Retry-After', 'unknown')}s")

        if not response.ok:
            raise RuntimeError(
                f"Groq Whisper API returned HTTP {response.status_code}: {response.text[:200]}"
            )

        transcript = response.text.strip()
        if not transcript:
            raise RuntimeError("Groq Whisper returned an empty transcript.")

        return transcript

    except requests.Timeout:
        raise RuntimeError(f"Groq Whisper API timed out after {GROQ_TIMEOUT}s.")
    except requests.RequestException as e:
        raise RuntimeError(f"Groq Whisper network error: {str(e)}")


def _transcribe_hf(audio_bytes: bytes) -> str:
    """
    [HF FALLBACK] Transcribe using Hugging Face Inference API running whisper-large-v3.
    Called ONLY when Groq fails. HF cold-starts can take 20-30s on free tier.
    Docs: https://huggingface.co/docs/api-inference/tasks/automatic-speech-recognition
    """
    if not HF_API_TOKEN:
        raise RuntimeError("HF_API_TOKEN is not configured.")

    headers = {
        "Authorization": f"Bearer {HF_API_TOKEN}",
        "Content-Type":  "audio/wav",  # HF Inference API accepts raw audio bytes
    }

    try:
        response = requests.post(
            HF_WHISPER_URL,
            headers=headers,
            data=audio_bytes,
            timeout=HF_TIMEOUT,
        )

        if response.status_code == 503:
            # Model is loading (cold start) — give it a moment and retry once
            logger.warning("[HF FALLBACK] Model loading (503), waiting 25s for cold start...")
            time.sleep(25)
            response = requests.post(
                HF_WHISPER_URL,
                headers=headers,
                data=audio_bytes,
                timeout=HF_TIMEOUT,
            )

        if not response.ok:
            raise RuntimeError(
                f"HuggingFace Inference API returned HTTP {response.status_code}: {response.text[:200]}"
            )

        result = response.json()

        # HF returns {"text": "..."} for ASR tasks
        transcript = result.get('text', '').strip()
        if not transcript:
            raise RuntimeError("HuggingFace Whisper returned an empty transcript.")

        return transcript

    except requests.Timeout:
        raise RuntimeError(f"HuggingFace Inference API timed out after {HF_TIMEOUT}s.")
    except requests.RequestException as e:
        raise RuntimeError(f"HuggingFace Inference API network error: {str(e)}")
    except (ValueError, KeyError) as e:
        raise RuntimeError(f"HuggingFace API returned unexpected response format: {str(e)}")


def _generate_groq_llm(
    english_transcript: str,
    category_name: str,
    existing_title_en: str,
    api_key: str,
    source_language: str = 'hi',
) -> dict:
    """
    [GROQ LLM] Call Groq Chat Completions API (Qwen 3.8 27B) to generate
    both English and dynamic regional language product catalog fields.
    """
    lang_name, lang_desc = LANG_MAP.get(source_language, ('Hindi', 'Hindi (Devanagari script)'))

    category_hint = (
        f" The product belongs to the '{category_name}' category." if category_name else ""
    )
    title_hint = (
        f" The artisan has already provided this English title: '{existing_title_en}'. "
        "Use it verbatim for title_en but still generate a natural title in the target language."
        if existing_title_en else ""
    )

    system_prompt = (
        "You are an expert e-commerce copywriter specialising in Indian handmade products. "
        "You write SEO-friendly, warm, and authentic product listings that honour the artisan's voice. "
        f"You are fluent in both English and {lang_name} ({lang_desc}). "
        "Always respond with valid JSON only — no markdown, no extra text."
    )

    user_prompt = f"""An artisan described their product as follows (translated to English from their regional language):

"{english_transcript}"
{category_hint}{title_hint}

Generate a professional e-commerce product listing. Return ONLY a JSON object with these exact keys:
- title_en: Short, SEO-friendly English product title (max 80 chars)
- title_hi: Same as title_en (English title). Do NOT translate the title into the regional language. It must be in English.
- description_en: 3–5 sentence English product description. Mention materials, craft technique, use cases, and cultural significance where relevant. Include natural SEO keywords.
- description_hi: The same description in fluent, natural {lang_name} ({lang_desc}) — not a word-for-word translation, but an authentic {lang_name} copywriter's voice.

JSON response only:"""

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type":  "application/json",
    }
    payload = {
        "model":           "qwen/qwen3.8-27b",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        "temperature":     0.7,
        "max_tokens":      1024,
        "response_format": {"type": "json_object"},  # Force strict JSON output
    }

    try:
        response = requests.post(
            GROQ_CHAT_URL,
            headers=headers,
            json=payload,
            timeout=60,
        )

        if not response.ok:
            raise RuntimeError(
                f"Groq LLM API returned HTTP {response.status_code}: {response.text[:200]}"
            )

        raw_json = response.json()['choices'][0]['message']['content'].strip()
        result   = json.loads(raw_json)

        # Validate all expected keys are present
        for key in ('title_en', 'title_hi', 'description_en', 'description_hi'):
            if key not in result:
                raise RuntimeError(
                    f"Description generation failed: LLM response missing key '{key}'."
                )

        # Preserve the artisan's manually-entered English title if provided
        if existing_title_en:
            result['title_en'] = existing_title_en

        logger.info("[GROQ LLM] Catalog entry generated successfully.")
        return result

    except json.JSONDecodeError as e:
        raise RuntimeError(f"Description generation failed: LLM returned invalid JSON — {str(e)}")
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"Description generation failed: unexpected Groq LLM response structure — {str(e)}")
    except requests.Timeout:
        raise RuntimeError("Description generation failed: Groq LLM API timed out.")
    except requests.RequestException as e:
        raise RuntimeError(f"Description generation failed: Groq LLM network error — {str(e)}")
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Description generation failed unexpectedly: {str(e)}")
