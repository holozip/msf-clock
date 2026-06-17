## 1. Back up current code and add section comments

- [x] 1.1 Copy current `capture.py` to `capture.py.bak` for reference
- [x] 1.2 Add top-level module docstring explaining the SDR signal chain (RF → downconversion → IQ demodulation → CS16 → float32 → .cfile)
- [x] 1.3 Add section comment headers dividing the file into: Constants, Device Discovery, Stream Setup, Capture Engine, File I/O, CLI, Main

## 2. Extract SDR capture engine class

- [x] 2.1 Create `SDRCaptureEngine` class with `__init__`, `__enter__`, `__exit__` for context manager support
- [x] 2.2 Move device discovery logic (`find_sdr`) into `SDRCaptureEngine.__init__` with device enumeration and RSPduo detection
- [x] 2.3 Move stream setup logic (`setup_stream`) into `SDRCaptureEngine.setup_stream()` with configurable frequency, sample rate, gain, antenna
- [x] 2.4 Move stream activation/deactivation/cleanup into `__enter__` / `__exit__`

## 3. Refactor capture loop with documentation

- [x] 3.1 Move capture loop into `SDRCaptureEngine.capture(num_samples)` method
- [x] 3.2 Add inline comments explaining: CS16 format (interleaved int16 I/Q), chunked reads (why 65536), partial read handling
- [x] 3.3 Keep the chunking logic identical to current implementation (65536 chunk size, loop until num_samples reached)

## 4. Refactor GQRX file output

- [x] 4.1 Extract `.cfile` writing into a standalone `write_cfile(samples, path, metadata)` function
- [x] 4.2 Add explicit comments documenting the GQRX `.cfile` format: interleaved float32, [-1, 1] normalization, little-endian
- [x] 4.3 Extract metadata JSON writing into `write_cfile_metadata(path, metadata)` function
- [x] 4.4 Add format validation: verify byte order, sample count, and metadata fields after writing

## 5. Refactor CLI and main function

- [x] 5.1 Keep `main()` as a thin wrapper that instantiates `SDRCaptureEngine` and calls methods sequentially
- [x] 5.2 Preserve all existing CLI flags (`-f`, `-r`, `-n`, `-o`, `-d`, `--device-addr`, `--probe`) with identical defaults and behavior
- [x] 5.3 Keep `--probe` mode logic unchanged
- [x] 5.4 Keep output filename auto-generation logic (`msf_capture_<timestamp>.cfile`)

## 6. Verify and test

- [x] 6.1 Run `python -c "from msf_clock.capture import main"` with `--probe` to verify device listing works
- [x] 6.2 Run a 10s capture (`-n 10000`) and verify the `.cfile` file structure (byte count, interleaved pattern)
- [x] 6.3 Verify the `.cfile.json` metadata contains all required fields
- [x] 6.4 Load the `.cfile` in GQRX and verify the signal spectrum displays correctly
- [x] 6.5 Compare output of refactored code with `.bak` version for a short capture to ensure byte-identical results
- [x] 6.6 Add software decimation: moving-average FIR filter with factor 40, clip to [-1, 1], output at 25 ksps
- [x] 6.7 Verify MSF signal (60 kHz carrier, ±5 Hz dithering, 1 Hz clock markers, 100 Hz subcarriers) is visible in decimated spectrum
