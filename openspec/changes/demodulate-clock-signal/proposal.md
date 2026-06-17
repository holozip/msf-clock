# Demodulate Clock Signal

## Why

The capture module produces raw IQ samples, but the MSF time code is encoded as **1-second-level transitions** (0.1s carrier-off for logical 1, 0.5s carrier-on for logical 0). Without demodulation, the signal remains an opaque blob of samples. Demodulating the MSF signal into a stream of edge transitions bridges the gap between raw capture and time decoding.

## What Changes

- Add a new `demodulate.py` module that takes IQ sample data (from capture output or live stream) and produces a chronological stream of edge transitions (rising/falling carrier edges with timestamps)
- The module will implement envelope detection or zero-crossing-based demodulation to recover the 1 Hz clock markers and derive the 1-second-level bit stream
- No actual time/date decoding — only edge transitions and bit-level reconstruction

## Capabilities

### New Capabilities
- `demodulate`: Demodulate MSF IQ samples into edge transitions and bit-level data

### Modified Capabilities
_(none — only new capability)_

## Impact

- **New file**: `src/msf_clock/demodulate.py` (~200-300 lines)
- **New dependency**: `scipy` for signal processing (envelope detection, filtering)
- **API**: Exposes a `demodulate_samples(samples, sample_rate)` function and a CLI entry point
- **No breaking changes** to existing capture module
