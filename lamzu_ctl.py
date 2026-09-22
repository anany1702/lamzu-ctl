#!/usr/bin/env python3
"""Control supported Lamzu mice directly through Linux ``hidraw``.

The protocol is vendor-specific and reverse engineered. Read-only commands
query battery, firmware, and polling-rate reports; only ``lamzu set`` writes
configuration data to the mouse's onboard EEPROM.

Supported transports:
* Compx report ID 8 with a 16-byte payload and checksum.
* Aurora report ID 0 with a 64-byte feature-report payload.
"""

import os
import sys
import fcntl
import struct
import time
import argparse
import glob
import re
import subprocess
import select

LAMZU_VIDS = {"3554", "373e", "37b0"}
VERSION = "0.1.0"

COMPX_RATE_TO_CODE = {
    125: 8,
    250: 4,
    500: 2,
    1000: 1,
    2000: 16,
    4000: 32,
}

AURORA_RATE_TO_CODE = {
    125: 0x08,
    250: 0x04,
    500: 0x02,
    1000: 0x01,
    2000: 0x20,
    4000: 0x40,
}

CODE_TO_RATE = {
    1: 1000,
    2: 500,
    4: 250,
    8: 125,
    16: 2000,
    32: 4000,
    64: 4000,
}

HIDIOCSFEATURE_17 = 0xC0114806
HIDIOCGFEATURE_17 = 0xC0114807
HIDIOCSFEATURE_65 = 0xC0414806
HIDIOCGFEATURE_65 = 0xC0414807


def find_lamzu_devices():
    """Discover all connected Lamzu HID devices using udevadm."""
    devices = []
    hidraw_paths = sorted(
        glob.glob("/dev/hidraw*"),
        key=lambda p: int(re.search(r"\d+", p).group()) if re.search(r"\d+", p) else 0,
    )

    for dev_path in hidraw_paths:
        try:
            out = subprocess.check_output(
                ["udevadm", "info", dev_path],
                text=True,
                stderr=subprocess.DEVNULL,
            )
            m = re.search(r"0003:([0-9a-fA-F]{4}):([0-9a-fA-F]{4})", out)
            if m:
                vid = m.group(1).lower()
                pid = m.group(2).lower()
                if vid in LAMZU_VIDS:
                    intf_m = re.search(r"/[\d\.\-]+:(\d+)\.(\d+)/", out)
                    intf = int(intf_m.group(2)) if intf_m else None
                    devices.append({
                        "path": dev_path,
                        "vid": vid,
                        "pid": pid,
                        "interface": intf,
                    })
        except Exception:
            continue

    return devices


def get_control_devices(specified_path=None):
    if specified_path:
        return [specified_path]
    devices = find_lamzu_devices()
    if not devices:
        return []
    intf2 = [d["path"] for d in devices if d["interface"] == 2]
    others = [d["path"] for d in devices if d["interface"] != 2]
    return intf2 + others


# ============================================================================
# Protocol Helpers
# ============================================================================

def compx_crc(data_15: bytes) -> int:
    """Return the Compx additive checksum complement for bytes 0..14."""
    s = sum(data_15[:15]) & 0xFF
    return (85 - s) & 0xFF


def build_compx_write_packet(address: int, value: int) -> bytes:
    """
    Build 17-byte buffer for Compx EEPROM Write (Report ID 8 + 16 payload bytes).
    Cmd 7: Set_Device_Eeprom_Value
    """
    t = bytearray(16)
    t[0] = 7                     # Cmd: WriteFlash
    t[1] = 0                     # Subcode
    t[2] = (address >> 8) & 0xFF # Addr High
    t[3] = address & 0xFF        # Addr Low
    t[4] = 2                     # Length = 2
    t[5] = value                 # Value
    t[6] = (85 - value) & 0xFF   # Checksum complement (0x55 - value)
    crc = compx_crc(t)
    t[15] = (crc - 8) & 0xFF     # crc - report_id (8)
    return bytes([0x08]) + bytes(t)


