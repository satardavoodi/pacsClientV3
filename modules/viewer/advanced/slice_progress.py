"""Present preview availability without changing the native slice range."""


def slice_counter_text(metadata, available_count, display_number):
    available = max(0, int(available_count))
    current = max(0, int(display_number)) if available else 0
    if not isinstance(metadata, dict) or not metadata.get("preview_only"):
        return f"{current} / {available}"
    try:
        known_total = int(metadata.get("preview_total_instances") or 0)
    except (TypeError, ValueError, OverflowError):
        known_total = 0
    if known_total > available:
        # VTK treats an unescaped pipe as MathText column syntax, importing
        # Matplotlib during the first render. This status label is plain text.
        return f"{current} / {known_total} ({available} ready)"
    # Unknown total, multiframe files or an unfiltered preview must not imply
    # that full filtered loading is already finished. Ignore stale totals.
    return f"{current} / {available} (Loading)"
