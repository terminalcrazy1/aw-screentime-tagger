"""Configuration: every knob in one dataclass."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


LABELS = ("violent-screentime", "screentime", "non-screentime")

CORRECTION_KINDS = ("with_friends", "extra", "educational", "nonviolent")
FORCE_NON = ("with_friends", "extra", "educational")
DOWNGRADE = ("nonviolent",)


def repo_root():
    return Path(__file__).resolve().parent.parent


@dataclass
class Config:
    base_dir: str = ""
    cache_path: str = ""
    state_path: str = ""
    violent_path: str = ""
    corrections_path: str = ""
    aw_host: str = "http://127.0.0.1:5600"
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5:7b"
    poll_interval: int = 15
    cache_max: int = 5000
    max_gpu_util: int = 40
    min_free_mb: int = 5500
    idle_gpu_util: int = 10

    @classmethod
    def from_env(cls, base_dir=None):
        here = str(base_dir or repo_root())
        data = os.environ.get("SCREENTIME_DATA_DIR", here)
        return cls(
            base_dir=here,
            cache_path=os.path.join(data, "cache.md"),
            state_path=os.path.join(data, "state.json"),
            violent_path=os.path.join(data, "violent.md"),
            corrections_path=os.path.join(data, "corrections.md"),
            aw_host=os.environ.get("AW_HOST", "http://127.0.0.1:5600"),
            ollama_url=os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434"),
            ollama_model=os.environ.get("OLLAMA_MODEL", "qwen2.5:7b"),
            poll_interval=int(os.environ.get("POLL_INTERVAL", "15")),
            max_gpu_util=int(os.environ.get("AW_MAX_GPU_UTIL", "40")),
            min_free_mb=int(os.environ.get("AW_MIN_FREE_MB", "5500")),
            idle_gpu_util=int(os.environ.get("AW_IDLE_GPU_UTIL", "10")),
        )
