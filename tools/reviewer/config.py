import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(dotenv_path: Path) -> None:
    if not dotenv_path.exists():
        return
    for line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


_load_dotenv(BASE_DIR / ".env")


@dataclass(frozen=True)
class Settings:
    ai_provider: str = os.getenv("AI_PROVIDER", "auto")
    
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
    gemini_proxy: str = os.getenv("GEMINI_PROXY", "")  # Например: http://user:pass@ip:port
    
    ollama_url: str = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "qwen2.5-coder:3b")
    temperature: float = float(os.getenv("OLLAMA_TEMPERATURE", "0.05"))
    num_ctx: int = int(os.getenv("OLLAMA_NUM_CTX", "8192"))
    timeout: int = int(os.getenv("OLLAMA_TIMEOUT", "180"))
    
    target_branch: str = os.getenv("TARGET_BRANCH", "origin/main")
    max_diff_chars: int = int(os.getenv("MAX_DIFF_CHARS", "24000"))
    system_prompt_path: Path = BASE_DIR / "system_prompt.txt"
    reports_dir: Path = BASE_DIR / os.getenv("REPORTS_DIR", "reports")
    ignore_patterns: List[str] = field(default_factory=lambda: [
        f":(exclude){p.strip()}"
        for p in os.getenv(
            "IGNORE_PATTERNS",
            "package-lock.json,pnpm-lock.yaml,yarn.lock,*.svg,*.png,*/alembic/versions/*"
        ).split(",")
        if p.strip()
    ])


settings = Settings()