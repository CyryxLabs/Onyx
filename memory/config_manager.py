import json
from pathlib import Path

from core.paths import config_dir, config_file, resource_root

def get_base_dir() -> Path:
    return resource_root()

BASE_DIR    = get_base_dir()
CONFIG_DIR  = config_dir()
CONFIG_FILE = config_file()

def ensure_config_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

def config_exists() -> bool:
    return CONFIG_FILE.exists()

def save_api_keys(gemini_api_key: str) -> None:
    from core.credentials import set
    set(gemini_api_key)

def load_api_keys() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"❌ Failed to load api_keys.json: {e}")
        return {}

def get_gemini_key() -> str | None:
    from core.credentials import get
    return get(required=False)

def is_configured() -> bool:
    key = get_gemini_key()
    return bool(key and len(key) > 15)
