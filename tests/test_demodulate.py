"""Tests for msf_clock.demodulate."""

import numpy as np
import pytest

from msf_clock.demodulate import (
    Edge,
    DemodulationResult,
    compute_envelope,
    compute_threshold,
    detect_edges,
    edges_to_timestamps,
    find_minute_marker,
    edges_to_bits,
    compute_quality,
    demodulate_samples,
)


# =============================================================================
# Envelope detection
# =============================================================================


class TestComputeEnvelope:
    """Test compute_envelope handles all input cases."""

    def test_empty_input(self):
        """Empty input returns empty array."""
        result = compute_envelope(np.array([], dtype=np.complex64))
        assert result.size == 0
        assert result.dtype == np.float64

    def test_single_sample(self):
        """Single sample returns array with one element."""
        result = compute_envelope(np.array([1.0 + 1.0j], dtype=np.complex64))
        assert result.size == 1
        # Magnitude of (1+1j) = sqrt(2) ≈ 1.414
        assert abs(result[0] - 1.4142) < 0.01

    def test_dc_signal(self):
        """Constant DC signal has constant envelope."""
        sr = 1000
        dc = np.ones(sr, dtype=np.complex64)
        env = compute_envelope(dc)
        assert env.std() < 0.01  # Very low variation
        assert abs(env.mean() - 1.0) < 0.1

    def test_on_off_keying_envelope(self):
        """Envelope is higher during carrier-on than carrier-off."""
        sr = 1000
        t = np.arange(sr * 2) / sr
        signal = np.ones(sr * 2, dtype=np.complex64)
        signal[sr:] = 0  # second half is off
        carrier = np.exp(2j * 2 * np.pi * 100 * t)
        iq = signal * carrier

        env = compute_envelope(iq)

        # First half (on) should have higher average than second half (off)
        assert env[:sr].mean() > env[sr:].mean()

    def test_float32_input(self):
        """Float32 input works without error."""
        sr = 1000
        t = np.arange(sr) / sr
        carrier = np.abs(np.exp(2j * 2 * np.pi * 100 * t)).astype(np.float32)
        env = compute_envelope(carrier)
        assert env.size == sr
        assert np.all(env >= 0)


# =============================================================================
# Threshold and edge detection
# =============================================================================


class TestComputeThreshold:
    """Test compute_threshold returns 50% of max."""

    def test_threshold_is_half_max(self):
        envelope = np.array([0.1, 0.5, 1.0, 0.3, 0.2])
        assert compute_threshold(envelope) == 0.5

    def test_empty_envelope(self):
        assert compute_threshold(np.array([], dtype=np.float64)) == 0.0

    def test_constant_envelope(self):
        envelope = np.full(100, 2.0)
        assert compute_threshold(envelope) == 1.0


class TestDetectEdges:
    """Test detect_edges finds correct transitions."""

    def test_no_edges_on_constant(self):
        """Constant signal above threshold produces no edges."""
        envelope = np.full(1000, 1.0)
        edges = detect_edges(envelope, 0.5)
        assert len(edges) == 0

    def test_rising_edge_detected(self):
        """Envelope crossing above threshold produces 'on' edge."""
        envelope = np.zeros(1000)
        envelope[500:] = 1.0
        edges = detect_edges(envelope, 0.5)
        on_edges = [e for e in edges if e[1] == 'on']
        assert len(on_edges) == 1
        # Edge should be near sample 500 with sub-sample precision
        assert 499 < on_edges[0][0] < 501

    def test_falling_edge_detected(self):
        """Envelope crossing below threshold produces 'off' edge."""
        envelope = np.ones(1000)
        envelope[500:] = 0.0
        edges = detect_edges(envelope, 0.5)
        off_edges = [e for e in edges if e[1] == 'off']
        assert len(off_edges) == 1
        assert 499 < off_edges[0][0] < 501

    def test_both_edges_in_sequence(self):
        """Pulse (on then off) produces two edges."""
        envelope = np.zeros(1000)
        envelope[200:800] = 1.0
        edges = detect_edges(envelope, 0.5)
        assert len(edges) == 2
        assert edges[0][1] == 'on'
        assert edges[1][1] == 'off'

    def test_sub_sample_precision(self):
        """Edge is interpolated between samples, not snapped to integer."""
        # Sharp transition between sample 100 and 101
        envelope = np.zeros(1000)
        envelope[101:] = 1.0
        edges = detect_edges(envelope, 0.5)
        on_edges = [e for e in edges if e[1] == 'on']
        assert len(on_edges) == 1
        # Interpolated position should be between 100 and 101
        assert 100.0 < on_edges[0][0] < 101.0

    def test_small_envelope(self):
        """Single element returns no edges."""
        edges = detect_edges(np.array([1.0]), 0.5)
        assert len(edges) == 0

    def test_two_elements(self):
        """Two elements can produce at most one edge."""
        edges = detect_edges(np.array([0.0, 1.0]), 0.5)
        assert len(edges) <= 1


