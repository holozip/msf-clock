## ADDED Requirements

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
The system SHALL derive two parallel bit streams (A channel and B channel) from the edge timeline using the MSF protocol structure defined in the NPL specification.

#### Scenario: Bit polarity
- **WHEN** the system evaluates a 100 ms slot within a second
- **THEN** carrier-on during the slot is interpreted as logical 0, and carrier-off is interpreted as logical 1

#### Scenario: A channel (even seconds)
- **WHEN** the system processes an even-numbered second (00, 02, 04, ...)
- **THEN** the bit value is assigned to the A channel

#### Scenario: B channel (odd seconds)
- **WHEN** the system processes an odd-numbered second (01, 03, 05, ...)
- **THEN** the bit value is assigned to the B channel

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
