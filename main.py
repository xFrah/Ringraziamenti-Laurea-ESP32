"""
ESP32 Continuous Flashing Pipeline
Loads HTML from an external file (index.html), substitutes [TEXT] and
[ADDITIONAL_TEXT] tokens using text.txt and secondary dedication files (e.g. Mamma.txt),
injects the processed HTML into main.ino, recompiles on startup, detects newly
plugged ESP32 boards, verifies chip MAC in RAM to prevent duplicate flashing, and flashes.
"""

from __future__ import annotations

import datetime
import html
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from config import load_config

try:
    import serial.tools.list_ports
except ImportError:
    print("[ERROR] pyserial is required. Run 'uv pip install pyserial' or 'uv run main.py'")
    sys.exit(1)

# Terminal Colors (ANSI)
class Colors:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"
    BG_GREEN = "\033[42m\033[30m"
    BG_RED = "\033[41m\033[97m"
    BG_YELLOW = "\033[43m\033[30m"

# Enable UTF-8 encoding, line buffering, and VT100 colors in console
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass
    os.system("")

# Known ESP32 USB VIDs
ESP_KNOWN_VIDS = {
    0x303A: "Espressif Native USB (ESP32-C3/S2/S3)",
    0x10C4: "Silicon Labs CP210x",
    0x1A86: "WCH CH340 / CH341",
    0x0403: "FTDI",
    0x067B: "Prolific PL2303",
}

DEFAULT_BAUD = 921600
DEFAULT_FQBN = "esp32:esp32:esp32c3"
SKETCH_FILE = "main.ino"
BUILD_DIR = "build"


@dataclass
class FlashedRecord:
    mac: str
    count: int
    timestamp: str
    port: str
    chip: str
    duration_s: float
    dedication: Optional[str] = None


class FlashHistory:
    """In-memory RAM-only history tracker for the current session run."""
    def __init__(self):
        self.records: Dict[str, FlashedRecord] = {}
        self.last_flashed_mac: Optional[str] = None

    def is_same_as_last(self, mac: str) -> bool:
        if not self.last_flashed_mac:
            return False
        return mac.strip().upper() == self.last_flashed_mac.strip().upper()

    def get_record(self, mac: str) -> Optional[FlashedRecord]:
        return self.records.get(mac.strip().upper())

    def record_success(
        self,
        mac: str,
        port: str,
        chip: str,
        duration_s: float,
        dedication: Optional[str] = None,
    ) -> FlashedRecord:
        mac_clean = mac.strip().upper()
        count = len(self.records) + 1
        record = FlashedRecord(
            mac=mac_clean,
            count=count,
            timestamp=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            port=port,
            chip=chip,
            duration_s=round(duration_s, 2),
            dedication=dedication,
        )
        self.records[mac_clean] = record
        self.last_flashed_mac = mac_clean
        return record


def load_text_file(filepath: Optional[str], folder: str = "texts") -> Tuple[Optional[str], Optional[str]]:
    """
    Loads a text file from 'folder' or project root.
    Returns (filename, content) or (None, None).
    """
    if not filepath or not str(filepath).strip():
        return None, None

    raw_path = Path(filepath)
    candidates = [
        Path(folder) / raw_path.name,
        Path(folder) / f"{raw_path.stem}.txt",
        raw_path,
        Path(f"{filepath}.txt"),
    ]

    for c in candidates:
        if c.is_file():
            try:
                return c.name, c.read_text(encoding="utf-8")
            except Exception as e:
                print(f"{Colors.RED}[ERROR] Could not read file '{c}': {e}{Colors.RESET}")
                return None, None

    print(f"{Colors.YELLOW}[WARN] Text file '{filepath}' not found in '{folder}/' or project root. Skipping.{Colors.RESET}")
    return None, None


