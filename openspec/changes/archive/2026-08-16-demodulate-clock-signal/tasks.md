## 1. Module scaffolding and dependencies

- [x] 1.1 Create `src/msf_clock/demodulate.py` with module docstring explaining the demodulation pipeline
- [x] 1.2 Add `scipy>=1.11` to `pyproject.toml` dependencies
- [x] 1.3 Define `Edge` namedtuple (timestamp: float, phase: str) at module level
- [x] 1.4 Define `DemodulationResult` namedtuple (edges: list[Edge], a_bits: list[int] | None, b_bits: list[int] | None, quality: dict)

## 2. Envelope detection

- [x] 2.1 Implement `compute_envelope(samples: np.ndarray) -> np.ndarray` using `scipy.signal.hilbert`
- [x] 2.2 Handle edge case: empty input returns empty array
- [x] 2.3 Handle edge case: single sample returns scalar magnitude
- [x] 2.4 Write unit tests for envelope detection with known sine wave input

## 3. Threshold and edge detection

- [x] 3.1 Implement `compute_threshold(envelope: np.ndarray) -> float` using 50% of envelope maximum
- [x] 3.2 Implement `detect_edges(envelope: np.ndarray, threshold: float) -> list[tuple[float, str]]` finding sample indices of crossings
- [x] 3.3 Implement linear interpolation for sub-sample edge precision
- [x] 3.4 Classify edges as 'on' (rising) or 'off' (falling) based on crossing direction
- [x] 3.5 Write unit tests for edge detection with synthetic on/off keying signal

## 4. Edge-to-timestamp conversion

- [x] 4.1 Implement `edges_to_timestamps(sample_indices: list[int], sample_rate: float) -> list[Edge]`
- [x] 4.2 Convert sample indices to seconds from capture start
- [x] 4.3 Ensure output edges are sorted by timestamp
- [x] 4.4 Write unit tests for timestamp conversion

## 5. Minute marker detection

- [x] 5.1 Implement `find_minute_marker(edges: list[Edge]) -> Edge | None` scanning for the first ≥400 ms carrier-off period
- [x] 5.2 Identify the minute marker as the longest consecutive carrier-off gap in the first N seconds of data
- [x] 5.3 Return the timestamp of the carrier-on edge immediately following the minute marker (start of second 00)
- [x] 5.4 Write unit tests for minute marker detection with synthetic data containing a 500 ms gap

## 6. Bit reconstruction

- [x] 6.1 Implement `edges_to_bits(edges: list[Edge], minute_start: Edge) -> tuple[list[int], list[int]]`
- [x] 6.2 Divide each second into 100 ms slots (10 slots per second)
- [x] 6.3 Determine bit value per second: bit = 0 if carrier present in the slot, bit = 1 if carrier absent
- [x] 6.4 Assign even-second bits to A channel, odd-second bits to B channel
- [x] 6.5 Skip incomplete last seconds (fewer than 700 ms carrier at end)
- [x] 6.6 Write unit tests for bit reconstruction with synthetic data

## 7. Signal quality

- [x] 7.1 Implement `compute_quality(envelope: np.ndarray) -> dict` computing SNR estimate
- [x] 7.2 SNR = 20 * log10(max(envelope) / median(noise_floor_envelope))
- [x] 7.3 Include `snr_db`, `edge_count`, and `low_snr` (bool if SNR < 10 dB) in quality dict
- [x] 7.4 Write unit tests for quality computation

## 8. Main demodulation function

- [x] 8.1 Implement `demodulate_samples(samples: np.ndarray, sample_rate: float, return_bits: bool = True) -> DemodulationResult`
- [x] 8.2 Chain: envelope → threshold → edges → minute marker → A/B bits
- [x] 8.3 Return all edges, optional A and B bit lists, and quality in a single result object
- [x] 8.4 Add input validation: check samples is numpy array, sample_rate > 0, samples not empty
- [x] 8.5 Write integration tests for full pipeline

## 9. CLI entry point

- [x] 9.1 Add `msf-demodulate` entry point to `pyproject.toml` pointing to `msf_clock.demodulate:main`
- [x] 9.2 Implement `main()` with argparse: `--input`, `--sample-rate`, `--threshold`, `--output`
- [x] 9.3 `--input`: path to .raw IQ file (required)
- [x] 9.4 `--sample-rate`: override sample rate (default: 1000000)
- [x] 9.5 `--threshold`: manual threshold multiplier (default: 0.5, i.e. 50% of max)
- [x] 9.6 `--output`: path to write JSON output (default: stdout)
- [x] 9.7 Output format: JSON with edges (array of {timestamp, phase}), a_bits (array of int), b_bits (array of int), and quality
- [x] 9.8 Test CLI with a captured .raw file

## 10. Verification

- [x] 10.1 Run `msf-demodulate --help` and verify all flags documented
- [x] 10.2 Run demodulation on a captured .raw file and inspect output
- [x] 10.3 Verify minute marker detected at expected position (first 500 ms off pulse)
- [x] 10.4 Verify edge density: approximately 2 edges per second (one on, one off per second)
- [x] 10.5 Verify bit stream has consistent length across A and B channels

<!-- Verified live on 2026-08-16 17:27-17:30 UTC (SDRplay RSPduo, streaming msf.py; the batch -->
<!-- demodulate.py CLI from this change was superseded by the streaming architecture). -->
<!-- 10.3: first [Sync Locked] at 17:28:00.551; marker off-onset ~17:28:00.05 UTC, i.e. at the -->
<!-- first 500 ms off pulse on the minute boundary (~50 ms constant SDR/USB pipeline offset). -->
<!-- 10.4: 54 consecutive seconds at exactly 1.000 s cadence (one off + one on edge per second); -->
<!-- one pulse per second held for the entire run. -->
<!-- 10.5: A/B 60-slot frames written in lockstep every second (~150 s observed, no channel skew). -->
<!-- Caveat observed (out of scope here): a spurious 180 ms pulse at ~second 55 desynced the -->
<!-- second counter (stuck at 59 via the >59 clamp) and the adaptive midpoint tracker fragmented -->
<!-- the 17:29:00 / 17:30:00 markers into 226+275 ms and 365+137 ms, so no second sync/parity -->
<!-- report fired. Needs its own follow-up change. -->
