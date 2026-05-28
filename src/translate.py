"""Translation provider module — batch translation via OpenAI-compatible API.

Supported providers: lm-studio, ollama, openai
All use the OpenAI chat completions API format.
"""

import json
import os
import re
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)


class TranslationError(Exception):
    """Raised when translation fails due to circuit breaker or API issues."""
    pass


# Circuit breaker state file path
circuit_breaker_file = os.path.join(os.path.dirname(__file__), "..", "data", "circuit_breaker.json")

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


def is_lm_studio_available() -> bool:
    """Check if LM Studio API is responding.

    Returns True if the health endpoint responds within 5 seconds.
    Used by circuit breaker to decide whether to skip translation.
    """
    import urllib.request
    try:
        req = urllib.request.Request(
            "http://192.168.16.20:1234/api/health",
            method="GET"
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status == 200
    except Exception:
        return False


def _check_circuit_breaker(provider: str) -> bool:
    """Check circuit breaker state. Returns True if translation is allowed.

    Circuit breaker opens after 3 consecutive failures and stays open for
    5 minutes. After that, it enters half-open state (allows one test request).
    If that succeeds, closes the circuit. If it fails, reopens.
    """
    import urllib.error
    
    if provider != "lm-studio":
        return True  # Only LM Studio needs circuit breaker
    
    # Check health first (fast path)
    if not is_lm_studio_available():
        logger.warning("LM Studio health check failed — skipping translation")
        raise TranslationError("LM Studio unavailable")
    
    # Load circuit breaker state
    cb_state = _load_circuit_breaker()
    
    if cb_state["state"] == "open":
        elapsed = time.time() - cb_state.get("last_failure", 0)
        recovery_timeout = cb_state.get("recovery_timeout", 300)  # 5 min
        
        if elapsed < recovery_timeout:
            remaining = int(recovery_timeout - elapsed)
            logger.warning(
                f"Circuit breaker OPEN — {remaining}s remaining "
                f"({cb_state.get('consecutive_failures', '?')} consecutive failures)"
            )
            raise TranslationError("Circuit breaker open")
        else:
            # Enter half-open state: allow one test request
            logger.info("Circuit breaker entering HALF-OPEN state (test request)")
            cb_state["state"] = "half-open"
            _save_circuit_breaker(cb_state)
    
    return True


def _record_success(provider: str):
    """Record successful API call — close circuit breaker."""
    if provider != "lm-studio":
        return
    cb_file = circuit_breaker_file
    if os.path.exists(cb_file):
        logger.info("Circuit breaker CLOSED after successful request")
        os.remove(cb_file)


def _record_failure(provider: str):
    """Record failed API call — open or increment circuit breaker."""
    if provider != "lm-studio":
        return
    cb_state = _load_circuit_breaker()
    cb_state["state"] = "open"
    cb_state["last_failure"] = time.time()
    cb_state["consecutive_failures"] = cb_state.get("consecutive_failures", 0) + 1
    logger.error(
        f"Circuit breaker OPEN — consecutive failures: {cb_state['consecutive_failures']}"
    )
    _save_circuit_breaker(cb_state)


def _load_circuit_breaker() -> dict:
    """Load circuit breaker state from file."""
    default = {
        "state": "closed",
        "last_failure": 0,
        "consecutive_failures": 0,
        "recovery_timeout": 300,  # 5 minutes
    }
    if os.path.exists(circuit_breaker_file):
        try:
            with open(circuit_breaker_file) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return default.copy()


def _save_circuit_breaker(state: dict):
    """Save circuit breaker state to file."""
    try:
        os.makedirs(os.path.dirname(circuit_breaker_file), exist_ok=True)
        with open(circuit_breaker_file, 'w') as f:
            json.dump(state, f)
    except IOError as e:
        logger.warning(f"Failed to save circuit breaker state: {e}")


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

    # Determine provider from api_base for circuit breaker
    provider = "lm-studio" if "192.168.16.20" in api_base else ("ollama" if "localhost:11434" in api_base else "openai")
    
    # Circuit breaker check (fast path — health check + state)
    _check_circuit_breaker(provider)

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
        # 180s timeout for local LLM (qwen3.6-35b needs time but not 5 min)
        with urllib.request.urlopen(req, timeout=180) as response:
            result = json.loads(response.read().decode("utf-8"))
            message = result["choices"][0]["message"]
            # Handle models with reasoning/thinking enabled (e.g., qwen3.6)
            content = message.get("content", "")
            if not content and "reasoning_content" in message:
                raw = message["reasoning_content"]
                # qwen3.6 outputs everything to reasoning_content (thinking mode).
                # Extract actual translation lines by looking for Basque text patterns.
                basque_indicators = [
                    r'Ilargia', r'Lurrarekiko', r'Lurrekiko', r'egongo da', r'izango da',
                    r'bere punturik', r'hurbilenean', r'hurbileneko', r'perigeo',
                ]
                basque_pattern = '|'.join(basque_indicators)
                lines = raw.split('\n')
                translation_lines = []
                for line in lines:
                    stripped = line.strip()
                    if not stripped or len(stripped) < 5:
                        continue
                    # Skip numbered steps and bullet points
                    if re.match(r'^\d+\.\s+', stripped):
                        continue
                    if re.match(r'^-\s+', stripped):
                        continue
                    # Check if line contains Basque text
                    if re.search(basque_pattern, stripped, re.IGNORECASE):
                        # Clean markdown and labels - extract only the translation sentence
                        cleaned = re.sub(r'[*`_]+', '', stripped)  # Remove markdown
                        cleaned = re.sub(r"""^['"]|['"]$""", '', cleaned.strip())  # Strip quotes
                        cleaned = re.sub(r'^.*?(?:translation|itzulpen):\s*', '', cleaned, flags=re.IGNORECASE)  # Strip label prefix
                        cleaned = cleaned.strip()
                        if cleaned and len(cleaned) > 3:
                            translation_lines.append(cleaned)
                content = '\n'.join(translation_lines).strip() if translation_lines else raw.strip()
            
            # Record success — close circuit breaker
            _record_success(provider)
            return content
    except urllib.error.URLError as e:
        logger.error(f"API call failed to {url}: {e}")
        _record_failure(provider)
        raise
    except Exception as e:
        logger.error(f"Unexpected error calling API at {url}: {e}")
        _record_failure(provider)
        raise


# ── Translation Cache (T1) ───────────────────────────────────────────────

_db_manager = None


def _get_db():
    """Lazily instantiate and return the DatabaseManager singleton."""
    global _db_manager
    if _db_manager is None:
        from pathlib import Path as _Path
        from db_manager import DatabaseManager  # type: ignore[import-not-found,unused-import]
        _db_path = str(_Path(__file__).parent.parent / "data" / "events.db")
        _db_manager = DatabaseManager(_db_path)
    return _db_manager


def translate_batch(
    titles: list[str],
    target_lang: str,
    config: dict,
    field_type: str = "title",
) -> list[str]:
    """Translate a batch of English strings to the target language.

    Args:
        titles: List of English source strings (max 20 per call).
        target_lang: Target language code (eu, ca, gl, es, fr).
        config: Provider configuration dict with keys:
            - provider: str ('lm-studio', 'ollama', 'openai')
            - api_base: str (API endpoint URL)
            - model: str (model name)
        field_type: Cache key hint — 'title', 'description',
                    'rich_description', or 'viewing_info'.

    Returns:
        List of translated strings in the same order as input.

    Raises:
        ValueError: If target_lang is not supported or titles is empty.
        RuntimeError: If API call fails.
    """
    if not titles:
        raise ValueError("titles list cannot be empty")

    # ── T1: Cache lookup — skip API for items already translated ────────
    db = _get_db()
    cached = []
    uncached_indices = []  # indices of items that need translation
    uncached_texts = []    # corresponding source texts

    for i, src in enumerate(titles):
        hit = db.get_cached_translation(src, target_lang, field_type=field_type)
        if hit is not None:
            cached.append((i, hit))
        else:
            uncached_indices.append(i)
            uncached_texts.append(src)

    # If everything is cached, return immediately — no API call needed.
    if len(cached) == len(titles):
        result = [None] * len(titles)
        for i, val in cached:
            result[i] = val
        return result

    # ── T1: Cache hit partial — pre-fill known positions ───────────────
    if cached:
        logger.info(
            f"Cache HIT {len(cached)}/{len(titles)} for '{field_type}' batch "
            f"(skipping API call for {len(cached)} items)"
        )

    # ── T1: Translate only the uncached portion ────────────────────────
    if uncached_texts:
        try:
            partial_results = _do_translate(uncached_texts, target_lang, config)
        except Exception as e:
            logger.error(f"Translation API call failed for {target_lang}: {e}")
            raise RuntimeError(f"Translation failed: {e}") from e

        # Store uncached results in cache and build final result
        result = [None] * len(titles)
        for i, val in cached:
            result[i] = val  # pre-filled cache hits
        for j, src_idx in enumerate(uncached_indices):
            translated = partial_results[j] if j < len(partial_results) else uncached_texts[j]
            result[src_idx] = translated
            db.store_translation_cache(
                uncached_texts[j], translated, target_lang, field_type=field_type
            )
        return result

    # ── T1: All items were cached (shouldn't reach here, but safety) ───
    result = [None] * len(titles)
    for i, val in cached:
        result[i] = val
    return result


def _do_translate(titles: list[str], target_lang: str, config: dict) -> list[str]:
    """Core translation logic — called only when cache misses exist.

    This is the original translate_batch body, extracted so that partial
    caching can call it for uncached items only.
    """
    if len(titles) > 20:
        logger.warning(f"Batch size {len(titles)} exceeds recommended max of 20; splitting")
        mid = len(titles) // 2
        first = _do_translate(titles[:mid], target_lang, config)
        second = _do_translate(titles[mid:], target_lang, config)
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
    except TranslationError as e:
        # Circuit breaker or health check failure — re-raise as-is
        logger.error(f"Translation skipped (circuit breaker/health): {e}")
        raise
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
    
    # If we got fewer translations than expected, try to split long lines
    # (model may have output a paragraph instead of line-by-line)
    if len(lines) < len(titles):
        expanded = []
        for line in lines:
            # Try splitting on common separators that might indicate multiple items
            parts = re.split(r'\n\s*\n|;\s*[A-Z]', line)
            if len(parts) > 1 and len(expanded) + len(parts) <= len(titles):
                expanded.extend([p.strip() for p in parts if p.strip()])
            else:
                expanded.append(line)
        lines = expanded
    
    # For single-item batches (rich_description, viewing_info), the model may output
    # a paragraph. In that case, use the whole response as one translation.
    if len(titles) == 1 and not lines:
        # Clean up the response - remove any reasoning/thinking artifacts
        cleaned = response_text.strip()
        # Remove common thinking/reasoning prefixes
        cleaned = re.sub(r'^.*?(?:translation|itzulpen):\s*', '', cleaned, flags=re.IGNORECASE)
        cleaned = cleaned.strip()
        if cleaned:
            lines.append(cleaned)
    
    if len(lines) != len(titles):
        logger.warning(
            f"Expected {len(titles)} translations but got {len(lines)}. "
            f"Padding with original titles."
        )
        while len(lines) < len(titles):
            lines.append(titles[len(lines)])
    
    return lines[:len(titles)]


def translate_event(event, config: dict, target_lang: str) -> Optional[dict]:
    """Translate a single event's title, description, rich_description, and viewing_info.

    Uses batch translation to reduce API calls:
    - Batch 1: title + description (combined in one call)
    - Batch 2: rich_description_en + viewing_info_en (combined in one call)

    This reduces total API calls from 4 per event to 2, cutting execution time by ~50%.

    Translation results are cached so that re-runs skip the API for unchanged content.

    Args:
        event: Event object with 'title', 'description', 'rich_description_en',
               and 'viewing_info_en' attributes
        config: Provider configuration dict
        target_lang: Target language code

    Returns:
        Dict with all translated fields, or None on failure
    """
    try:
        # Batch 1: Translate title + description together
        batch1_items = [event.title]
        if event.description:
            batch1_items.append(event.description)

        batch1_results = translate_batch(batch1_items, target_lang, config, field_type="title")
        translated_title = batch1_results[0]
        translated_desc = batch1_results[1] if len(batch1_results) > 1 else ""

        # Batch 2: Translate rich_description + viewing_info together (if present)
        translated_rich_desc = ""
        translated_viewing = ""

        has_rich = hasattr(event, 'rich_description_en') and event.rich_description_en
        has_viewing = hasattr(event, 'viewing_info_en') and event.viewing_info_en

        if has_rich or has_viewing:
            batch2_items = []
            if has_rich:
                batch2_items.append(event.rich_description_en)
            if has_viewing:
                batch2_items.append(event.viewing_info_en)

            if len(batch2_items) == 1:
                # Single item — no need to combine, just translate directly
                ft = "rich_description" if has_rich else "viewing_info"
                translated_rich_desc = (
                    translate_batch(batch2_items, target_lang, config, field_type=ft)[0]
                    if has_rich else ""
                )
                translated_viewing = (
                    translate_batch(batch2_items, target_lang, config, field_type=ft)[0]
                    if has_viewing else ""
                )
            else:
                # Two items — combine in one batch call
                batch2_results = translate_batch(
                    batch2_items, target_lang, config, field_type="rich_description"
                )
                idx = 0
                if has_rich:
                    translated_rich_desc = batch2_results[idx]
                    idx += 1
                if has_viewing:
                    translated_viewing = batch2_results[idx]

        return {
            "translated_title": translated_title,
            "translated_description": translated_desc,
            "translated_rich_description": translated_rich_desc,
            "translated_viewing_info": translated_viewing,
        }
    except Exception as e:
        logger.error(f"Failed to translate event '{getattr(event, 'title', '?')}': {e}")
        return None


def global_batch_translate(
    events: list,
    target_lang: str,
    config: dict,
) -> list[dict]:
    """Translate ALL fields from ALL events in a single batch per field type.

    Instead of calling translate_event() per event (2 API calls each), this
    collects every title/description/rich_description/viewing_info across all
    events and sends ONE batch call per field type — max 4 API calls total
    regardless of how many events there are.

    This is the O(1) global batching optimization (Option 1).

    Args:
        events: List of event objects with attributes:
            - title (str): English title
            - description (str): English description
            - rich_description_en (str, optional): English rich description
            - viewing_info_en (str, optional): English viewing info
        target_lang: Target language code (eu, ca, gl, es, fr)
        config: Provider configuration dict

    Returns:
        List of result dicts in the same order as input events, each containing:
            - translated_title
            - translated_description
            - translated_rich_description (empty string if not present)
            - translated_viewing_info (empty string if not present)
    """
    if not events:
        return []

    # ── Phase 1: Collect all fields from all events ────────────────────
    titles = []
    descriptions = []
    rich_descriptions = []
    viewing_infos = []

    for event in events:
        t = getattr(event, "title", "") or ""
        d = getattr(event, "description", "") or ""
        rd = getattr(event, "rich_description_en", "") or ""
        vi = getattr(event, "viewing_info_en", "") or ""

        titles.append(t)
        descriptions.append(d)
        rich_descriptions.append(rd)
        viewing_infos.append(vi)

    # ── Phase 2: Translate each field type in ONE batch call (sequential) ────
    # Note: LM Studio processes one request at a time, so parallel would not
    # speed things up — it would just queue requests. Sequential is fine.

    has_any_desc = any(d.strip() for d in descriptions)
    translated_descs = translate_batch(descriptions, target_lang, config, field_type="description") if has_any_desc else [""] * len(events)

    has_any_rd = any(rd.strip() for rd in rich_descriptions)
    translated_rds = translate_batch(rich_descriptions, target_lang, config, field_type="rich_description") if has_any_rd else [""] * len(events)

    has_any_vi = any(vi.strip() for vi in viewing_infos)
    translated_vis = translate_batch(viewing_infos, target_lang, config, field_type="viewing_info") if has_any_vi else [""] * len(events)

    # ── Phase 3: Distribute results back to each event ─────────────────
    results = []
    for i in range(len(events)):
        result = {
            "translated_title": translated_titles[i] if i < len(translated_titles) else titles[i],
            "translated_description": (
                translated_descs[i] if i < len(translated_descs) and descriptions[i].strip() else ""
            ),
            "translated_rich_description": (
                translated_rds[i] if i < len(translated_rds) and rich_descriptions[i].strip() else ""
            ),
            "translated_viewing_info": (
                translated_vis[i] if i < len(translated_vis) and viewing_infos[i].strip() else ""
            ),
        }
        results.append(result)

    logger.info(
        f"Global batch translate: {len(events)} events, {target_lang} — "
        f"{has_any_desc + has_any_rd + has_any_vi}/4 field batches sent"
    )

    return results


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
