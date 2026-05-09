#!/usr/bin/env python3

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import GLib, Gtk


CONNECTED_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9-]+)\sconnected(?P<primary>\sprimary)?(?:\s(?P<geometry>\d+x\d+\+\d+\+\d+))?"
)
DISCONNECTED_RE = re.compile(r"^[A-Za-z0-9-]+\s(?:disconnected|unknown connection)")
BRIGHTNESS_RE = re.compile(r"^\s*Brightness:\s*(?P<value>\d+(?:\.\d+)?)")
DDC_BUS_RE = re.compile(r"/dev/i2c-(?P<bus>\d+)")
DDC_VCP_RE = re.compile(r"current value\s*=\s*(?P<current>\d+),\s*max value\s*=\s*(?P<maximum>\d+)")

DAY_PRESET = 100
NIGHT_PRESET = 55


@dataclass(slots=True)
class Display:
    name: str
    title: str
    details: str
    brightness_percent: int
    primary: bool
    backend: str
    backend_target: str
    backend_label: str
    min_percent: int
    max_percent: int


def clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, value))


def run_command(*args: str) -> str:
    completed = subprocess.run(args, capture_output=True, text=True)
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or "Command failed."
        raise RuntimeError(message)
    return completed.stdout


def command_exists(command: str) -> bool:
    return shutil.which(command) is not None


def is_internal_output(output_name: str) -> bool:
    return output_name.startswith(("eDP", "LVDS", "DSI"))


def describe_output(output_name: str, is_primary: bool) -> str:
    if is_internal_output(output_name):
        return "Laptop display"
    if is_primary:
        return "Primary monitor"
    return "External monitor"


def parse_xrandr_displays(xrandr_output: str) -> list[Display]:
    displays: list[Display] = []
    current: dict[str, object] | None = None

    def flush_current() -> None:
        nonlocal current
        if current is None:
            return

        output_name = str(current["name"])
        geometry = str(current.get("geometry") or "Connected")
        primary = bool(current.get("primary", False))
        brightness_percent = clamp(int(round(float(current.get("brightness", 1.0)) * 100)), 10, 130)

        details_parts = [output_name]
        if geometry:
            details_parts.append(geometry)

        displays.append(
            Display(
                name=output_name,
                title=describe_output(output_name, primary),
                details=" • ".join(details_parts),
                brightness_percent=brightness_percent,
                primary=primary,
                backend="xrandr",
                backend_target=output_name,
                backend_label="XRandR software brightness",
                min_percent=10,
                max_percent=130,
            )
        )
        current = None

    for line in xrandr_output.splitlines():
        connected_match = CONNECTED_RE.match(line)
        if connected_match:
            flush_current()
            current = {
                "name": connected_match.group("name"),
                "geometry": connected_match.group("geometry") or "",
                "primary": bool(connected_match.group("primary")),
                "brightness": 1.0,
            }
            continue

        if current is None:
            continue

        if DISCONNECTED_RE.match(line):
            flush_current()
            continue

        brightness_match = BRIGHTNESS_RE.match(line)
        if brightness_match:
            current["brightness"] = float(brightness_match.group("value"))

    flush_current()
    return sorted(displays, key=lambda display: (not display.primary, display.name))


def get_backlight_device() -> Path | None:
    if not command_exists("brightnessctl"):
        return None

    backlight_dir = Path("/sys/class/backlight")
    if not backlight_dir.exists():
        return None

    devices = sorted(path for path in backlight_dir.iterdir() if path.is_dir())
    return devices[0] if devices else None


def read_backlight_percent(device: Path) -> int:
    current = int((device / "brightness").read_text().strip())
    maximum = int((device / "max_brightness").read_text().strip())
    if maximum <= 0:
        raise RuntimeError("Backlight maximum brightness is invalid.")
    return clamp(int(round((current / maximum) * 100)), 1, 100)


def set_backlight_percent(device: Path, brightness_percent: int) -> None:
    run_command("brightnessctl", "--device", device.name, "set", f"{clamp(brightness_percent, 1, 100)}%")


def normalize_drm_connector(connector: str) -> str:
    normalized = re.sub(r"^card\d+-", "", connector.strip())
    normalized = normalized.replace("HDMI-A-", "HDMI-")
    normalized = normalized.replace("DisplayPort-", "DP-")
    normalized = normalized.replace("DVI-D-", "DVI-")
    normalized = normalized.replace("DVI-I-", "DVI-")
    return normalized


