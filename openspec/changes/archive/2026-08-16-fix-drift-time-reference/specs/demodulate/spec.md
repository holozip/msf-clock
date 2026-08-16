## ADDED Requirements

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
