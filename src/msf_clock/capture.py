"""
MSF clock signal IQ capture using SDRPlay RSPduo via SoapySDR.

Signal chain:
  1. RF front-end: tuned to 60 kHz (MSF transmitter frequency)
  2. Downconversion: SDR hardware converts RF to baseband I/Q
  3. CF32 capture: SoapySDR delivers interleaved float32 (I0, Q0, I1, Q1, ...)
  4. Direct write: no conversion needed, bytes already in GQRX .raw format

GQRX .raw format:
   - Binary layout: [I0_f32, Q0_f32, I1_f32, Q1_f32, ...] (little-endian)
   - Each sample is 2 x 4 bytes (8 bytes per complex sample)
   - Values in float32 range (typically [-1.0, 1.0])
   - No header, no sidecar metadata

Requires:
  System: soapy-sdr, soapy-sdr-play3 (Debian/Ubuntu)
  Python: numpy (via pip or system package python3-numpy)
"""

import argparse
import json
import sys
import time
from pathlib import Path

try:
    import SoapySDR
except ImportError:
    print("Error: SoapySDR Python bindings not found.")
    print("  Install with: sudo apt-get install python3-soapysdr")
    sys.exit(1)

try:
    import numpy as np
except ImportError:
    print("Error: numpy not installed.")
    print("  Install with: pip install numpy  (or: sudo apt-get install python3-numpy)")
    sys.exit(1)

# =============================================================================
# Constants
# =============================================================================

# MSF signal parameters
# To receive RF at 60 kHz
MSF_FREQUENCY = 60000  # 60khz
SAMPLE_RATE = 1000000  # 1Msps (matches GQRX reference, ideal for MSF ~100 Hz BW)
NUM_SAMPLES_DEFAULT = 10000000  # 10 second by default
CF_FILE_EXT = ".raw"

# GQRX naming convention for automatic sample rate/frequency detection
# Pattern: gqrx_yymmdd_hhmmss_<center_freq>_<sample_rate>_fc.raw
# Example: gqrx_260612_160000_60000000_100000_fc.raw
#   - center_freq = 60000000 (60 MHz)
#   - sample_rate = 100000 (100 ksps)
GQRX_FILE_PREFIX = "gqrx"
GQRX_FILE_EXT = ".raw"

# CF32 chunk size - RSPduo may not return all requested samples in one readStream call
# 65536 is a power-of-2 buffer that fits comfortably in memory and matches USB transfer sizes
CF32_CHUNK_SIZE = 65536

# Decimation is not used — capture at native rate, write directly
DEFAULT_DECIMATION_FACTOR = 1


# =============================================================================
# Device Discovery
# =============================================================================

def find_sdr(device_idx: int = 0, device_addr: str | None = None) -> SoapySDR.Device:
    """Find and return the SDRPlay RSPduo device.

    Device selection priority:
      1. Explicit device address string (via --device-addr)
      2. 8 MS/s master device on RSPduo (preferred for LF reception)
      3. First RSPduo/RSPdevice found
      4. User-specified index or first available device

    Args:
        device_idx: Index into enumerated device list (default: 0).
        device_addr: Full SoapySDR address string (e.g. "driver=sdrplay,serial=...").

    Returns:
        Configured SoapySDR.Device instance.
    """
    SoapySDR.loadModules()

    if device_addr:
        kwargs = SoapySDR.KwargsFromString(device_addr)
        print(f"Using device: {device_addr}")
        return SoapySDR.Device(kwargs)

    # Enumerate all SDRPlay devices first, then fall back to all SoapySDR devices
    devices = SoapySDR.Device.enumerate(SoapySDR.KwargsFromString("driver=sdrplay"))
    if not devices:
        devices = SoapySDR.Device.enumerate(SoapySDR.KwargsFromString(""))

    if not devices:
        print("Error: No SoapySDR devices found.")
        print("  Make sure the SDRPlay driver is installed and the device is connected.")
        print("  Run 'SoapySDRUtil --probe' to verify.")
        sys.exit(1)

    # Print all available devices
    for i, dev_info in enumerate(devices):
        d = dev_info.asdict()
        label = d.get("label", "")
        print(f"  [{i}] {label}")

    # Try to find RSPduo specifically
    rspduo_devices = []
    for i, dev_info in enumerate(devices):
        d = dev_info.asdict()
        label = d.get("label", "")
        if "rspduo" in label.lower() or "sdrplay" in label.lower():
            rspduo_devices.append(i)

    if rspduo_devices:
        # Prefer the Single Tuner device (first RSPduo entry) for LF reception
        # The 8 MHz master mode has a 138 kHz baseband offset that complicates tuning
        device_idx = rspduo_devices[0]
        d = devices[device_idx].asdict()
        print(f"Found RSPduo Single Tuner at device index {device_idx}: {d.get('label', '')}")
    else:
        print(f"No RSPduo detected. Using device index {device_idx}")

    # Build kwargs from the selected device
    dev_info = devices[device_idx]
    d = dev_info.asdict()
    kwargs = SoapySDR.KwargsFromString(
        f"driver={d['driver']},serial={d['serial']}"
    )
    return SoapySDR.Device(kwargs)


