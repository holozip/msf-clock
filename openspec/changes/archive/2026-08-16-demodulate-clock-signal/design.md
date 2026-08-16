# Design: Demodulate Clock Signal

## Context

The capture module saves raw IQ samples in GQRX `.raw` format (interleaved float32, CF32). The MSF 60 kHz signal encodes time data using **on-off keying** of the carrier at 1 Hz resolution.

Per the NPL specification (`docs/msf-time-date-code-2019.txt`):

- Every second boundary is marked by a **100 ms carrier-off** pulse (preceded by ≥500 ms of carrier)
- Within each second, **two bits** are transmitted: one in the **A channel** (even seconds) and one in the **B channel** (odd seconds)
- **Bit polarity**: carrier **on** = logical **0**, carrier **off** = logical **1**
- A bit is represented by a **100 ms carrier-off** pulse at the appropriate position within the second
- The minute begins with a **500 ms carrier-off** period (minute marker)
- Each second (except the minute marker) has ≥100 ms off at the start and ≥700 ms carrier on at the end
- Seconds 01-16 carry the DUT1 code; the remaining seconds carry the time/date code
- A unique marker sequence `01111110` in bit A uniquely identifies the start of the minute

The captured samples are at 1 Msps (1 MHz bandwidth), far exceeding the ~1 Hz signal bandwidth. Demodulation must recover the on/off carrier state to extract the bit stream.

## Goals / Non-Goals

**Goals:**
- Convert raw IQ samples into a chronological stream of edge timestamps (carrier on/off transitions)
- Reconstruct the bit stream (one bit per 100 ms slot within each second)
- Provide a clean API: `demodulate_samples(samples, sample_rate) -> DemodulationResult`
- Support both file-based (from capture output) and live-stream usage
- Work with decimated data (25 ksps) that shows the signal clearly

**Non-Goals:**
- Decoding the time/date from the bit stream (next change)
- Real-time processing (batch-only for now)
- Automatic gain control or signal strength normalization
- Handling multiple captures or stitching
- Leap second handling (61-second minutes)

## Decisions

### 1. Demodulation approach: envelope detection via analytic signal
**Decision**: Use `scipy.signal.hilbert` to compute the analytic signal, then take the magnitude as the envelope. Threshold the envelope to recover the on/off carrier state.

**Rationale**: 
- The MSF signal is a narrowband AM signal — envelope detection is the simplest and most robust method
- Hilbert transform gives a clean analytic signal without needing a custom bandpass filter
- Alternative: zero-crossing detection — more complex, less robust to noise
- Alternative: FFT-based carrier extraction — overkill for a single known frequency

### 2. Decimation before demodulation
**Decision**: Demodulate the decimated data (25 ksps from factor-40 moving average) rather than raw 1 Msps data.

**Rationale**:
- 40x reduction in data volume (from 10M samples to 250k for a 10s capture)
- The MSF signal bandwidth (~1 Hz) is far below the decimated Nyquist frequency (12.5 kHz)
- SNR improves by ~16 dB due to decimation (confirmed in testing)
- Decimation is already implemented in capture.py as a commented-out path

### 3. Output representation: Edge objects with timestamps
**Decision**: Represent demodulated output as a list of `Edge` namedtuples with `timestamp` (seconds from capture start) and `phase` ('on' or 'off').

**Rationale**:
- Edges are the fundamental observable — both bit reconstruction and time decoding build on them
- Namedtuple is simple, serializable, and testable
- Alternative: generator yielding edges — would work but makes testing harder

### 4. Thresholding: fixed at 50% of envelope maximum
**Decision**: Use a fixed threshold at 50% of the envelope's maximum value.

**Rationale**:
- MSF is a clean on/off keying signal — the carrier is either present (strong envelope) or absent (noise floor)
- A fixed threshold is simpler and more predictable than adaptive
- The 100 ms marker pulses are always present and strong, so the max envelope is reliable
- Alternative: adaptive threshold based on median — more complex, marginal benefit for a clean signal

### 5. Bit channel: two parallel channels (A and B)
**Decision**: Output two parallel bit streams — A channel (bits on even seconds) and B channel (bits on odd seconds) — rather than a single interleaved stream.

**Rationale**:
- The MSF protocol transmits two independent bits per second (one per channel), alternating every second
- The A channel carries year, month, day, hour, minute, day-of-week, and parity
- The B channel carries DUT1, summer time, and parity
- Separate channels match the protocol structure and simplify the decoder's job
- Alternative: single interleaved stream — loses the natural A/B grouping

### 6. Minute marker detection
**Decision**: Detect the minute boundary by finding the 500 ms carrier-off period at the start of the minute. This is the first long gap in the carrier after a period of continuous carrier.

**Rationale**:
- The minute marker is a unique 500 ms off period, followed by second 00
- The specification notes a unique marker sequence `01111110` in bit A that identifies the following second 00, but detecting the 500 ms gap is simpler and equally reliable
- Once the minute boundary is found, all subsequent 100 ms off pulses are regular second markers
- Alternative: search for the `01111110` sequence — requires bit-level knowledge we don't yet have

### 7. Module structure: single file, no class
**Decision**: `demodulate.py` as a single module with standalone functions, no class.

**Rationale**:
- Demodulation is a pure function of samples → edges → bits; no state needed
- Simpler to test and compose
- Matches the existing `capture.py` post-refactor convention

### 8. Dependency: scipy
**Decision**: Add `scipy` as a dependency for `scipy.signal.hilbert`.

**Rationale**:
- `scipy.signal.hilbert` is the standard, well-tested implementation
- Alternative: implement Hilbert transform manually with FFT — reinvents the wheel
- Alternative: use a simple moving-average envelope — less precise, harder to get threshold right

## Risks / Trade-offs

| Risk | Impact | Mitigation |
|------|--------|------------|
| Hilbert transform edge artifacts at boundaries | Minor — first/last few edges may be noisy | Document known edge region; users can discard first/last N edges |
| Fixed threshold fails on very weak signals | Medium — missed edges or false edges | Add signal quality metric (SNR estimate) to output; log warnings |
| scipy dependency increases install size | Low — scipy is ~10 MB | Acceptable trade-off for correctness; document as required dependency |
| Decimation loses timing precision | Low — 25 ksps gives 40 µs resolution, far better than 100 ms slot | Not a practical concern; timing precision is more than adequate |
| Minute marker misdetected in noisy signal | Medium — wrong boundary shifts all bits | Use the unique `01111110` sequence as a secondary confirmation once bits are available |
| A/B channel misalignment | Medium — bits assigned to wrong channel | After minute marker detection, A starts on second 00 (even), B on second 01 (odd) — deterministic |

## Open Questions

1. Should the module also return a simple bit stream alongside edges? (Currently edges-only; bits are trivially derived.) — **Decided: yes, return both.**
2. Should we support a `--demodulate` flag on the existing CLI, or keep demodulation as a separate tool? — **Decided: separate CLI (`msf-demodulate`).**