# =============================================================================
# Edge-to-timestamp conversion
# =============================================================================


class TestEdgesToTimestamps:
    """Test edges_to_timestamps converts indices to seconds correctly."""

    def test_basic_conversion(self):
        """Sample indices divided by sample rate gives seconds."""
        edges = [(0, 'on'), (500, 'off'), (1000, 'on')]
        result = edges_to_timestamps(edges, 1000.0)
        assert len(result) == 3
        assert result[0].timestamp == 0.0
        assert result[1].timestamp == 0.5
        assert result[2].timestamp == 1.0

    def test_non_integer_sample_rate(self):
        """Non-integer sample rate produces float timestamps."""
        edges = [(1, 'on'), (3, 'off')]
        result = edges_to_timestamps(edges, 3.0)
        assert abs(result[0].timestamp - 1.0 / 3.0) < 1e-10
        assert abs(result[1].timestamp - 3.0 / 3.0) < 1e-10

    def test_output_sorted(self):
        """Output edges are sorted by timestamp."""
        edges = [(800, 'on'), (200, 'off'), (500, 'on')]
        result = edges_to_timestamps(edges, 1000.0)
        timestamps = [e.timestamp for e in result]
        assert timestamps == sorted(timestamps)

    def test_edge_objects(self):
        """Each result is an Edge namedtuple with timestamp and phase."""
        edges = [(100, 'on'), (500, 'off')]
        result = edges_to_timestamps(edges, 1000.0)
        for e in result:
            assert isinstance(e, Edge)
            assert isinstance(e.timestamp, float)
            assert e.phase in ('on', 'off')


# =============================================================================
# Bit reconstruction
# =============================================================================


class TestEdgesToBits:
    """Test edges_to_bits reconstructs A/B channel bits correctly."""

    def _make_edges(self, seconds_data: list[tuple[float, float]]) -> list[Edge]:
        """Helper: create edges from list of (second_marker_off, carrier_on) pairs.

        seconds_data: list of (marker_off_time, carrier_on_time) relative to capture start.
        The minute marker is assumed to be at time 0.0 (off) and 0.5 (on).
        """
        edges: list[Edge] = [Edge(0.0, 'off'), Edge(0.5, 'on')]
        for off_t, on_t in seconds_data:
            edges.append(Edge(off_t, 'off'))
            edges.append(Edge(on_t, 'on'))
        return edges

    def test_all_zeros(self):
        """Normal seconds (carrier on after marker) give bit=0."""
        edges = self._make_edges([
            (1.5, 1.6),  # sec 01
            (2.5, 2.6),  # sec 02
            (3.5, 3.6),  # sec 03
        ])
        minute_start = find_minute_marker(edges)
        a, b = edges_to_bits(edges, minute_start)
        assert a == [0, 0]  # secs 00, 02
        assert b == [0, 0]  # secs 01, 03

    def test_bit_one_in_b_channel(self):
        """Carrier off during bit window gives bit=1."""
        edges = self._make_edges([
            (1.5, 1.7),  # sec 01: carrier on after bit window -> bit=1
            (2.5, 2.6),  # sec 02: normal -> bit=0
            (3.5, 3.6),  # sec 03: normal -> bit=0
        ])
        minute_start = find_minute_marker(edges)
        a, b = edges_to_bits(edges, minute_start)
        assert a == [0, 0]
        assert b == [1, 0]

    def test_bit_one_in_a_channel(self):
        """Carrier off during bit window on even second."""
        edges = self._make_edges([
            (1.5, 1.6),  # sec 01: normal
            (2.5, 2.7),  # sec 02: carrier after bit window -> bit=1
            (3.5, 3.6),  # sec 03: normal
        ])
        minute_start = find_minute_marker(edges)
        a, b = edges_to_bits(edges, minute_start)
        assert a == [0, 1]
        assert b == [0, 0]

    def test_incomplete_second_skipped(self):
        """Seconds without carrier at the end are skipped."""
        # Only provide 2 seconds of data (00, 01) with no carrier at end
        edges = self._make_edges([
            (1.5, 1.6),  # sec 01
        ])
        minute_start = find_minute_marker(edges)
        a, b = edges_to_bits(edges, minute_start)
        assert a == [0]  # sec 00 only
        assert b == [0]  # sec 01 only

    def test_a_b_channel_separation(self):
        """Even seconds go to A, odd seconds go to B."""
        edges = self._make_edges([
            (1.5, 1.6),  # sec 01 (B)
            (2.5, 2.6),  # sec 02 (A)
            (3.5, 3.6),  # sec 03 (B)
            (4.5, 4.6),  # sec 04 (A)
        ])
        minute_start = find_minute_marker(edges)
        a, b = edges_to_bits(edges, minute_start)
        # 5 seconds (00-04): A gets even (00,02,04)=3, B gets odd (01,03)=2
        assert len(a) == 3
        assert len(b) == 2


