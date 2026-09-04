---
name: run-sim
description: Launches the UCT Micromouse virtual physics simulator with a visible on-screen window and runs the Milestone 1 square-driving controller (python/milestone1_square.py) against it over its local TCP loopback. Use this whenever the user asks to run, watch, demo, show, or test the (virtual) simulation/simulator, "run the sim", "watch the mouse drive the square", or wants to see Milestone 1 working, in this repository. Do not use for the local autograder (tools/autograder/grade_runner.py) — that runs headless and scores the run; this skill is specifically for a visible, watchable run.
---

# Run the Milestone 1 Virtual Simulation

This repo's Milestone 1 controller (`python/milestone1_square.py`) talks to
`tools/physics_sim.py` over a local TCP socket on port 8000. To let the user watch it run:

## 1. Find a Python with the simulator's dependencies

The repo's own `python3` (WSL/Linux) has no `pip` and lacks `numpy`/`pygame`/`opencv-python`, and
even if it did, a Linux Python process has no straightforward path to a visible window in this
environment. Use the Windows Python install instead — being a native Windows process, its pygame
window just appears on the desktop with no extra setup:

```bash
WINPY="/mnt/c/Users/hmans/AppData/Local/Programs/Python/Python313/python.exe"
"$WINPY" -c "import numpy, pygame, cv2" 2>&1
```

If that path doesn't exist or the import check fails, search
`/mnt/c/Users/*/AppData/Local/Programs/Python/Python*/python.exe` for another candidate, or ask the
user where their Windows Python lives.

## 2. Pick simulation parameters

Default to the graded **Public Baseline** scenario unless the user names a different one or gives
explicit values (all three mirror `tools/autograder/assignments/milestone1_square/test_suite.py`):

| Scenario (user might say...)              | `--imbalance` | `--slip` | `--seed` |
|--------------------------------------------|---------------|----------|----------|
| baseline / default / public                | 0.05          | 0.04     | 42       |
| asymmetry / heavy imbalance / stress test 2 | 0.12          | 0.02     | 43       |
| slip / traction / stress test 3             | 0.04          | 0.10     | 44       |

Always pass `--map empty` (Milestone 1's grading map — do not use `random` or `spiral` here).
Never pass `--headless`; the whole point of this skill is a visible window.

## 3. Start the simulator in the background

From the repo root, launch it with `Bash` using `run_in_background: true` — it opens a window and
blocks until closed, so it must not be the foreground call. Use `-u` (unbuffered) so its log
actually shows up if you go read the background output file instead of buffering until exit:

```bash
cd /mnt/c/Users/hmans/Music/UCT-Micromouse
WINPY="/mnt/c/Users/hmans/AppData/Local/Programs/Python/Python313/python.exe"
"$WINPY" -u tools/physics_sim.py --map empty --imbalance 0.05 --slip 0.04 --seed 42
```

Give it a couple of seconds to bind to port 8000 before moving on (e.g. `sleep 2`).

## 4. Run the controller in the foreground

```bash
cd /mnt/c/Users/hmans/Music/UCT-Micromouse/python
WINPY="/mnt/c/Users/hmans/AppData/Local/Programs/Python/Python313/python.exe"
"$WINPY" -u milestone1_square.py
```

Always pass `-u` — without it, Windows Python fully buffers stdout when its output is piped (as it
is when Claude Code's Bash tool captures it), so nothing appears until the process exits.

**Timing:** this runs in true real time here (unlike the autograder, which sets
`GRADESCOPE_AUTOGRADER=1` to skip real-time pacing). The simulator's own render loop caps at 20fps,
and each control-loop exchange blocks on that, so a run that reports ~25s of "simulated time" in a
fast-sim/graded run actually takes on the order of 2–3 minutes of real wall-clock time here. Pass a
generous `timeout` to the Bash tool call (e.g. `240000`ms) rather than wrapping the command in a
short shell `timeout N` — a run that's just pacing normally is not stuck.

This blocks until the run finishes (drives the four sides, turns, then holds still for 3s) and
prints its own progress (`Driving straight...`, `Turning 90 degrees left...`, `Milestone 1
Completed!`). It auto-connects to the simulator started in step 3.

## 5. Report back

Summarize what happened (did it complete the square, any errors) from the controller's stdout.
The simulator window stays open after the run so the user can inspect the final resting position —
mention they can close it themselves, or stop the background task if they're done.

## Notes / gotchas

- `python/sim_config.json` has `"map": "random"` left over from Milestone 2 experiments — that only
  matters if something relies on `milestone1_square.py`'s own `auto_start` fallback instead of a
  simulator you launched explicitly. This skill always launches `physics_sim.py` itself with
  `--map empty`, so that stale config value is irrelevant here.
- If the simulator fails to bind ("port 8000 in use" / connection refused persists), there's likely
  a stale `physics_sim.py` process still holding the port — find and stop it before retrying.
- For a headless, scored (not just watched) run across all three weighted test scenarios, use
  `tools/autograder/grade_runner.py` instead — that's a separate workflow from this skill.
