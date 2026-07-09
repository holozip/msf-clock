import SoapySDR
from SoapySDR import *
import numpy

# --- HARDWARE CONFIGURATION PARAMS ---
SAMPLE_RATE = 1e6
CHUNK_SIZE = 10240
DECIMATION_FACTOR = 1000  # 1 Msps / 1000 = exactly 1000 Hz target (1 sample = 1ms)

# Direct 60 kHz Hardware Tuning
HARDWARE_LO_FREQ = 60000.0

# --- SDR Initialization ---
sdr = SoapySDR.Device("driver=sdrplay")
sdr.setAntenna(SOAPY_SDR_RX, 0, "Tuner 1 Hi-Z")
sdr.setSampleRate(SOAPY_SDR_RX, 0, SAMPLE_RATE)
sdr.setFrequency(SOAPY_SDR_RX, 0, HARDWARE_LO_FREQ)

sdr.setGainMode(SOAPY_SDR_RX, 0, False)
sdr.setGain(SOAPY_SDR_RX, 0, 26.8)

# Setup standard Complex Float 32-bit stream interface
rx_stream = sdr.setupStream(SOAPY_SDR_RX, SOAPY_SDR_CF32)
sdr.activateStream(rx_stream)

buffer = numpy.zeros(CHUNK_SIZE, dtype=numpy.complex64)
sample_accumulator = numpy.array([], dtype=numpy.complex64)

# Slicer long history buffer (10 seconds) to calculate the dynamic threshold
THRESHOLD_HISTORY_LEN = 10000
threshold_history = numpy.zeros(THRESHOLD_HISTORY_LEN)
thresh_ptr = 0

# --- TIMING STATE MACHINE REGISTERS ---
carrier_is_high = True
falling_edge_ms_idx = 0
global_ms_counter = 0

# --- RHYTHM REGISTERS ---
is_synchronized = False
current_second = 0

# --- NEW: ABSOLUTE TIME STAMP TRACKERS ---
last_valid_pulse_ms = 0  # Remembers the global millisecond marker of the last valid pulse

# --- 60-SECOND FRAME MEMORY BUFFER BUCKETS ---
frame_bit_a = numpy.zeros(60, dtype=int)
frame_bit_b = numpy.zeros(60, dtype=int)


def bcd_decode(bit_array, start_sec, end_sec, weights):
    sub_slice = bit_array[start_sec:end_sec + 1]
    if len(sub_slice) != len(weights):
        return 0
    return int(numpy.sum(sub_slice * weights))


def print_atomic_clock(bits_a, bits_b):
    """Validates frame parity, extracts DUT1, checks STW/DST states, and prints final readout"""

    # Extract Parity bits from Bit B track
    parity_year = bits_b[54]
    parity_date = bits_b[55]
    parity_dow = bits_b[56]
    parity_time = bits_b[57]

    # Calculate Odd Parity Validation Status
    year_valid = (numpy.sum(bits_a[17:25]) + parity_year) % 2 == 1
    date_valid = (numpy.sum(bits_a[25:36]) + parity_date) % 2 == 1
    dow_valid = (numpy.sum(bits_a[36:39]) + parity_dow) % 2 == 1
    time_valid = (numpy.sum(bits_a[39:52]) + parity_time) % 2 == 1

    print("\n------------------ PARITY CHECK REPORT ------------------")
    print(f" -> Year Parity (Sec 54):  {'PASSED' if year_valid else 'FAILED'}")
    print(f" -> Date Parity (Sec 55):  {'PASSED' if date_valid else 'FAILED'}")
    print(f" -> DOW Parity  (Sec 56):  {'PASSED' if dow_valid else 'FAILED'}")
    print(f" -> Time Parity (Sec 57):  {'PASSED' if time_valid else 'FAILED'}")
    print("---------------------------------------------------------")

    if not (year_valid and date_valid and dow_valid and time_valid):
        print(" ❌ FRAME CORRUPTED: Parity check failed. Dropping data.\n")
        return

    # Extract DUT1 Orbital Correction
    pos_dut1_count = numpy.sum(bits_b[1:9])
    neg_dut1_count = numpy.sum(bits_b[9:17])
    dut1_val = pos_dut1_count * 0.1 if pos_dut1_count > 0 else (neg_dut1_count * -0.1 if neg_dut1_count > 0 else 0.0)

    # Extract Summer Time Change Warning (Second 53)
    stw_warning = "ACTIVE (Time Change Impending)" if bits_b[53] == 1 else "Inactive"

    # --- NEW: AUTOMATIC TIME ZONE LABEL SWITCHER ---
    # Second 58 is the official MSF Summer Time indicator bit
    is_bst = bits_b[58] == 1
    tz_label = "BST (UTC+1)" if is_bst else "GMT (UTC+0)"

    # Parse BCD Data Fields
    w_year = numpy.array([80, 40, 20, 10, 8, 4, 2, 1])
    w_month = numpy.array([10, 8, 4, 2, 1])
    w_day = numpy.array([20, 10, 8, 4, 2, 1])
    w_dow = numpy.array([4, 2, 1])
    w_hour = numpy.array([20, 10, 8, 4, 2, 1])
    w_minute = numpy.array([40, 20, 10, 8, 4, 2, 1])

    year = bcd_decode(bits_a, 17, 24, w_year)
    month = bcd_decode(bits_a, 25, 29, w_month)
    day = bcd_decode(bits_a, 30, 35, w_day)
    dow = bcd_decode(bits_a, 36, 38, w_dow)
    hour = bcd_decode(bits_a, 39, 44, w_hour)
    minute = bcd_decode(bits_a, 45, 51, w_minute)

    days_map = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
    dow_str = days_map[dow] if dow < 7 else "Unknown"

    print("==================================================")
    print(" 🎉 SUCCESS: ATOMIC DATA TIME FRAME VERIFIED & RECEIVED")
    print(f" Time Readout: {hour:02d}:{minute:02d}:00 {tz_label}")
    print(f" Date Readout: 20{year:02d}-{month:02d}-{day:02d} ({dow_str})")
    print(f" Earth Orbit Correction (DUT1): {dut1_val:+.1f} seconds")
    print(f" DST Change Warning (STW):      {stw_warning}")
    print("==================================================\n")