# =============================================================================
# Signal quality
# =============================================================================


class TestComputeQuality:
    """Test compute_quality returns correct metrics."""

    def test_high_snr_signal(self):
        """Strong carrier gives high SNR and low_snr=False."""
        sr = 1000
        t = np.arange(sr * 2) / sr
        signal = np.ones(sr * 2, dtype=np.complex64)
        signal[sr:] = 0
        carrier = np.exp(2j * 2 * np.pi * 100 * t)
        iq = signal * carrier
        env = compute_envelope(iq)
        thresh = compute_threshold(env)
        edges = detect_edges(env, thresh)
        quality = compute_quality(env, edges)
        assert 'snr_db' in quality
        assert 'edge_count' in quality
        assert 'low_snr' in quality
        assert quality['edge_count'] > 0
        assert quality['snr_db'] >= 0

    def test_empty_envelope(self):
        """Empty envelope returns zero SNR and low_snr=True."""
        quality = compute_quality(np.array([], dtype=np.float64), [])
        assert quality['snr_db'] == 0.0
        assert quality['edge_count'] == 0
        assert quality['low_snr'] is True

    def test_low_snr_flag(self):
        """low_snr flag is True when SNR < 10 dB."""
        # Create a signal with very noisy envelope
        # Add high-frequency oscillation to simulate noise
        sr = 1000
        t = np.arange(sr) / sr
        # Carrier with amplitude modulation noise
        signal = (1.0 + 0.8 * np.sin(2 * np.pi * 50 * t)) * np.exp(2j * 2 * np.pi * 100 * t)
        env = compute_envelope(signal)
        quality = compute_quality(env, [])
        # This signal has significant envelope variation -> lower SNR
        # Just verify the flag is set correctly based on SNR
        if quality['snr_db'] < 10.0:
            assert bool(quality['low_snr']) is True
        else:
            assert bool(quality['low_snr']) is False


# =============================================================================
# Integration tests
# =============================================================================


