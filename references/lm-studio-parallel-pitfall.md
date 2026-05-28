# LM Studio: No Parallel Translation

## The Problem

LM Studio's API server processes **one request at a time**. Submitting multiple concurrent requests does not speed things up — it just queues them.

### What NOT to do

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

with ThreadPoolExecutor(max_workers=2) as executor:
    futures = {
        executor.submit(translate_batch, titles, ...): "titles",
        executor.submit(translate_batch, descriptions, ...): "descs",
    }
```

This creates a queue of 2 requests that LM Studio processes one at a time. The overhead of thread management makes it **slower** than sequential calls.

### What to do instead

```python
# Sequential — simple and correct for LM Studio
translated_titles = translate_batch(titles, target_lang, config)
translated_descs = translate_batch(descriptions, target_lang, config)
```

## When Parallel IS Appropriate

| Provider | Concurrent? | Safe parallel workers |
|----------|-------------|----------------------|
| LM Studio (local) | No | 1 (sequential only) |
| Ollama (`--parallel` flag) | Yes | 2-4 depending on GPU |
| OpenAI API | Yes | 5-10+ (rate-limited by API) |
| Ollama (default, no --parallel) | No | 1 (sequential only) |

## Session Reference

Tested in May 28 2026 session: `ThreadPoolExecutor(max_workers=2)` was added to `global_batch_translate()`, then reverted after user pointed out LM Studio's single-request limitation. The fix is documented in SKILL.md pitfalls table and the "Parallel Translation Note" section.
