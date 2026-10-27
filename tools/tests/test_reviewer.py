import json
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

from reviewer import (
    evaluate_pass_status,
    format_markdown_report,
    analyze_diff_with_ollama,
    load_system_prompt,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_evaluate_pass_status_blocks_on_critical():
    """Даже если модель случайно вернула passed=True, наличие CRITICAL обязано заблокировать PR."""
    mock_report = {
        "passed": True,
        "summary": "Найдена одна ошибка",
        "issues": [
            {
                "rule_id": "TMA-UI-01",
                "severity": "CRITICAL",
                "file": "TaskItem.tsx",
                "line_hint": "window.alert()",
                "message": "Запрещен нативный alert",
                "suggestion": "Используйте Telegram.WebApp.showAlert"
            }
        ]
    }
    assert evaluate_pass_status(mock_report) is False


def test_evaluate_pass_status_allows_warnings_only():
    """Если есть только WARNING (например, CSS-переменные или селектор), PR не блокируется."""
    mock_report = {
        "passed": True,
        "summary": "Есть некритичные замечания",
        "issues": [
            {
                "rule_id": "STATE-01",
                "severity": "WARNING",
                "file": "TaskItem.tsx",
                "line_hint": "useTaskStore()",
                "message": "Вызов стора без селектора",
                "suggestion": "useTaskStore(s => s.action)"
            }
        ]
    }
    assert evaluate_pass_status(mock_report) is True


def test_markdown_report_generation():
    mock_report = {
        "passed": False,
        "summary": "Обнаружены нарушения безопасности",
        "issues": [
            {
                "rule_id": "TMA-SEC-01",
                "severity": "CRITICAL",
                "file": "tasks.py",
                "line_hint": "async def create_task(user_id: int)",
                "message": "Отсутствует валидация initData",
                "suggestion": "Depends(verify_telegram_init_data)"
            }
        ]
    }
    md = format_markdown_report(mock_report, passed=False)
    assert "❌ BLOCKED" in md
    assert "TMA-SEC-01" in md
    assert "`tasks.py`" in md


@patch("urllib.request.urlopen")
def test_analyze_diff_with_mocked_ollama(mock_urlopen):
    """Проверка корректности формирования HTTP-запроса и парсинга ответа Ollama."""
    expected_json = {
        "passed": True,
        "summary": "Код чистый",
        "issues": []
    }
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps({
        "message": {"content": json.dumps(expected_json)}
    }).encode("utf-8")
    mock_response.__enter__.return_value = mock_response
    mock_urlopen.return_value = mock_response

    prompt = load_system_prompt()
    result = analyze_diff_with_ollama("+ const x = 1;", prompt)
    assert result["passed"] is True
    assert result["issues"] == []