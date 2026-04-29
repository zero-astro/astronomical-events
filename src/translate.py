"""Translation provider module — batch translation via OpenAI-compatible API.

Supported providers: lm-studio, ollama, openai
All use the OpenAI chat completions API format.
"""

import json
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

# Default provider configurations
PROVIDERS = {
    "lm-studio": {"api_base": "http://192.168.16.20:1234/v1", "model": "qwen3.6-35b-a3b"},
    "ollama":    {"api_base": "http://localhost:11434/v1", "model": None},  # user-specified
    "openai":    {"api_base": "https://api.openai.com/v1", "model": "gpt-4o-mini"},
}

# Translation prompt templates per language
TRANSLATION_PROMPTS = {
    "eu": """Translate the following English astronomical event titles to Basque (Euskara).
Return ONLY the translations, one per line, in the same order. Do not add any explanation or numbering.
DO NOT THINK ALOUD. DO NOT REPEAT THE PROMPT. JUST OUTPUT THE TRANSLATIONS.

{titles}

Translations:""",
    "ca": """Translate the following English astronomical event titles to Catalan (Català).
Return ONLY the translations, one per line, in the same order. Do not add any explanation or numbering.

{titles}

Translations:""",
    "gl": """Translate the following English astronomical event titles to Galician (Galego).
Return ONLY the translations, one per line, in the same order. Do not add any explanation or numbering.

{titles}

Translations:""",
    "es": """Translate the following English astronomical event titles to Spanish (Español).
Return ONLY the translations, one per line, in the same order. Do not add any explanation or numbering.

{titles}

Translations:""",
    "fr": """Translate the following English astronomical event titles to French (Français).
Return ONLY the translations, one per line, in the same order. Do not add any explanation or numbering.

{titles}

Translations:""",
}


def _get_api_key(provider: str) -> Optional[str]:
    """Get API key for provider from environment variables."""
    import os
    keys = {
        "openai": os.environ.get("OPENAI_API_KEY"),
        "ollama": None,  # No key needed
        "lm-studio": None,  # No key needed
    }
    return keys.get(provider)


def _call_api(messages: list, api_base: str, model: str, api_key: Optional[str] = None) -> str:
    """Call OpenAI-compatible chat completions API.

    Args:
        messages: List of message dicts with 'role' and 'content' keys
        api_base: Base URL of the API (e.g., http://localhost:1234/v1)
        model: Model name to use
        api_key: Optional API key

    Returns:
        Response text from the API
    """
    import os
    import urllib.request
    import urllib.error

    url = f"{api_base}/chat/completions"
    
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.3,  # Low temperature for consistent translations
        "max_tokens": 4096,
    }

    headers = {
        "Content-Type": "application/json",
    }
    
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    data = json.dumps(payload).encode("utf-8")
    
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    
    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            result = json.loads(response.read().decode("utf-8"))
            return result["choices"][0]["message"]["content"]
    except urllib.error.URLError as e:
        logger.error(f"API call failed to {url}: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error calling API at {url}: {e}")
        raise


