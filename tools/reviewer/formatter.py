import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple


def filter_false_positives(report: Dict[str, Any], diff_text: str) -> Dict[str, Any]:
    """
    Детерминированный Guardrail поверх ответа малой LLM (3b):
    отсекает галлюцинации, если модель перепутала разрешенный паттерн с запрещенным.
    """
    added_lines = "\n".join(
        line[1:] for line in diff_text.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    )

    valid_issues: List[Dict[str, Any]] = []
    for issue in report.get("issues", []):
        rule = issue.get("rule_id")

        # 1. Защита от путаницы showAlert() и window.alert()
        if rule == "TMA-UI-01":
            has_real_native_dialog = bool(
                re.search(r"(?<!\.)\b(alert|confirm|prompt)\s*\(|window\.(alert|confirm|prompt)\s*\(", added_lines)
            )
            if not has_real_native_dialog:
                continue

        # 2. Защита от ложного срабатывания TMA-SEC-01, когда Depends(verify_telegram_init_data) уже есть
        if rule == "TMA-SEC-01":
            if "verify_telegram_init_data" in added_lines:
                continue

        # 3. Защита от ложного срабатывания STATE-01, если селектор передан
        if rule == "STATE-01":
            has_empty_store_call = bool(re.search(r"use\w*Store\(\s*\)", added_lines))
            if not has_empty_store_call:
                continue

        valid_issues.append(issue)

    report["issues"] = valid_issues
    if not valid_issues:
        report["passed"] = True
        report["summary"] = "Нарушений архитектуры TMA, React/Zustand и FastAPI не обнаружено."

    return report


def evaluate_pass_status(report: Dict[str, Any]) -> bool:
    """Наличие хотя бы одной ошибки CRITICAL гарантированно блокирует PR."""
    issues: List[Dict[str, Any]] = report.get("issues", [])
    has_critical = any(i.get("severity") == "CRITICAL" for i in issues)
    return bool(report.get("passed", True)) and not has_critical


def _guess_code_lang(file_path: str) -> str:
    """Определяет язык для подсветки синтаксиса по расширению файла."""
    if file_path.endswith((".tsx", ".ts")):
        return "tsx"
    if file_path.endswith((".jsx", ".js")):
        return "jsx"
    if file_path.endswith(".py"):
        return "python"
    if file_path.endswith((".scss", ".css")):
        return "scss"
    return "text"


def format_markdown_report(report: Dict[str, Any], passed: bool, source_label: str = "") -> str:
    """Генерирует подробный Markdown-отчет, совместимый с рендерером комментариев OneDev."""
    status_badge = "✅ PASSED (Слияние разрешено)" if passed else "❌ BLOCKED (Слияние заблокировано)"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    summary = report.get("summary", "Проверка завершена.")
    issues = report.get("issues", [])

    crit_count = sum(1 for i in issues if i.get("severity") == "CRITICAL")
    warn_count = sum(1 for i in issues if i.get("severity") == "WARNING")

    lines = [
        "## 🤖 TMA Compliance AI Review Report",
        "",
        f"- **Статус:** {status_badge}",
        f"- **Дата проверки:** `{timestamp}`",
        f"- **Источник изменений:** `{source_label}`",
        f"- **Найдено проблем:** Всего `{len(issues)}` (🛑 Critical: `{crit_count}`, ⚠️ Warning: `{warn_count}`)",
        f"- **Резюме:** {summary}",
        "",
        "---",
        "",
    ]

    if not issues:
        lines.append("### 🎉 Код полностью соответствует стандартам TMA!")
        lines.append("Нарушений правил Telegram WebApp SDK, React/Zustand и безопасности FastAPI не обнаружено.")
    else:
        lines.append("## 📋 Детализация найденных нарушений")
        lines.append("")

        for idx, issue in enumerate(issues, 1):
            sev = issue.get("severity", "WARNING")
            icon = "🛑 **CRITICAL**" if sev == "CRITICAL" else "⚠️ **WARNING**"
            rule = issue.get("rule_id", "UNKNOWN")
            file_name = issue.get("file", "unknown")
            hint = (issue.get("line_hint") or "").strip()
            msg = (issue.get("message") or "").strip()
            suggestion = (issue.get("suggestion") or "").strip()

            lines.append(f"### {idx}. {icon} · `{rule}`")
            lines.append(f"📁 **Файл:** `{file_name}`")
            lines.append("")

            if hint:
                lang = _guess_code_lang(file_name)
                lines.append(f"```{lang}")
                lines.append(hint)
                lines.append("```")
                lines.append("")

            lines.append(f"> ❌ **Проблема:** {msg}")
            lines.append(">")
            lines.append(f"> 💡 **Решение:** `{suggestion}`")
            lines.append("")

            if idx < len(issues):
                lines.append("---")
                lines.append("")

    return "\n".join(lines) + "\n"


def save_reports(
    report: Dict[str, Any],
    passed: bool,
    reports_dir: Path,
    source_label: str,
    custom_md_path: str | None = None,
) -> Tuple[Path, Path]:
    """Сохраняет Markdown и JSON отчеты в папку reports/ и перезаписывает latest_review.md."""
    reports_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    md_content = format_markdown_report(report, passed, source_label)

    # 1. Сохраняем в историю и в latest_review.md
    history_md_path = reports_dir / f"review_{ts}.md"
    latest_md_path = Path(custom_md_path) if custom_md_path else (reports_dir / "latest_review.md")
    latest_json_path = reports_dir / "latest_review.json"

    history_md_path.write_text(md_content, encoding="utf-8")
    latest_md_path.write_text(md_content, encoding="utf-8")
    latest_json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    return latest_md_path, latest_json_path


def print_compact_summary(report: Dict[str, Any], passed: bool, md_path: Path, verbose: bool = False) -> None:
    """Короткий вывод в терминал в 2 строчки без спама."""
    issues = report.get("issues", [])
    crit_count = sum(1 for i in issues if i.get("severity") == "CRITICAL")
    warn_count = sum(1 for i in issues if i.get("severity") == "WARNING")

    status_icon = "✅ PASSED" if passed else "❌ BLOCKED"
    print(f"🤖 Результат: {status_icon} | Ошибок: {len(issues)} (🛑 Critical: {crit_count}, ⚠️ Warning: {warn_count})")
    print(f"📄 Полный отчет сохранен в: {md_path}")

    if verbose and issues:
        print("\n" + "-" * 70)
        for idx, issue in enumerate(issues, 1):
            print(f"{idx}. [{issue.get('severity')}] {issue.get('rule_id')} ({issue.get('file')}): {issue.get('message')}")
        print("-" * 70)