def build_compx_read_packet(address: int, length: int = 2) -> bytes:
    """
    Build 17-byte buffer for Compx EEPROM Read (Report ID 8 + 16 payload bytes).
    Cmd 8: Get_Device_Eeprom_Buffer
    """
    t = bytearray(16)
    t[0] = 8                     # Cmd: ReadFlash
    t[1] = 0                     # Subcode
    t[2] = (address >> 8) & 0xFF # Addr High
    t[3] = address & 0xFF        # Addr Low
    t[4] = length                # Length
    crc = compx_crc(t)
    t[15] = (crc - 8) & 0xFF     # crc - report_id (8)
    return bytes([0x08]) + bytes(t)


def build_compx_cmd_packet(cmd_id: int) -> bytes:
    """Build general Compx command (e.g. 14 for active profile, 18 for FW)."""
    t = bytearray(16)
    t[0] = cmd_id
    crc = compx_crc(t)
    t[15] = (crc - 8) & 0xFF
    return bytes([0x08]) + bytes(t)


def build_compx_battery_packet() -> bytes:
    """Build a Compx battery/charging-status query (command 4).

    Command 4 replies with the percentage in payload byte 5 and power state
    in byte 6 (0=discharging, 1=charging, 2=full).
    """
    return build_compx_cmd_packet(4)


def build_aurora_set_rate_packet(rate_code: int, profile: int = 1) -> bytes:
    """Build 65-byte buffer for Aurora Set Polling Rate (Report ID 0 + 64 payload bytes)."""
    p = bytearray(64)
    p[2] = 0x02        # Mouse
    p[3] = 0x02        # Length
    p[4] = 0x01        # Category: Config
    p[5] = 0x00        # Opcode: Set Polling Rate
    p[6] = profile     # Profile
    p[7] = rate_code   # Value
    return bytes([0x00]) + bytes(p)


def build_aurora_get_rate_packet(profile: int = 1) -> bytes:
    """Build 65-byte buffer for Aurora Get Polling Rate."""
    p = bytearray(64)
    p[2] = 0x02
    p[3] = 0x02
    p[4] = 0x01
    p[5] = 0x80        # Opcode: Get Polling Rate
    p[6] = profile
    return bytes([0x00]) + bytes(p)


def build_aurora_get_battery_packet(new_protocol: bool = True) -> bytes:
    """Build a 65-byte Aurora battery query for either protocol revision."""
    p = bytearray(64)
    if new_protocol:
        p[2] = 0x02       # Mouse
        p[3] = 0x02       # Length
        p[5] = 0x83       # Get battery/status
    else:
        p[1] = 0x02       # Mouse
        p[2] = 0x8F       # Get battery/status (legacy)
        p[3] = 0x01       # Wireless receiver target
    return bytes([0x00]) + bytes(p)


def battery_state_name(raw_state):
    """Return a readable name for a protocol battery-state byte."""
    return {
        0: "Discharging",
        1: "Charging",
        2: "Full",
    }.get(raw_state, f"Unknown ({raw_state})")


def parse_aurora_battery_response(resp):
    """Decode Aurora battery responses with or without a leading report ID.

    Linux may return the leading zero report ID for a feature report but omit
    it for an input report, so both layouts are accepted explicitly.
    """
    if not resp:
        return None

    # New protocol: A1 .. 02 .. 83 <state> <percent>
    if len(resp) >= 9 and resp[1] == 0xA1 and resp[4] == 0x02 and resp[6] == 0x83:
        state, level = resp[7], resp[8]
    elif len(resp) >= 8 and resp[0] == 0xA1 and resp[3] == 0x02 and resp[5] == 0x83:
        state, level = resp[6], resp[7]
    # Legacy protocol: A1 02 8F .. <state> <percent>
    elif len(resp) >= 7 and resp[1] == 0xA1 and resp[2] == 0x02 and resp[3] == 0x8F:
        state, level = resp[5], resp[6]
    elif len(resp) >= 6 and resp[0] == 0xA1 and resp[1] == 0x02 and resp[2] == 0x8F:
        state, level = resp[4], resp[5]
    else:
        return None

    if level > 100:
        return None
    return level, state