def parse_ddcutil_buses(ddcutil_output: str) -> dict[str, str]:
    connectors_to_buses: dict[str, str] = {}
    current_connector: str | None = None
    current_bus: str | None = None

    def flush_current() -> None:
        nonlocal current_connector, current_bus
        if current_connector and current_bus:
            connectors_to_buses[current_connector] = current_bus
        current_connector = None
        current_bus = None

    for raw_line in ddcutil_output.splitlines():
        line = raw_line.strip()
        if line.startswith("Display "):
            flush_current()
            continue
        if line.startswith("I2C bus:"):
            match = DDC_BUS_RE.search(line)
            if match:
                current_bus = match.group("bus")
            continue
        if line.startswith("DRM connector:"):
            current_connector = normalize_drm_connector(line.split(":", 1)[1].strip())

    flush_current()
    return connectors_to_buses


def get_ddcutil_buses() -> dict[str, str]:
    if not command_exists("ddcutil"):
        return {}
    try:
        output = run_command("ddcutil", "detect", "--brief")
    except RuntimeError:
        output = run_command("ddcutil", "detect")
    return parse_ddcutil_buses(output)


def read_ddc_brightness(bus: str) -> int:
    output = run_command("ddcutil", "--bus", bus, "getvcp", "10")
    match = DDC_VCP_RE.search(output)
    if match is None:
        raise RuntimeError("Could not parse the monitor brightness response.")
    current = int(match.group("current"))
    maximum = int(match.group("maximum"))
    if maximum <= 0:
        raise RuntimeError("Monitor brightness maximum is invalid.")
    return clamp(int(round((current / maximum) * 100)), 1, 100)


def set_ddc_brightness(bus: str, brightness_percent: int) -> None:
    run_command("ddcutil", "--bus", bus, "setvcp", "10", str(clamp(brightness_percent, 1, 100)))


def resolve_display_backends(xrandr_displays: list[Display]) -> list[Display]:
    displays: list[Display] = []
    backlight_device = get_backlight_device()
    ddcutil_buses = get_ddcutil_buses()

    for display in xrandr_displays:
        backend = "xrandr"
        backend_target = display.name
        backend_label = "XRandR software brightness"
        brightness_percent = display.brightness_percent
        min_percent = 10
        max_percent = 130

        if is_internal_output(display.name) and backlight_device is not None:
            try:
                brightness_percent = read_backlight_percent(backlight_device)
                backend = "brightnessctl"
                backend_target = backlight_device.name
                backend_label = f"Hardware backlight ({backlight_device.name})"
                min_percent = 1
                max_percent = 100
            except (OSError, RuntimeError):
                pass
        elif display.name in ddcutil_buses:
            try:
                brightness_percent = read_ddc_brightness(ddcutil_buses[display.name])
                backend = "ddcutil"
                backend_target = ddcutil_buses[display.name]
                backend_label = f"DDC/CI hardware brightness (bus {backend_target})"
                min_percent = 1
                max_percent = 100
            except RuntimeError:
                pass

        displays.append(
            Display(
                name=display.name,
                title=display.title,
                details=f"{display.details} • {backend_label}",
                brightness_percent=brightness_percent,
                primary=display.primary,
                backend=backend,
                backend_target=backend_target,
                backend_label=backend_label,
                min_percent=min_percent,
                max_percent=max_percent,
            )
        )

    return displays


def get_connected_displays() -> list[Display]:
    return resolve_display_backends(parse_xrandr_displays(run_command("xrandr", "--verbose")))


def set_display_brightness(display: Display, brightness_percent: int) -> int:
    target_percent = clamp(brightness_percent, display.min_percent, display.max_percent)

    if display.backend == "brightnessctl":
        set_backlight_percent(Path("/sys/class/backlight") / display.backend_target, target_percent)
        return target_percent

    if display.backend == "ddcutil":
        set_ddc_brightness(display.backend_target, target_percent)
        return target_percent

    brightness_value = clamp(target_percent, 10, 130) / 100
    run_command("xrandr", "--output", display.backend_target, "--brightness", f"{brightness_value:.2f}")
    return target_percent


def has_night_light_support() -> bool:
    try:
        output = run_command(
            "gsettings",
            "writable",
            "org.gnome.settings-daemon.plugins.color",
            "night-light-enabled",
        )
    except RuntimeError:
        return False
    return output.strip() == "true"


def get_night_light_enabled() -> bool:
    output = run_command(
        "gsettings",
        "get",
        "org.gnome.settings-daemon.plugins.color",
        "night-light-enabled",
    )
    return output.strip() == "true"


