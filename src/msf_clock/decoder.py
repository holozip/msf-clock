import numpy
import datetime


def bcd_decode(bit_array, start_sec, end_sec, weights):
    """Multiplies a specific slice of the frame array by its NPL protocol BCD weights."""
    # Strict array scalar coercion block loop
    sub_slice = numpy.zeros(len(weights), dtype=int)
    for idx, sec in enumerate(range(start_sec, end_sec + 1)):
        val = bit_array[sec]
        # If a slot contains multiple nested elements, extract the first entry safely
        if isinstance(val, (numpy.ndarray, list)):
            sub_slice[idx] = int(val[0])
        else:
            sub_slice[idx] = int(val)
    return int(numpy.sum(sub_slice * weights))


MINUTE_SIGNATURE = (0, 1, 1, 1, 1, 1, 1, 0)
SIGNATURE_SLOT = 52


def find_minute_signature(clean_a):
    """Scan a flattened A track for the 01111110 Minute Identifier; returns start slot or None."""
    doubled = numpy.concatenate([clean_a, clean_a])
    for slot in range(60):
        if tuple(doubled[slot:slot + len(MINUTE_SIGNATURE)]) == MINUTE_SIGNATURE:
            return slot
    return None


def print_atomic_clock(bits_a, bits_b, sys_snapshot_dt):
    """Validates parity tracks, extracts NPL data, and runs drift comparison math."""

    try:
        # --- FIXED: SAFE MULTI-ELEMENT ARRAY EXTRACTION SCALAR PICKER ---
        # Instead of calling .item(), we strictly extract the first element at the index location
        def get_scalar_bit(array_track, second_slot):
            bit_val = array_track[second_slot]
            if isinstance(bit_val, (numpy.ndarray, list)):
                return int(bit_val[0])
            return int(bit_val)

        # Flatten the entire data tracks to flat clean 1D integer arrays
        clean_a = numpy.zeros(60, dtype=int)
        clean_b = numpy.zeros(60, dtype=int)
        for i in range(60):
            clean_a[i] = get_scalar_bit(bits_a, i)
            clean_b[i] = get_scalar_bit(bits_b, i)

    except Exception as e:
        print(f"\n ❌ PARITY EXTRACTION FAULT: Frame array mismatch ({e}). Dropping data.\n")
        return

    # --- MINUTE IDENTIFIER: SCAN, ALIGN, VERIFY ---
    sig_start = find_minute_signature(clean_a)
    if sig_start is None:
        print("\n------------------ PARITY CHECK REPORT ------------------")
        print(" -> Minute Identifier (Sec 52-59):  FAILED (01111110 not found in frame)")
        print("---------------------------------------------------------")
        print(" ❌ FRAME DROPPED: Minute identifier missing. No time data displayed.\n")
        return

    delta = SIGNATURE_SLOT - sig_start
    if delta != 0:
        clean_a = numpy.roll(clean_a, delta)
        clean_b = numpy.roll(clean_b, delta)

    if tuple(clean_a[SIGNATURE_SLOT:SIGNATURE_SLOT + len(MINUTE_SIGNATURE)]) != MINUTE_SIGNATURE:
        print("\n------------------ PARITY CHECK REPORT ------------------")
        print(" -> Minute Identifier (Sec 52-59):  FAILED (sequence not at expected position)")
        print("---------------------------------------------------------")
        print(" ❌ FRAME DROPPED: Minute identifier invalid. No time data displayed.\n")
        return

    identifier_status = "PASSED" if delta == 0 else f"RECOVERED (Δ={delta:+d})"

    parity_year = int(clean_b[54])
    parity_date = int(clean_b[55])
    parity_dow = int(clean_b[56])
    parity_time = int(clean_b[57])

    # --- PARITY FIELD RANGE MATCHING ---
    # The sum of the data bits + the parity bit must equal an ODD number (sum % 2 == 1)
    year_valid = (numpy.sum(clean_a[17:25]) + parity_year) % 2 == 1  # Sec 17-24 (Year)
    date_valid = (numpy.sum(clean_a[25:36]) + parity_date) % 2 == 1  # Sec 25-35 (Month/Day)
    dow_valid = (numpy.sum(clean_a[36:39]) + parity_dow) % 2 == 1  # Sec 36-38 (DOW)
    time_valid = (numpy.sum(clean_a[39:52]) + parity_time) % 2 == 1  # Sec 39-51 (Hour/Min)

    print("\n------------------ PARITY CHECK REPORT ------------------")
    print(f" -> Minute Identifier (Sec 52-59):  {identifier_status}")
    print(f" -> Year Parity (Sec 54):  {'PASSED' if year_valid else 'FAILED'}")
    print(f" -> Date Parity (Sec 55):  {'PASSED' if date_valid else 'FAILED'}")
    print(f" -> DOW Parity  (Sec 56):  {'PASSED' if dow_valid else 'FAILED'}")
    print(f" -> Time Parity (Sec 57):  {'PASSED' if time_valid else 'FAILED'}")
    print("---------------------------------------------------------")

    if not (year_valid and date_valid and dow_valid and time_valid):
        print(" ❌ FRAME CORRUPTED: Parity check failed. Dropping data.\n")
        return

    # Extract DUT1 and STW parameters safely as flat arrays
    pos_dut1_count = numpy.sum(clean_b[1:9])
    neg_dut1_count = numpy.sum(clean_b[9:17])
    if pos_dut1_count > 0 and neg_dut1_count > 0:
        dut1_line = "MALFORMED DUT1 (positive and negative codes both set)"
    else:
        dut1_val = pos_dut1_count * 0.1 if pos_dut1_count > 0 else (neg_dut1_count * -0.1 if neg_dut1_count > 0 else 0.0)
        dut1_line = f"{dut1_val:+.1f} seconds"

    stw_warning = "ACTIVE (Time Change Impending)" if clean_b[53] == 1 else "Inactive"
    is_bst = clean_b[58] == 1
    tz_label = "BST (UTC+1)" if is_bst else "GMT (UTC+0)"

    # Parse BCD Data Fields
    w_year = numpy.array([80, 40, 20, 10, 8, 4, 2, 1])  # Sec 17-24
    w_month = numpy.array([10, 8, 4, 2, 1])  # Sec 25-29
    w_day = numpy.array([20, 10, 8, 4, 2, 1])  # Sec 30-35
    w_dow = numpy.array([4, 2, 1])  # Sec 36-38
    w_hour = numpy.array([20, 10, 8, 4, 2, 1])  # Sec 39-44
    w_minute = numpy.array([40, 20, 10, 8, 4, 2, 1])  # Sec 45-51

    year = bcd_decode(clean_a, 17, 24, w_year)
    month = bcd_decode(clean_a, 25, 29, w_month)
    day = bcd_decode(clean_a, 30, 35, w_day)
    dow = bcd_decode(clean_a, 36, 38, w_dow)
    hour = bcd_decode(clean_a, 39, 44, w_hour)
    minute = bcd_decode(clean_a, 45, 51, w_minute)

    days_map = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
    dow_str = days_map[dow] if dow < 7 else "Unknown"

    # --- TIME OFFSET AND BROADCAST DELAY ADJUSTMENTS ---
    target_hour_utc = hour - 1 if is_bst else hour
    target_minute = minute
    target_day = day

    if target_hour_utc < 0:
        target_hour_utc = 23
        target_day = max(1, day - 1)

    broadcast_target_dt = datetime.datetime(
        year=2000 + year, month=month, day=target_day,
        hour=target_hour_utc, minute=target_minute, second=0,
        tzinfo=datetime.timezone.utc
    )

    actual_atomic_utc_dt = broadcast_target_dt - datetime.timedelta(minutes=1)

    # Calculate RAW System Drift
    time_delta = sys_snapshot_dt - actual_atomic_utc_dt
    drift_seconds = time_delta.total_seconds()

    print("==================================================")
    print(" 🎉 SUCCESS: ATOMIC DATA TIME FRAME VERIFIED & RECEIVED")
    print(f" True Atomic Time: {hour:02d}:{minute:02d}:00 {tz_label}")
    print(f" True Atomic Date: 20{year:02d}-{month:02d}-{day:02d} ({dow_str})")
    print(f" Earth Orbit Correction (DUT1): {dut1_line}")
    print(f" DST Change Warning (STW):      {stw_warning}")
    print("--------------------------------------------------")
    print(f" ⏱️  LOCAL SYSTEM TIME DRIFT ANALYZER:")
    print(f"   -> System Clock Snapshot:   {sys_snapshot_dt.strftime('%H:%M:%S.%f')[:-3]} UTC")
    print(f"   -> Total Calculated Drift:  {drift_seconds:+.3f} seconds")

    if abs(drift_seconds) < 0.050:
        print("   -> Status: PERFECTLY IN SYNC (Drift within loop processing overhead)")
    elif drift_seconds > 0:
        print(f"   -> Status: YOUR COMPUTER SYSTEM CLOCK IS {drift_seconds:.3f}s FAST")
    else:
        print(f"   -> Status: YOUR COMPUTER SYSTEM CLOCK IS {abs(drift_seconds):.3f}s SLOW")
    print("==================================================\n")
