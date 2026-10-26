"""
ESP32 Greeting Page - Browser Preview & Live Reload Server
Generates a rendered preview of index.html by injecting text from text.txt and
the selected dedication file (e.g. Mamma.txt, Papà.txt), opens the default web
browser, and automatically reloads the page whenever you edit any file.
"""

from __future__ import annotations

import datetime
import html
import http.server
import json
import os
import socket
import socketserver
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Optional, Tuple

from config import load_config

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

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass
    os.system("")


def load_text_file(filepath: Optional[str], folder: str = "texts") -> Tuple[Optional[str], Optional[str]]:
    """Loads a text file from 'folder' or project root. Returns (filename, content) or (None, None)."""
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

    return None, None


def render_preview_html(
    html_file: str = "index.html",
    texts_dir: str = "texts",
    base_text_file: str = "text.txt",
    person_file: Optional[str] = None,
    include_live_reload: bool = False,
) -> str:
    """Reads index.html and injects base text and dedication from texts/."""
    html_path = Path(html_file)
    if not html_path.is_file():
        return f"<h1>Error: {html_file} not found</h1>"

    raw_html = html_path.read_text(encoding="utf-8")

    # Load base text from texts/
    _, base_text = load_text_file(base_text_file, folder=texts_dir)
    if not base_text:
        base_text = "Grazie di cuore per aver condiviso questo traguardo con me! 🎓"

    # Load secondary dedication from texts/
    _, dedication_text = load_text_file(person_file, folder=texts_dir)

    escaped_main = html.escape(base_text.strip())
    escaped_ded = html.escape(dedication_text.strip()) if dedication_text else ""

    # Build ALL_TEXTS JSON map from all .txt files in texts_dir (excluding base_text_file)
    all_texts_map = {}
    texts_path = Path(texts_dir)
    if texts_path.is_dir():
        base_name = Path(base_text_file).name.lower()
        for txt_file in texts_path.glob("*.txt"):
            if txt_file.name.lower() == base_name:
                continue  # skip the base text file
            try:
                content = txt_file.read_text(encoding="utf-8").strip()
                all_texts_map[txt_file.stem.lower()] = content
            except Exception:
                pass
    all_texts_json = json.dumps(all_texts_map, ensure_ascii=False)

    rendered = raw_html.replace("[TEXT]", escaped_main)
    rendered = rendered.replace("[ADDITIONAL_TEXT]", escaped_ded)
    rendered = rendered.replace("[ALL_TEXTS]", all_texts_json)

    # Inject the current person file name as the search bar placeholder
    person_display = Path(person_file).stem if person_file else ""
    rendered = rendered.replace("[PERSON_NAME]", html.escape(person_display))

    if include_live_reload:
        reload_script = """
  <!-- Live Reload Script -->
  <script id="__live_reload">
    (function() {
      let currentVersion = null;
      setInterval(async () => {
        try {
          const res = await fetch('/__version?t=' + Date.now());
          if (res.ok) {
            const v = await res.text();
            if (currentVersion !== null && v !== currentVersion) {
              console.log('[LiveReload] File modified, reloading page...');
              window.location.reload();
            }
            currentVersion = v;
          }
        } catch (e) {}
      }, 500);
    })();
  </script>
</body>
"""
        rendered = rendered.replace("</body>", reload_script)

    return rendered


def get_files_version(watched_paths: list[Path]) -> str:
    """Returns combined timestamps of all watched files for change detection."""
    timestamps = []
    for p in watched_paths:
        try:
            if p.is_file():
                timestamps.append(f"{p.name}:{p.stat().st_mtime_ns}")
            else:
                timestamps.append(f"{p.name}:0")
        except Exception:
            timestamps.append(f"{p.name}:0")
    return "|".join(timestamps)