def set_night_light_enabled(enabled: bool) -> None:
    run_command(
        "gsettings",
        "set",
        "org.gnome.settings-daemon.plugins.color",
        "night-light-enabled",
        "true" if enabled else "false",
    )


class MonitorLightsWindow(Gtk.ApplicationWindow):
    def __init__(self, app: Gtk.Application) -> None:
        super().__init__(application=app, title="Monitor Lights")
        self.set_default_size(560, 460)

        self.pending_updates: dict[str, int] = {}
        self.displays: dict[str, Display] = {}
        self.scales: dict[str, Gtk.Scale] = {}
        self.scale_handlers: dict[str, int] = {}
        self.value_labels: dict[str, Gtk.Label] = {}
        self._syncing_night_light = False

        header = Gtk.HeaderBar()
        header.set_title_widget(Gtk.Label(label="Monitor Lights"))
        self.set_titlebar(header)

        self.refresh_button = Gtk.Button(label="Refresh")
        self.refresh_button.connect("clicked", self.on_refresh_clicked)
        header.pack_start(self.refresh_button)

        self.day_button = Gtk.Button(label="Day")
        self.day_button.connect("clicked", self.on_day_clicked)
        header.pack_end(self.day_button)

        self.night_button = Gtk.Button(label="Night")
        self.night_button.connect("clicked", self.on_night_clicked)
        header.pack_end(self.night_button)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        root.set_margin_top(16)
        root.set_margin_bottom(16)
        root.set_margin_start(16)
        root.set_margin_end(16)
        self.set_child(root)

        subtitle = Gtk.Label(
            label="Adjust each connected display with the best available Ubuntu brightness backend.",
            xalign=0,
            wrap=True,
        )
        subtitle.add_css_class("dim-label")
        root.append(subtitle)

        self.night_light_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.night_light_box.set_halign(Gtk.Align.FILL)
        self.night_light_box.set_hexpand(True)
        self.night_light_label = Gtk.Label(label="Night Light", xalign=0)
        self.night_light_label.set_hexpand(True)
        self.night_light_switch = Gtk.Switch()
        self.night_light_switch.connect("notify::active", self.on_night_light_toggled)
        self.night_light_box.append(self.night_light_label)
        self.night_light_box.append(self.night_light_switch)
        root.append(self.night_light_box)

        self.status_label = Gtk.Label(xalign=0, wrap=True)
        root.append(self.status_label)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_vexpand(True)
        root.append(scroller)

        self.display_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        scroller.set_child(self.display_list)

        hint = Gtk.Label(
            label="Hardware backlight and DDC/CI are preferred when available. XRandR is used as the fallback on X11.",
            xalign=0,
            wrap=True,
        )
        hint.add_css_class("dim-label")
        root.append(hint)

        self.refresh_displays()

    def set_status(self, message: str) -> None:
        self.status_label.set_text(message)

    def clear_display_list(self) -> None:
        child = self.display_list.get_first_child()
        while child is not None:
            next_child = child.get_next_sibling()
            self.display_list.remove(child)
            child = next_child
        self.displays.clear()
        self.scales.clear()
        self.scale_handlers.clear()
        self.value_labels.clear()

    def refresh_displays(self) -> None:
        for source_id in self.pending_updates.values():
            GLib.source_remove(source_id)
        self.pending_updates.clear()
        self.clear_display_list()

        try:
            displays = get_connected_displays()
        except RuntimeError as error:
            self.set_status(f"Could not read displays: {error}")
            return

        night_light_supported = has_night_light_support()
        self.night_light_box.set_visible(night_light_supported)
        if night_light_supported:
            try:
                self._syncing_night_light = True
                self.night_light_switch.set_active(get_night_light_enabled())
            except RuntimeError as error:
                self.set_status(f"Night Light status unavailable: {error}")
            finally:
                self._syncing_night_light = False

        if not displays:
            self.display_list.append(Gtk.Label(label="No connected displays found.", xalign=0))
            self.set_status("No connected displays found.")
            return

        for display in displays:
            self.displays[display.name] = display
            self.display_list.append(self.build_display_card(display))

        self.set_status(f"Found {len(displays)} connected display(s).")

    def build_display_card(self, display: Display) -> Gtk.Widget:
        frame = Gtk.Frame()

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        card.set_margin_top(12)
        card.set_margin_bottom(12)
        card.set_margin_start(12)
        card.set_margin_end(12)
        frame.set_child(card)

        title = Gtk.Label(xalign=0)
        title.set_markup(f"<b>{GLib.markup_escape_text(display.title)}</b>")
        card.append(title)

        details = Gtk.Label(label=display.details, xalign=0, wrap=True)
        details.add_css_class("dim-label")
        card.append(details)

        slider_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        card.append(slider_row)

        scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, display.min_percent, display.max_percent, 1
        )
        scale.set_hexpand(True)
        scale.set_draw_value(False)
        scale.set_value(display.brightness_percent)
        handler_id = scale.connect("value-changed", self.on_scale_changed, display.name)
        slider_row.append(scale)

        value_label = Gtk.Label(label=f"{display.brightness_percent}%")
        slider_row.append(value_label)

        self.scales[display.name] = scale
        self.scale_handlers[display.name] = handler_id
        self.value_labels[display.name] = value_label
        return frame

    def on_refresh_clicked(self, _button: Gtk.Button) -> None:
        self.refresh_displays()

    def on_day_clicked(self, _button: Gtk.Button) -> None:
        self.apply_preset(DAY_PRESET, False, "Day preset applied.")

    def on_night_clicked(self, _button: Gtk.Button) -> None:
        self.apply_preset(NIGHT_PRESET, True, "Night preset applied.")

    def apply_preset(self, brightness_percent: int, enable_night_light: bool, message: str) -> None:
        failures: list[str] = []
        for output_name, scale in self.scales.items():
            display = self.displays[output_name]
            target_percent = clamp(brightness_percent, display.min_percent, display.max_percent)
            try:
                applied_percent = set_display_brightness(display, target_percent)
                handler_id = self.scale_handlers[output_name]
                scale.handler_block(handler_id)
                scale.set_value(applied_percent)
                scale.handler_unblock(handler_id)
                self.value_labels[output_name].set_text(f"{applied_percent}%")
                self.displays[output_name].brightness_percent = applied_percent
            except RuntimeError as error:
                failures.append(f"{output_name}: {error}")

        if self.night_light_box.get_visible():
            try:
                self._syncing_night_light = True
                set_night_light_enabled(enable_night_light)
                self.night_light_switch.set_active(enable_night_light)
            except RuntimeError as error:
                failures.append(f"Night Light: {error}")
            finally:
                self._syncing_night_light = False

        if failures:
            self.set_status(" | ".join(failures))
            return

        self.set_status(message)

    def on_scale_changed(self, scale: Gtk.Scale, output_name: str) -> None:
        display = self.displays[output_name]
        brightness_percent = clamp(int(round(scale.get_value())), display.min_percent, display.max_percent)
        self.value_labels[output_name].set_text(f"{brightness_percent}%")

        existing_source = self.pending_updates.pop(output_name, None)
        if existing_source is not None:
            GLib.source_remove(existing_source)

        source_id = GLib.timeout_add(120, self.apply_scale_value, output_name)
        self.pending_updates[output_name] = source_id

    def apply_scale_value(self, output_name: str) -> bool:
        self.pending_updates.pop(output_name, None)
        scale = self.scales.get(output_name)
        display = self.displays.get(output_name)
        if scale is None or display is None:
            return GLib.SOURCE_REMOVE

        brightness_percent = clamp(
            int(round(scale.get_value())), display.min_percent, display.max_percent
        )
        try:
            applied_percent = set_display_brightness(display, brightness_percent)
        except RuntimeError as error:
            self.set_status(f"Could not update {output_name}: {error}")
            return GLib.SOURCE_REMOVE

        self.displays[output_name].brightness_percent = applied_percent
        self.set_status(f"{output_name} set to {applied_percent}% via {display.backend_label}.")
        return GLib.SOURCE_REMOVE

    def on_night_light_toggled(self, switch: Gtk.Switch, _param: object) -> None:
        if self._syncing_night_light:
            return

        try:
            set_night_light_enabled(switch.get_active())
        except RuntimeError as error:
            self._syncing_night_light = True
            switch.set_active(not switch.get_active())
            self._syncing_night_light = False
            self.set_status(f"Could not update Night Light: {error}")
            return

        state = "enabled" if switch.get_active() else "disabled"
        self.set_status(f"Night Light {state}.")


class MonitorLightsApp(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id="app.monitorlights.MonitorLights")

    def do_activate(self) -> None:
        window = self.props.active_window
        if window is None:
            window = MonitorLightsWindow(self)
        window.present()


def main() -> int:
    app = MonitorLightsApp()
    return app.run(None)


if __name__ == "__main__":
    raise SystemExit(main())