# =============================================================================
# Stream Setup
# =============================================================================

def _setup_stream(sdr: SoapySDR.Device, frequency: float, sample_rate: float):
    """Configure the SDR stream for IQ capture.

    Configuration:
      - Sample rate: user-specified (default 1 MHz)
      - RF frequency: user-specified (default 60 kHz for MSF)
      - Gain: automatic (gain mode enabled, hardware controls RF gain)
      - Antenna: High-Z input (optimized for LF signals like MSF at 60 kHz)
      - Stream format: CF32 (complex 32-bit interleaved I/Q)

    Args:
        sdr: Opened SoapySDR.Device instance.
        frequency: RF center frequency in Hz.
        sample_rate: Baseband sample rate in samples/second.

    Returns:
        The SoapySDR.Stream object for the configured stream.
    """
    channel = 0

    # Set sample rate
    sdr.setSampleRate(SoapySDR.SOAPY_SDR_RX, channel, sample_rate)

    # Set RF frequency
    sdr.setFrequency(SoapySDR.SOAPY_SDR_RX, channel, frequency)

    # Set RF gain (manual, 0 dB = strongest signal for RSPduo at LF)
    # RSPduo gain control is an attenuator at LF — 0 dB gives strongest signal
    sdr.setGainMode(SoapySDR.SOAPY_SDR_RX, channel, False)
    sdr.setGain(SoapySDR.SOAPY_SDR_RX, channel, 0)

    # Enable High-Z antenna input for MSF LF reception
    sdr.setAntenna(SoapySDR.SOAPY_SDR_RX, channel, "Tuner 1 Hi-Z")

    # Setup stream with CF32 format (complex 32-bit interleaved I/Q)
    # CF32 = float32[I0, Q0, I1, Q1, ...] - each complex sample is 8 bytes
    # Already in GQRX .raw format - no conversion needed
    stream = sdr.setupStream(SoapySDR.SOAPY_SDR_RX, "CF32")

    print(f"Stream configured:")
    print(f"  Frequency: {frequency / 1e3:.1f} kHz")
    print(f"  Sample rate: {sample_rate / 1e6:.1f} MS/s")
    print(f"  Channel: RX0")

    return stream


# =============================================================================
# Capture Engine
# =============================================================================

