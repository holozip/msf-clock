# demodulate

## Purpose

Demodulate captured IQ samples of the MSF 60 kHz time signal: recover the amplitude envelope via the Hilbert transform, detect carrier edges, identify the minute marker, reconstruct the A/B channel bit streams, and report a signal quality metric.

## Requirements

### Requirement: Envelope detection
The system SHALL compute the signal envelope from IQ samples using the Hilbert transform (analytic signal magnitude) to recover the amplitude-modulated carrier envelope.

#### Scenario: Envelope from complex64 samples
- **WHEN** demodulate_samples is called with numpy complex64 samples
- **THEN** the system returns an envelope array with the same length as the input, where each value is the magnitude of the analytic signal

#### Scenario: Envelope reflects carrier presence
- **WHEN** the input contains a strong carrier signal at the expected frequency
- **THEN** the envelope shows high-amplitude regions corresponding to carrier-on periods and near-zero regions during carrier-off periods

### Requirement: Edge detection
The system SHALL detect carrier transition edges by thresholding the envelope and identifying zero-crossings of the envelope-minus-threshold signal.

#### Scenario: Rising edge detection
- **WHEN** the envelope crosses above the threshold (carrier-off to carrier-on transition)
- **THEN** the system records an 'on' edge at the interpolated timestamp of the crossing

#### Scenario: Falling edge detection
- **WHEN** the envelope crosses below the threshold (carrier-on to carrier-off transition)
- **THEN** the system records an 'off' edge at the interpolated timestamp of the crossing

#### Scenario: Sub-sample edge interpolation
- **WHEN** an edge falls between two sample points
- **THEN** the system interpolates the exact crossing point using linear interpolation between the two surrounding samples

### Requirement: Edge output format
The system SHALL output edges as a list of Edge objects, each containing a timestamp (in seconds from capture start) and a phase ('on' or 'off').

#### Scenario: Edge namedtuple structure
- **WHEN** demodulate_samples returns edges
- **THEN** each edge is a namedtuple-like object with attributes `timestamp` (float, seconds) and `phase` (str, 'on' or 'off')

#### Scenario: Edges are chronologically ordered
- **WHEN** the edge list is returned
- **THEN** edges are sorted by timestamp in ascending order

### Requirement: Minute marker detection
The system SHALL identify the start of each minute by detecting the 500 ms carrier-off period that marks second 00 (the minute marker).

#### Scenario: Minute marker as long off period
- **WHEN** the system scans the edge timeline for the first extended carrier-off period
- **THEN** the system identifies a carrier-off duration of ≥400 ms as the minute marker boundary

#### Scenario: Minute marker followed by second 00
- **WHEN** the minute marker is detected
- **THEN** the system marks the subsequent carrier-on edge as the start of second 00

### Requirement: Bit reconstruction
The system SHALL derive two parallel bit streams (the A channel and the B channel) from the edge timeline following the MSF protocol structure defined in the NPL specification: within each second, bit A occupies the 100–200 ms interval and bit B occupies the 200–300 ms interval, both measured from the start of the second's carrier-off marker.

#### Scenario: Bit polarity
- **WHEN** the system evaluates a 100 ms bit slot within a second
- **THEN** carrier-on during the slot is interpreted as logical 0, and carrier-off is interpreted as logical 1

#### Scenario: Per-second A and B assignment
- **WHEN** the system processes a second while synchronized
- **THEN** the A bit is taken from the 100–200 ms interval and the B bit from the 200–300 ms interval of that same second, and both are stored in the current second's slot of the respective channel

#### Scenario: A=0, B=1 second with two off intervals
- **WHEN** a second carries A=0 and B=1 (start-of-second off, about 100 ms on, about 100 ms off, then long on)
- **THEN** the system assigns A=0 and B=1 to that second's slot and does not treat the second carrier-off interval as a new second boundary

#### Scenario: Bit stream output
- **WHEN** demodulate_samples is called with return_bits=True
- **THEN** the system returns both A and B channel bit lists, each containing integers 0 or 1, aligned to the minute marker

#### Scenario: Incomplete second handling
- **WHEN** the last second in the input data is incomplete (fewer than 700 ms of carrier at the end)
- **THEN** the system skips that second and does not include its bit in the output

### Requirement: Signal quality metric
The system SHALL compute and return a signal quality estimate based on the ratio of envelope peak to envelope noise floor.

#### Scenario: SNR calculation
- **WHEN** demodulate_samples completes
- **THEN** the system returns a quality dict containing `snr_db` (float, estimated SNR in decibels) and `edge_count` (int, number of detected edges)

#### Scenario: Low signal warning
- **WHEN** the estimated SNR is below 10 dB
- **THEN** the system includes a 'low_snr' flag in the quality dict to indicate unreliable demodulation

### Requirement: CLI interface
The system SHALL provide a CLI entry point that reads IQ sample data from a file and writes demodulated output to stdout.

#### Scenario: Demodulate from file
- **WHEN** the user runs `msf-demodulate --input capture.raw`
- **THEN** the system reads the .raw file, demodulates the signal, and prints edge timestamps and bit values to stdout

#### Scenario: Help text
- **WHEN** the user runs `msf-demodulate --help`
- **THEN** the system prints available flags: `--input`, `--sample-rate`, `--threshold`, `--output`

