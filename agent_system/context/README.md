# Context Builder

The context builder is intentionally cache-aware.

The stable prefix contains material that changes rarely. Ticket-specific data is appended afterward. Keep the stable prefix stable and avoid timestamps, random IDs, or run-specific information inside it.

This follows DeepSeek's automatic prefix cache behavior: overlapping prefixes can be served from cache, and usage exposes cache-hit/cache-miss token counts.