# ============================================================================
# Device Controller
# ============================================================================

class LamzuDevice:
    def __init__(self, path):
        self.path = path
        self.fd = None

    def open(self):
        try:
            self.fd = os.open(self.path, os.O_RDWR | os.O_NONBLOCK)
        except PermissionError:
            print(f"\n[!] Permission denied accessing {self.path}.")
            print("    Please run this command with sudo:")
            print(f"    sudo lamzu {' '.join(sys.argv[1:])}\n")
            sys.exit(1)
        except Exception as e:
            raise RuntimeError(f"Could not open {self.path}: {e}")

    def close(self):
        if self.fd is not None:
            try:
                os.close(self.fd)
            except Exception:
                pass
            self.fd = None

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def flush_input(self):
        """Discard any stale pending input reports."""
        while True:
            r, _, _ = select.select([self.fd], [], [], 0.005)
            if not r:
                break
            try:
                os.read(self.fd, 64)
            except Exception:
                break

    def send_report(self, buf: bytes) -> bool:
        """Send a report via Output Report (os.write) and Feature Report ioctl."""
        ok = False
        # 1. Output Report via write()
        try:
            os.write(self.fd, buf)
            ok = True
        except OSError:
            pass

        # 2. Feature Report via ioctl
        try:
            if len(buf) == 17:
                fcntl.ioctl(self.fd, HIDIOCSFEATURE_17, buf)
                ok = True
            elif len(buf) == 65:
                fcntl.ioctl(self.fd, HIDIOCSFEATURE_65, buf)
                ok = True
        except OSError:
            pass

        return ok

    def read_input(self, timeout=0.15) -> bytes:
        """Read an incoming report with timeout."""
        r, _, _ = select.select([self.fd], [], [], timeout)
        if r:
            try:
                return os.read(self.fd, 64)
            except Exception:
                return None
        return None

    def read_feature_17(self) -> bytes:
        buf = bytearray(17)
        buf[0] = 0x08
        try:
            fcntl.ioctl(self.fd, HIDIOCGFEATURE_17, buf)
            return bytes(buf)
        except OSError:
            return None

    def read_feature_65(self) -> bytes:
        buf = bytearray(65)
        buf[0] = 0x00
        try:
            fcntl.ioctl(self.fd, HIDIOCGFEATURE_65, buf)
            return bytes(buf)
        except OSError:
            return None

    # ------------------------------------------------------------------------
    # Compx Operations
    # ------------------------------------------------------------------------

    def compx_query(self, query_packet: bytes, expected_cmd: int, timeout=0.15):
        self.flush_input()
        if not self.send_report(query_packet):
            return None

        # Try reading input report
        start = time.time()
        while time.time() - start < timeout:
            resp = self.read_input(timeout=0.03)
            if resp:
                # resp may start with Report ID 8
                if len(resp) >= 6 and resp[0] == 0x08 and resp[1] == expected_cmd:
                    return resp
                if len(resp) >= 5 and resp[0] == expected_cmd:
                    return bytes([0x08]) + resp
            time.sleep(0.01)

        # Fallback to feature report
        feat = self.read_feature_17()
        if feat and len(feat) >= 6 and feat[0] == 0x08 and feat[1] == expected_cmd:
            return feat

        return None

    def compx_get_polling_rate(self):
        """Read flash address 0 (ReportRate)."""
        pkt = build_compx_read_packet(address=0, length=2)
        resp = self.compx_query(pkt, expected_cmd=8, timeout=0.15)
        if resp and len(resp) >= 7:
            val = resp[6]
            if val in CODE_TO_RATE:
                return CODE_TO_RATE[val]
        return None

    def compx_set_polling_rate(self, rate_hz):
        """Write flash address 0 (ReportRate)."""
        val = COMPX_RATE_TO_CODE.get(rate_hz)
        if not val:
            return False
        pkt = build_compx_write_packet(address=0, value=val)
        resp = self.compx_query(pkt, expected_cmd=7, timeout=0.15)
        # Verify write acknowledgment
        if resp and len(resp) >= 7 and resp[6] == val:
            return True
        return resp is not None

    def compx_get_firmware(self):
        pkt = build_compx_cmd_packet(18)
        resp = self.compx_query(pkt, expected_cmd=18, timeout=0.15)
        if resp and len(resp) >= 7:
            return f"{resp[5]:x}.{resp[6]:x}"
        return None

    def compx_get_battery(self):
        """Return (percentage, raw charging state) using Compx command 4."""
        resp = self.compx_query(
            build_compx_battery_packet(), expected_cmd=4, timeout=0.25
        )
        if resp and len(resp) >= 8:
            level, state = resp[6], resp[7]
            if level <= 100:
                return level, state
        return None

    # ------------------------------------------------------------------------
    # Aurora Operations
    # ------------------------------------------------------------------------

    def aurora_query(self, query_packet: bytes, expected_opcode: int, timeout=0.15):
        self.flush_input()
        if not self.send_report(query_packet):
            return None

        # Check feature report
        time.sleep(0.02)
        feat = self.read_feature_65()
        if feat and len(feat) >= 7:
            marker = feat[1]
            if 0xA0 <= marker <= 0xAF:
                if feat[6] == expected_opcode or feat[5] == expected_opcode:
                    return feat

        # Check input report
        resp = self.read_input(timeout=timeout)
        if resp and len(resp) >= 7:
            marker = resp[1]
            if 0xA0 <= marker <= 0xAF:
                if resp[6] == expected_opcode or resp[5] == expected_opcode:
                    return resp

        return None

    def aurora_get_polling_rate(self, profile=1):
        pkt = build_aurora_get_rate_packet(profile)
        resp = self.aurora_query(pkt, expected_opcode=0x80, timeout=0.15)
        if resp:
            idx = 8 if resp[6] == 0x80 else 7
            code = resp[idx]
            if code in CODE_TO_RATE:
                return CODE_TO_RATE[code]
        return None

    def aurora_set_polling_rate(self, rate_hz, profile=1):
        code = AURORA_RATE_TO_CODE.get(rate_hz)
        if not code:
            return False
        pkt = build_aurora_set_rate_packet(code, profile)
        return self.send_report(pkt)

    def aurora_get_battery(self):
        """Return (percentage, raw charging state) using Aurora feature reports."""
        for new_protocol, delay in ((True, 0.10), (False, 0.05)):
            self.flush_input()
            if not self.send_report(build_aurora_get_battery_packet(new_protocol)):
                continue
            time.sleep(delay)

            battery = parse_aurora_battery_response(self.read_feature_65())
            if battery:
                return battery

            battery = parse_aurora_battery_response(self.read_input(timeout=0.10))
            if battery:
                return battery
        return None

    def get_battery(self):
        """Try all supported Lamzu battery protocols."""
        return self.compx_get_battery() or self.aurora_get_battery()


