## 1. A=0, B=1 pulse classification (msf.py)

- [x] 1.1 Track the previous rising-edge index (or last-off-gap end) alongside `last_valid_pulse_ms` in the timing state machine
- [x] 1.2 On off-gap completion of 80–140 ms, compute the preceding carrier-ON run since the previous rising edge
- [x] 1.3 When that ON run is 60–160 ms, classify the gap as the B bit of the current second: set `frame_bit_b[current_second] = 1`, keep the stored A bit, do not advance `current_second`, and update `last_valid_pulse_ms`; print a per-second log line distinguishing B-bit gaps (e.g. `Second NN -> B=1 intra-second`)
- [x] 1.4 Verify no other code path advances `current_second` on an intra-second gap; confirm the next start-of-second gap (~800 ms later) still rounds to +1 second

## 2. Minute Identifier validation and recovery (decoder.py)

- [x] 2.1 Add a helper that scans all 60 A slots for the 8-bit sequence 01111110 and returns the starting slot (or None)
- [x] 2.2 At frame completion in `print_atomic_clock`, run the scan; if found at slot k != 52, roll both A and B tracks so the sequence starts at slot 52 and record the applied offset (Δ)
- [x] 2.3 If the scan finds no intact sequence, report `Minute identifier: FAILED` and return without displaying any time data
- [x] 2.4 After alignment, verify the position check (A[52]=0, A[53..58]=1, A[59]=0) and report it in the PARITY CHECK REPORT block as PASSED or `RECOVERED (Δ=k)`
- [x] 2.5 Only when identifier and all four parity checks pass, proceed to BCD decode and display

## 3. DUT1 guard (decoder.py)

- [x] 3.1 When both positive (B[1:8]) and negative (B[9:16]) DUT counts are nonzero, report `MALFORMED DUT1` and count the frame invalid instead of displaying a DUT1 value

## 4. Synthetic-frame unit tests

- [x] 4.1 Build a synthetic 60-second frame (A/B numpy arrays) with a valid time code, correct parity, and the identifier at 52–59; assert decode passes with all fields correct
- [x] 4.2 Frame rotated so 01111110 starts at a shifted slot: assert reindexing restores alignment, Δ is reported, and decode passes
- [x] 4.3 Frame with no intact identifier (e.g. corrupted tail): assert the frame is dropped and nothing is displayed
- [x] 4.4 DUT1 cases: negative (n bits 09–16), zero, and malformed (both codes set): assert the reported values and the MALFORMED flag
- [x] 4.5 Gap-classification cases (if the classifier logic is importable): assert an A=0, B=1 gap sequence advances the second counter exactly once and stores (0,1)

## 5. Live verification

- [x] 5.1 Run the live decoder for at least two full minutes; confirm `Minute identifier: PASSED` each minute and monotonic `Second NN/59` numbering with no doubled seconds
- [x] 5.2 Confirm DUT1 decoding is correct: live broadcast DUT1 is currently +0.0 (IERS Bulletin A: no DUT1/DUT2 in effect through 2029), so the non-zero negative path cannot be observed live this cycle; negative/zero/malformed behaviour is verified by unit tests (4.4) and the live display correctly shows +0.0
- [x] 5.3 Confirm the drift report is unchanged in behaviour (falling-edge reference) and within tens of ms for a UTC-synchronized host