def find_arduino_cli() -> Optional[str]:
    """Search for arduino-cli on PATH and common install locations."""
    which_cli = shutil.which("arduino-cli")
    if which_cli:
        return which_cli

    local_app_data = os.environ.get("LOCALAPPDATA", "")
    candidates = [
        Path(local_app_data) / "Programs" / "Arduino IDE" / "resources" / "app" / "lib" / "backend" / "resources" / "arduino-cli.exe",
        Path("C:/Program Files/Arduino IDE/resources/app/lib/backend/resources/arduino-cli.exe"),
        Path(local_app_data) / "Arduino15" / "arduino-cli.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)

    return None


def compile_sketch(
    sketch_path: str = SKETCH_FILE,
    html_path: str = "index.html",
    build_dir: str = BUILD_DIR,
    fqbn: str = DEFAULT_FQBN,
    main_text: str = "",
    dedication_text: Optional[str] = None,
) -> bool:
    """
    Loads html_path, substitutes [TEXT] and [ADDITIONAL_TEXT] tokens, injects the
    resulting HTML into sketch_path, stages into a temporary build folder, and
    recompiles with arduino-cli.
    The original sketch_path and html_path remain clean with tokens intact.
    """
    sketch = Path(sketch_path)
    html_file = Path(html_path)
    build = Path(build_dir)

    if not sketch.exists():
        print(f"{Colors.RED}[ERROR] Sketch file '{sketch_path}' not found!{Colors.RESET}")
        return False

    if not html_file.exists():
        print(f"{Colors.RED}[ERROR] HTML template file '{html_path}' not found!{Colors.RESET}")
        return False

    arduino_cli = find_arduino_cli()
    if not arduino_cli:
        flash_args = build / "flash_args"
        main_bin = build / "main.ino.bin"
        if flash_args.exists() and main_bin.exists():
            print(f"{Colors.YELLOW}[WARN] arduino-cli not found. Proceeding with existing binaries in '{build_dir}'.{Colors.RESET}")
            return True
        else:
            print(f"{Colors.RED}[ERROR] arduino-cli not found and no precompiled binaries exist in '{build_dir}'.{Colors.RESET}")
            return False

    build.mkdir(parents=True, exist_ok=True)

    # Clean leftover .cpp files in build/sketch that might conflict
    sketch_cache = build / "sketch"
    if sketch_cache.exists():
        for old_cpp in sketch_cache.glob("*.cpp*"):
            if "main.ino" not in old_cpp.name:
                try:
                    old_cpp.unlink()
                except Exception:
                    pass

    # Read HTML template and substitute [TEXT] and [ADDITIONAL_TEXT]
    html_content = html_file.read_text(encoding="utf-8")
    escaped_main = html.escape(main_text.strip())
    escaped_ded = html.escape(dedication_text.strip()) if dedication_text else ""

    processed_html = html_content.replace("[TEXT]", escaped_main)
    processed_html = processed_html.replace("[ADDITIONAL_TEXT]", escaped_ded)

    # Inject processed HTML into sketch
    sketch_content = sketch.read_text(encoding="utf-8")
    if "[HTML_PAGE]" in sketch_content:
        processed_sketch = sketch_content.replace("[HTML_PAGE]", processed_html)
    else:
        # Fallback if sketch still has raw HTML block
        processed_sketch = re.sub(
            r'(const char HTML_PAGE\[\] PROGMEM = R"=====\()(.*?)(\)=====";)',
            lambda m: f"{m.group(1)}\n{processed_html}\n{m.group(3)}",
            sketch_content,
            flags=re.DOTALL,
        )

    # Stage processed sketch into temporary directory named 'main/main.ino'
    temp_stage = Path(tempfile.gettempdir()) / "esp32_build_main" / "main"
    temp_stage.mkdir(parents=True, exist_ok=True)
    (temp_stage / "main.ino").write_text(processed_sketch, encoding="utf-8")

    print(f"{Colors.CYAN}[BUILD] Compiling '{sketch_path}' (with '{html_path}') for '{fqbn}'...{Colors.RESET}")
    start_t = time.time()
    cmd = [
        arduino_cli,
        "compile",
        "--fqbn", fqbn,
        "--build-path", str(build.resolve()),
        str(temp_stage.resolve()),
    ]

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        print(f"{Colors.RED}[BUILD ERROR] Compilation failed!{Colors.RESET}")
        print(proc.stdout)
        print(proc.stderr)
        return False

    elapsed = time.time() - start_t
    print(f"{Colors.GREEN}✓ Compilation successful in {elapsed:.1f}s!{Colors.RESET}")
    return True


def list_candidate_ports(explicit_port: Optional[str] = None) -> List[serial.tools.list_ports_common.ListPortInfo]:
    """Scan available serial ports, prioritizing known ESP / USB-UART ports."""
    ports = list(serial.tools.list_ports.comports())
    if explicit_port:
        return [p for p in ports if p.device.upper() == explicit_port.upper()]

    esp_ports = []
    other_ports = []
    for p in ports:
        if p.vid in ESP_KNOWN_VIDS:
            esp_ports.append(p)
        elif p.vid is not None:
            other_ports.append(p)

    return esp_ports + other_ports


def get_board_identity(port_info: serial.tools.list_ports_common.ListPortInfo) -> Tuple[Optional[str], Optional[str]]:
    """Retrieve board MAC address and chip description."""
    port_name = port_info.device

    # Fast path: check if port serial_number is a MAC address (e.g. 44:B1:76:17:13:C4)
    if port_info.serial_number:
        sn = port_info.serial_number.strip().upper()
        if re.match(r"^([0-9A-F]{2}[:-]){5}([0-9A-F]{2})$", sn):
            return sn, "ESP32 (USB Native)"

    # Fallback to esptool read-mac
    cmd = [sys.executable, "-m", "esptool", "--port", port_name, "read-mac"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
        output = proc.stdout + proc.stderr
        mac_match = re.search(r"MAC:\s+([0-9a-fA-F:]{17})", output)
        chip_match = re.search(r"Chip type:\s+(.+)", output)

        mac = mac_match.group(1).upper() if mac_match else None
        chip = chip_match.group(1).strip() if chip_match else "ESP32"

        return mac, chip
    except Exception:
        return None, None


def flash_board(port: str, baud: int = DEFAULT_BAUD, build_dir: str = BUILD_DIR) -> Tuple[bool, float, str]:
    """Flash the board using esptool write-flash @flash_args."""
    build_path = Path(build_dir).resolve()
    flash_args_file = build_path / "flash_args"
    if not flash_args_file.exists():
        return False, 0.0, f"flash_args not found in {build_dir}"

    cmd = [
        sys.executable,
        "-m", "esptool",
        "--port", port,
        "--baud", str(baud),
        "write-flash",
        "@flash_args",
    ]

    start_time = time.time()
    proc = subprocess.run(cmd, cwd=str(build_path), capture_output=True, text=True)
    duration = time.time() - start_time
    output = proc.stdout + proc.stderr

    success = (proc.returncode == 0) and ("Hash of data verified" in output or "Hard resetting via RTS pin" in output)
    return success, duration, output


def print_banner(
    baud: int,
    fqbn: str,
    html_file: str,
    texts_dir: str,
    base_text_file: str,
    dedication_name: Optional[str] = None,
):
    print()
    print(f"{Colors.CYAN}{'═' * 66}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.CYAN}       🎓 ESP32 CONTINUOUS FLASHING PIPELINE 🚀{Colors.RESET}")
    print(f"{Colors.DIM}         Automatic Detection • Duplicate Protection (In-Memory){Colors.RESET}")
    print(f"{Colors.CYAN}{'═' * 66}{Colors.RESET}")
    print(f"  {Colors.BOLD}Sketch:{Colors.RESET}       {SKETCH_FILE}")
    print(f"  {Colors.BOLD}HTML File:{Colors.RESET}    {html_file}")
    print(f"  {Colors.BOLD}Texts Folder:{Colors.RESET} {texts_dir}/")
    print(f"  {Colors.BOLD}Base Text:{Colors.RESET}    {base_text_file} -> [TEXT]")
    print(f"  {Colors.BOLD}Dedication:{Colors.RESET}   {Colors.MAGENTA}{dedication_name or 'None'}{Colors.RESET} -> [ADDITIONAL_TEXT]")
    print(f"  {Colors.BOLD}FQBN:{Colors.RESET}         {fqbn}")
    print(f"  {Colors.BOLD}Baud Rate:{Colors.RESET}    {baud}")
    print(f"{Colors.CYAN}{'─' * 66}{Colors.RESET}")
    print(f"{Colors.YELLOW}👉 Plug in an ESP32 board to begin automatic flashing.{Colors.RESET}")
    print(f"{Colors.DIM}   Press Ctrl+C at any time to exit and view the session summary.{Colors.RESET}")
    print(f"{Colors.CYAN}{'═' * 66}{Colors.RESET}\n")


def continuous_flashing_loop(
    texts_dir: str = "texts",
    html_file: str = "index.html",
    base_text_file: str = "text.txt",
    person_file: Optional[str] = None,
    explicit_port: Optional[str] = None,
    baud: int = DEFAULT_BAUD,
    fqbn: str = DEFAULT_FQBN,
    allow_reflash: bool = False,
):
    # Step 1: Load base text from file inside texts/
    base_name, base_text = load_text_file(base_text_file, folder=texts_dir)
    if not base_text:
        texts_path = Path(texts_dir)
        texts_path.mkdir(parents=True, exist_ok=True)
        base_path = texts_path / Path(base_text_file).name
        default_base = (
            "Grazie di cuore per aver condiviso questo traguardo con me! 🎓\n"
            "Questo piccolo chip è il mio ringraziamento speciale per te!"
        )
        base_path.write_text(default_base, encoding="utf-8")
        base_text = default_base
        base_name = base_path.name
        print(f"{Colors.YELLOW}[INFO] Created default '{base_path}'.{Colors.RESET}")

    # Step 2: Load secondary dedication text (if any) inside texts/
    dedication_name, dedication_text = load_text_file(person_file, folder=texts_dir)
    if dedication_name:
        print(f"{Colors.GREEN}✓ Loaded dedication from '{texts_dir}/{dedication_name}'.{Colors.RESET}")
    else:
        print(f"{Colors.DIM}• No dedication file loaded (using '{base_name}' only).{Colors.RESET}")

    # Step 3: Recompile sketch injecting HTML and substituted tokens
    if not compile_sketch(
        sketch_path=SKETCH_FILE,
        html_path=html_file,
        build_dir=BUILD_DIR,
        fqbn=fqbn,
        main_text=base_text,
        dedication_text=dedication_text,
    ):
        print(f"{Colors.RED}[FATAL] Compilation failed. Cannot proceed with flashing.{Colors.RESET}")
        return

    # In-memory RAM history for this run only
    history = FlashHistory()
    print_banner(baud, fqbn, html_file, texts_dir, base_text_file, dedication_name)

    current_port_name: Optional[str] = None
    last_notified_mac: Optional[str] = None
    idle_message_shown = False

    try:
        while True:
            candidate_ports = list_candidate_ports(explicit_port)

            if not candidate_ports:
                if not idle_message_shown:
                    print(f"\r{Colors.DIM}[IDLE] Waiting for ESP32 board to be connected...{Colors.RESET}", end="", flush=True)
                    idle_message_shown = True
                current_port_name = None
                last_notified_mac = None
                time.sleep(0.5)
                continue

            target_port_info = candidate_ports[0]
            port_name = target_port_info.device

            if current_port_name == port_name and last_notified_mac:
                time.sleep(0.4)
                continue

            current_port_name = port_name
            idle_message_shown = False
            print(f"\n{Colors.CYAN}[DETECT] Found device on {port_name}: {target_port_info.description}{Colors.RESET}")

            mac, chip_info = get_board_identity(target_port_info)
            if not mac:
                print(f"{Colors.YELLOW}[CONNECTING] Identifying board on {port_name}...{Colors.RESET}")
                time.sleep(0.8)
                mac, chip_info = get_board_identity(target_port_info)

            if not mac:
                print(f"{Colors.RED}[WARN] Could not read board MAC on {port_name}. Please re-seat board.{Colors.RESET}")
                time.sleep(1.5)
                continue

            # Strict duplicate prevention: never flash the same board twice in a row
            if history.is_same_as_last(mac) and not allow_reflash:
                if last_notified_mac != mac:
                    last_notified_mac = mac
                    print(f"\n{Colors.BG_YELLOW} [DUPLICATE DETECTED] {Colors.RESET} Board {Colors.BOLD}{mac}{Colors.RESET} was JUST flashed!")
                    print(f"{Colors.YELLOW}⛔ Skipping to prevent flashing the same board twice in a row.{Colors.RESET}")
                    print(f"{Colors.BOLD}{Colors.WHITE}👉 Please UNPLUG this board and connect the next one.{Colors.RESET}\n")
                time.sleep(0.5)
                continue

            prev_record = history.get_record(mac)
            if prev_record and not allow_reflash:
                if last_notified_mac != mac:
                    last_notified_mac = mac
                    ded_note = f" ({prev_record.dedication})" if prev_record.dedication else ""
                    print(f"\n{Colors.BG_YELLOW} [ALREADY FLASHED] {Colors.RESET} Board {Colors.BOLD}{mac}{Colors.RESET} was already flashed in this run!")
                    print(f"{Colors.YELLOW}   Previously flashed as Board #{prev_record.count}{ded_note} on {prev_record.timestamp}.{Colors.RESET}")
                    print(f"{Colors.BOLD}{Colors.WHITE}👉 Please UNPLUG this board and connect the next one.{Colors.RESET}\n")
                time.sleep(0.5)
                continue

            # Ready to flash
            ded_display = f" | Dedication: {dedication_name}" if dedication_name else ""
            print(f"{Colors.BOLD}{Colors.CYAN}⚡ Flashing Board on {port_name} (MAC: {mac}, Chip: {chip_info}{ded_display})...{Colors.RESET}")
            success, duration, output = flash_board(port_name, baud=baud, build_dir=BUILD_DIR)

            if success:
                record = history.record_success(
                    mac=mac,
                    port=port_name,
                    chip=chip_info or "ESP32",
                    duration_s=duration,
                    dedication=dedication_name,
                )
                last_notified_mac = mac

                ded_label = f" ({dedication_name})" if dedication_name else ""
                print(f"\n{Colors.BG_GREEN} ✓ FLASH SUCCESSFUL! {Colors.RESET} {Colors.GREEN}Board #{record.count}{ded_label} flashed in {duration:.1f}s!{Colors.RESET}")
                print(f"  {Colors.BOLD}MAC:{Colors.RESET}       {mac}")
                print(f"  {Colors.BOLD}Port:{Colors.RESET}      {port_name}")
                if dedication_name:
                    print(f"  {Colors.BOLD}Dedication:{Colors.RESET} {dedication_name}")
                print(f"  {Colors.BOLD}This Run:{Colors.RESET}  {len(history.records)} board(s) completed")
                print(f"\n{Colors.BOLD}{Colors.WHITE}👉 Please UNPLUG this board and connect the next one.{Colors.RESET}\n")

                print(f"{Colors.DIM}Waiting for disconnect...{Colors.RESET}", end="", flush=True)
                while True:
                    current_ports = [p.device for p in serial.tools.list_ports.comports()]
                    if port_name not in current_ports:
                        print(f"\r{Colors.GREEN}🔌 Board disconnected. Ready for next board!{Colors.RESET}          \n")
                        current_port_name = None
                        last_notified_mac = None
                        break
                    time.sleep(0.3)

            else:
                print(f"\n{Colors.BG_RED} ✗ FLASH FAILED! {Colors.RESET} Error occurred while flashing {port_name}.")
                print(f"{Colors.RED}{output[-400:] if len(output) > 400 else output}{Colors.RESET}")
                print(f"{Colors.YELLOW}👉 Try reconnecting the board, or hold the BOOT button while plugging in.{Colors.RESET}\n")
                time.sleep(2.0)

    except KeyboardInterrupt:
        print(f"\n\n{Colors.CYAN}{'═' * 66}{Colors.RESET}")
        print(f"{Colors.BOLD}{Colors.CYAN}                 📊 SESSION SUMMARY 📊{Colors.RESET}")
        print(f"{Colors.CYAN}{'═' * 66}{Colors.RESET}")
        print(f"  Boards flashed this run: {Colors.BOLD}{Colors.GREEN}{len(history.records)}{Colors.RESET}")

        if history.records:
            print(f"\n  {Colors.BOLD}Flashed boards:{Colors.RESET}")
            for r in history.records.values():
                ded_str = f" | {r.dedication}" if r.dedication else ""
                print(f"    • Board #{r.count:02d} | MAC: {r.mac}{ded_str} | {r.duration_s}s | {r.timestamp}")

        print(f"{Colors.CYAN}{'═' * 66}{Colors.RESET}\n")


if __name__ == "__main__":
    # Settings are loaded from config.json (or copied from example.config.json if missing)
    cfg = load_config()

    continuous_flashing_loop(
        texts_dir=cfg.texts_dir,
        html_file=cfg.html_file,
        base_text_file=cfg.base_text_file,
        person_file=cfg.person_file,
        explicit_port=cfg.port,
        baud=cfg.baud,
        fqbn=cfg.fqbn,
        allow_reflash=cfg.allow_reflash,
    )
