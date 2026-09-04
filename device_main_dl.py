# =========================================================================
# UCT Micromouse - Milestone 1: Run a Square (1m x 1m)
# =========================================================================
# ASSIGNMENT DESCRIPTION:
# Implement a control loop to drive the mouse in a 1 meter by 1 meter square,
# turning 90 degrees at each corner, and returning to the start position.
#w
# KEY CONTROLS:
# - uct_mouse.set_motors(left_pwm, right_pwm) -> Set speed (-100 to 100)
# - uct_mouse.get_encoders() -> Returns (left_ticks, right_ticks)
# - uct_mouse.get_tof()      -> Returns (left_mm, center_mm, right_mm)
# - uct_mouse.delay_ms(ms)   -> Suspends execution and updates sensors
#
# GRADING:
# - The autograder applies 8% motor imbalance and 8% wheel slip.
# - Oÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿjson "robot" block) ---
WHEEL_RADIUS_M = 0.0325
TICKS_PER_REV = 1170.0
TICK_DIST_M = (2.0 * math.pi * WHEEL_RADIUS_M) / TICKS_PER_REV

# --- Control loop pacing ---
STEP_MS = 10
DT_S = STEP_MS / 1000.0

# --- Motor deadband margin ---
# tools/simulation_config.json defines dead_band_l/r ~= 60 (+/- perturbation).
# Any commanded PWM below the deadband produces zero wheel motion, so every
# "moving" speed used below is kept comfortably above that threshold.
MIN_ACTIVE_PWM = 68.0
MAX_PWM = 100.0

# --- Straight-line drive tuning ---
DRIVE_CRUISE_PWM = 88.0
DRIVE_APPROACH_PWM = 74.0
DRIVE_APPROACH_DIST_M = 0.15
KP_HEADING = 2.5        # PWM correction per degree of heading error
KD_HEADING = 0.10       # PWM correction per (deg/s) of instantaneous gyro rate.
                         # Rate feedback (damping on the raw sensor reading, not on
                         # accumulated angle): counters a disturbance the instant it
                         # appears, instead of waiting for it to integrate into
                         # heading_deg before the P-term can react. Targets the
                         # simulator's ~200ms "starting slip" event specifically.
KP_SYNC = 0.03           # PWM correction per tick of left/right encoder mismatch
MAX_CORRECTION_PWM = 18.0
DRIVE_TIMEOUT_MS = 8000

# --- Turn-in-place tuning ---
TURN_TARGET_DEG = 90.0
TURN_COARSE_PWM = 82.0
TURN_FINE_PWM = 70.0
TURN_COARSE_THRESHOLD_DEG = 25.0
TURN_SETTLE_TOL_DEG = 2.0
TURN_SETTLE_TICKS = 10          # consecutive in-tolerance 10ms ticks (100ms)
TURN_NUDGE_PWM = 70.0
TURN_NUDGE_MS = 20
TURN_TIMEOUT_MS = 4000

# --- Battery safety guard ---
BATT_NOMINAL_V = 6.0
BATT_LOW_V = 5.2
BATT_MIN_SCALE = 0.6


def clamp(value, lo, hi):
    return max(lo, min(hi, value))


def battery_scale():
    """Scales commanded speeds down if supply voltage sags under load."""
    v = uct_mouse.get_vbatt()
    if v <= 0.0 or v >= BATT_NOMINAL_V:
        return 1.0
    if v <= BATT_LOW_V:
        return BATT_MIN_SCALE
    span = BATT_NOMINAL_V - BATT_LOW_V
    return BATT_MIN_SCALE + (v - BATT_LOW_V) / span * (1.0 - BATT_MIN_SCALE)


def drive_straight(distance_m):
    """
    Closed-loop straight line control.
    Distance is measured from the average of both encoders; heading is
    tracked by integrating the gyro yaw rate every control tick and fed
    back as a differential PWM correction to hold 0 degrees heading.
    """
    print(f"Driving straight for {distance_m}m...")
    l0, r0 = uct_mouse.get_encoders()
    heading_deg = 0.0
    elapsed_ms = 0
    scale = battery_scale()

    while elapsed_ms < DRIVE_TIMEOUT_MS:
        gyro_dps = uct_mouse.get_gyro()
        heading_deg += gyro_dps * DT_S

        l, r = uct_mouse.get_encoders()
        dist_l = (l - l0) * TICK_DIST_M
        dist_r = (r - r0) * TICK_DIST_M
        avg_dist = (dist_l + dist_r) / 2.0
        remaining = distance_m - avg_dist

        if remaining <= 0.0:
            break

        base = DRIVE_APPROACH_PWM if remaining <= DRIVE_APPROACH_DIST_M else DRIVE_CRUISE_PWM
        base *= scale

        heading_error = 0.0 - heading_deg
        sync_error = (l - l0) - (r - r0)
        correction = clamp(
            KP_HEADING * heading_error - KD_HEADING * gyro_dps - KP_SYNC * sync_error,
            -MAX_CORRECTION_PWM, MAX_CORRECTION_PWM,
        )

        left_pwm = clamp(base - correction, MIN_ACTIVE_PWM, MAX_PWM)
        right_pwm = clamp(base + correction, MIN_ACTIVE_PWM, MAX_PWM)

        uct_mouse.set_motors(int(left_pwm), int(right_pwm))
        uct_mouse.delay_ms(STEP_MS)
        elapsed_ms += STEP_MS

    uct_mouse.set_motors(0, 0)


