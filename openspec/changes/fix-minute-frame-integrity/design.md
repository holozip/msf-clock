# Design: fix-minute-frame-integrity

## Context

The live decoder (`src/msf_clock/msf.py` + `src/msf_clock/decoder.py`) works as:

1. SDRPlay stream at 1 Msps, decimated to one 1 ms envelope sample per chunk average.
2. Adaptive-midpoint state machine (leaky peak trackers) detects carrier on/off edges; a "pulse" is a carrier-OFF interval measured in ms.
3. Gap classification while synchronized:
   - 450–550 ms → minute marker (500 ms off onset): decode the just-completed frame, reset buffers and the second counter.
   - Otherwise: `current_second += round(ms_since_last_gap / 1000)`, then gap width → bit pair: 80–140 ms → (A,B)=(0,0); 180–240 ms → (1,0); 280–340 ms → (1,1); stored at `frame_bit_[a|b][current_second]`.
4. `decoder.print_atomic_clock` runs four odd-parity checks over A bits seconds 17–51, then BCD-decodes the time/date and reports DUT1 (from B bits 01–16), STW/BST, and drift against the falling-edge wall-clock reference (drift reference fix already merged).

Per the NPL 2019 spec (`docs/msf-time-date-code-2019.txt:38-59`), each second's bits occupy fixed phases: bit A at 100–200 ms, bit B at 200–300 ms after the second's marker, carrier-on = 0. Consequences:

- Three of the four A/B pairs produce exactly **one** off gap per second: (0,0)→100 ms, (1,0)→200 ms, (1,1)→300 ms.
- **A=0, B=1 produces two**: ~100 ms off, ~100 ms on, ~100 ms off, then ~700 ms on. Today the second (100 ms) gap is reclassified as a fresh second boundary: `round(200/1000)=0` → `current_second += 1` spuriously, the slot is overwritten with (0,0), and the B=1 bit is lost. DUT1 currently (negative) makes seconds 09–16 (worst case 01–16) `A=0, B=1`, so the frame drifts several slots per minute, DUT1 always reports 0.0, and parity reads A bits from wrong slots.
- The spec's **Minute Identifier**: A bits of seconds 52–59 are permanently `01111110`, which "never appears elsewhere in bit A, so it uniquely identifies the following second 00 minute marker". The decoder captures these A bits but never checks them.

## Goals / Non-Goals

**Goals:**

- Correct A/B decode for all four combinations, including `A=0, B=1`, without spurious second-counter advances.
- Per-frame validation against the Minute Identifier in addition to the existing parity checks.
- Alignment recovery when a misindexed frame still contains an intact signature; safe drop when it does not.
- DUT1 reported from real decoded bits.

**Non-Goals:**

- Leap-second (59/61-second) minute handling — the signature shifts by one second there; frames are expected to fail validation and drop (documented limitation).
- Using the signature as a leading *lock* accelerator (pre-arming the minute marker near end-of-frame).
- Changing the offline `demodulate_samples` tool surface, SDR configuration, or the drift time reference.

## Decisions

### D1: Detect A=0, B=1 by the preceding carrier-ON duration, not by gap width

The B-bit gap of an `A=0, B=1` second is ~100 ms — identical in width to a start-of-second gap. The distinguishing context is the carrier-ON run **before** the gap:

- B-bit gap: previous rising edge (end of start-of-second gap) was ~100 ms earlier → ON run ≈ 100 ms.
- Any legitimate start-of-second gap: the preceding ON run is the tail of the previous second minus its marker, in the range ~500–800 ms (500 ms after the minute marker).