def cmd_set(args):
    rate_hz = args.rate
    if rate_hz not in COMPX_RATE_TO_CODE:
        supported = ", ".join(str(k) for k in sorted(COMPX_RATE_TO_CODE.keys()))
        print(f"[!] Invalid polling rate: {rate_hz} Hz")
        print(f"    Supported options: {supported}")
        sys.exit(1)

    devices = get_control_devices(args.device)
    if not devices:
        print("[!] No Lamzu devices found.")
        sys.exit(1)

    compx_code = COMPX_RATE_TO_CODE[rate_hz]
    aurora_code = AURORA_RATE_TO_CODE[rate_hz]

    print(f"\n[*] Target Polling Rate: {rate_hz} Hz (Compx code: 0x{compx_code:02x}, Aurora code: 0x{aurora_code:02x})")
    print("=" * 64)
    print("  [!] CRITICAL: PLEASE MOVE / WIGGLE YOUR MOUSE CONTINUOUSLY")
    print("      RIGHT NOW while the configuration is being sent!")
    print("      (Wireless mice sleep when stationary and drop RF packets)")
    print("=" * 64)

    verified = False
    verified_rate = None

    # Multi-burst transmission over ~2.5 seconds
    bursts = 8
    for burst in range(1, bursts + 1):
        print(f"  --> Transmitting burst {burst}/{bursts}... (KEEP MOVING MOUSE)", end="\r", flush=True)

        for dev_path in devices:
            try:
                with LamzuDevice(dev_path) as dev:
                    # 1. Compx EEPROM Write Protocol (Report ID 8)
                    dev.compx_set_polling_rate(rate_hz)

                    # Also send 2000/4000 alternate codes if applicable
                    if rate_hz == 2000:
                        dev.send_report(build_compx_write_packet(0, 32))
                    elif rate_hz == 4000:
                        dev.send_report(build_compx_write_packet(0, 64))

                    # 2. Aurora Protocol across profiles 0 to 4 (Report ID 0)
                    for prof in range(5):
                        dev.aurora_set_polling_rate(rate_hz, profile=prof)

                    # 3. Readback Verification Check
                    read_rate = dev.compx_get_polling_rate()
                    if not read_rate:
                        read_rate = dev.aurora_get_polling_rate()

                    if read_rate == rate_hz:
                        verified = True
                        verified_rate = read_rate
                        break
            except Exception:
                pass

        if verified:
            break
        time.sleep(0.3)

    print()
    if verified:
        print(f"\n[✓] SUCCESS: Hardware verified! Polling rate is now confirmed at {verified_rate} Hz.")
    else:
        # Final readback attempt across all devices
        for dev_path in devices:
            try:
                with LamzuDevice(dev_path) as dev:
                    r = dev.compx_get_polling_rate() or dev.aurora_get_polling_rate()
                    if r:
                        verified_rate = r
                        if r == rate_hz:
                            verified = True
                        break
            except Exception:
                pass

        if verified:
            print(f"\n[✓] SUCCESS: Hardware confirmed polling rate is {verified_rate} Hz.")
        elif verified_rate:
            print(f"\n[!] Hardware responded, but reported {verified_rate} Hz instead of {rate_hz} Hz.")
            print("    If the mouse was stationary, repeat the command and keep moving the mouse!")
        else:
            print("\n[✓] Transmission complete (Fire-and-forget).")
            print("    Please verify your new polling rate at: https://devicetests.com/mouse-rate-test")

    print()


