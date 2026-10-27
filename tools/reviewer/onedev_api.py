import os
import json
import sys
import socket
import subprocess
import urllib.request
import urllib.parse
from pathlib import Path
from typing import Optional

_ORIGINAL_SOCKET = socket.socket


def _restore_direct_network() -> None:
    """Отключает глобальный SOCKS5-прокси, чтобы запросы к OneDev шли напрямую."""
    socket.socket = _ORIGINAL_SOCKET
    for env_var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        os.environ.pop(env_var, None)


def _make_headers(auth_token: str, is_post: bool = False) -> dict:
    headers = {
        "Authorization": f"Bearer {auth_token}",
        "Accept": "application/json, text/plain, */*",
    }
    if is_post:
        headers["Content-Type"] = "application/json"
    return headers


def _get_local_head_commit() -> str:
    """Получает хеш текущего коммита напрямую из локального git-репозитория."""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except Exception:
        return ""


def _get_pull_request_id(base_url: str, pr_num: str, auth_token: str) -> Optional[int]:
    """Ищет внутренний requestId пулл-реквеста по номеру и хешу коммита."""
    commit_hash = _get_local_head_commit()

    params = urllib.parse.urlencode({"offset": 0, "count": 100})
    url = f"{base_url}/pulls?{params}"
    req = urllib.request.Request(url, headers=_make_headers(auth_token), method="GET")

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            pulls = json.loads(resp.read().decode("utf-8"))
            if isinstance(pulls, list):
                candidates = [p for p in pulls if str(p.get("number")) == str(pr_num)]
                print(
                    f"ℹ️ Найдено PR с номером #{pr_num}: "
                    f"{[(p.get('id'), p.get('title'), p.get('sourceBranch'), p.get('status')) for p in candidates]}"
                )

                # 1. Ищем точное совпадение по хешу коммита сборки
                if commit_hash:
                    for p in candidates:
                        if commit_hash in (p.get("buildCommitHash"), p.get("headCommitHash"), p.get("baseCommitHash")):
                            print(f"🔍 Выбран requestId по хешу коммита ({commit_hash[:7]}): {p['id']}")
                            return int(p["id"])

                # 2. Если хеш не совпал — берем самый свежий открытый (с максимальным id)
                open_candidates = [p for p in candidates if p.get("status") == "OPEN"]
                if open_candidates:
                    best = max(open_candidates, key=lambda x: int(x.get("id", 0)))
                    print(f"🔍 Выбран самый свежий открытый PR #{pr_num}: requestId={best['id']} ('{best.get('title')}')")
                    return int(best["id"])

                if candidates:
                    best = max(candidates, key=lambda x: int(x.get("id", 0)))
                    return int(best["id"])
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        print(f"⚠️ Ошибка при запросе списка /pulls (HTTP {e.code}): {err_body}", file=sys.stderr)
    except Exception as e:
        print(f"⚠️ Ошибка при запросе к /pulls: {e}", file=sys.stderr)

    return None

def _get_current_user_id(base_url: str, auth_token: str) -> int:
    """Берет userId из окружения или пытается запросить у API."""
    env_user_id = os.environ.get("ONEDEV_USER_ID", "").strip()
    if env_user_id.isdigit():
        return int(env_user_id)

    url = f"{base_url}/users/me"
    req = urllib.request.Request(url, headers=_make_headers(auth_token), method="GET")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if isinstance(data, dict) and "id" in data:
                return int(data["id"])
    except Exception as e:
        print(f"⚠️ Не удалось запросить /users/me: {e}", file=sys.stderr)
    
    # Если бот совсем закрыт, возвращаем 2 (или можно вернуть 1, если это токен Олега)
    return 2


def post_onedev_comment(md_path: Optional[str], token: Optional[str] = None) -> None:
    """Публикует отчет комментарием в Pull Request OneDev через /~api/pull-request-comments."""
    if not md_path or not Path(md_path).exists():
        return

    pr_num = os.environ.get("ONEDEV_PULL_REQUEST_ID")
    auth_token = token or os.environ.get("ONEDEV_TOKEN") or os.environ.get("TOKEN")

    if not pr_num or pr_num.strip() in ("", "None") or pr_num.startswith("@"):
        print(f"ℹ️ ONEDEV_PULL_REQUEST_ID не задан ({pr_num}). Пропускаем отправку комментария.")
        return

    if not auth_token:
        print("ℹ️ Токен OneDev не задан. Пропускаем отправку комментария.")
        return

    _restore_direct_network()

    md_content = Path(md_path).read_text(encoding="utf-8")
    base_url = "https://git.dizzzy.space/~api"

    # Шаг 0: Узнаем реальный ID владельца токена (будь то Олег или бот)
    user_id = _get_current_user_id(base_url, auth_token)

    # Шаг 1: Находим настоящий внутренний requestId
    request_id = _get_pull_request_id(base_url, pr_num.strip(), auth_token)
    if request_id is None:
        print("❌ Не удалось определить внутренний requestId пулл-реквеста.", file=sys.stderr)
        return

    # Шаг 2: Отправляем комментарий с правильным userId токена
    api_url = f"{base_url}/pull-request-comments"
    payload = json.dumps({
        "requestId": request_id,
        "userId": user_id,
        "content": md_content,
    }).encode("utf-8")

    req = urllib.request.Request(
        api_url,
        data=payload,
        headers=_make_headers(auth_token, is_post=True),
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            comment_id = response.read().decode("utf-8", errors="replace").strip()
            print(f"💬 Отчет успешно опубликован от имени userId={user_id} в PR #{pr_num} (commentId: {comment_id}).")
    except urllib.error.HTTPError as e:
        err_detail = e.read().decode("utf-8", errors="replace")
        print(f"⚠️ Не удалось отправить комментарий в OneDev API (HTTP {e.code}): {err_detail}", file=sys.stderr)
    except Exception as e:
        print(f"⚠️ Ошибка сети при отправке комментария в OneDev API: {e}", file=sys.stderr)