def find_available_port(preferred_port: int = 8000) -> int:
    """Finds an available TCP port starting from preferred_port."""
    for port in range(preferred_port, preferred_port + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return 8000


def open_preview(
    texts_dir: str = "texts",
    html_file: str = "index.html",
    base_text_file: str = "text.txt",
    person_file: Optional[str] = None,
    live_reload: bool = True,
    port: int = 8000,
):
    # Determine files to watch: index.html and all .txt files in texts/
    watched_files = [Path(html_file)]
    texts_path = Path(texts_dir)
    if texts_path.is_dir():
        for txt in texts_path.glob("*.txt"):
            watched_files.append(txt)
    else:
        watched_files.append(Path(base_text_file))
        if person_file:
            watched_files.append(Path(person_file))

    # Save static preview.html copy
    static_preview = Path("preview.html")
    static_html = render_preview_html(
        html_file=html_file,
        texts_dir=texts_dir,
        base_text_file=base_text_file,
        person_file=person_file,
        include_live_reload=False,
    )
    static_preview.write_text(static_html, encoding="utf-8")

    dedication_name, _ = load_text_file(person_file, folder=texts_dir)

    if not live_reload:
        print(f"{Colors.GREEN}✓ Generated '{static_preview.name}'{Colors.RESET}")
        print(f"{Colors.CYAN}🌐 Opening browser...{Colors.RESET}")
        webbrowser.open(static_preview.resolve().as_uri())
        return

    # Live reload server
    actual_port = find_available_port(port)
    url = f"http://127.0.0.1:{actual_port}/"

    class PreviewHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, format, *args):
            # Suppress normal GET request logs to keep console clean
            pass

        def do_GET(self):
            if self.path.startswith("/__version"):
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                self.end_headers()
                # Dynamically update watched files list in case new txt files are added
                all_watched = [Path(html_file)]
                if texts_path.is_dir():
                    all_watched.extend(texts_path.glob("*.txt"))
                version = get_files_version(all_watched)
                self.wfile.write(version.encode("utf-8"))
                return

            if self.path in ("/", "/index.html", "/preview.html") or self.path.startswith("/?"):
                content = render_preview_html(
                    html_file=html_file,
                    texts_dir=texts_dir,
                    base_text_file=base_text_file,
                    person_file=person_file,
                    include_live_reload=True,
                )
                data = content.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                self.end_headers()
                self.wfile.write(data)
                return

            # Serve any local static files (images, css, etc.)
            super().do_GET()

    # Allow fast restart without port lock
    socketserver.TCPServer.allow_reuse_address = True
    server = socketserver.TCPServer(("127.0.0.1", actual_port), PreviewHTTPRequestHandler)

    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    print()
    print(f"{Colors.CYAN}{'═' * 66}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.CYAN}            🌐 ESP32 GREETING PAGE PREVIEW 🎓{Colors.RESET}")
    print(f"{Colors.DIM}          Live Browser Preview with Instant Auto-Reload{Colors.RESET}")
    print(f"{Colors.CYAN}{'═' * 66}{Colors.RESET}")
    print(f"  {Colors.BOLD}HTML File:{Colors.RESET}     {html_file}")
    print(f"  {Colors.BOLD}Texts Folder:{Colors.RESET}  {texts_dir}/")
    print(f"  {Colors.BOLD}Base Text:{Colors.RESET}     {base_text_file} -> [TEXT]")
    print(f"  {Colors.BOLD}Dedication:{Colors.RESET}    {Colors.MAGENTA}{dedication_name or 'None'}{Colors.RESET} -> [ADDITIONAL_TEXT]")
    print(f"  {Colors.BOLD}Preview URL:{Colors.RESET}   {Colors.GREEN}{url}{Colors.RESET}")
    print(f"  {Colors.BOLD}Live Reload:{Colors.RESET}   {Colors.CYAN}Active{Colors.RESET} (editing files automatically refreshes browser)")
    print(f"{Colors.CYAN}{'─' * 66}{Colors.RESET}")
    print(f"{Colors.YELLOW}👉 Opening {url} in your default browser...{Colors.RESET}")
    print(f"{Colors.DIM}   Press Ctrl+C at any time in this window to stop the preview.{Colors.RESET}")
    print(f"{Colors.CYAN}{'═' * 66}{Colors.RESET}\n")

    # Open browser
    time.sleep(0.3)
    webbrowser.open(url)

    # Monitor for changes and print notification in terminal
    last_version = get_files_version(watched_files)
    try:
        while True:
            time.sleep(0.5)
            all_watched = [Path(html_file)]
            if texts_path.is_dir():
                all_watched.extend(texts_path.glob("*.txt"))
            new_version = get_files_version(all_watched)
            if new_version != last_version:
                last_version = new_version
                now = datetime.datetime.now().strftime("%H:%M:%S")
                print(f"{Colors.GREEN}[{now}] ⚡ File change detected in {texts_dir}/! Browser refreshed.{Colors.RESET}")
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}[STOP] Preview server stopped.{Colors.RESET}")
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    # Settings are loaded from config.json (or copied from example.config.json if missing)
    cfg = load_config()

    open_preview(
        texts_dir=cfg.texts_dir,
        html_file=cfg.html_file,
        base_text_file=cfg.base_text_file,
        person_file=cfg.person_file,
        live_reload=cfg.live_reload,
        port=cfg.preview_port,
    )