def cmd_info(args):
    devices = get_control_devices(args.device)
    if not devices:
        print("[!] No Lamzu devices found.")
        sys.exit(1)

    print("\n" + "=" * 55)
    print("             LAMZU MAYA HARDWARE STATUS              ")
    print("=" * 55)

    detected = False
    for path in devices:
        try:
            with LamzuDevice(path) as dev:
                rate = dev.compx_get_polling_rate()
                fw = dev.compx_get_firmware()
                battery = dev.get_battery()
                proto = "Compx 16-byte Protocol (Report ID 8)"

                if not rate:
                    rate = dev.aurora_get_polling_rate()
                    if rate:
                        proto = "Aurora 64-byte Protocol (Report ID 0)"

                if rate or fw or battery:
                    detected = True
                    print(f" Device Node       : {path}")
                    print(f" Protocol Active   : {proto}")
                    if fw:
                        print(f" Firmware Version  : v{fw}")
                    if rate:
                        delay = 1000.0 / rate
                        print(f" Active Report Rate: {rate} Hz (~{delay:.2f} ms)")
                    if battery:
                        level, state = battery
                        print(f" Battery Level     : {level}%")
                        print(f" Battery Status    : {battery_state_name(state)}")
                    else:
                        print(" Battery Level     : Unavailable (wake mouse and retry)")
                    print("-" * 55)
        except Exception:
            pass

    if not detected:
        print(f" Control Interface : {devices[0]}")
        print(" Active Report Rate: [Move mouse and re-run, or test online]")
        print(" Battery Level     : [Wake mouse and re-run]")
        print(" Online Test URL   : https://devicetests.com/mouse-rate-test")
        print("-" * 55)

    print()


