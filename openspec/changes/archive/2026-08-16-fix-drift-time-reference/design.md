## Context

`msf.py` runs a live SDR loop at 1 MHz, decimating 1000 complex samples into one 1 ms envelope value, then classifies carrier OFF periods into a 60-second frame. The minute marker is the 450–550 ms OFF period at second 00. On detecting its **rising edge** (end of the OFF period, t=+500 ms) the code snapshots `datetime.now(utc)` (msf.py:105) into `minute_trigger_system_time`, and `decoder.py` later computes drift as that snapshot minus the minute reference reconstructed from the frame bits.

The NPL MSF specification guarantees the second marker's **off onset** (falling edge) to better than ±1 ms vs UTC; the OFF period's trailing edge shape is unspecified ("determined by the combination of antenna and transmitter"). Since the marker OFF lasts exactly 500 ms, snapshotting at the rising edge while referencing the minute **start** biases every drift reading by +0.5 s.

## Goals / Non-Goals

**Goals:**
- Reference the drift measurement to the off onset (falling edge) of the minute marker
- Remove the systematic +0.5 s bias from the reported drift
- Zero changes to bit decoding, output format, or `decoder.py` semantics

**Non-Goals:**
- Pipeline latency calibration (SDR/USB/Python processing delay remains in the measurement; separate issue)
- Envelope decimation fix (`abs(mean(x))` cancellation issue), threshold robustness, DUT1 split-pulse handling (deferred per user), frame structural validation, output label fixes

## Decisions

1. **Capture wall-clock at the falling edge, reuse it at marker confirmation.**
   A new register `falling_edge_wall_dt` is set (via `datetime.now(utc)`) whenever a falling edge is detected. When the resulting OFF period classifies as the minute marker, the stored falling-edge instant becomes the drift snapshot (`captured_system_dt`).
   - *Alternative rejected (reconstruct):* snapshot the rising edge and subtract the measured OFF width. This adds quantization error from both edge measurements (1 ms decimation grid + threshold-lag asymmetry on each edge), when the falling-edge instant is already directly observed — no arithmetic needed.
   - *Alternative rejected (sample-clock):* derive the reference from `global_ms_counter` × 1 ms. That ties the reference to the SDR's crystal (ppm-erroneous sample clock) rather than system time, changing the meaning of the drift output.
2. **Keep the existing data flow.** `minute_trigger_system_time`, the `decoder.print_atomic_clock(...)` call, and all printed output stay unchanged in shape; only the instant stored changes. `decoder.py` is untouched.
3. **Defensive fallback.** If `falling_edge_wall_dt` is ever `None` at marker classification (e.g. state anomaly), fall back to the old rising-edge snapshot so the receiver keeps running with the legacy behaviour instead of crashing or printing nothing.

## Risks / Trade-offs

- [Falling-edge wall-clock still contains the same uncalibrated pipeline latency L] → only the 500 ms systematic component is removed; L is a separate calibration concern (review item, out of scope). Expected drift shift on live signal ≈ −500 ms toward the true small offset.
- [Extra `datetime.now()` call on every falling edge (marker + all data-second pulses, <70/min)] → microsecond cost, negligible throughput impact at this processing rate.
- [No synthetic test harness exists in the repo] → verification is a live SDR run: compare drift before/after (user-assisted), expecting the +0.5 s bias to disappear.

## Migration Plan

Single small commit on the `accuracy-fixes` branch; rollback = revert the commit. No data, format, or API migration.

## Open Questions

None.