print("Demodulator running with Absolute Edge Sync tracking active. Press Ctrl+C to stop.")
print("Waiting for a 500ms Minute Marker to align time slots...\n")

try:
    while True:
        sr = sdr.readStream(rx_stream, [buffer], CHUNK_SIZE, timeoutUs=100000)
        if sr.ret <= 0: continue

        valid_samples = buffer[:sr.ret]
        if len(valid_samples) > 0:
            sample_accumulator = numpy.append(sample_accumulator, valid_samples)

        if len(sample_accumulator) >= DECIMATION_FACTOR:
            keep_count = len(sample_accumulator) // DECIMATION_FACTOR
            end_idx = keep_count * DECIMATION_FACTOR

            processing_block = sample_accumulator[:end_idx]
            sample_accumulator = sample_accumulator[end_idx:]

            reshaped_block = processing_block.reshape(-1, DECIMATION_FACTOR)
            averaged_block = numpy.mean(reshaped_block, axis=1)
            envelope_chunk = numpy.abs(averaged_block)

            for val in envelope_chunk:
                threshold_history[thresh_ptr] = val
                thresh_ptr = (thresh_ptr + 1) % THRESHOLD_HISTORY_LEN

            sig_max = numpy.max(threshold_history)
            sig_min = numpy.min(threshold_history)
            midpoint = (sig_max + sig_min) / 2.0

            # --- TIMING STATE MACHINE ---
            for sample in envelope_chunk:
                global_ms_counter += 1

                if carrier_is_high:
                    if sample < midpoint:
                        carrier_is_high = False
                        falling_edge_ms_idx = global_ms_counter
                else:
                    if sample > midpoint:
                        carrier_is_high = True
                        pulse_duration_ms = global_ms_counter - falling_edge_ms_idx

                        if pulse_duration_ms < 50:
                            continue

                        # Check for the 500ms Minute Sync Marker
                        elif 450 <= pulse_duration_ms <= 550:
                            if is_synchronized:
                                print_atomic_clock(frame_bit_a, frame_bit_b)

                            print("\n[Sync Locked] -> Minute Marker Caught! Aligning timeline...")
                            is_synchronized = True
                            current_second = 0
                            last_valid_pulse_ms = falling_edge_ms_idx
                            frame_bit_a.fill(0)
                            frame_bit_b.fill(0)
                            continue

                        # --- NEW: ABSOLUTE TIME GAP REALIGNMENT ENGINE ---
                        elif is_synchronized:
                            # Calculate exactly how many milliseconds passed since the previous real pulse
                            ms_since_last_pulse = falling_edge_ms_idx - last_valid_pulse_ms
                            last_valid_pulse_ms = falling_edge_ms_idx

                            # Round the elapsed time to the nearest whole second block
                            elapsed_seconds = int(round(ms_since_last_pulse / 1000.0))

                            # If a OS stutter happened, this handles the slot jump automatically!
                            if elapsed_seconds > 0:
                                current_second += elapsed_seconds
                            else:
                                current_second += 1  # Default increment fall-through

                            if current_second > 59:
                                current_second = 59  # Boundary clip safety fallback

                            a_bit, b_bit = 0, 0
                            if 80 <= pulse_duration_ms <= 140:
                                a_bit, b_bit = 0, 0
                            elif 180 <= pulse_duration_ms <= 240:
                                a_bit, b_bit = 1, 0
                            elif 280 <= pulse_duration_ms <= 340:
                                a_bit, b_bit = 1, 1

                            frame_bit_a[current_second] = a_bit
                            frame_bit_b[current_second] = b_bit

                            print(
                                f"Second {current_second:02d}/59 -> Bits: A={a_bit}, B={b_bit} (Width: {pulse_duration_ms}ms | Step: +{elapsed_seconds}s)")

except KeyboardInterrupt:
    print("\nStopping loop...")
finally:
    sdr.deactivateStream(rx_stream)
    sdr.closeStream(rx_stream)