class SDRCaptureEngine:
    """Encapsulates SDR device lifecycle, stream configuration, and IQ sample capture.

    Usage as a context manager ensures proper cleanup:
        with SDRCaptureEngine(freq, rate) as engine:
            samples = engine.capture(num_samples)

    The engine handles:
      - Device opening and closing
      - Stream setup and activation/deactivation
      - Chunked sample reading (RSPduo may deliver samples in fragments)
      - CF32 (float32) direct capture, no conversion needed
    """

    def __init__(self, frequency: float, sample_rate: float,
                 device_idx: int = 0, device_addr: str | None = None):
        """Initialize the capture engine.

        Args:
            frequency: RF center frequency in Hz.
            sample_rate: Baseband sample rate in samples/second.
            device_idx: Device index for enumeration (default: 0).
            device_addr: Explicit device address string.
        """
        self.frequency = frequency
        self.sample_rate = sample_rate
        self.device_idx = device_idx
        self.device_addr = device_addr
        self.sdr = None
        self.stream = None

    def __enter__(self):
        """Open device, configure stream, activate stream."""
        # Open and configure the SDR device
        self.sdr = find_sdr(self.device_idx, self.device_addr)
        # Store the stream object returned by _setup_stream
        self.stream = _setup_stream(self.sdr, self.frequency, self.sample_rate)

        # Activate the stream for reading
        self.sdr.activateStream(self.stream)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Deactivate stream, close stream, close device."""
        if self.sdr is not None:
            try:
                if self.stream is not None:
                    self.sdr.deactivateStream(self.stream)
                    self.sdr.closeStream(self.stream)
            except Exception:
                pass  # Best-effort cleanup
            try:
                self.sdr.close()
            except Exception:
                pass
        return False  # Do not suppress exceptions

    def capture(self, num_samples: int, output_path: Path) -> dict:
        """Capture IQ samples and save to GQRX .raw format.

        Capture process:
          1. Allocate buffer for CF32 (interleaved float32 I/Q) samples
          2. Read in chunks of CF32_CHUNK_SIZE (65536) - RSPduo may not return
             all samples in a single readStream call, so we loop until complete
          3. Write interleaved float32 I/Q data directly to .raw (GQRX native format)

        Args:
            num_samples: Number of complex samples to capture.
            output_path: Path for the output .raw file.

        Returns:
            Metadata dict with capture details.
        """
        print(f"\nCapturing {num_samples} samples...")
        start_time = time.time()

        # Buffer for complex float32 IQ samples
        # CF32 format: SoapySDR writes complex64 numpy array directly
        # Each element is np.complex64 (8 bytes = 2 x float32)
        buf = np.zeros(num_samples, dtype=np.complex64)

        # Read in chunks - RSPduo/streaming drivers may not return all samples at once.
        # 65536 is a reasonable chunk size that fits in USB transfer buffers.
        total_read = 0
        chunk_size = min(CF32_CHUNK_SIZE, num_samples)

        try:
            while total_read < num_samples:
                to_read = min(chunk_size, num_samples - total_read)
                # Allocate fresh buffer for each chunk to avoid view/strides issues
                chunk_buf = np.zeros(to_read, dtype=np.complex64)
                result = self.sdr.readStream(self.stream, [chunk_buf], to_read, timeoutUs=100000)
                ret = result.ret
                flags = result.flags
                time_ns = result.timeNs

                if ret <= 0:
                    print(f"Capture error: readStream returned {result}")
                    sys.exit(1)

                buf[total_read:total_read + ret] = chunk_buf[:ret]
                total_read += ret

            actual_samples = total_read
            elapsed = time.time() - start_time

            # CF32 stream delivers complex64 numpy array — tobytes() gives interleaved float32 [I0, Q0, I1, Q1, ...]
            # Already in GQRX .raw format — just write directly
            output_samples = actual_samples
            output_sample_rate = self.sample_rate

            # Write the .raw file (GQRX native format, no header, no metadata sidecar)
            output_path.write_bytes(buf[:actual_samples].tobytes())

            metadata = {
                "num_samples": output_samples,
                "sample_rate": output_sample_rate,
                "frequency": self.frequency,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(start_time)),
                "elapsed_seconds": elapsed,
                "actual_sample_rate": output_samples / elapsed,
                "capture_sample_rate": self.sample_rate,
            }

            print(f"Captured {actual_samples} samples in {elapsed:.3f}s")
            print(f"  Output file: {output_path} ({output_path.stat().st_size / 1024 / 1024:.1f} MB)")
            print(f"  Sample rate: {self.sample_rate / 1e6:.1f} MS/s")

            return metadata

        except Exception as e:
            print(f"Capture failed: {e}")
            raise

    def probe(self):
        """List all available SoapySDR devices and exit."""
        SoapySDR.loadModules()
        devices = SoapySDR.Device.enumerate(SoapySDR.KwargsFromString(""))
        print("Available SoapySDR devices:")
        for i, dev in enumerate(devices):
            d = dev.asdict()
            label = d.get("label", "")
            print(f"  [{i}] {label}")


# =============================================================================
# File I/O
# =============================================================================

def write_iq(iq_data: np.ndarray, output_path: Path) -> None:
    """Write IQ samples to GQRX-compatible .raw format.

    GQRX .raw format specification:
      - Binary layout: interleaved float32 [I0, Q0, I1, Q1, ...]
      - Endianness: little-endian (native on x86/x64)
      - Each complex sample = 8 bytes (2 x float32)
      - Total file size = num_samples x 8 bytes
      - No header, no metadata sidecar

    Args:
        iq_data: numpy float32 array of interleaved I/Q values.
        output_path: Path for the .raw output.
    """
    output_path.write_bytes(iq_data.tobytes())





def validate_iq(output_path: Path, expected_samples: int) -> bool:
    """Validate the .iq format after writing.

    Checks:
      - File exists and has correct size (expected_samples x 8 bytes)
      - File can be read as interleaved float32
      - Values are within [-1.0, 1.0] range

    Args:
        output_path: Path to the .iq file.
        expected_samples: Expected number of complex samples.

    Returns:
        True if validation passes, False otherwise.
    """
    if not output_path.exists():
        print(f"Validation failed: {output_path} does not exist")
        return False

    expected_size = expected_samples * 8  # 8 bytes per complex sample (2 x float32)
    actual_size = output_path.stat().st_size

    if actual_size != expected_size:
        print(f"Validation failed: expected {expected_size} bytes, got {actual_size}")
        return False

    # Read and verify float32 values are in [-1, 1]
    data = np.frombuffer(output_path.read_bytes(), dtype=np.float32)
    if data.size != expected_samples * 2:
        print(f"Validation failed: expected {expected_samples * 2} float32 values, got {data.size}")
        return False

    if not np.all((data >= -1.0) & (data <= 1.0)):
        print("Validation failed: values outside [-1.0, 1.0] range")
        return False

    return True





# =============================================================================
# CLI
# =============================================================================

def main():
    """CLI entry point for MSF clock signal capture."""
    parser = argparse.ArgumentParser(description="Capture MSF clock signal IQ data")
    parser.add_argument("-f", "--frequency", type=float, default=MSF_FREQUENCY,
                        help=f"RF frequency in Hz (default: {MSF_FREQUENCY})")
    parser.add_argument("-r", "--rate", type=float, default=SAMPLE_RATE,
                        help=f"Sample rate in Hz (default: {SAMPLE_RATE})")
    parser.add_argument("-n", "--num-samples", type=int, default=NUM_SAMPLES_DEFAULT,
                        help=f"Number of samples to capture (default: {NUM_SAMPLES_DEFAULT})")
    parser.add_argument("-o", "--output", type=str, default=None,
                        help="Output file path (default: gqrx_<timestamp>_<freq>_<rate>_fc.raw)")
    parser.add_argument("-d", "--device", type=int, default=0,
                        help="Device index (default: 0)")
    parser.add_argument("--device-addr", type=str, default=None,
                        help="Device address string")
    parser.add_argument("--probe", action="store_true",
                        help="List available devices and exit")
  

    args = parser.parse_args()

    if args.probe:
        engine = SDRCaptureEngine(args.frequency, args.rate, args.device, args.device_addr)
        engine.probe()
        return

    # Generate output filename if not specified
    # Use GQRX naming convention for automatic sample rate/frequency detection
    # Pattern: gqrx_yymmdd_hhmmss_<center_freq>_<sample_rate>_fc.raw
    if args.output is None:
        timestamp = time.strftime("%y%m%d_%H%M%S")
        args.output = f"{GQRX_FILE_PREFIX}_{timestamp}_{int(args.frequency)}_{int(args.rate)}_fc{GQRX_FILE_EXT}"

    output_path = Path(args.output)

    # Capture using context manager for proper cleanup
    with SDRCaptureEngine(args.frequency, args.rate, args.device, args.device_addr) as engine:
        metadata = engine.capture(args.num_samples, output_path)

    # Validate output
    actual_num_samples = metadata.get("num_samples", args.num_samples)
    if validate_iq(output_path, actual_num_samples):
        print(f"  Output validation: OK")
    else:
        print("  Output validation: FAILED")

    print("\nDone.")


if __name__ == "__main__":
    main()
