#!/usr/bin/env python3
import argparse
import sys
from dataclasses import replace
from pathlib import Path

from reviewer.config import settings
from reviewer.formatter import (
    evaluate_pass_status,
    filter_false_positives,
    print_compact_summary,
    save_reports,
)
from reviewer.git_client import get_git_diff
from reviewer.ollama_client import analyze_diff_with_ollama
from reviewer.onedev_api import post_onedev_comment

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="TMA Compliance AI Reviewer")
    parser.add_argument("--staged", action="store_true", help="Проверить индексированные изменения (git diff --cached)")
    parser.add_argument("--target", default=settings.target_branch, help="Целевая ветка для сравнения")
    parser.add_argument("--diff-file", type=str, help="Путь к готовому .diff файлу")
    parser.add_argument("--model", default=settings.ollama_model, help="Модель Ollama")
    parser.add_argument("--output-md", type=str, help="Кастомный путь для сохранения Markdown-отчета")
    parser.add_argument("--verbose", "-v", action="store_true", help="Вывести список ошибок также в консоль")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    runtime_cfg = replace(settings, ollama_model=args.model, target_branch=args.target)

    if args.diff_file:
        diff_path = Path(args.diff_file)
        if not diff_path.exists():
            print(f"❌ Файл не найден: {diff_path}", file=sys.stderr)
            sys.exit(2)
        diff_text = diff_path.read_text(encoding="utf-8").strip()
        source_label = f"file: {diff_path.name}"
    else:
        diff_text = get_git_diff(
            staged=args.staged,
            target_branch=runtime_cfg.target_branch,
            ignore_patterns=runtime_cfg.ignore_patterns,
        )
        source_label = "git diff --cached" if args.staged else f"git diff {runtime_cfg.target_branch}...HEAD"

    if not diff_text:
        print("ℹ️ Изменений для анализа не найдено. Выход.")
        sys.exit(0)

    system_prompt = runtime_cfg.system_prompt_path.read_text(encoding="utf-8")

    use_gemini = runtime_cfg.ai_provider.lower() == "gemini" or (
        runtime_cfg.ai_provider.lower() == "auto" and bool(runtime_cfg.gemini_api_key)
    )
    active_model_label = f"Gemini ({runtime_cfg.gemini_model})" if use_gemini else f"Ollama ({runtime_cfg.ollama_model})"

    print(f"🔍 Анализ кода ({source_label}, модель: {active_model_label})...")
    raw_report = analyze_diff_with_ollama(diff_text, system_prompt, runtime_cfg)

    # Пост-обработка: отсекаем галлюцинации
    report = filter_false_positives(raw_report, diff_text)
    passed = evaluate_pass_status(report)

    md_path, _ = save_reports(
        report=report,
        passed=passed,
        reports_dir=runtime_cfg.reports_dir,
        source_label=source_label,
        custom_md_path=args.output_md,
    )

    post_onedev_comment(md_path)

    print_compact_summary(report, passed, md_path, verbose=args.verbose)

    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()