# ESP32 Continuous Flashing Pipeline 🎓⚡

Automated continuous flashing pipeline for ESP32 boards (specifically designed for mass production of devices like the graduation greeting tokens in `main.ino`).

## Features

- **Automatic Plug-and-Flash Detection**: Continuously monitors serial/USB ports (`pyserial`) and triggers flashing the moment an ESP32 board is plugged in.
- **Strict Duplicate Board Protection (In-Memory)**: Reads each board's factory-burned hardware MAC address. **Guarantees that the same board is never flashed twice in a row** during the run, even if it stays plugged in, reboots, or is re-inserted.
- **In-Memory History**: Starts completely fresh every time you start the script (stored strictly in RAM, no disk clutter).
- **High-Speed Flashing**: Flashes at 921,600 baud using optimized component offsets (`@flash_args`), completing each board in ~3.5 to 5 seconds.
- **Visual Terminal Feedback**: Clear ANSI colored status banners indicating detection, flashing progress, duplicates, and completion.
- **Auto-Compilation on Startup**: Always injects text from `texts/` and recompiles `main.ino` with `arduino-cli` upon start.

---

## How to Run

### 1. Browser Preview with Live Reload 🌐

Before flashing, you can preview the rendered greeting page in your browser:

```bash
uv run python preview.py
```

- Injects text from `texts/text.txt` and your chosen dedication file (e.g. `texts/Mamma.txt`).
- Automatically opens your default web browser at `http://127.0.0.1:8000`.
- **Live Reload**: Automatically refreshes the browser page whenever you modify `index.html` or any text file inside `texts/`!
- Press `Ctrl+C` in the terminal to close the preview server.

### 2. Flashing Pipeline 🚀

```bash
uv run python main.py
```

### Typical Workflow

1. Start `uv run python main.py`.
2. Connect an ESP32 board to your computer via USB.
3. The pipeline detects the board, checks its MAC address, and flashes it automatically in ~4 seconds.
4. When you see `✓ FLASH SUCCESSFUL`, **unplug the board**.
5. Connect the next board — the pipeline immediately detects it and repeats!
6. If you accidentally reconnect a board you just flashed, the pipeline skips it and prompts you to connect a new one.
7. Press `Ctrl+C` when finished to view your session summary.

---

## Configuration

All configuration is centralized in `config.json`. If `config.json` does not exist, `config.py` automatically initializes it by copying from `example.config.json`.

```json
{
  "texts_dir": "texts",
  "html_file": "index.html",
  "base_text_file": "text.txt",
  "person_file": "Mamma.txt",
  "port": null,
  "baud": 921600,
  "fqbn": "esp32:esp32:esp32c3",
  "allow_reflash": false,
  "preview_port": 8000,
  "live_reload": true
}
```

### Configuration Flags:
- **`texts_dir`**: Folder containing all your plain text files (default: `"texts"`).
- **`html_file`**: HTML template file with `[TEXT]` and `[ADDITIONAL_TEXT]` tokens (default: `"index.html"`).
- **`base_text_file`**: Base greeting message inside `texts/` (default: `"text.txt"`).
- **`person_file`**: Secondary dedication file inside `texts/` (e.g. `"Mamma.txt"`, `"Papà.txt"`, or `null`).
- **`port`**: Serial port (e.g. `"COM3"`) or `null` for automatic detection.
- **`baud`**: Flashing speed in baud (default: `921600` for ~3.5s flash time).
- **`fqbn`**: Target ESP32 architecture (default: `"esp32:esp32:esp32c3"`).
- **`allow_reflash`**: `false` strictly prevents flashing the same board twice in a row; `true` allows re-flashing.
- **`preview_port`**: Local port for the browser preview server (default: `8000`).
- **`live_reload`**: `true` automatically reloads the browser when any text or HTML file is edited.

Both `main.py` and `preview.py` load their settings through `config.py`. If any required key is missing from `config.json`, `config.py` raises a `MissingConfigError` explaining which flags need to be added.

---

## Folder Structure & File Separation

- **`texts/`**: Contains all plain text files:
  - `text.txt`: Base message injected into `[TEXT]`.
  - Dedication files (e.g. `Mamma.txt`, `Papà.txt`): Injected into `[ADDITIONAL_TEXT]`.
- **`index.html`**: Contains the full web page structure, styling, and the `[TEXT]` / `[ADDITIONAL_TEXT]` tokens.
- **`main.ino`**: Contains `const char HTML_PAGE[] PROGMEM = R"=====([HTML_PAGE])=====";`. When compiling, `main.py` reads `index.html`, loads texts from `texts/`, and injects the resulting HTML into the sketch before flashing.
- **`config.py`**: Configuration loader and validator.
- **`example.config.json`**: Template configuration tracked in git.
- **`config.json`**: Active user configuration.
