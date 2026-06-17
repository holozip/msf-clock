## Why

The SDR signal capture code in `capture.py` is a single 240-line function-heavy module that mixes device discovery, stream configuration, sample capture, file I/O, and CLI argument parsing. This makes it hard to understand, modify, or test. The capture output also needs to be verified as fully compatible with GQRX's `.cfile` format so it loads and plays correctly without manual conversion.

## What Changes

- Refactor `capture.py` into a clean, modular package with separate concerns (device management, stream setup, capture loop, file writing, CLI)
- Extract each major function into clearly named, independently testable components
- Add docstrings and inline comments explaining the SDR signal chain and GQRX file format
- Verify and document the GQRX `.cfile` output format (interleaved float32 I/Q, normalization, metadata sidecar)
- Ensure the output is directly loadable in GQRX without any post-processing
- Add software decimation (factor 40) to reduce 1 Msps capture bandwidth to 25 ksps for GQRX waterfall display

## Capabilities

### New Capabilities
- `sdr-capture`: Requirements for SDR IQ signal capture from SDRPlay RSPduo, including device discovery, stream configuration, sample acquisition, and GQRX-compatible file output

## Impact

- Affected code: `src/msf_clock/capture.py` (entire file refactored)
- No API or CLI interface changes — all existing flags (`-f`, `-r`, `--n`, `-o`, `-d`, `--device-addr`, `--probe`) preserved
- No new dependencies — still uses only numpy and SoapySDR
