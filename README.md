# Monitor Lights

Monitor Lights is a small GTK app for Ubuntu and other Linux desktops that lets you adjust the brightness of connected displays from a simple desktop window.

It detects displays dynamically and picks the best available backend per screen:

- `brightnessctl` for laptop backlight control
- `ddcutil` for external monitors with DDC/CI support
- `xrandr` as the fallback on X11 sessions

## Features

- Detects connected laptop and external displays automatically
- Per-display brightness sliders
- Day and Night presets
- GNOME Night Light toggle
- Desktop launcher installation for the applications menu

## Compatibility

Monitor Lights currently targets Ubuntu-style desktop setups best, especially:

- Ubuntu on **X11** for `xrandr` fallback support
- GNOME desktops for Night Light integration
- Systems with `brightnessctl` and/or `ddcutil` installed for better hardware brightness control

Wayland-only setups may have reduced functionality because `xrandr` is an X11 tool.

## Requirements

- Python 3
- PyGObject / GTK 4 (`python3-gi`)
- `xrandr`
- Optional: `brightnessctl`
- Optional: `ddcutil`
- Optional: `gsettings` for Night Light integration

## Safety and privacy

- No telemetry
- No network access
- No bundled credentials, secrets, or API keys
- Uses only local desktop tools such as `xrandr`, `brightnessctl`, `ddcutil`, and `gsettings`

## Install

```bash
cd monitor-lights
chmod +x install.sh uninstall.sh monitor-lights monitor_lights.py
./install.sh
```

That installs the app to `~/.local/share/monitor-lights` and creates a launcher in `~/.local/share/applications`.

## Run without installing

```bash
cd monitor-lights
./monitor-lights
```

## Uninstall

```bash
cd monitor-lights
./uninstall.sh
```

## Publishing notes

Before publishing, consider:

- adding screenshots
- tagging a first release
- packaging for `.deb` or Flatpak if you want easier distribution

## License

MIT
