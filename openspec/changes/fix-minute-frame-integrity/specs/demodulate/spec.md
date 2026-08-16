## MODIFIED Requirements

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

## ADDED Requirements

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
