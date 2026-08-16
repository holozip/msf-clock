def classify_off_gap(duration_ms, on_run_ms):
    """Classify a completed carrier-off gap; returns (kind, a_bit, b_bit)."""
    if duration_ms < 50:
        return "ignored", 0, 0
    if 450 <= duration_ms <= 550:
        return "marker", 0, 0
    if 80 <= duration_ms <= 140 and 60 <= on_run_ms <= 160:
        return "b_bit", 0, 1
    a_bit, b_bit = 0, 0
    if 180 <= duration_ms <= 240:
        a_bit, b_bit = 1, 0
    elif 280 <= duration_ms <= 340:
        a_bit, b_bit = 1, 1
    return "second", a_bit, b_bit


def second_step(ms_since_ms):
    """Whole-second advance applied when a new data second starts."""
    elapsed = int(round(ms_since_ms / 1000.0))
    return elapsed if elapsed > 0 else 1
