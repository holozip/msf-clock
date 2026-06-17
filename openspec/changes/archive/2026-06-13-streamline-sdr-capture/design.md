## Context

Current state: `src/msf_clock/capture.py` is a single 241-line module with five top-level functions (`find_sdr`, `setup_stream`, `capture_iq`, `main`) plus module-level constants. All concerns — device enumeration, stream setup, sample capture loop, file I/O, metadata generation, and CLI parsing — live in one file with no separation.

The project targets SDRPlay RSPduo hardware, captures 1 MHz bandwidth centered on 60 kHz (MSF time signal), and outputs GQRX-compatible `.cfile` (interleaved float32 I/Q) with a JSON metadata sidecar. No tests exist. The code works but is opaque to newcomers.

The RSPduo minimum sample rate is 200 ksps, which means the analog bandwidth is always wide (200 kHz+). This makes the weak 60 kHz MSF signal nearly invisible in GQRX's waterfall display due to the high noise floor. Software decimation (capture at 1-2 Msps, then decimate to 25 ksps) reduces the displayed bandwidth to 25 kHz, dramatically improving SNR and making the MSF signal clearly visible.

Constraints:
- Must preserve all existing CLI flags and behavior
- No new dependencies allowed
- Must work with SoapySDR + SDRPlay3 driver stack on Ubuntu/Debian
- Output must be directly loadable in GQRX
- RSPduo antenna: "Tuner 1 Hi-Z" only (long wire antenna)

## Goals / Non-Goals

**Goals:**
- Improve code readability by separating concerns into logical modules or clearly structured classes
- Add docstrings explaining the SDR signal chain (RF → downconversion → IQ demodulation → file format)
- Document the GQRX `.cfile` format and verify correctness
- Make individual components independently testable (mockable SDR device, file I/O separation)

**Non-Goals:**
- Adding signal decoding (MSF bit extraction) — that's a separate concern
- Adding new CLI flags or changing existing ones
- Adding real-time streaming or GUI
- Supporting additional SDR hardware models

## Decisions

### 1. Keep as a single file, restructure with classes and clear function boundaries
**Rationale:** The project is small (one module). Introducing a package with multiple files adds complexity without proportional benefit. Instead, restructure within `capture.py` using:
- A `SDRCaptureEngine` class encapsulating device, stream, and capture state
- Free functions for CLI parsing and file I/O
- Clear section comments dividing the file into logical blocks

This keeps the entry point simple (`msf-capture` console script) while making the code navigable.

### 2. Use a context manager for SDR device lifecycle
**Rationale:** The current code manually calls `sdr.deactivateStream()`, `sdr.closeStream()`, and `sdr.close()` in a try/finally. A context manager (`__enter__`/`__exit__`) guarantees cleanup even on exceptions and makes the capture flow easier to follow.

### 3. Separate GQRX file writing into its own function with explicit format validation
**Rationale:** The `.cfile` format has specific requirements:
- Interleaved float32: `[I0, Q0, I1, Q1, ...]`
- Values normalized to [-1.0, 1.0] from int16 (dividing by 32768)
- Optional `.cfile.json` metadata sidecar

Document these requirements explicitly and add a validation step that writes a small test pattern and verifies the output structure.

### 4. No refactoring of the capture loop itself
**Rationale:** The chunked read loop (65536-sample chunks) is already correct for handling RSPduo's streaming behavior. The logic is sound; it just needs comments explaining why chunking is necessary.

### 5. Apply software decimation after capture for GQRX display
**Rationale:** The RSPduo minimum sample rate is 200 ksps, which gives a 200 kHz+ analog bandwidth. At this bandwidth, the weak MSF 60 kHz signal (received via long 20m wire on Hi-Z) is buried in the noise floor and appears as a flickering speckle in GQRX's waterfall.

By capturing at 1-2 Msps and applying a moving-average FIR decimation filter (factor 40), we reduce to 25 ksps output bandwidth. The moving average provides anti-aliasing, and the narrower bandwidth improves SNR by ~16 dB (10·log₁₀(40)). The decimated output is clipped to [-1, 1] to maintain GQRX compatibility.

Trade-offs:
- Capture still uses 1-2 Msps USB bandwidth (RSPduo limitation)
- Decimation introduces ~1 sample latency (moving average window)
- Clipping can cause minor amplitude distortion at peaks
- Output sample rate is fixed at 25 ksps (input_rate / 40)

## Risks / Trade-offs

| Risk | Mitigation |
|------|-----------|
| Refactoring introduces a regression in capture behavior | Preserve all CLI flags; run `--probe` and a short capture before/after to verify |
| GQRX compatibility breaks silently | Add a format validation step that checks byte layout and metadata |
| Class-based refactoring makes the simple CLI flow harder to follow | Keep `main()` as a thin wrapper that calls engine methods sequentially |
| No existing tests to guard against regressions | At minimum, add a unit test for the `.cfile` serialization function using numpy-generated data (no hardware needed) |
