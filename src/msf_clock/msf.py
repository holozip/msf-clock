import SoapySDR
from SoapySDR import *
import numpy
import datetime
import os
import sys
import decoder

SAMPLE_RATE = 1e6
CHUNK_SIZE = 2000
DECIMATION_FACTOR = 1000  # 1 Msps / 1000 = exactly 1000 Hz target (1 sample = 1ms)

# Tune SDR to 60khz
HARDWARE_LO_FREQ = 60000.0

# --- SDR Initialization ---
sdr = SoapySDR.Device("driver=sdrplay")
sdr.setAntenna(SOAPY_SDR_RX, 0, "Tuner 1 Hi-Z")
sdr.setSampleRate(SOAPY_SDR_RX, 0, SAMPLE_RATE)
sdr.setFrequency(SOAPY_SDR_RX, 0, HARDWARE_LO_FREQ)

sdr.setGainMode(SOAPY_SDR_RX, 0, False)
sdr.setGain(SOAPY_SDR_RX, 0, 26.8)

# Setup SDR
rx_stream = sdr.setupStream(SOAPY_SDR_RX, SOAPY_SDR_CF32)
sdr.activateStream(rx_stream)

buffer = numpy.zeros(CHUNK_SIZE, dtype=numpy.complex64)
sample_accumulator = numpy.array([], dtype=numpy.complex64)

# --- TIMING STATE MACHINE REGISTERS ---
carrier_is_high = True
falling_edge_ms_idx = 0
global_ms_counter = 0

# --- RHYTHM REGISTERS ---
is_synchronized = False
current_second = 0
last_valid_pulse_ms = 0

# --- SYSTEM TIMESTAMP CAPTURE REGISTER ---
minute_trigger_system_time = None

# Leaky Peak Tracking Scalars
peak_high = 0.010
peak_low = 0.0005

# 60-Second Data Storage Buckets
frame_bit_a = numpy.zeros(60, dtype=int)
frame_bit_b = numpy.zeros(60, dtype=int)

print("\nDemodulator running in Real-Time Mode. Press Ctrl+C to stop.")
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

            # --- TIMING STATE MACHINE ---
            for sample in envelope_chunk:
                global_ms_counter += 1

                if sample > peak_high:
                    peak_high = sample
                else:
                    peak_high = 0.9995 * peak_high + 0.0005 * sample

                if sample < peak_low:
                    peak_low = sample
                else:
                    peak_low = 0.9995 * peak_low + 0.0005 * sample

                midpoint = (peak_high + peak_low) / 2.0

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

                        elif 450 <= pulse_duration_ms <= 550:
                            captured_system_dt = datetime.datetime.now(datetime.timezone.utc)

                            if is_synchronized:
                                decoder.print_atomic_clock(frame_bit_a, frame_bit_b, minute_trigger_system_time)

                            print("\n[Sync Locked] -> Minute Marker Caught! Aligning timeline...")
                            is_synchronized = True
                            current_second = 0
                            last_valid_pulse_ms = falling_edge_ms_idx
                            minute_trigger_system_time = captured_system_dt
                            frame_bit_a.fill(0)
                            frame_bit_b.fill(0)
                            continue

                        elif is_synchronized:
                            ms_since_last_pulse = falling_edge_ms_idx - last_valid_pulse_ms
                            last_valid_pulse_ms = falling_edge_ms_idx

                            elapsed_seconds = int(round(ms_since_last_pulse / 1000.0))

                            if elapsed_seconds > 0:
                                current_second += elapsed_seconds
                            else:
                                current_second += 1

                            if current_second > 59:
                                current_second = 59

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
