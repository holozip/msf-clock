## ADDED Requirements

### Requirement: SDR device discovery
The system SHALL enumerate available SoapySDR devices and identify the SDRPlay RSPduo by its label. If the RSPduo is not detected, it SHALL fall back to the first available SoapySDR device or allow the user to specify a device index or address.

#### Scenario: RSPduo detected
- **WHEN** the user runs `msf-capture` with an RSPduo connected
- **THEN** the system selects the 8 MS/s master device and prints its index

#### Scenario: No RSPduo detected
- **WHEN** the user runs `msf-capture` with no RSPduo but another SoapySDR device connected
- **THEN** the system uses the user-specified device index (default 0)

#### Scenario: User specifies device address
- **WHEN** the user runs `msf-capture --device-addr "driver=sdrplay,serial=..."`
- **THEN** the system uses the provided address string directly

#### Scenario: Probe mode
- **WHEN** the user runs `msf-capture --probe`
- **THEN** the system lists all available SoapySDR devices and exits without capturing

### Requirement: Stream configuration
The system SHALL configure the SDR stream with the following parameters:
- Sample rate: configurable via `-r` flag (default 1 MHz)
- RF frequency: configurable via `-f` flag (default 60 kHz, the MSF signal frequency)
- Gain: automatic gain control enabled
- Antenna: High-Z input selected for LF reception
- Stream format: CS16 (complex 16-bit interleaved I/Q)

#### Scenario: Default configuration
- **WHEN** the user runs `msf-capture` with no flags
- **THEN** the stream is configured at 60 kHz, 1 MHz sample rate, auto-gain, High-Z antenna

#### Scenario: Custom frequency and rate
- **WHEN** the user runs `msf-capture -f 60000 -r 2000000`
- **THEN** the stream is configured at 60 kHz, 2 MHz sample rate

### Requirement: IQ sample capture
The system SHALL capture raw IQ samples from the SDR stream in chunks, handling partial reads from the hardware. The capture loop SHALL continue until the requested number of samples is collected.

#### Scenario: Successful capture
- **WHEN** the user runs `msf-capture -n 1000000`
- **THEN** the system captures exactly 1,000,000 samples and reports the elapsed time

#### Scenario: Partial read handling
- **WHEN** the SDR driver returns fewer samples than requested in a single `readStream` call
- **THEN** the system continues reading in chunks until the full sample count is reached

#### Scenario: Capture error
- **WHEN** `readStream` returns an error (return value <= 0)
- **THEN** the system prints an error message and exits with a non-zero status

### Requirement: GQRX .cfile output format
The system SHALL write captured IQ samples to a `.cfile` in GQRX-compatible format:
- Data type: interleaved float32 (`[I0, Q0, I1, Q1, ...]`)
- Values normalized to [-1.0, 1.0] by dividing int16 raw values by 32768.0
- File extension: `.cfile`
- The system SHALL also write a JSON metadata sidecar (`.cfile.json`) containing format description, sample count, sample rate, center frequency, timestamp, and elapsed time

#### Scenario: Correct byte layout
- **WHEN** the system writes a `.cfile`
- **THEN** the file contains interleaved float32 values (4 bytes per I, 4 bytes per Q) in little-endian byte order

#### Scenario: Normalization
- **WHEN** int16 raw samples with maximum value (32767) are captured
- **THEN** the normalized output value is 0.999969... (32767/32768), within [-1.0, 1.0]

#### Scenario: Metadata sidecar
- **WHEN** the system writes a `.cfile`
- **THEN** a `.cfile.json` file is written with format, num_samples, sample_rate, frequency, timestamp, elapsed_seconds, and actual_sample_rate fields

#### Scenario: GQRX compatibility
- **WHEN** the generated `.cfile` is opened in GQRX
- **THEN** GQRX correctly interprets the interleaved float32 I/Q data and displays the signal spectrum

### Requirement: CLI interface
The system SHALL preserve all existing CLI flags with identical behavior:
- `-f, --frequency`: RF frequency in Hz (default: 60000)
- `-r, --rate`: Sample rate in Hz (default: 1000000)
- `-n, --num-samples`: Number of samples (default: 1000000)
- `-o, --output`: Output file path
- `-d, --device`: Device index (default: 0)
- `--device-addr`: Device address string
- `--probe`: List devices and exit

#### Scenario: Default flags
- **WHEN** the user runs `msf-capture` with no arguments
- **THEN** the system captures 1,000,000 samples at 60 kHz / 1 MHz and saves to `msf_capture_<timestamp>.cfile`

#### Scenario: Custom output path
- **WHEN** the user runs `msf-capture -o /tmp/my_capture.cfile`
- **THEN** the output is saved to `/tmp/my_capture.cfile`

#### Scenario: Help text
- **WHEN** the user runs `msf-capture --help`
- **THEN** the system prints a description and all available flags with their defaults