def cmd_battery(args):
    devices = get_control_devices(args.device)
    if not devices:
        print("[!] No Lamzu devices found.")
        sys.exit(1)

    for path in devices:
        try:
            with LamzuDevice(path) as dev:
                battery = dev.get_battery()
                if battery:
                    level, state = battery
                    print(f"Battery: {level}% ({battery_state_name(state)})")
                    return
        except Exception:
            pass

    print("[!] Battery status unavailable. Move/wake the mouse and try again.")
    sys.exit(1)


def cmd_diag(args):
    devices = find_lamzu_devices()
    if not devices:
        print("[!] No Lamzu devices found.")
        return

    print("\n" + "=" * 65)
    print("                 LAMZU PROTOCOL DIAGNOSTICS                  ")
    print("=" * 65)
    print(" TIP: Move your mouse continuously during this test!\n")

    for d in devices:
        path = d["path"]
        intf = d["interface"]
        name = d.get("name", "Lamzu Device")
        print(f"---> Testing {path} (Interface {intf} - {name}):")

        try:
            with LamzuDevice(path) as dev:
                # Test Compx Read EEPROM
                compx_read = build_compx_read_packet(0, 2)
                resp_compx = dev.compx_query(compx_read, expected_cmd=8, timeout=0.1)
                if resp_compx:
                    hex_str = " ".join(f"{b:02x}" for b in resp_compx[:10])
                    val = resp_compx[6] if len(resp_compx) >= 7 else None
                    hz = CODE_TO_RATE.get(val, "Unknown")
                    print(f"  [Compx EEPROM] Responded: {hex_str} (Rate: {hz})")
                else:
                    print("  [Compx EEPROM] No response")

                # Test Aurora Feature Report
                aurora_read = build_aurora_get_rate_packet(1)
                resp_aurora = dev.aurora_query(aurora_read, expected_opcode=0x80, timeout=0.1)
                if resp_aurora:
                    hex_str = " ".join(f"{b:02x}" for b in resp_aurora[:10])
                    print(f"  [Aurora Feature] Responded: {hex_str}")
                else:
                    print("  [Aurora Feature] No response")

                battery = dev.get_battery()
                if battery:
                    level, state = battery
                    print(f"  [Battery] {level}% ({battery_state_name(state)})")
                else:
                    print("  [Battery] No response")

        except Exception as e:
            print(f"  [Error] {e}")

    print("\n" + "=" * 65 + "\n")


def cmd_list(args):
    devices = find_lamzu_devices()
    if not devices:
        print("[!] No Lamzu USB devices found.")
        return

    print("\n" + "=" * 55)
    print("              DETECTED LAMZU DEVICES                 ")
    print("=" * 55)
    for d in devices:
        ctrl = " [Control Interface]" if d["interface"] == 2 else ""
        print(f" Path      : {d['path']}{ctrl}")
        print(f" VID:PID   : {d['vid']}:{d['pid']}")
        print(f" Interface : {d['interface']}")
        print("-" * 55)
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Lamzu Maya Mouse Configuration Utility for Linux",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-d", "--device",
        help="Specify hidraw device path (e.g. /dev/hidraw2)",
        default=None,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {VERSION}",
    )

    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser(
        "info", help="Query battery, polling rate, firmware, and mouse status"
    )
    subparsers.add_parser("battery", help="Show battery percentage and charging status")
    subparsers.add_parser("diag", help="Run protocol diagnostic probe across all interfaces")
    subparsers.add_parser("debug", help="Run protocol diagnostic probe (alias for diag)")
    subparsers.add_parser("list", help="List all detected Lamzu devices")

    set_parser = subparsers.add_parser("set", help="Set mouse polling rate")
    set_parser.add_argument(
        "rate",
        type=int,
        choices=[125, 250, 500, 1000, 2000, 4000],
        help="Target polling rate in Hz (125, 250, 500, 1000, 2000, 4000)",
    )

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(0)

    if args.command == "info":
        cmd_info(args)
    elif args.command == "battery":
        cmd_battery(args)
    elif args.command == "set":
        cmd_set(args)
    elif args.command in ("diag", "debug"):
        cmd_diag(args)
    elif args.command == "list":
        cmd_list(args)


if __name__ == "__main__":
    main()
