#!/usr/bin/env python3
"""
ByeDPI Batch Strategy Evaluator for macOS
Runs a batch of candidate strategies through the core test engine (test_config.py),
ranks them by availability, handshake latency, and real CDN streaming throughput,
and outputs human-readable tables, structured JSON, and Markdown reports.
"""

import sys
import os
import argparse
import json
import time
from datetime import datetime

# Allow importing sibling module
sys.path.insert(0, os.path.dirname(__file__))
from test_config import (
    evaluate_strategy,
    load_targets,
    locate_ciadpi,
    DEFAULT_TARGETS_FILE,
    REPORTS_DIR,
)

DEFAULT_STRATEGIES_FILE = os.path.join(os.path.dirname(__file__), "strategies.txt")


def parse_strategy_line(line):
    """
    Parse a single strategy line from a file or string.
    Supports formats:
      - 'Strategy Name: -m2 -r1+s ...'
      - 'Strategy Name | -m2 -r1+s ...'
      - '-m2 -r1+s ...'
    """
    line = line.strip()
    if not line or line.startswith("#"):
        return None

    if ":" in line and not line.startswith("-"):
        parts = line.split(":", 1)
        name = parts[0].strip()
        strat = parts[1].strip()
        return (name, strat)
    elif "|" in line and not line.startswith("-"):
        parts = line.split("|", 1)
        name = parts[0].strip()
        strat = parts[1].strip()
        return (name, strat)
    else:
        return (line, line)


def load_strategies_from_file(file_path):
    """Load strategies from a file or stdin (if file_path == '-')."""
    strategies = []
    if file_path == "-":
        lines = sys.stdin.read().splitlines()
    else:
        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"Strategies file not found: {file_path}")
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

    for idx, line in enumerate(lines, 1):
        item = parse_strategy_line(line)
        if item:
            name, strat = item
            if name == strat:
                name = f"Стратегия #{idx}"
            strategies.append((name, strat))
    return strategies


