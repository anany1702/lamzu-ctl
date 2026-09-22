# lamzu-ctl

A zero-dependency Linux command-line utility for Lamzu wireless mice. It reads battery and charging status, queries firmware and polling rate, and changes the polling rate through the mouse's HID control interface.

The utility supports the Compx 16-byte report protocol and both known revisions of the Aurora 64-byte feature-report protocol. It was built for the Lamzu Maya and discovers Lamzu devices using vendor IDs `3554`, `373e`, and `37b0`.

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

This is an unofficial, reverse-engineered utility. It was developed for the Lamzu Maya/Compx 4K receiver; other Lamzu models sharing the protocol may work but have not all been hardware-tested. Battery support uses Compx command `4` and the corresponding Aurora battery feature reports. Hardware revisions can differ, so include `lamzu diag` output when reporting compatibility issues.

The Compx battery layout was cross-checked against the open-source [Orpheus protocol implementation](https://github.com/lindestad/orpheus). The broader Lamzu configuration protocol has also been independently explored by [lamzu-cfg](https://github.com/LeadSun/lamzu-cfg).

## Uninstall

```bash
rm ~/.local/bin/lamzu
sudo rm /etc/udev/rules.d/70-lamzu-ctl.rules
sudo udevadm control --reload-rules
```

## License

MIT