So: when an off gap of 80–140 ms completes, if the ON run since the previous rising edge is 60–160 ms, classify it as the **B bit of the current second**: set `frame_bit_b[current_second] = 1` (A stays 0, already stored), do **not** advance `current_second`, and update `last_valid_pulse_ms` to this rising edge (the next second's start-of-second gap then arrives ~800 ms later → still rounds to +1 second).

The 100 ms nominal sits far from every legitimate start-of-second ON run (≥500 ms), giving ~400 ms of margin on each side; the adaptive threshold's ms jitter is at most a few ms.

**Alternatives considered:**

- *Classify by inter-gap spacing alone* (gap only 200 ms after the previous → back-fix the earlier slot): retroactive corrections of already-stored slots, fragile under a missed gap.
- *Slot-sampling rewrite* (sample the envelope at fixed 150/250 ms offsets from each marker): correct long-term, but rewrites the streaming loop; deferred.

### D2: Validate at frame completion; scan-then-verify in `print_atomic_clock`

The signature only exists once seconds 52–59 have been received, so validation happens at frame completion (it cannot speed initial lock). New flow in `print_atomic_clock`, before any display:

1. **Scan** the 60 A slots for the 8-bit sequence `01111110` (a 60×8 comparison — the NPL spec guarantees exactly one occurrence in a correctly received frame).
2. **Align**: found at slot 52 → aligned. Found at slot k → roll both A and B tracks by (52 − k) so true second 52 lands at slot 52, and continue. This is the recovery path for slot drift from any missed/duplicated second.
3. **Verify**: after alignment, confirm `A[52]=0, A[53..58]=1, A[59]=0` (equivalent in the aligned case to the scan hit; a belt-and-braces position check).
4. **Then** the existing four parity checks; only if all pass, BCD-decode and display. Any failure (no signature found, or parity) drops the frame with a reason line in the existing report block; a recovered frame is displayed but reports the applied offset (e.g. `Minute identifier: RECOVERED (Δ=+3)`) so chronic drift stays visible in logs.

**Alternatives considered:**

- *Position-only verification* (check slots 52–59, drop on mismatch): simpler, but converts every misindexing event into a lost minute — exactly the outcome this change is meant to prevent.
- *Parity-only recovery*: parity carries no positional information; cannot reindex.

Note: when overflow clamping (`current_second > 59 → 59`) has already overwritten the signature tail, the scan correctly fails and the frame drops — a safe failure, consistent with the fail-closed intent.

### D3: DUT1 decode unchanged, gains a malformed guard

The decoder already computes `pos = sum(B[1:8])`, `neg = sum(B[9:16])` and maps to ±pos*0.1 / −neg*0.1. Once D1 lands, the bits are real. Add one guard: per the NPL spec the positive and negative DUT codes are mutually exclusive; if both are nonzero the frame's DUT field is malformed → report `MALFORMED DUT1` (and count the frame invalid) rather than silently printing a value.

### D4: Leap-second minutes deliberately fail closed

In a 59/61-second minute the NPL spec shifts all bit positions by one, so the signature lands at 53–60A / 51–58A (or is truncated by the slot-59 clamp). The frame will fail validation and be dropped; the next minute re-locks on the 500 ms marker as today. This matches the NPL "shortcomings" note that autonomous receivers may lose sync around a leap second; proper 59/61 s handling is a future change.

## Risks / Trade-offs

- [A noise-induced ~100 ms ON blip plus a ~100 ms gap could fake a B-bit classification] → the only legitimate 100 ms ON run between gaps is the D1 case; any residual misdecode is caught by the signature/parity gate — the failure mode is a dropped frame, never a displayed wrong time.
- [Lost-second + A=0,B=1 combinations in the same minute] → verified orthogonal: a lost marker is absorbed by the `round(ms_since/1000)` interval (always +2; ms_since bounded 1800–2200 ms across all A/B combos) and re-synchronizes the counter, while the D1 discriminator (the ~100 ms ON run) is a local property of the intra-second structure and is unaffected by the previous second's loss. A zeroed slot in a parity-covered range (17–51) or the signature region (52–59) drops the frame; a zeroed DUT slot (1–16) leaves displayed time intact (DUT1 at worst off by 0.1 s, report-only).
- [B slots 17–59 are unguarded by design (parity and signature are A-only)] → a noise-faked B=1 there is structurally undetectable, but the blast radius is loud, not silent: a spurious B at 58 flips the BST flag for a winter minute and shows up as a ≈ ±1 h drift in the existing drift analysis; B at 1–16 changes only the DUT1 report (±0.1 s); B at 17–52 is written to a slot the decoder never reads.
- [Recovery (roll) could mask a systematic classifier fault] → the applied offset (Δ) is printed every recovered minute; persistent Δ≠0 is immediately visible in the log and diagnosable.
- [Dropping frames in a leap minute extends gaps with no display] → parity would have failed those frames anyway; behavior is strictly more conservative, and re-lock is automatic on the next 500 ms marker.
- [Uniqueness of `01111110` is a property of the transmitted code] → enforced by the NPL transmitter; even if the transmitter ever deviated, worst case is dropped frames (false negatives), not misaligned acceptance (false positives).
- [Rolling the B track by the A-estimated offset assumes A/B drifted together] → they share the same `current_second` counter today, so any misindexing applies to both tracks identically.

## Migration Plan

- Self-contained in `msf.py` + `decoder.py`; no persisted state, no migration.
- Verification without hardware: unit-test the reindex/validate/DUT1 logic with synthetic 60×2 frames (signature at 52; at k≠52; absent; DUT1 ±/0/malformed).
- Live verification: one minute of reception — expect `Minute identifier: PASSED` each minute, monotonic `Second N/59` numbering with no doubled seconds, and a nonzero negative DUT1 line.
- Rollback: revert the commit; prior behavior restored (misindexing remains, as today).

## Open Questions

- Should a **recovered** (Δ≠0) frame be displayed at all, or only logged? Current decision: display, since after the roll the frame is aligned and parity-verified — but flagging this for review at implementation time is cheap.
