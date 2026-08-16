# Fix minute frame integrity

## Why

The live MSF decoder misdecodes every second that carries an `A=0, B=1` bit pair. Because DUT1 has been negative, seconds 01–16 of every minute can carry `A=0, B=1`; such a second produces **two** separate ~100 ms carrier-off gaps (one at second start, one for the B bit), and the pulse classifier treats the second gap as a fresh second boundary — advancing the second counter spuriously, misindexing the frame, and corrupting the DUT1 data (which is reported as 0.0 even when nonzero).

Additionally, the decoder never validates the NPL "Minute Identifier": the fixed A-bit sequence `01111110` in seconds 52–59, which per the NPL 2019 spec "never appears elsewhere in bit A, so it uniquely identifies the following second 00 minute marker". With no such check, slot misindexing (from the bug above or from any missed/dropped second) cannot be detected or recovered — the frame can be silently misaligned and only the parity checks stand between it and a wrong displayed time.

## What Changes

- The live pulse classifier SHALL decode all four A/B bit combinations, including `A=0, B=1` (pattern: ~100 ms off, ~100 ms on, ~100 ms off within a single second) without advancing the second counter on the intra-second gap.
- Each completed 60-second frame SHALL be validated against the Minute Identifier (`52A=0, 53A–58A=1, 59A=0`) in addition to the existing four parity checks, before the frame's time data is displayed.
- When a frame is misindexed, the system SHALL attempt to recover alignment by scanning the frame's A slots for the unique `01111110` signature and reindexing the frame to the found position; if the signature is not found anywhere, the frame SHALL be dropped.
- DUT1 SHALL be decoded and reported from seconds 01–16 B bits (positive/negative unary code), which becomes correct once the `A=0, B=1` decode is fixed.
- Out of scope: leap-second (59/61-second) minutes, in which the NPL spec shifts the signature position by one second. Frames in such minutes are expected to fail validation and be dropped; this is documented as a known limitation.

## Capabilities

### New Capabilities

(None)

### Modified Capabilities

- `demodulate`: Adds requirements for per-second A/B bit decoding (including the two-gap `A=0, B=1` case), Minute Identifier validation, and frame alignment recovery via signature scan.

## Impact

- `src/msf_clock/msf.py` — live pulse classifier and second state machine: `A=0, B=1` gap handling, resync/reindex logic.
- `src/msf_clock/decoder.py` — frame validation (Minute Identifier check + scan/reindex), DUT1 decode correctness.
- `openspec/specs/demodulate/spec.md` — new requirements appended.
- No SDR/hardware configuration changes; no API surface changes.