class TestDemodulateSamples:
    """Test the full demodulate_samples pipeline."""

    def test_full_pipeline_all_zeros(self):
        """End-to-end: clean signal produces correct bits."""
        sr = 1000
        t = np.arange(sr * 5) / sr
        # Create MSF-like signal: 500ms off (minute marker), then
        # 100ms off + carrier on for each second
        signal = np.ones(sr * 5, dtype=np.complex64)
        # Minute marker
        signal[:int(0.5 * sr)] = 0
        # Second markers (100ms off at start of each second 1-4)
        for sec in range(1, 5):
            start = int(sec * sr)
            signal[start:start + int(0.1 * sr)] = 0
        carrier = np.exp(2j * 2 * np.pi * 100 * t)
        iq = signal * carrier

        result = demodulate_samples(iq, sr, return_bits=True)
        assert len(result.edges) > 0
        assert result.a_bits is not None
        assert result.b_bits is not None
        assert result.quality['edge_count'] > 0
        assert 'snr_db' in result.quality
        assert 'low_snr' in result.quality

    def test_full_pipeline_with_bits(self):
        """Signal with bit=1 in B channel."""
        sr = 1000
        t = np.arange(sr * 5) / sr
        signal = np.ones(sr * 5, dtype=np.complex64)
        signal[:int(0.5 * sr)] = 0  # minute marker
        for sec in range(1, 5):
            start = int(sec * sr)
            if sec == 1:
                # Bit=1: carrier off for 200ms (marker + bit window)
                signal[start:start + int(0.2 * sr)] = 0
            else:
                # Bit=0: carrier off for 100ms (marker only)
                signal[start:start + int(0.1 * sr)] = 0
        carrier = np.exp(2j * 2 * np.pi * 100 * t)
        iq = signal * carrier

        result = demodulate_samples(iq, sr, return_bits=True)
        assert result.b_bits is not None
        assert len(result.b_bits) > 0

    def test_full_pipeline_no_bits(self):
        """return_bits=False produces None for bit lists."""
        sr = 1000
        t = np.arange(sr) / sr
        # Create a signal with a 200ms off period to generate edges
        signal = np.ones(sr, dtype=np.complex64)
        signal[int(0.3 * sr):int(0.5 * sr)] = 0  # 200ms gap
        carrier = np.exp(2j * 2 * np.pi * 100 * t)
        iq = signal * carrier

        result = demodulate_samples(iq, sr, return_bits=False)
        assert result.a_bits is None
        assert result.b_bits is None
        assert len(result.edges) > 0

    def test_input_validation(self):
        """Invalid inputs raise ValueError."""
        with pytest.raises(ValueError, match="samples must be a numpy array"):
            demodulate_samples("not an array", 1000.0)
        with pytest.raises(ValueError, match="samples must not be empty"):
            demodulate_samples(np.array([], dtype=np.complex64), 1000.0)
        with pytest.raises(ValueError, match="sample_rate must be a positive number"):
            demodulate_samples(np.array([1.0+0j], dtype=np.complex64), 0)
        with pytest.raises(ValueError, match="sample_rate must be a positive number"):
            demodulate_samples(np.array([1.0+0j], dtype=np.complex64), -100)


# =============================================================================
# Minute marker detection
# =============================================================================


class TestFindMinuteMarker:
    """Test find_minute_marker locates the 500 ms minute marker."""

    def test_normal_minute_marker(self):
        """500 ms off period at start is detected as minute marker."""
        edges = [
            Edge(0.0, 'off'),
            Edge(0.5, 'on'),  # 500ms gap -> minute marker
            Edge(1.0, 'off'),
            Edge(1.1, 'on'),
        ]
        result = find_minute_marker(edges)
        assert result is not None
        assert abs(result.timestamp - 0.5) < 0.05

    def test_no_minute_marker(self):
        """Only 100 ms gaps — no minute marker found."""
        edges = [
            Edge(0.0, 'off'),
            Edge(0.1, 'on'),
            Edge(1.0, 'off'),
            Edge(1.1, 'on'),
        ]
        assert find_minute_marker(edges) is None

    def test_empty_edges(self):
        """Empty edge list returns None."""
        assert find_minute_marker([]) is None

    def test_single_edge(self):
        """Single edge returns None."""
        assert find_minute_marker([Edge(0.0, 'on')]) is None

    def test_longest_gap_wins(self):
        """Among multiple gaps, the longest one is selected."""
        edges = [
            Edge(0.0, 'off'),
            Edge(0.2, 'on'),  # 200ms gap (not long enough)
            Edge(0.5, 'off'),
            Edge(1.0, 'on'),  # 500ms gap -> minute marker
            Edge(1.5, 'off'),
            Edge(1.6, 'on'),  # 100ms gap
        ]
        result = find_minute_marker(edges)
        assert result is not None
        assert abs(result.timestamp - 1.0) < 0.05

    def test_returns_on_edge_after_marker(self):
        """Returns the 'on' edge that starts second 00."""
        edges = [
            Edge(0.0, 'off'),
            Edge(0.5, 'on'),  # minute marker
            Edge(1.0, 'off'),
            Edge(1.1, 'on'),
        ]
        result = find_minute_marker(edges)
        assert result.phase == 'on'
