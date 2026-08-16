import datetime

import numpy

from msf_clock import decoder
from msf_clock.timing import classify_off_gap, second_step

SNAPSHOT = datetime.datetime(2026, 8, 16, 12, 29, 0, tzinfo=datetime.timezone.utc)


def _set_bcd(track, start, weights, value):
    for idx, weight in enumerate(weights):
        bit = (value // weight) % 2
        track[start + idx] = bit
        value -= bit * weight


def build_valid_frame(dut_neg=3):
    a = numpy.zeros(60, dtype=int)
    b = numpy.zeros(60, dtype=int)

    a[53:59] = 1

    _set_bcd(a, 17, [80, 40, 20, 10, 8, 4, 2, 1], 26)
    _set_bcd(a, 25, [10, 8, 4, 2, 1], 8)
    _set_bcd(a, 30, [20, 10, 8, 4, 2, 1], 16)
    _set_bcd(a, 36, [4, 2, 1], 0)
    _set_bcd(a, 39, [20, 10, 8, 4, 2, 1], 12)
    _set_bcd(a, 45, [40, 20, 10, 8, 4, 2, 1], 30)

    b[54] = 1 - numpy.sum(a[17:25]) % 2
    b[55] = 1 - numpy.sum(a[25:36]) % 2
    b[56] = 1 - numpy.sum(a[36:39]) % 2
    b[57] = 1 - numpy.sum(a[39:52]) % 2

    if dut_neg:
        b[9:9 + dut_neg] = 1

    return a, b


def test_valid_frame_displays(capsys):
    a, b = build_valid_frame()
    decoder.print_atomic_clock(a, b, SNAPSHOT)
    out = capsys.readouterr().out
    assert "Minute Identifier (Sec 52-59):  PASSED" in out
    assert "SUCCESS" in out
    assert "True Atomic Time: 12:30:00" in out
    assert "2026-08-16 (Sunday)" in out
    assert "-0.3 seconds" in out


def test_shifted_signature_recovers(capsys):
    a, b = build_valid_frame()
    a = numpy.roll(a, 3)
    b = numpy.roll(b, 3)
    decoder.print_atomic_clock(a, b, SNAPSHOT)
    out = capsys.readouterr().out
    assert "RECOVERED (Δ=-3)" in out
    assert "SUCCESS" in out
    assert "True Atomic Time: 12:30:00" in out
    assert "2026-08-16 (Sunday)" in out


def test_missing_signature_drops_frame(capsys):
    a, b = build_valid_frame()
    a[55] = 0
    decoder.print_atomic_clock(a, b, SNAPSHOT)
    out = capsys.readouterr().out
    assert "FAILED (01111110 not found in frame)" in out
    assert "FRAME DROPPED" in out
    assert "SUCCESS" not in out
    assert "True Atomic Time" not in out


def test_dut1_zero(capsys):
    a, b = build_valid_frame(dut_neg=0)
    decoder.print_atomic_clock(a, b, SNAPSHOT)
    out = capsys.readouterr().out
    assert "+0.0 seconds" in out


def test_dut1_malformed(capsys):
    a, b = build_valid_frame()
    b[1] = 1
    decoder.print_atomic_clock(a, b, SNAPSHOT)
    out = capsys.readouterr().out
    assert "Earth Orbit Correction (DUT1): MALFORMED DUT1" in out


def test_gap_classification():
    assert classify_off_gap(100, 500) == ("second", 0, 0)
    assert classify_off_gap(100, 100) == ("b_bit", 0, 1)
    assert classify_off_gap(200, 700) == ("second", 1, 0)
    assert classify_off_gap(300, 600) == ("second", 1, 1)
    assert classify_off_gap(500, 900) == ("marker", 0, 0)
    assert classify_off_gap(40, 900) == ("ignored", 0, 0)
    assert classify_off_gap(120, 30) == ("second", 0, 0)
    assert classify_off_gap(250, 90) == ("second", 0, 0)


def test_second_step():
    assert second_step(1000) == 1
    assert second_step(1050) == 1
    assert second_step(950) == 1
    assert second_step(900) == 1
    assert second_step(700) == 1
    assert second_step(1900) == 2
    assert second_step(2000) == 2
    assert second_step(2100) == 2


def test_a0_b1_second_advances_once():
    frame_a = numpy.zeros(60, dtype=int)
    frame_b = numpy.zeros(60, dtype=int)
    state = {"second": 5, "last_valid": 5100, "prev_rising": 5100}

    def process(falling, rising):
        on_run = falling - state["prev_rising"]
        state["prev_rising"] = rising
        kind, a_bit, b_bit = classify_off_gap(rising - falling, on_run)
        if kind == "b_bit":
            frame_b[state["second"]] = 1
            state["last_valid"] = rising
        elif kind == "second":
            state["second"] = min(59, state["second"] + second_step(falling - state["last_valid"]))
            frame_a[state["second"]] = a_bit
            frame_b[state["second"]] = b_bit
            state["last_valid"] = falling

    process(6000, 6100)
    assert state["second"] == 6
    process(6200, 6300)
    assert state["second"] == 6
    assert frame_a[6] == 0
    assert frame_b[6] == 1
    process(7000, 7100)
    assert state["second"] == 7
    assert frame_b[7] == 0
