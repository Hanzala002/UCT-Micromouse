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
# - Open-loop timing alone will accumulate errors. Use encoder and gyro
#   feedback to compensate.
# =========================================================================

import uct_mouse
import math

# --- Robot geometry (matches tools/simulation_config.json "robot" block) ---
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
TURN_COARSE_PWM = 84.0
TURN_FINE_PWM = 72.0
TURN_COARSE_THRESHOLD_DEG = 25.0
TURN_SETTLE_TOL_DEG = 2.0
TURN_SETTLE_TICKS = 10          # consecutive in-tolerance 10ms ticks (100ms)
TURN_BRAKE_RATE_DPS = 30.0      # residual spin rate above which coasting at 0 PWM
                                 # isn't enough to hold position -- angular momentum
                                 # keeps carrying it (see TURN_BRAKE_LOOKAHEAD_S).
TURN_BRAKE_PWM = 84.0
# Reacting only once heading is already inside the settle tolerance is too
# late: at the coarse/fine spin rates measured (~150-200 deg/s), the mouse
# was sailing from +90.5 deg all the way to +114.5 deg before 0 PWM (friction
# alone) could arrest it -- momentum, not a sign or unit bug. Instead,
# extrapolate the current gyro rate forward by this lookahead window every
# tick; once that predicted heading would overshoot the target band, start
# actively braking (reverse PWM) immediately, well before crossing into the
# tolerance window, rather than after.
TURN_BRAKE_LOOKAHEAD_S = 0.15
TURN_NUDGE_PWM = 70.0
TURN_NUDGE_MS = 20
TURN_TIMEOUT_MS = 6000  # was 4000 -- widened by 2s as a diagnostic check on whether the timeout itself is cutting turns short

# Sanity check: the turn loop otherwise trusts get_gyro() blindly. If it reads
# near-zero for a long stretch while actively commanding full turn PWM, that's
# not plausible physical stillness -- it points at a stall, a wall crash, or a
# sensor/connection fault silently returning stale data (this exact failure
# mode showed up in simulator testing: a wall crash closed the connection and
# the mock kept returning near-zero gyro readings with no visible error).
FLAT_GYRO_DPS = 5.0        # deg/s -- suspicious if this low while actively driving
FLAT_GYRO_WARN_TICKS = 20  # ~200-300ms of real ticks before flagging

# --- Battery safety guard ---
# This board's supply reads out of a 3.3V rail (not the 6-7.4V nominal RC
# battery pack range some other boards use), so the thresholds are scaled
# to that range instead.
BATT_NOMINAL_V = 3.3
BATT_LOW_V = 2.8
BATT_MIN_SCALE = 0.6

# Pivot turns need much more torque margin than straight driving: both wheels
# must scrub/slip at once to rotate the chassis in place, so under-throttling
# a turn doesn't just slow it down (as it does for drive_straight()) -- it can
# fail to rotate the chassis at all. On hardware, 82*0.6=49 PWM never overcame
# static friction, so turns get a shallower floor than straight-line driving.
TURN_BATT_MIN_SCALE = 0.85
# A single instantaneous vbatt read can catch a transient post-drive_straight()
# voltage sag and lock in a too-low scale for the whole turn. Sample a few
# times a few ms apart instead and take the max, so a dip that recovers within
# tens of ms can't falsely trigger the floor (a genuinely low, sustained
# battery still reads low across every sample, so the floor still applies).
TURN_VBATT_SAMPLES = 4
TURN_VBATT_SAMPLE_MS = 15

# --- Gyro bias calibration ---
# MEMS gyros read a small nonzero rate even sitting still. Integrating that
# raw offset over an 8s drive_straight() accumulates into a large phantom
# heading error, which the heading P-term then "corrects" -- steering the
# mouse into a growing curve. Sampled once at startup while stationary.
GYRO_BIAS_DPS = 0.0
GYRO_CAL_SAMPLES = 200
GYRO_CAL_SAMPLE_MS = 10


def clamp(value, lo, hi):
    return max(lo, min(hi, value))


def battery_scale_from_vbatt(v, min_scale):
    if v <= 0.0 or v >= BATT_NOMINAL_V:
        return 1.0
    if v <= BATT_LOW_V:
        return min_scale
    span = BATT_NOMINAL_V - BATT_LOW_V
    return min_scale + (v - BATT_LOW_V) / span * (1.0 - min_scale)


def battery_scale(min_scale=BATT_MIN_SCALE):
    """Scales commanded speeds down if supply voltage sags under load."""
    return battery_scale_from_vbatt(uct_mouse.get_vbatt(), min_scale)