### Requirement: Drift measurement time reference
The system SHALL reference the system-time drift computation to the off onset (carrier ON→OFF transition, falling edge) of the minute marker, which is the event the NPL MSF specification transmits with accuracy better than ±1 ms relative to UTC. The system SHALL NOT use the end of the marker's carrier-OFF period (the rising edge) as the time reference for drift.

#### Scenario: Snapshot captured at off onset
- **WHEN** the system detects a carrier-OFF period of 450–550 ms (the minute marker)
- **THEN** the system-time instant used for drift computation is the instant the OFF period began (falling edge), not the instant it ended

#### Scenario: Falling-edge timestamp captured before marker confirmation
- **WHEN** a falling edge begins a carrier-OFF period of as-yet-unknown duration
- **THEN** the system records the falling edge's wall-clock time and uses it only if the period is subsequently classified as the minute marker

#### Scenario: No half-second bias
- **WHEN** a complete minute frame is decoded and drift is printed
- **THEN** the reported drift differs from the value computed with a rising-edge reference by approximately −500 ms, and for a system clock close to UTC the reported drift is within tens of milliseconds rather than ≈ +500 ms

#### Scenario: Missing falling-edge timestamp
- **WHEN** a carrier-OFF period classifies as the minute marker but no falling-edge wall-clock time is available
- **THEN** the system falls back to using the current (rising-edge) wall-clock time, retaining previous behaviour rather than failing

### Requirement: Second index stability
The system SHALL advance the second index by exactly one for each UTC second present in the synchronized signal, independent of the A/B bit values decoded in that second, so that frame slots remain aligned to UTC seconds.

#### Scenario: Index advances once per second for all bit combinations
- **WHEN** the synchronized signal contains seconds with any A/B combination, including A=0, B=1
- **THEN** the second index increments by exactly one per observed second and each second's bits are stored in that second's slot

#### Scenario: No spurious advance from intra-second off interval
- **WHEN** the second carrier-off interval of an A=0, B=1 second is detected
- **THEN** the second index is not advanced and the previously stored A=0 value for that second is retained

#### Scenario: Missed second absorbed by interval rounding
- **WHEN** the interval between consecutive second markers indicates more than one elapsed second (a detected gap was missed)
- **THEN** the second index advances by the rounded whole-second count for that interval

### Requirement: Minute identifier validation
The system SHALL validate each completed 60-second frame against the NPL Minute Identifier before displaying its time data: bit A of second 52 SHALL be 0, bits A of seconds 53–58 SHALL be 1, and bit A of second 59 SHALL be 0. Validation SHALL occur in addition to the existing parity checks.

#### Scenario: Aligned frame passes validation
- **WHEN** a completed frame's A bits at seconds 52–59 equal 01111110 and all parity checks pass
- **THEN** the system displays the frame's time and date data and reports the identifier check as PASSED

#### Scenario: Invalid identifier drops the frame
- **WHEN** the Minute Identifier cannot be found intact in the completed frame
- **THEN** the system drops the frame, reports the identifier check as FAILED, and displays no time data for that frame

#### Scenario: Validation precedes display
- **WHEN** a completed frame has failed identifier validation regardless of parity results
- **THEN** the system reports the failure and displays no time data for that frame

### Requirement: Frame alignment recovery
The system SHALL use the uniqueness of the Minute Identifier sequence 01111110 within the A bit stream (guaranteed by NPL specification) to scan a completed frame's A slots and recover alignment when the frame is misindexed.

#### Scenario: Signature found at expected position
- **WHEN** the scan finds 01111110 starting at second slot 52
- **THEN** the frame is treated as aligned and proceeds to identifier/parity validation

#### Scenario: Signature found at shifted position
- **WHEN** the scan finds an intact 01111110 sequence starting at slot k other than 52
- **THEN** the system reindexes the frame (shifting both A and B streams) so that the sequence starts at slot 52, reports the applied offset (Δ), and proceeds to identifier/parity validation on the reindexed frame

#### Scenario: No intact signature
- **WHEN** the scan finds no intact 01111110 sequence in any A slot (e.g. the sequence was truncated by overflow clamping or corrupted)
- **THEN** the system drops the frame and reports the identifier check as FAILED

### Requirement: DUT1 decoding
The system SHALL decode the DUT1 code from the B bits of seconds 01–16 using the NPL unary scheme: consecutive 1s in bits 01B–08B indicate positive DUT1 (+0.1 s per bit), consecutive 1s in bits 09B–16B indicate negative DUT1 (−0.1 s per bit), and the two codes are mutually exclusive.

#### Scenario: Negative DUT1 reported
- **WHEN** B bits 09–16 contain n consecutive 1s and bits 01–08 are all 0
- **THEN** the system reports DUT1 as −0.1·n seconds

#### Scenario: Zero DUT1 reported
- **WHEN** B bits 01–16 are all 0
- **THEN** the system reports DUT1 as 0.0 seconds

#### Scenario: Malformed DUT1 flagged
- **WHEN** both a positive (bits 01–08) and a negative (bits 09–16) DUT code are set in the same frame
- **THEN** the system reports the DUT1 field as MALFORMED and counts the frame invalid rather than displaying a value
