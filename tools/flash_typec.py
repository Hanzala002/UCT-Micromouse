"""
Guided flash + deploy helper for the two-cable-position workflow:

  1. ST-LINK port  (VID 0483:PID 374B) -> flashes the MicroPython interpreter.
  2. Processor board OTG port (VID F055:PID 9800/9801/9802) -> deploys the
     student script (e.g. milestone1_square.py) over mpremote and runs it.

Only one cable may be connected at a time, so this script pauses between the
two phases and asks you to physically move it. See docs/getting_started_python.md
and .agents/AGENTS.md ("MicroPython Connection Strategy") for background.
"""
import os
import subprocess
import sys
import time
import argparse

MPY_VID = 0xF055
MPY_PIDS = (0x9800, 0x9801, 0x9802)
STLINK_VID_PID = (0x0483, 0x374B)

STM32_PROGRAMMER_CLI = (
    r"C:\Program Files\STMicroelectronics\STM32Cube\STM32CubeProgrammer\bin\STM32_Programmer_CLI.exe"
)


def find_mpy_port():
    import serial.tools.list_ports
    for p in serial.tools.list_ports.comports():
        if p.vid == MPY_VID and p.pid in MPY_PIDS:
            return p.device
    return None


def find_stlink_port():
    import serial.tools.list_ports
    for p in serial.tools.list_ports.comports():
        if (p.vid, p.pid) == STLINK_VID_PID:
            return p.device
    return None


def run_windows_diagnostics():
    print("\nNo processor-board USB device detected. Running diagnostics...\n")

    if sys.platform == "win32" and os.path.exists(STM32_PROGRAMMER_CLI):
        print(f"$ {STM32_PROGRAMMER_CLI} -l")
        try:
            subprocess.run([STM32_PROGRAMMER_CLI, "-l"], timeout=15)
        except Exception as e:
            print(f"  (failed to run: {e})")
    elif sys.platform == "win32":
        print(f"  (STM32CubeProgrammer not found at {STM32_PROGRAMMER_CLI}, skipping)")

    if sys.platform == "win32":
        print("\n$ Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -like 'USB*' }")
        try:
            subprocess.run(
                [
                    "powershell", "-Command",
                    "Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -like 'USB*' }",
                ],
                timeout=15,
            )
        except Exception as e:
            print(f"  (failed to run: {e})")

    print(
        "\nIf BOTH of the above show nothing at all for the processor board, the "
        "host isn't seeing any USB enumeration -- that points to a physical issue: "
        "wrong port, a charge-only cable, or a damaged connector. Test the cable on "
        "a phone: if it only ever charges and never offers file transfer, it's the cable."
    )


def wait_for_mpy_port(timeout_s=15):
    print(f"Waiting up to {timeout_s}s for the processor board to enumerate...")
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        port = find_mpy_port()
        if port:
            return port
        time.sleep(1)
    return None


def flash_interpreter(repo_root):
    print("=== Phase 1: Flash MicroPython interpreter over ST-LINK ===")
    stlink_port = find_stlink_port()
    if not stlink_port:
        print(
            "Warning: no ST-Link VCP (VID 0483:PID 374B) detected. Make sure the "
            "cable is plugged into the ST-LINK port, not the processor board or "
            "power board port."
        )
    deploy_script = os.path.join(repo_root, "tools", "deploy.py")
    result = subprocess.run(
        [sys.executable, deploy_script, "--engine", "micropython", "--flash"],
        cwd=repo_root,
    )
    if result.returncode != 0:
        print("Error: flashing the MicroPython interpreter failed. Aborting.")
        sys.exit(1)


def deploy_script_over_typec(repo_root, script_path):
    print("\n=== Phase 2: Deploy script over the processor board's Type-C port ===")
    print(
        "Unplug the USB-C cable from the ST-LINK port and plug it into the "
        "PROCESSOR BOARD port instead."
    )
    input("Press Enter once the cable has been moved...")

    print(
        "\nNote: if a Windows Explorer window has the UCT_MMOUSE drive open, close "
        "it before continuing -- writing over mpremote while Explorer also has the "
        "drive mounted can corrupt the FAT filesystem."
    )

    port = wait_for_mpy_port()
    if not port:
        run_windows_diagnostics()
        sys.exit(1)

    print(f"Found processor board on {port}")

    mpremote_base = [sys.executable, "-m", "mpremote", "connect", port, "resume"]

    boot_script = os.path.join(repo_root, "python", "boot.py")
    if os.path.exists(boot_script):
        print("Pushing boot.py...")
        subprocess.run(mpremote_base + ["fs", "cp", boot_script, ":boot.py"], check=True)

    print(f"Pushing {os.path.basename(script_path)} as main.py...")
    subprocess.run(mpremote_base + ["fs", "cp", script_path, ":main.py"], check=True)

    print("Resetting the board so the new main.py runs...")
    subprocess.run(mpremote_base + ["reset"], check=False)

    print("\nDone. The mouse should now be running the deployed script.")


def main():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    default_script = os.path.join(repo_root, "python", "milestone1_square.py")

    parser = argparse.ArgumentParser(
        description="Guided ST-Link flash + Type-C deploy for a MicroPython script."
    )
    parser.add_argument(
        "--script", default=default_script,
        help="Path to the script to deploy as main.py (default: python/milestone1_square.py)",
    )
    parser.add_argument(
        "--skip-flash", action="store_true",
        help="Skip Phase 1 if the MicroPython interpreter is already flashed.",
    )
    args = parser.parse_args()

    script_path = os.path.abspath(args.script)
    if not os.path.exists(script_path):
        print(f"Error: script not found at {script_path}")
        sys.exit(1)

    if not args.skip_flash:
        flash_interpreter(repo_root)
    else:
        print("Skipping Phase 1 (--skip-flash).")

    deploy_script_over_typec(repo_root, script_path)


if __name__ == "__main__":
    main()
