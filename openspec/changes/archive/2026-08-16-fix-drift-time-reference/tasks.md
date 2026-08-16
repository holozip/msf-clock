## 1. Implementation (src/msf_clock/msf.py)

- [x] 1.1 Add register `falling_edge_wall_dt = None` beside `minute_trigger_system_time` (SYSTEM TIMESTAMP CAPTURE section, ~line 43)
- [x] 1.2 In the falling-edge branch of the edge state machine (~lines 94–95), set `falling_edge_wall_dt = datetime.datetime.now(datetime.timezone.utc)`
- [x] 1.3 In the minute-marker branch (~lines 104–117), use the stored `falling_edge_wall_dt` for `captured_system_dt`, with a fallback to a rising-edge `datetime.now(utc)` snapshot if it is `None`
- [x] 1.4 Confirm `minute_trigger_system_time`, the `decoder.print_atomic_clock(...)` call, and all printed output are otherwise unchanged; `decoder.py` untouched
- [x] 1.5 Syntax check: `python -m py_compile src/msf_clock/msf.py`

## 2. Verification

- [x] 2.1 Live SDR run (user): verify reported drift is shifted by ≈ −500 ms versus previous runs and is near 0 for a clock close to UTC (bias gone) — verified 2026-08-16: drift +0.051 s (was ≈ +0.55 s); residual is uncalibrated pipeline latency, expected
- [x] 2.2 Commit as a single commit on branch `accuracy-fixes`
