# lamzu-ctl

A zero-dependency Linux command-line utility for Lamzu wireless mice. It reads battery and charging status, queries firmware and polling rate, and changes the polling rate through the mouse's HID control interface.

The utility supports the Compx 16-byte report protocol and both known revisions of the Aurora 64-byte feature-report protocol. It was built around a Lamzu Maya/Compx receiver and discovers candidate Lamzu devices using vendor IDs `3554`, `373e`, and `37b0`.

## Features

- Battery percentage and charging state
- Current polling rate and firmware information
- Polling-rate selection from 125 Hz through 4,000 Hz
- Automatic Lamzu HID-interface discovery
- Hardware diagnostics across every detected interface
- No runtime dependencies beyond Python 3 and standard Linux utilities

## Install

Clone the repository and run the dependency-free installer:

```bash
git clone https://github.com/anany1702/lamzu-ctl.git
cd lamzu-ctl
./install.sh
```

This installs `lamzu` into `~/.local/bin`. Ensure that directory is on your `PATH`.

The project can also be installed as a standard Python package in environments with `pip` or `pipx`:

```bash
pipx install git+https://github.com/anany1702/lamzu-ctl.git
```

## Device permissions

Install the included udev rule once so the active desktop user can access the mouse without running the CLI as root:

```bash
sudo install -Dm644 udev/70-lamzu-ctl.rules /etc/udev/rules.d/70-lamzu-ctl.rules
sudo udevadm control --reload-rules
sudo udevadm trigger
```

Unplug and reconnect the receiver after installing the rule. As a temporary fallback, commands can be run as `sudo ~/.local/bin/lamzu ...`.

## Usage

Show just the battery reading:

```bash
lamzu battery
```

Example:

```text
Battery: 85% (Discharging)
```

Show battery, firmware, protocol, and polling rate:

```bash
lamzu info
```

Set the polling rate:

```bash
lamzu set 1000
```

Supported values are `125`, `250`, `500`, `1000`, `2000`, and `4000`.

List detected Lamzu interfaces or run protocol diagnostics:

```bash
lamzu list
lamzu diag
```

Use a specific interface when automatic selection is unsuitable:

```bash
lamzu --device /dev/hidraw2 battery
```

Wireless mice may sleep while stationary. Move the mouse while querying or changing settings if it does not respond.

### Command reference

| Command | Purpose | Changes device state? |
| --- | --- | --- |
| `lamzu battery` | Show charge percentage and power state | No |
| `lamzu info` | Show battery, firmware, protocol, and rate | No |
| `lamzu list` | List matching HID interfaces | No |
| `lamzu diag` | Probe supported protocols on every interface | No |
| `lamzu set RATE` | Store a new polling rate on the mouse | Yes |

Run `lamzu --help` for the complete command-line reference.

## Development

Run the tests with the Python standard library:

```bash
python3 -m unittest discover -s tests -v
```

## Compatibility

### Ubuntu versions

`lamzu-ctl` uses only the Python standard library, Linux `hidraw`, and `udevadm`. The following versions are covered by the project's Python compatibility target and CI matrix:

| Ubuntu | Default Python | Project status |
| --- | --- | --- |
| 26.04 LTS | 3.14 | Supported by CI |
| 24.04 LTS | 3.12 | Supported by CI; recommended |
| 22.04 LTS | 3.10 | Supported by CI |
| 20.04 LTS | 3.8 | Compatible and covered by CI; Ubuntu itself now requires Ubuntu Pro for security maintenance |

Other Linux distributions should work when they provide Python 3.8 or newer, `udevadm`, and Linux `hidraw`. Windows and macOS are not supported because the transport uses Linux-specific `fcntl` ioctls and device nodes.

### Mouse variants

There are two different levels of support: a device may be *detected* by its vendor ID without every command being verified on that hardware revision.

| Mouse / connection | USB VID:PID | Protocol expectation | Status |
| --- | --- | --- | --- |
| Maya/Atlantis-family Compx 4K/8K receiver | `3554:f510` | Compx report 8 | Primary target; battery/rate implementation available |
| Maya/Atlantis-family wired | `3554:f50f` | Compx report 8 | Expected compatible; independently identified as report-8 hardware |
| Atlantis-family 1K receiver | `3554:f50d` | Compx report 8 | Expected compatible; do not select rates above 1,000 Hz |
| Maya X 8K receiver / wired | `373e:001e`, `373e:001c` | Aurora feature reports | Provisional; detected, not hardware-verified here |
| INCA 8K receiver | `37b0:0010` | Aurora feature reports | Provisional; detected, not hardware-verified here |
| Paro receiver / wired revisions | `37b0:000d`, `37b0:0001`, `37b0:0007`, `37b0:000e` | Aurora feature reports | Provisional; detected, not hardware-verified here |
| Maya Champion receiver / wired | `37b0:0015`, `37b0:0011` | Aurora feature reports | Provisional; detected, not hardware-verified here |

This is an unofficial, reverse-engineered utility. Battery support uses Compx command `4` and the corresponding Aurora battery feature reports. Firmware and receiver revisions can change behavior even when the product name is the same. Run `lamzu list` to see the detected VID:PID and include `lamzu diag` output with compatibility reports.

The Compx battery layout was cross-checked against the open-source [Orpheus protocol implementation](https://github.com/lindestad/orpheus). The report-8 IDs and polling limits are independently documented by [lamzu-cfg](https://github.com/LeadSun/lamzu-cfg). The newer Maya X, INCA, Paro, and Champion VID:PIDs come from the community-maintained [Lamzu Aurora Linux udev rules](https://github.com/passionofcrisis/Lamzu-Webdriver-Aurora-Linux-fix); their inclusion documents discovery candidates, not a claim that every CLI operation has been tested on them.

## Uninstall

```bash
rm ~/.local/bin/lamzu
sudo rm /etc/udev/rules.d/70-lamzu-ctl.rules
sudo udevadm control --reload-rules
```

## License

MIT
