import json
import time
import sys
import urllib.error
import urllib.request
from typing import Any, Dict

from .config import Settings
from .schemas import RESPONSE_JSON_SCHEMA


def analyze_diff_with_ollama(diff_text: str, system_prompt: str, cfg: Settings) -> Dict[str, Any]:
    """Отправляет git diff в Gemini API (если задан ключ) или в локальный сервер Ollama."""
    if len(diff_text) > cfg.max_diff_chars:
        print(f"⚠️ Diff превышает лимит ({len(diff_text)} симв.), обрезаем до {cfg.max_diff_chars}...")
        diff_text = diff_text[:cfg.max_diff_chars] + "\n... [DIFF TRUNCATED]"

    use_gemini = cfg.ai_provider.lower() == "gemini" or (
        cfg.ai_provider.lower() == "auto" and bool(cfg.gemini_api_key)
    )

    if use_gemini:
        return _call_gemini(diff_text, system_prompt, cfg)
    return _call_ollama(diff_text, system_prompt, cfg)


def _call_gemini(diff_text: str, system_prompt: str, cfg: Settings) -> Dict[str, Any]:
    """Отправляет запрос в Gemini REST API с ретраями и фоллбэком моделей при 503/429."""
    payload = {
        "systemInstruction": {
            "parts": [{"text": system_prompt}]
        },
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "text": f"Проанализируй следующий git diff на соответствие правилам TMA:\n\n```diff\n{diff_text}\n```"
                    }
                ],
            }
        ],
        "generationConfig": {
            "temperature": cfg.temperature,
            "responseMimeType": "application/json",
            "responseSchema": RESPONSE_JSON_SCHEMA,
        },
    }

    handlers = []
    if cfg.gemini_proxy:
        if cfg.gemini_proxy.startswith("socks"):
            try:
                import socks
                import socket
                # Парсим socks5://172.17.0.1:10808
                proxy_clean = cfg.gemini_proxy.replace("socks5://", "").replace("socks4://", "")
                host, _, port_str = proxy_clean.partition(":")
                socks.set_default_proxy(socks.SOCKS5, host, int(port_str))
                socket.socket = socks.socksocket
            except ImportError:
                print("❌ Для SOCKS5 прокси требуется библиотека PySocks (`pip install PySocks`)", file=sys.stderr)
                sys.exit(2)
        else:
            handlers.append(
                urllib.request.ProxyHandler({
                    "http": cfg.gemini_proxy,
                    "https": cfg.gemini_proxy,
                })
            )
    opener = urllib.request.build_opener(*handlers)

    # Список моделей: сначала твоя из конфига, затем резервные на случай перегрузки (503)
    fallback_models = [
        cfg.gemini_model,
        "gemini-3.8-flash",
        "gemini-3.5-flash-lite",
        "gemini-3.5-flash",
    ]
    # Убираем дубликаты, сохраняя порядок
    models_to_try = list(dict.fromkeys(fallback_models))

    last_error = ""
    for model_name in models_to_try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={cfg.gemini_api_key}"
        
        for attempt in range(1, 3):  # По 2 попытки на модель
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with opener.open(req, timeout=cfg.timeout) as response:
                    res_data = json.loads(response.read().decode("utf-8"))
                    candidates = res_data.get("candidates", [])
                    if not candidates:
                        raise ValueError(f"Пустой ответ от Gemini: {res_data}")
                    raw_content = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "{}")
                    return json.loads(raw_content)
            except urllib.error.HTTPError as e:
                err_body = e.read().decode("utf-8", errors="replace")
                last_error = f"HTTP {e.code}: {err_body}"
                # Если 503 (перегружен), 429 (лимит) или 404 (модель не найдена) — пробуем дальше
                if e.code in (503, 429, 404):
                    print(f"⚠️ Модель {model_name} недоступна (HTTP {e.code}, попытка {attempt}/2). Переключаемся...", file=sys.stderr)
                    time.sleep(1.5)
                    if e.code == 404:
                        break  # Если модели нет, сразу идем к следующей в списке
                    continue
                print(f"❌ Критическая ошибка Gemini API ({model_name}, HTTP {e.code}): {err_body}", file=sys.stderr)
                sys.exit(2)
            except urllib.error.URLError as e:
                print(f"❌ Не удалось подключиться к Gemini API (проверь GEMINI_PROXY): {e}", file=sys.stderr)
                sys.exit(2)
            except (json.JSONDecodeError, ValueError, KeyError, IndexError) as e:
                print(f"❌ Ошибка разбора ответа от Gemini: {e}", file=sys.stderr)
                sys.exit(2)

    print(f"❌ Все модели Gemini временно недоступны. Последняя ошибка: {last_error}", file=sys.stderr)
    sys.exit(2)


def _call_ollama(diff_text: str, system_prompt: str, cfg: Settings) -> Dict[str, Any]:
    """Отправляет git diff в локальный сервер Ollama."""
    payload = {
        "model": cfg.ollama_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": f"Проанализируй следующий git diff на соответствие правилам TMA:\n\n```diff\n{diff_text}\n```",
            },
        ],
        "format": RESPONSE_JSON_SCHEMA,
        "stream": False,
        "options": {
            "temperature": cfg.temperature,
            "num_ctx": cfg.num_ctx,
        },
    }

    req = urllib.request.Request(
        cfg.ollama_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=cfg.timeout) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            raw_content = res_data.get("message", {}).get("content", "{}")
            return json.loads(raw_content)
    except urllib.error.URLError as e:
        print(f"❌ Не удалось подключиться к Ollama ({cfg.ollama_url}): {e}", file=sys.stderr)
        print("💡 Проверь, что запущена команда `ollama serve` и скачана модель.", file=sys.stderr)
        sys.exit(2)
    except json.JSONDecodeError as e:
        print(f"❌ Модель вернула невалидный JSON: {e}", file=sys.stderr)
        sys.exit(2)