def turn_left_90():
    """
    Closed-loop turn-in-place control.
    Spins with the left wheel reversed / right wheel forward while
    integrating gyro yaw until +90 degrees is reached, then holds inside a
    settling window (with small corrective nudges if needed) to avoid
    overshoot and oscillation before handing control back.
    """
    print("Turning 90 degrees left...")
    heading_deg = 0.0
    elapsed_ms = 0
    settle_count = 0
    scale = battery_scale()

    while elapsed_ms < TURN_TIMEOUT_MS:
        gyro_dps = uct_mouse.get_gyro()
        heading_deg += gyro_dps * DT_S
        error = TURN_TARGET_DEG - heading_deg

        if abs(error) <= TURN_SETTLE_TOL_DEG:
            uct_mouse.set_motors(0, 0)
            settle_count += 1
            if settle_count >= TURN_SETTLE_TICKS:
                break
        else:
            # Always keep driving (never idle at 0,0) while outside tolerance:
            # sitting at zero PWM mid-turn holds the mouse motionless, and the
            # simulator watchdog auto-ends the whole run after 3s of no motion.
            settle_count = 0
            spin = TURN_COARSE_PWM if abs(error) > TURN_COARSE_THRESHOLD_DEG else TURN_FINE_PWM
            spin *= scale
            direction = 1.0 if error > 0 else -1.0
            uct_mouse.set_motors(int(-spin * direction), int(spin * direction))

        uct_mouse.delay_ms(STEP_MS)
        elapsed_ms += STEP_MS

    # Final trim: if we settled outside tolerance (e.g. coast undershot),
    # apply brief corrective nudges rather than leaving the heading wrong.
    while elapsed_ms < TURN_TIMEOUT_MS and abs(TURN_TARGET_DEG - heading_deg) > TURN_SETTLE_TOL_DEG:
        error = TURN_TARGET_DEG - heading_deg
        direction = 1.0 if error > 0 else -1.0
        spin = TURN_NUDGE_PWM * scale
        uct_mouse.set_motors(int(-spin * direction), int(spin * direction))
        uct_mouse.delay_ms(TURN_NUDGE_MS)
        elapsed_ms += TURN_NUDGE_MS
        gyro_dps = uct_mouse.get_gyro()
        heading_deg += gyro_dps * (TURN_NUDGE_MS / 1000.0)
        uct_mouse.set_motors(0, 0)
        uct_mouse.delay_ms(STEP_MS)
        elapsed_ms += STEP_MS

    uct_mouse.set_motors(0, 0)


def run_square():
    if not uct_mouse.init():
        print("Initialization failed.")
        return

    # Load polarity calibration if it exists
    try:
        with open("polarity.txt", "r") as f:
            lines = f.read().strip().split(",")
            uct_mouse.set_polarity(int(lines[0]), int(lines[1]))
            if len(lines) >= 4:
                uct_mouse.set_encoder_polarity(int(lines[2]), int(lines[3]))
    except Exception:
        uct_mouse.set_polarity(1, 1)

    print("--- Milestone 1: Run a Square ---")

    for side in range(4):
        # 1. Drive forward 1 meter
        drive_straight(1.0)

        # 2. Settle briefly
        uct_mouse.set_motors(0, 0)
        uct_mouse.delay_ms(200)

        # 3. Turn 90 degrees left
        turn_left_90()

        # 4. Settle briefly
        uct_mouse.set_motors(0, 0)
        uct_mouse.delay_ms(200)

    # Come to a complete, autonomous stop and hold for >= 3s to make
    # task completion unambiguous on video and in the telemetry log.
    uct_mouse.set_motors(0, 0)
    uct_mouse.delay_ms(3000)

    print("Milestone 1 Completed!")


if __name__ == "__main__":
    run_square()