def generate_batch_markdown_report(ranked_results, targets_count, phase2_count):
    """Generate Markdown report for batch results."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    winner = ranked_results[0] if ranked_results else None

    lines = [
        "# Сводный отчёт пакетного тестирования стратегий ByeDPI",
        "",
        f"- **Дата и время:** `{now_str}`",
        f"- **Всего протестировано стратегий:** `{len(ranked_results)}`",
        f"- **Количество целевых хостов:** `{targets_count}`",
        f"- **Финалистов со стресс-тестом CDN:** `{phase2_count}`",
    ]

    if winner:
        lines.extend([
            f"- 🏆 **Победившая стратегия:** `{winner['strategy']}`",
            f"- **Результат лидера:** {winner['pass_pct']}% доступности, ср. хэндшейк {winner['avg_handshake_ms']} мс"
            + (f", стрим CDN **{winner['stream_bench']['avg_mbps']} Мбит/с**" if winner.get("stream_bench") and winner["stream_bench"].get("avg_mbps") else ""),
            "",
            "> [!TIP]",
            f"> Для применения лучшей стратегии скопируйте строку в файл `config`:",
            f"> ```bash",
            f"> {winner['strategy']}",
            f"> ```",
        ])

    lines.extend([
        "",
        "## Итоговый рейтинг стратегий",
        "",
        "| Место | Название / Описание | Успех (%) | Ср. TLS | TTFB | Скорость CDN | Симптомы ТСПУ | Стратегия |",
        "| :---: | :--- | :---: | :---: | :---: | :---: | :--- | :--- |",
    ])

    for rank, res in enumerate(ranked_results, 1):
        icon = "🥇" if rank == 1 else ("🥈" if rank == 2 else ("🥉" if rank == 3 else f"#{rank}"))
        name = res["name"]
        pct = f"{res['pass_pct']}%"
        hs = f"{res['avg_handshake_ms']} мс" if res["avg_handshake_ms"] > 0 else "—"
        ttfb = f"{res['avg_ttfb_ms']} мс" if res["avg_ttfb_ms"] > 0 else "—"

        speed = "—"
        if res.get("stream_bench") and res["stream_bench"].get("avg_mbps") is not None:
            speed = f"**{res['stream_bench']['avg_mbps']} Мбит/с**"

        s_counts = res.get("status_counts", {})
        issues = []
        if s_counts.get("BLACKHOLE"): issues.append(f"🔴 Drop {s_counts['BLACKHOLE']}")
        if s_counts.get("RST"): issues.append(f"🔴 RST {s_counts['RST']}")
        if s_counts.get("SSL_ERR"): issues.append(f"🔴 SSL {s_counts['SSL_ERR']}")
        if s_counts.get("SHAPED"): issues.append(f"🟡 Shaped {s_counts['SHAPED']}")
        if not issues:
            issues_str = "🟢 Чисто"
        else:
            issues_str = ", ".join(issues)

        strat_code = f"`{res['strategy']}`"
        lines.append(f"| {icon} | {name} | {pct} | {hs} | {ttfb} | {speed} | {issues_str} | {strat_code} |")

    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description="ByeDPI Batch Strategy Evaluator for macOS")
    parser.add_argument(
        "--file", "-f",
        type=str,
        help="Path to file containing strategies (one per line, with optional 'Name: ' prefix) or '-' for stdin",
    )
    parser.add_argument(
        "--configs", "-c",
        nargs="+",
        help="One or more strategy strings passed as CLI arguments",
    )
    parser.add_argument(
        "--targets", "-t",
        type=str,
        default=DEFAULT_TARGETS_FILE,
        help=f"Path to targets.txt (default: {DEFAULT_TARGETS_FILE})",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=4.0,
        help="Timeout per probe in seconds (default: 4.0)",
    )
    parser.add_argument(
        "--speed-test",
        action="store_true",
        help="Perform real YouTube CDN video stream benchmark on candidate finalists",
    )
    parser.add_argument(
        "--top-speed",
        type=int,
        default=3,
        help="Number of top strategies from Phase 1 to benchmark in Phase 2 with --speed-test (default: 3, 0 = all passing)",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=15,
        help="Target video chunk size in MB for stream benchmark (default: 15)",
    )
    parser.add_argument(
        "--bench-timeout",
        type=float,
        default=25.0,
        help="Timeout in seconds for stream benchmark (default: 25.0)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output structured JSON results to stdout",
    )
    parser.add_argument(
        "--output-json",
        type=str,
        help="Save structured JSON results to specified file path",
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Custom path for Markdown report (default: autotune/reports/batch_latest.md)",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Suppress intermediate per-host progress logs",
    )

    args = parser.parse_args()

    # Pre-flight check: ensure ciadpi exists
    locate_ciadpi()

    # Load targets
    targets = load_targets(args.targets)
    if not targets:
        print(f"❌ Error: No targets loaded from {args.targets}", file=sys.stderr)
        sys.exit(1)

    # Resolve strategies
    if args.file:
        strategies = load_strategies_from_file(args.file)
    elif args.configs:
        strategies = [(f"Конфиг #{idx}", c) for idx, c in enumerate(args.configs, 1)]
    elif os.path.isfile(DEFAULT_STRATEGIES_FILE):
        strategies = load_strategies_from_file(DEFAULT_STRATEGIES_FILE)
    else:
        print(f"❌ Ошибка: Файл со стратегиями не найден: {DEFAULT_STRATEGIES_FILE}", file=sys.stderr)
        print("👉 Укажите стратегии одним из способов:", file=sys.stderr)
        print(f"   1. Создайте файл {DEFAULT_STRATEGIES_FILE} со списком стратегий", file=sys.stderr)
        print("   2. Передайте файл через аргумент: --file <путь>", file=sys.stderr)
        print("   3. Передайте строки через аргумент: --configs \"<стратегия_1>\" \"<стратегия_2>\"", file=sys.stderr)
        sys.exit(1)

    if not strategies:
        print("❌ Ошибка: Список стратегий пуст.", file=sys.stderr)
        sys.exit(1)

    if not args.json:
        print("=" * 80)
        print(f"🚀 ByeDPI Batch Strategy Evaluator")
        print(f"📡 Целевых хостов для проверки: {len(targets)} (файл: {args.targets})")
        print(f"⚙️  Кандидатов для тестирования: {len(strategies)}")
        if args.speed_test:
            print(f"⚡ Стресс-тест CDN видеопотока: включён (топ-{args.top_speed} финалистов)")
        print("=" * 80)

    # Phase 1: Fast Screening
    phase1_results = []
    for idx, (name, strat) in enumerate(strategies, 1):
        if not args.json:
            print(f"\n[{idx}/{len(strategies)}] 🔍 Скрининг: {name}")
            print(f"    Параметры: {strat}")

        # Probing strategy
        eval_data = evaluate_strategy(
            strategy_str=strat,
            is_current=False,
            targets=targets,
            timeout=args.timeout,
            speed_test=False,
            verbose=(not args.quiet and not args.json),
        )

        eval_data["name"] = name
        phase1_results.append(eval_data)

        if not args.json and args.quiet:
            print(f"    -> Результат: {eval_data['passed']}/{eval_data['total']} ({eval_data['pass_pct']}%), Ср. TLS: {eval_data['avg_handshake_ms']} мс")

    # Sort Phase 1: highest pass_pct, lowest avg_handshake_ms, lowest avg_ttfb_ms
    phase1_results.sort(
        key=lambda x: (
            -x["pass_pct"],
            x["avg_handshake_ms"] if x["avg_handshake_ms"] > 0 else 9999,
            x["avg_ttfb_ms"] if x["avg_ttfb_ms"] > 0 else 9999,
        )
    )

    # Phase 2: Deep CDN Benchmark on Finalists
    phase2_count = 0
    if args.speed_test:
        passing = [r for r in phase1_results if r["pass_pct"] > 0]
        finalists = passing if args.top_speed == 0 else passing[:args.top_speed]
        phase2_count = len(finalists)

        if not args.json and finalists:
            print("\n" + "=" * 80)
            print(f"⚡ ФАЗА 2: Стресс-тест реального видеопотока CDN для топ-{len(finalists)} финалистов")
            print("=" * 80)

        for f_idx, res in enumerate(finalists, 1):
            if not args.json:
                print(f"\n[Финалист {f_idx}/{len(finalists)}] 🎬 {res['name']}")
                print(f"    Параметры: {res['strategy']}")

            deep_eval = evaluate_strategy(
                strategy_str=res["strategy"],
                is_current=False,
                targets=targets[:3],  # lightweight verify
                timeout=args.timeout,
                speed_test=True,
                chunk_size=args.chunk_size,
                bench_timeout=args.bench_timeout,
                verbose=(not args.quiet and not args.json),
            )
            res["stream_bench"] = deep_eval.get("stream_bench")

    # Final Ranking Sort
    # 1. pass_pct (desc)
    # 2. avg_mbps (desc, if tested)
    # 3. avg_handshake_ms (asc)
    # 4. avg_ttfb_ms (asc)
    def final_sort_key(x):
        bench = x.get("stream_bench") or {}
        speed = bench.get("avg_mbps") or 0.0
        hs = x["avg_handshake_ms"] if x["avg_handshake_ms"] > 0 else 9999
        ttfb = x["avg_ttfb_ms"] if x["avg_ttfb_ms"] > 0 else 9999
        return (-x["pass_pct"], -speed, hs, ttfb)

    phase1_results.sort(key=final_sort_key)

    # Save Markdown reports
    os.makedirs(REPORTS_DIR, exist_ok=True)
    report_md = generate_batch_markdown_report(phase1_results, len(targets), phase2_count)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    history_report = os.path.join(REPORTS_DIR, f"batch_{timestamp}.md")
    latest_report = args.output or os.path.join(REPORTS_DIR, "batch_latest.md")

    with open(latest_report, "w", encoding="utf-8") as f:
        f.write(report_md)
    with open(history_report, "w", encoding="utf-8") as f:
        f.write(report_md)

    if args.output_json:
        with open(args.output_json, "w", encoding="utf-8") as f:
            json.dump(phase1_results, f, ensure_ascii=False, indent=2)

    # Output JSON mode
    if args.json:
        print(json.dumps(phase1_results, ensure_ascii=False, indent=2))
        sys.exit(0)

    # Print summary ASCII table
    print("\n" + "=" * 95)
    print(f"{'ИТОГОВЫЙ РЕЙТИНГ СТРАТЕГИЙ BYEDPI':^95}")
    print("=" * 95)
    print(f"{'МЕСТО':<6} | {'УСПЕХ':<7} | {'TLS MS':<8} | {'TTFB MS':<8} | {'СТРИМ CDN':<13} | {'СТРАТЕГИЯ'}")
    print("-" * 95)

    for rank, res in enumerate(phase1_results, 1):
        icon = "🥇" if rank == 1 else ("🥈" if rank == 2 else ("🥉" if rank == 3 else f"#{rank}"))
        pct = f"{res['pass_pct']}%"
        hs = f"{res['avg_handshake_ms']} мс" if res["avg_handshake_ms"] > 0 else "—"
        ttfb = f"{res['avg_ttfb_ms']} мс" if res["avg_ttfb_ms"] > 0 else "—"

        bench = res.get("stream_bench") or {}
        speed = f"{bench['avg_mbps']} Мб/с" if bench.get("avg_mbps") is not None else "—"

        strat_short = res["strategy"]
        if len(strat_short) > 42:
            strat_short = strat_short[:39] + "..."

        print(f"{icon:<6} | {pct:>5} | {hs:>6} | {ttfb:>7} | {speed:>11} | {strat_short}")

    print("=" * 95)
    winner = phase1_results[0]
    print(f"🏆 Победитель: {winner['name']}")
    print(f"⚙️  Команда:    {winner['strategy']}")
    if winner.get("stream_bench") and winner["stream_bench"].get("avg_mbps"):
        print(f"⚡ Скорость:   {winner['stream_bench']['avg_mbps']} Мбит/с ({winner['stream_bench']['quality']})")
    print(f"📄 Отчёт:      {latest_report}")
    print("=" * 95)

    sys.exit(0 if winner["pass_pct"] == 100 else 2)


if __name__ == "__main__":
    main()
