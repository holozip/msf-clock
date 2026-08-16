# Fix Drift Time Reference

## Why

Every reported "Total Calculated Drift" is systematically biased by ~+0.5 s. The minute marker is the 500 ms carrier-OFF period at second 00, and the code snapshots system time at the **end** of that OFF period (the rising edge, t=+500 ms) while `decoder.py` treats the snapshot as the **start** of the minute. The NPL MSF specification guarantees timing accuracy (better than ±1 ms vs UTC) for the second marker's off **onset** (falling edge) — the rise/fall edge shapes of the OFF period's end are not specified. Using the wrong edge makes the drift display (and its "PERFECTLY IN SYNC" threshold) meaningless.

## What Changes

- `msf.py`: record the wall-clock instant when a falling edge (carrier ON→OFF) occurs; when the resulting OFF period is classified as the minute marker (450–550 ms), use that stored falling-edge instant as the drift snapshot instead of the rising-edge instant
- `decoder.py`: no semantic change — it continues to receive a system-time snapshot at the minute boundary, which is now correctly referenced to the off onset
- No change to bit decoding, output format, CLI, or dependencies

## Capabilities

### New Capabilities

_(none)_

### Modified Capabilities

- `demodulate`: drift measurement SHALL be referenced to the off onset (falling edge) of the minute marker; the end of the marker's OFF period SHALL NOT be used as the time reference

## Impact

- **Code**: `src/msf_clock/msf.py` (few lines in the edge state machine / minute-marker branch)
- **Observable behavior**: reported drift values shift by ~−0.5 s; the "PERFECTLY IN SYNC" threshold now measures what it claims (residual pipeline latency remains, tracked separately)
- **No breaking changes** to API, CLI, or file formats