def translate_batch(titles: list[str], target_lang: str, config: dict) -> list[str]:
    """Translate a batch of English titles to the target language.

    Args:
        titles: List of English title strings (max 20 per call)
        target_lang: Target language code (eu, ca, gl, es, fr)
        config: Provider configuration dict with keys:
            - provider: str ('lm-studio', 'ollama', 'openai')
            - api_base: str (API endpoint URL)
            - model: str (model name)

    Returns:
        List of translated strings in the same order as input

    Raises:
        ValueError: If target_lang is not supported or titles is empty
        RuntimeError: If API call fails
    """
    if not titles:
        raise ValueError("titles list cannot be empty")
    
    if len(titles) > 20:
        logger.warning(f"Batch size {len(titles)} exceeds recommended max of 20; splitting")
        mid = len(titles) // 2
        first = translate_batch(titles[:mid], target_lang, config)
        second = translate_batch(titles[mid:], target_lang, config)
        # Add delay between split calls
        time.sleep(3)
        return first + second
    
    if target_lang not in TRANSLATION_PROMPTS:
        raise ValueError(f"Unsupported language: {target_lang}. Supported: {list(TRANSLATION_PROMPTS.keys())}")
    
    provider = config.get("provider", "lm-studio")
    api_base = config.get("api_base", PROVIDERS[provider]["api_base"])
    model = config.get("model", PROVIDERS[provider]["model"])
    
    if not model:
        raise ValueError(f"Model not specified for provider '{provider}'")
    
    # Format the prompt with titles
    prompt_template = TRANSLATION_PROMPTS[target_lang]
    formatted_titles = "\n".join(titles)
    user_message = prompt_template.format(titles=formatted_titles)
    
    messages = [
        {"role": "system", "content": "You are a professional translator. You MUST return ONLY the translated text, one per line. NEVER add explanations, reasoning, or any other text. If you output anything besides pure translations, your response will be rejected."},
        {"role": "user", "content": user_message},
    ]
    
    api_key = _get_api_key(provider)
    
    try:
        response_text = _call_api(messages, api_base, model, api_key)
    except Exception as e:
        logger.error(f"Translation API call failed for {target_lang}: {e}")
        raise RuntimeError(f"Translation failed: {e}") from e
    
    # Parse response — extract actual translations from potentially verbose output
    # LM Studio models often include reasoning text before the actual answer.
    # Strategy: look for a line that starts with "Output:" or similar markers,
    # then take the next N non-empty lines as translations.
    
    raw_lines = response_text.strip().split("\n")
    
    # Try to find translation block after common markers
    start_idx = None
    for i, line in enumerate(raw_lines):
        stripped = line.strip()
        if stripped.lower() in ("output:", "translations:", "output", "translations"):
            start_idx = i + 1
            break
    
    # If no marker found, try to find the first line that looks like a translation
    # (not English, not code blocks, not reasoning)
    if start_idx is None:
        for i, line in enumerate(raw_lines):
            stripped = line.strip()
            # Skip empty lines, code fences, reasoning markers
            if not stripped or stripped.startswith("```") or "thinking" in stripped.lower():
                continue
            # If it looks like a translation (not starting with English words from prompt)
            start_idx = i
            break
    
    if start_idx is None:
        start_idx = 0
    
    # Collect non-empty lines after the marker
    lines = []
    for line in raw_lines[start_idx:]:
        stripped = line.strip()
        if stripped and not stripped.startswith("```"):
            lines.append(stripped)
        if len(lines) >= len(titles):
            break
    
    if len(lines) != len(titles):
        logger.warning(
            f"Expected {len(titles)} translations but got {len(lines)}. "
            f"Padding with original titles."
        )
        while len(lines) < len(titles):
            lines.append(titles[len(lines)])
    
    return lines[:len(titles)]


def translate_event(event, config: dict, target_lang: str) -> Optional[dict]:
    """Translate a single event's title and description.

    Args:
        event: Event object with 'title' and 'description' attributes
        config: Provider configuration dict
        target_lang: Target language code

    Returns:
        Dict with 'translated_title' and 'translated_description', or None on failure
    """
    try:
        # Translate title (batch of 1)
        translated_title = translate_batch([event.title], target_lang, config)[0]
        
        # Translate description if present
        translated_desc = ""
        if event.description:
            translated_desc = translate_batch([event.description], target_lang, config)[0]
        
        return {
            "translated_title": translated_title,
            "translated_description": translated_desc,
        }
    except Exception as e:
        logger.error(f"Failed to translate event '{getattr(event, 'title', '?')}': {e}")
        return None


def get_provider_config(provider_name: str = "lm-studio") -> dict:
    """Get provider configuration from environment or defaults.

    Args:
        provider_name: Provider name ('lm-studio', 'ollama', 'openai')

    Returns:
        Config dict with api_base, model, and provider keys
    """
    import os
    
    base = PROVIDERS[provider_name]["api_base"]
    model = PROVIDERS[provider_name]["model"]
    
    # Allow environment overrides
    env_prefix = f"TRANSLATION_{provider_name.upper()}"
    api_base_override = os.environ.get(f"{env_prefix}_API_BASE") or \
                        os.environ.get("TRANSLATION_API_BASE")
    model_override = os.environ.get(f"{env_prefix}_MODEL") or \
                     os.environ.get("TRANSLATION_MODEL")
    
    if api_base_override:
        base = api_base_override
    if model_override:
        model = model_override
    
    return {
        "provider": provider_name,
        "api_base": base,
        "model": model,
    }
