import subprocess
import sys
from typing import List


def get_git_diff(staged: bool, target_branch: str, ignore_patterns: List[str]) -> str:
    """Извлекает git diff относительно индекса (--staged) или целевой ветки."""
    try:
        if staged:
            cmd = ["git", "diff", "--cached", "--ignore-submodules", "--", "."] + ignore_patterns
        else:
            cmd = ["git", "diff", "--ignore-submodules", f"{target_branch}...HEAD", "--", "."] + ignore_patterns

        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"⚠️ Ошибка при получении git diff: {e.stderr}", file=sys.stderr)
        sys.exit(2)