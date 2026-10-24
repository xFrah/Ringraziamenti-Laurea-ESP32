"""
Configuration loader and validator for ESP32 Greeting Pipeline.
Loads settings from config.json. If config.json does not exist, copies
example.config.json automatically. Validates that all required flags are present.
"""

from __future__ import annotations

import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


class ConfigError(Exception):
    """Base exception for configuration errors."""
    pass


class MissingConfigError(ConfigError):
    """Raised when one or more required flags are missing from config.json."""
    pass


REQUIRED_FLAGS: List[str] = [
    "texts_dir",
    "html_file",
    "base_text_file",
    "person_file",
    "port",
    "baud",
    "fqbn",
    "allow_reflash",
    "preview_port",
    "live_reload",
]


@dataclass
class Config:
    texts_dir: str
    html_file: str
    base_text_file: str
    person_file: Optional[str]
    port: Optional[str]
    baud: int
    fqbn: str
    allow_reflash: bool
    preview_port: int
    live_reload: bool

    def __getitem__(self, key: str) -> Any:
        if hasattr(self, key):
            return getattr(self, key)
        raise KeyError(f"Configuration has no field '{key}'")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "texts_dir": self.texts_dir,
            "html_file": self.html_file,
            "base_text_file": self.base_text_file,
            "person_file": self.person_file,
            "port": self.port,
            "baud": self.baud,
            "fqbn": self.fqbn,
            "allow_reflash": self.allow_reflash,
            "preview_port": self.preview_port,
            "live_reload": self.live_reload,
        }


def load_config(
    config_path: str = "config.json",
    example_path: str = "example.config.json",
) -> Config:
    """
    Loads configuration from config_path.
    If config_path does not exist, copies from example_path.
    Validates that all required flags are present, raising MissingConfigError if not.
    """
    cfg_file = Path(config_path)
    ex_file = Path(example_path)

    if not cfg_file.exists():
        if not ex_file.exists():
            raise FileNotFoundError(
                f"Neither '{config_path}' nor template '{example_path}' could be found!"
            )
        print(f"[CONFIG] '{config_path}' not found. Initializing from '{example_path}'...")
        shutil.copyfile(ex_file, cfg_file)

    try:
        data: Dict[str, Any] = json.loads(cfg_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ConfigError(f"Failed to parse JSON in '{config_path}': {e}") from e

    if not isinstance(data, dict):
        raise ConfigError(f"'{config_path}' must contain a JSON object (dictionary).")

    missing_flags = [flag for flag in REQUIRED_FLAGS if flag not in data]
    if missing_flags:
        formatted_missing = ", ".join(f"'{flag}'" for flag in missing_flags)
        raise MissingConfigError(
            f"Missing required flag(s) in '{config_path}': {formatted_missing}.\n"
            f"Please check '{example_path}' for the expected format."
        )

    return Config(
        texts_dir=str(data["texts_dir"]),
        html_file=str(data["html_file"]),
        base_text_file=str(data["base_text_file"]),
        person_file=str(data["person_file"]) if data["person_file"] is not None else None,
        port=str(data["port"]) if data["port"] is not None else None,
        baud=int(data["baud"]),
        fqbn=str(data["fqbn"]),
        allow_reflash=bool(data["allow_reflash"]),
        preview_port=int(data["preview_port"]),
        live_reload=bool(data["live_reload"]),
    )