def turn_battery_scale():
    """Battery scale for turn_left_90(): takes the max of a few quick vbatt
    samples instead of one instantaneous read, so a transient voltage sag
    right after drive_straight() (which recovers within tens of ms) can't
    lock in a too-low scale for the whole turn."""
    best_v = 0.0
    for i in range(TURN_VBATT_SAMPLES):
        best_v = max(best_v, uct_mouse.get_vbatt())
        if i < TURN_VBATT_SAMPLES - 1:
            uct_mouse.delay_ms(TURN_VBATT_SAMPLE_MS)
    return battery_scale_from_vbatt(best_v, TURN_BATT_MIN_SCALE)


def calibrate_gyro_bias():
    """Samples the gyro while stationary to measure its resting offset."""
    global GYRO_BIAS_DPS
    print("Calibrating gyro bias (keep mouse still)...")
    total = 0.0
    for _ in range(GYRO_CAL_SAMPLES):
        total += uct_mouse.get_gyro()
        uct_mouse.delay_ms(GYRO_CAL_SAMPLE_MS)
    GYRO_BIAS_DPS = total / GYRO_CAL_SAMPLES
    print(f"Gyro bias: {GYRO_BIAS_DPS:.4f} deg/s")


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
        gyro_dps = uct_mouse.get_gyro() - GYRO_BIAS_DPS
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

    Two-stage coarse/fine spin speed (TURN_COARSE_PWM above
    TURN_COARSE_THRESHOLD_DEG remaining, TURN_FINE_PWM below it): this is the
    same shape as the first version of this function that was proven on
    hardware to settle cleanly at ~90-91.5 degrees across a full run. Every
    commanded speed is floored at MIN_ACTIVE_PWM after battery scaling, so a
    low-battery scale factor can never silently drop it below the motor
    deadband.

    The timeout budget is tracked against real elapsed time
    (uct_mouse.get_ticks_ms(), a wall-clock ms counter available on both
    real hardware and the PC simulator), not an assumed-fixed 10ms step. On
    real hardware uct_mouse.delay_ms() is a busy-poll loop that also
    refreshes sensors internally, so a single "10ms" tick can genuinely take
    longer -- with a fixed-step assumption the timeout was cutting the turn
    off well before the (under-tracked) heading ever reached 90 degrees.

    Heading is a separate matter and is integrated against the FIXED nominal
    step (DT_S), not that same measured wall-clock gap -- delay_ms(STEP_MS)
    always performs exactly one exchange with the PC simulator, which steps
    its own physics by exactly DT_S simulated seconds per exchange (the rate
    negotiated once via configure(rate=100) in micromouse.py). On a real-time
    (non-fast-sim) run the measured wall-clock gap is inflated well past
    STEP_MS by OS sleep granularity, so integrating heading against it
    overstates the turn versus the simulator's own ground truth -- confirmed
    via --json-log, where the reported heading read +88 deg while the
    simulator's actual theta had only reached +59 deg for the same turn.

    Power is scaled via turn_battery_scale() rather than battery_scale(): a
    pivot needs much more torque margin than straight driving, and a single
    instantaneous vbatt read right after drive_straight() can catch a
    transient sag and falsely floor the whole turn (see its docstring).
    """
    print(f"Turning {TURN_TARGET_DEG:.0f} degrees left...")
    heading_deg = 0.0
    settle_count = 0
    settled = False
    scale = turn_battery_scale()

    start_ms = uct_mouse.get_ticks_ms()
    last_print_ms = start_ms
    flat_gyro_ticks = 0
    flat_gyro_warned = False

    while uct_mouse.get_ticks_ms() - start_ms < TURN_TIMEOUT_MS:
        uct_mouse.delay_ms(STEP_MS)

        now_ms = uct_mouse.get_ticks_ms()
        # Integrate over the FIXED nominal step (DT_S, same constant
        # drive_straight() uses), not the measured wall-clock gap. The PC
        # simulator negotiates a fixed exchange rate via configure(rate=100)
        # and steps its physics by exactly 1/rate == DT_S seconds per
        # delay_ms(STEP_MS) exchange, regardless of how long that exchange
        # actually took on the wall clock. On real-time (non-fast-sim) runs,
        # OS sleep granularity inflates the measured gap well past STEP_MS
        # (confirmed via --json-log: reported heading hit +88 deg while the
        # simulator's own ground-truth theta had only reached +59 deg for the
        # same turn) -- integrating against that inflated gap overstates the
        # heading beyond what actually happened, letting the mouse hand
        # control back believing it's on-heading when it is not. STEP_MS is
        # unaffected: delay_ms(STEP_MS) always performs exactly one exchange.
        gyro_dps = uct_mouse.get_gyro() - GYRO_BIAS_DPS
        heading_deg += gyro_dps * DT_S
        error = TURN_TARGET_DEG - heading_deg

        if now_ms - last_print_ms >= 100:
            print(f"  heading={heading_deg:+.1f} deg")
            last_print_ms = now_ms

        predicted_heading = heading_deg + gyro_dps * TURN_BRAKE_LOOKAHEAD_S
        will_overshoot = predicted_heading > TURN_TARGET_DEG + TURN_SETTLE_TOL_DEG

        if abs(error) <= TURN_SETTLE_TOL_DEG and abs(gyro_dps) <= TURN_BRAKE_RATE_DPS:
            uct_mouse.set_motors(0, 0)
            settle_count += 1
            if settle_count >= TURN_SETTLE_TICKS:
                settled = True
                break
        elif will_overshoot or (abs(error) <= TURN_SETTLE_TOL_DEG and abs(gyro_dps) > TURN_BRAKE_RATE_DPS):
            # Momentum is about to (or already did) carry heading past the
            # target band -- actively brake (reverse PWM) instead of either
            # continuing to drive toward target or coasting at 0 PWM.
            settle_count = 0
            brake = max(MIN_ACTIVE_PWM, TURN_BRAKE_PWM * scale)
            uct_mouse.set_motors(int(brake), int(-brake))
        else:
            # Always keep driving (never idle at 0,0) while outside tolerance:
            # sitting at zero PWM mid-turn holds the mouse motionless, and the
            # simulator watchdog auto-ends the whole run after 3s of no motion.
            settle_count = 0

            if abs(gyro_dps) < FLAT_GYRO_DPS:
                flat_gyro_ticks += 1
                if flat_gyro_ticks >= FLAT_GYRO_WARN_TICKS and not flat_gyro_warned:
                    print("  WARNING: gyro reading flat despite full PWM -- "
                          "possible stall, wall crash, or sensor fault")
                    flat_gyro_warned = True
            else:
                flat_gyro_ticks = 0

            if abs(error) > TURN_COARSE_THRESHOLD_DEG:
                spin = max(MIN_ACTIVE_PWM, TURN_COARSE_PWM * scale)
            else:
                spin = max(MIN_ACTIVE_PWM, TURN_FINE_PWM * scale)
            direction = 1.0 if error > 0 else -1.0
            uct_mouse.set_motors(int(-spin * direction), int(spin * direction))

    # Final trim: if we settled outside tolerance (e.g. coast undershot),
    # apply brief corrective nudges rather than leaving the heading wrong.
    while (not settled
           and uct_mouse.get_ticks_ms() - start_ms < TURN_TIMEOUT_MS
           and abs(TURN_TARGET_DEG - heading_deg) > TURN_SETTLE_TOL_DEG):
        error = TURN_TARGET_DEG - heading_deg
        direction = 1.0 if error > 0 else -1.0
        spin = max(MIN_ACTIVE_PWM, TURN_NUDGE_PWM * scale)
        uct_mouse.set_motors(int(-spin * direction), int(spin * direction))
        uct_mouse.delay_ms(TURN_NUDGE_MS)

        # TURN_NUDGE_MS / 1000.0 -- see the fixed-dt note in the main loop
        # above; delay_ms(TURN_NUDGE_MS) always performs TURN_NUDGE_MS/STEP_MS
        # exchanges of exactly DT_S simulated seconds each.
        gyro_dps = uct_mouse.get_gyro() - GYRO_BIAS_DPS
        heading_deg += gyro_dps * (TURN_NUDGE_MS / 1000.0)
        print(f"  heading={heading_deg:+.1f} deg (nudge)")

        uct_mouse.set_motors(0, 0)
        uct_mouse.delay_ms(STEP_MS)

    uct_mouse.set_motors(0, 0)

    total_ms = uct_mouse.get_ticks_ms() - start_ms
    if settled or abs(TURN_TARGET_DEG - heading_deg) <= TURN_SETTLE_TOL_DEG:
        print(f"Turn complete: heading={heading_deg:+.1f} deg in {total_ms}ms")
    else:
        print(f"Turn TIMED OUT: heading={heading_deg:+.1f} deg (target {TURN_TARGET_DEG}) after {total_ms}ms")


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
        uct_mouse.set_polarity(-1, -1)

    calibrate_gyro_bias()

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
