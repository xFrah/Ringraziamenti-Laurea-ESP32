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
    "placeholder_names",
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
    placeholder_names: List[str]
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
            "placeholder_names": self.placeholder_names,
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

    raw_names = data.get("placeholder_names")
    if isinstance(raw_names, list):
        names_list = [str(n) for n in raw_names]
    else:
        names_list = [
            "Mamma", "Papà", "Francesco", "Boys", "Mea",
            "Nonna", "Teo", "Zio", "Sonia", "Martina", "Manuela"
        ]

    return Config(
        texts_dir=str(data["texts_dir"]),
        html_file=str(data["html_file"]),
        base_text_file=str(data["base_text_file"]),
        placeholder_names=names_list,
        port=str(data["port"]) if data.get("port") is not None else None,
        baud=int(data["baud"]),
        fqbn=str(data["fqbn"]),
        allow_reflash=bool(data["allow_reflash"]),
        preview_port=int(data["preview_port"]),
        live_reload=bool(data["live_reload"]),
    )


def load_all_texts_map(
    texts_dir: str = "texts",
    base_text_file: str = "text.txt",
    mapping_file: str = "mapping.json",
) -> Dict[str, str]:
    """
    Builds a dictionary mapping search keys/aliases to dedication text content.
    - All .txt files in texts_dir (except base_text_file) are automatically included,
      indexed by their filename stem (e.g. 'mea', 'boys', 'nonna', 'francesco').
    - If mapping_file exists, custom string-to-filename aliases are loaded.
      Supports single keys ("mamma": "Mamma e papà.txt"), comma-separated keys
      ("Zio, Martina, Manuela, Marco, Alessio, Sonia": "Zio.txt"), and list values.
    - Handles case-insensitivity, .txt extensions, and accented characters.
    """
    all_texts: Dict[str, str] = {}
    file_contents: Dict[str, str] = {}

    texts_path = Path(texts_dir)
    base_name = Path(base_text_file).name.lower()

    if texts_path.is_dir():
        for txt_file in texts_path.glob("*.txt"):
            if txt_file.name.lower() == base_name:
                continue
            try:
                content = txt_file.read_text(encoding="utf-8").strip()
            except Exception:
                continue

            stem_clean = txt_file.stem.strip().lower()
            file_contents[stem_clean] = content
            file_contents[f"{stem_clean}.txt"] = content

            # Default: filename stem is always a valid search key
            all_texts[stem_clean] = content
            unaccented = (
                stem_clean.replace("à", "a")
                .replace("è", "e")
                .replace("é", "e")
                .replace("ì", "i")
                .replace("ò", "o")
                .replace("ù", "u")
            )
            if unaccented != stem_clean:
                all_texts[unaccented] = content

    # Load mapping.json if present
    map_path = Path(mapping_file)
    if map_path.is_file():
        try:
            mapping_data = json.loads(map_path.read_text(encoding="utf-8"))
            if isinstance(mapping_data, dict):
                for raw_key, raw_val in mapping_data.items():
                    if isinstance(raw_val, str):
                        target_key = raw_val.strip().lower()
                        target_stem = target_key[:-4] if target_key.endswith(".txt") else target_key

                        content = file_contents.get(target_stem) or file_contents.get(target_key)
                        if not content:
                            print(f"[WARN] {mapping_file}: Target file '{raw_val}' not found in '{texts_dir}'.")
                            continue

                        # Extract aliases (comma-separated or single)
                        aliases = [part.strip() for part in raw_key.split(",") if part.strip()]
                        for alias in aliases:
                            ak = alias.lower()
                            if ak.endswith(".txt"):
                                ak = ak[:-4]
                            all_texts[ak] = content
                            unacc = (
                                ak.replace("à", "a")
                                .replace("è", "e")
                                .replace("é", "e")
                                .replace("ì", "i")
                                .replace("ò", "o")
                                .replace("ù", "u")
                            )
                            if unacc != ak:
                                all_texts[unacc] = content

                    elif isinstance(raw_val, list):
                        target_key = raw_key.strip().lower()
                        target_stem = target_key[:-4] if target_key.endswith(".txt") else target_key

                        content = file_contents.get(target_stem) or file_contents.get(target_key)
                        if not content:
                            continue

                        for alias in raw_val:
                            if isinstance(alias, str):
                                ak = alias.strip().lower()
                                if ak.endswith(".txt"):
                                    ak = ak[:-4]
                                all_texts[ak] = content
                                unacc = (
                                    ak.replace("à", "a")
                                    .replace("è", "e")
                                    .replace("é", "e")
                                    .replace("ì", "i")
                                    .replace("ò", "o")
                                    .replace("ù", "u")
                                )
                                if unacc != ak:
                                    all_texts[unacc] = content
        except Exception as e:
            print(f"[WARN] Failed to parse '{mapping_file}': {e}")

    return all_texts
