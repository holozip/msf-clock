"""
MSF 60 kHz signal demodulation — envelope detection and bit reconstruction.

Demodulation pipeline:
  1. Envelope detection: Hilbert transform on IQ samples → amplitude envelope
  2. Thresholding: 50% of envelope max separates carrier-on from carrier-off
  3. Edge detection: find carrier transitions (on/off) with sub-sample interpolation
  4. Minute marker: locate the 500 ms off period at the start of each minute
  5. Bit reconstruction: evaluate 100 ms slots to extract A/B channel bits

MSF encoding (per NPL spec):
  - Bit polarity: carrier on = logical 0, carrier off = logical 1
  - Every second boundary has a 100 ms carrier-off pulse
  - Minute marker: 500 ms carrier-off at second 00
  - Two bits per second: A channel (even seconds), B channel (odd seconds)
  - Each bit occupies a 100 ms slot within its second

Requires:
  Python: numpy, scipy (via pip or system packages)
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.signal import hilbert


# =============================================================================
# Data types
# =============================================================================


@dataclass(frozen=True)
class Edge:
    """A carrier transition edge."""
    timestamp: float  # seconds from capture start
    phase: str  # 'on' (carrier-on) or 'off' (carrier-off)


@dataclass
class DemodulationResult:
    """Result of demodulating IQ samples."""
    edges: list[Edge]
    a_bits: list[int] | None  # A channel bits (even seconds)
    b_bits: list[int] | None  # B channel bits (odd seconds)
    quality: dict  # snr_db, edge_count, low_snr


# =============================================================================
# 1. Envelope detection (tasks 2.1-2.3)
# =============================================================================


def compute_envelope(samples: np.ndarray) -> np.ndarray:
    """Compute the signal envelope using the Hilbert transform.

    Args:
        samples: Input IQ samples (complex64 or float32).

    Returns:
        Envelope array (magnitude of the analytic signal).
        Same length as input.
    """
    if samples.size == 0:
        return np.array([], dtype=np.float64)

    # Hilbert transform works on real data; for complex IQ, extract the
    # analytic signal magnitude directly.
    if np.iscomplexobj(samples):
        # For complex64 input, the signal is already baseband I/Q.
        # Compute envelope as magnitude, then apply Hilbert on the magnitude
        # to get smooth envelope.
        mag = np.abs(samples).astype(np.float64)
        envelope = hilbert(mag)
        envelope = np.abs(envelope)
    else:
        analytic = hilbert(samples.astype(np.float64))
        envelope = np.abs(analytic)

    if samples.size == 1:
        return np.array([float(envelope[0])], dtype=np.float64)

    return envelope


# =============================================================================
# 2. Threshold and edge detection (tasks 3.1-3.4)
# =============================================================================


def compute_threshold(envelope: np.ndarray) -> float:
    """Compute detection threshold at 50% of envelope maximum.

    Args:
        envelope: Signal envelope array.

    Returns:
        Threshold value as float.
    """
    if envelope.size == 0:
        return 0.0
    return float(np.max(envelope)) * 0.5


def _interpolate_crossing(
    envelope: np.ndarray,
    index: int,
    threshold: float,
) -> float:
    """Linearly interpolate the exact crossing point between two samples.

    Args:
        envelope: Full envelope array.
        index: Index of the sample *after* the crossing point.
        threshold: Detection threshold.

    Returns:
        Interpolated sample index (float) of the crossing.
    """
    prev_val = envelope[index - 1]
    curr_val = envelope[index]
    # Linear interpolation: find t where prev + t*(curr-prev) = threshold
    delta = curr_val - prev_val
    if abs(delta) < 1e-15:
        return float(index - 0.5)
    t = (threshold - prev_val) / delta
    return float(index - 1) + t


def detect_edges(
    envelope: np.ndarray,
    threshold: float,
) -> list[tuple[float, str]]:
    """Detect carrier transition edges by threshold crossing.

    Scans the envelope for crossings above/below the threshold.
    Uses linear interpolation for sub-sample precision.

    Args:
        envelope: Signal envelope array.
        threshold: Detection threshold.

    Returns:
        List of (interpolated_sample_index, phase) tuples.
        phase is 'on' for rising crossings, 'off' for falling crossings.
    """
    if envelope.size < 2:
        return []

    edges: list[tuple[float, str]] = []

    for i in range(1, envelope.size):
        prev_val = envelope[i - 1]
        curr_val = envelope[i]

        # Rising edge: envelope crosses above threshold (carrier-off → on)
        if prev_val <= threshold and curr_val > threshold:
            t = _interpolate_crossing(envelope, i, threshold)
            edges.append((t, 'on'))

        # Falling edge: envelope crosses below threshold (carrier-on → off)
        elif prev_val > threshold and curr_val <= threshold:
            t = _interpolate_crossing(envelope, i, threshold)
            edges.append((t, 'off'))

    return edges


# =============================================================================
# 3. Edge-to-timestamp conversion (tasks 4.1-4.3)
# =============================================================================


def edges_to_timestamps(
    edge_samples: list[tuple[float, str]],
    sample_rate: float,
) -> list[Edge]:
    """Convert sample-index edges to timestamp edges.

    Args:
        edge_samples: List of (sample_index, phase) tuples from detect_edges.
        sample_rate: Sample rate in samples per second.

    Returns:
        List of Edge objects sorted by timestamp.
    """
    edges: list[Edge] = []
    for sample_idx, phase in edge_samples:
        edge = Edge(
            timestamp=float(sample_idx) / sample_rate,
            phase=phase,
        )
        edges.append(edge)

    edges.sort(key=lambda e: e.timestamp)
    return edges


# =============================================================================
# 4. Minute marker detection (tasks 5.1-5.3)
# =============================================================================


def find_minute_marker(edges: list[Edge]) -> Edge | None:
    """Find the minute marker by scanning for the first ≥400 ms carrier-off period.

    The minute marker is a 500 ms carrier-off period at the start of each minute
    (second 00). This function scans the first 5 seconds of edges to find the
    longest consecutive carrier-off gap.

    Args:
        edges: Chronologically sorted list of Edge objects.

    Returns:
        The first 'on' edge after the minute marker (start of second 00),
        or None if no minute marker found.
    """
    if len(edges) < 2:
        return None

    # Look for carrier-off gaps in the first 5 seconds of edges
    search_window_end = edges[0].timestamp + 5.0

    best_gap_start: Edge | None = None
    best_gap_duration = 0.0

    # Find all consecutive off→on transitions
    for i in range(len(edges) - 1):
        if edges[i].phase == 'off' and edges[i + 1].phase == 'on':
            gap_start = edges[i].timestamp
            gap_end = edges[i + 1].timestamp
            gap_duration = gap_end - gap_start

            if gap_start <= search_window_end and gap_duration > best_gap_duration:
                best_gap_duration = gap_duration
                best_gap_start = edges[i]

    if best_gap_start is not None and best_gap_duration >= 0.4:
        # Return the 'on' edge that starts second 00
        for edge in edges:
            if edge.phase == 'on' and edge.timestamp >= best_gap_start.timestamp:
                return edge

    return None


# =============================================================================
# 5. Bit reconstruction (tasks 6.1-6.5)
# =============================================================================


def edges_to_bits(
    edges: list[Edge],
    minute_start: Edge,
) -> tuple[list[int], list[int]]:
    """Reconstruct A and B channel bit streams from edge timestamps.

    MSF protocol:
      - Each second has a 100 ms carrier-off pulse at the start (second marker)
      - Bit value per second: carrier on = logical 0, carrier off = logical 1
      - The bit is determined by whether carrier is present in the 100 ms
        window immediately following the second marker
      - A channel: even seconds (0, 2, 4, ...)
      - B channel: odd seconds (1, 3, 5, ...)
      - Skip incomplete last seconds (fewer than 700 ms carrier at end)

    Args:
        edges: Chronologically sorted list of Edge objects.
        minute_start: The 'on' edge marking the start of second 00.

    Returns:
        Tuple of (a_bits, b_bits) — lists of 0/1 integers.
    """
    a_bits: list[int] = []
    b_bits: list[int] = []

    second_start = minute_start.timestamp

    # Build a lookup: for each second, determine if carrier is present
    # in the 100 ms window after the 100 ms marker
    # Second N's window: [second_start + N*1.0, second_start + N*1.0 + 0.2)
    # (100 ms marker + 100 ms bit window)
    second_data: list[tuple[bool, bool]] = []  # (marker_off, bit_slot_has_carrier)

    for sec in range(60):
        sec_start = second_start + sec * 1.0
        marker_window_end = sec_start + 0.1  # end of 100 ms marker
        bit_window_start = sec_start + 0.1
        bit_window_end = sec_start + 0.2

        # Check for marker: is there a carrier-off period at the start?
        marker_off = False
        for i, edge in enumerate(edges):
            if edge.timestamp >= marker_window_end:
                break
            if edge.phase == 'off':
                marker_off = True
                break

        # Check for carrier in the bit window (100-200 ms into the second).
        # Carrier is present if there's an 'on' edge before the window and
        # no 'off' edge between that 'on' edge and the end of the bit window.
        bit_has_carrier = False
        on_edge_ts: float | None = None
        for edge in edges:
            if edge.timestamp >= bit_window_end:
                break
            if edge.timestamp >= bit_window_start:
                # Inside the bit window
                if edge.phase == 'off':
                    on_edge_ts = None
                    break
                else:
                    on_edge_ts = edge.timestamp
            else:
                # Before the bit window but within this second
                if edge.timestamp >= sec_start:
                    if edge.phase == 'on':
                        on_edge_ts = edge.timestamp
                    elif edge.phase == 'off':
                        on_edge_ts = None
        if on_edge_ts is not None:
            bit_has_carrier = True

        second_data.append((marker_off, bit_has_carrier))

    # Determine bit values per second
    for sec in range(len(second_data)):
        marker_off, bit_has_carrier = second_data[sec]

        # Skip incomplete seconds: need at least 700 ms of carrier at the end.
        # Carrier is on at the end of the second if the last 'on' edge before
        # sec_end has no 'off' edge between it and sec_end.
        # Also require that the 'on' edge is within this second (after marker).
        sec_end = second_start + (sec + 1) * 1.0
        sec_start = second_start + sec * 1.0
        has_carrier_at_end = False

        # Find the last 'on' edge within this second
        last_on_ts: float | None = None
        for edge in edges:
            if edge.timestamp >= sec_end:
                break
            if edge.phase == 'on' and edge.timestamp >= sec_start:
                last_on_ts = edge.timestamp

        if last_on_ts is not None:
            # Check if carrier turns off between last_on_ts and sec_end
            carrier_stays_on = True
            for edge in edges:
                if edge.timestamp <= last_on_ts:
                    continue
                if edge.timestamp >= sec_end:
                    break
                if edge.phase == 'off':
                    carrier_stays_on = False
                    break
            if carrier_stays_on:
                has_carrier_at_end = True

        if not has_carrier_at_end:
            continue

        # Bit value: carrier on = 0, carrier off = 1
        bit = 0 if bit_has_carrier else 1

        if sec % 2 == 0:
            a_bits.append(bit)
        else:
            b_bits.append(bit)

    return a_bits, b_bits


# =============================================================================
# 6. Signal quality (tasks 7.1-7.3)
# =============================================================================


def compute_quality(envelope: np.ndarray, edges: list[Edge]) -> dict:
    """Compute signal quality metrics.

    SNR = 20 * log10(max(envelope) / median(noise_floor_envelope))
    Noise floor is estimated as the median of envelope values below the threshold.

    Args:
        envelope: Signal envelope array.
        edges: List of detected edges.

    Returns:
        Dict with 'snr_db', 'edge_count', and 'low_snr' keys.
    """
    if envelope.size == 0:
        return {'snr_db': 0.0, 'edge_count': 0, 'low_snr': True}

    max_env = float(np.max(envelope))

    # Estimate noise floor from values below 50% of max
    threshold = max_env * 0.5
    noise_floor = envelope[envelope < threshold]

    if noise_floor.size > 0:
        noise_median = float(np.median(noise_floor))
    else:
        noise_median = 1e-10  # Prevent division by zero

    if noise_median > 0:
        snr_db = 20.0 * np.log10(max_env / noise_median)
    else:
        snr_db = 100.0  # Effectively infinite SNR

    return {
        'snr_db': float(snr_db),
        'edge_count': len(edges),
        'low_snr': snr_db < 10.0,
    }


# =============================================================================
# 7. Main demodulation function (tasks 8.1-8.5)
# =============================================================================


def demodulate_samples(
    samples: np.ndarray,
    sample_rate: float,
    return_bits: bool = True,
) -> DemodulationResult:
    """Demodulate MSF IQ samples into edges and optional bit streams.

    Pipeline:
      1. Compute envelope via Hilbert transform
      2. Detect threshold and find carrier edges
      3. Convert edges to timestamps
      4. Find minute marker
      5. Reconstruct A and B channel bits (if requested)
      6. Compute signal quality

    Args:
        samples: IQ samples as numpy array (complex64 or float32).
        sample_rate: Sample rate in samples per second.
        return_bits: If True, also compute A and B channel bit streams.

    Returns:
        DemodulationResult with edges, bits, and quality.

    Raises:
        ValueError: If samples is empty or sample_rate <= 0.
    """
    # Input validation
    if not isinstance(samples, np.ndarray):
        raise ValueError("samples must be a numpy array")
    if samples.size == 0:
        raise ValueError("samples must not be empty")
    if not isinstance(sample_rate, (int, float)) or sample_rate <= 0:
        raise ValueError("sample_rate must be a positive number")

    # Step 1: Envelope detection
    envelope = compute_envelope(samples)

    # Step 2: Threshold and edge detection
    threshold = compute_threshold(envelope)
    edge_samples = detect_edges(envelope, threshold)

    # Step 3: Convert to timestamps
    edges = edges_to_timestamps(edge_samples, sample_rate)

    # Step 4: Minute marker detection
    minute_start = find_minute_marker(edges)

    # Step 5: Bit reconstruction
    a_bits: list[int] | None = None
    b_bits: list[int] | None = None
    if return_bits and minute_start is not None:
        a_bits, b_bits = edges_to_bits(edges, minute_start)

    # Step 6: Signal quality
    quality = compute_quality(envelope, edges)

    return DemodulationResult(
        edges=edges,
        a_bits=a_bits,
        b_bits=b_bits,
        quality=quality,
    )


# =============================================================================
# 8. CLI entry point (tasks 9.1-9.8)
# =============================================================================


def main():
    """CLI entry point for MSF signal demodulation."""
    parser = argparse.ArgumentParser(
        description="Demodulate MSF 60 kHz clock signal from IQ samples",
    )
    parser.add_argument(
        "-i", "--input",
        type=str,
        required=True,
        help="Path to .raw IQ file (required)",
    )
    parser.add_argument(
        "-r", "--sample-rate",
        type=float,
        default=1000000.0,
        help="Sample rate in Hz (default: 1000000)",
    )
    parser.add_argument(
        "-t", "--threshold",
        type=float,
        default=0.5,
        help="Threshold multiplier 0.0-1.0 (default: 0.5 = 50%% of max)",
    )
    parser.add_argument(
        "-o", "--output",
        type=str,
        default=None,
        help="Path to write JSON output (default: stdout)",
    )

    args = parser.parse_args()

    # Read IQ samples from .raw file
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: input file not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    raw_bytes = input_path.read_bytes()
    samples = np.frombuffer(raw_bytes, dtype=np.complex64)

    # Override threshold if specified
    envelope = compute_envelope(samples)
    threshold = float(np.max(envelope)) * args.threshold

    # Detect edges
    edge_samples = detect_edges(envelope, threshold)
    edges = edges_to_timestamps(edge_samples, args.sample_rate)

    # Minute marker
    minute_start = find_minute_marker(edges)

    # Bits
    a_bits: list[int] | None = None
    b_bits: list[int] | None = None
    if minute_start is not None:
        a_bits, b_bits = edges_to_bits(edges, minute_start)

    # Quality
    quality = compute_quality(envelope, edges)

    # Build output (convert numpy types to native Python for JSON)
    output = {
        'edges': [
            {'timestamp': float(e.timestamp), 'phase': e.phase}
            for e in edges
        ],
        'a_bits': a_bits,
        'b_bits': b_bits,
        'quality': {
            'snr_db': float(quality['snr_db']),
            'edge_count': int(quality['edge_count']),
            'low_snr': bool(quality['low_snr']),
        },
    }

    json_output = json.dumps(output, indent=2)

    if args.output:
        Path(args.output).write_text(json_output)
        print(f"Output written to {args.output}")
    else:
        print(json_output)


if __name__ == "__main__":
    main()
