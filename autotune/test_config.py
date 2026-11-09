#!/usr/bin/env python3
"""
ByeDPI Strategy Tester for macOS
Tests host availability and packet transmission characteristics against TSPU/DPI.
"""

import sys
import os
import argparse
import subprocess
import time
import socket
import shlex
import signal
from datetime import datetime

DEFAULT_TARGETS_FILE = os.path.join(os.path.dirname(__file__), "targets.txt")
REPORTS_DIR = os.path.join(os.path.dirname(__file__), "reports")
DEFAULT_PORT = 1081
ACTIVE_PORT = int(os.environ.get("BYEDPI_PORT", 1080))


def find_free_port(start_port=1081):
    """Find a free TCP port for isolated testing."""
    for port in range(start_port, start_port + 100):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("Cannot find an available TCP port for testing.")


def locate_ciadpi():
    """Locate the ciadpi executable binary."""
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    candidates = [
        os.path.join(root_dir, "build", "ciadpi"),
        os.path.join(root_dir, "ciadpi"),
        "/usr/local/bin/ciadpi",
    ]
    for c in candidates:
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    raise FileNotFoundError(
        "ciadpi binary not found in build/ciadpi. Run ./install.sh or make -C src first."
    )


def get_active_strategy():
    """Read the active strategy from the last non-empty line of the config file."""
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    config_path = os.path.join(root_dir, "config")
    if os.path.isfile(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip() and not l.strip().startswith("#")]
            if lines:
                return lines[-1]
    return None


def load_targets(targets_path):
    """Parse targets.txt: extracts domains, optional resolve IPs, and comments."""
    if not os.path.isfile(targets_path):
        raise FileNotFoundError(f"Targets file not found: {targets_path}")

    targets = []
    with open(targets_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            domain_part = parts[0]
            resolve_ip = parts[1] if len(parts) > 1 else None

            # Handle format domain:ip if present
            if not resolve_ip and ":" in domain_part and not domain_part.startswith("http"):
                d, ip = domain_part.split(":", 1)
                # Verify if ip looks like an IPv4 address
                if ip.replace(".", "").isdigit():
                    domain_part = d
                    resolve_ip = ip

            targets.append({"domain": domain_part, "resolve_ip": resolve_ip})
    return targets


def build_probe_url(domain):
    """Determine the optimal URL and path to probe for a given domain."""
    if domain.startswith("http://") or domain.startswith("https://"):
        return domain
    # Use /generate_204 for lightweight endpoints
    if any(k in domain for k in ("googlevideo.com", "ytimg.com", "ggpht.com", "googleapis.com")):
        return f"https://{domain}/generate_204"
    return f"https://{domain}"


def probe_host(target, proxy_port, timeout=5.0):
    """
    Probe a host through the SOCKS5h proxy using curl.
    Collects granular TLS handshake, TTFB, and packet transmission metrics.
    """
    domain = target["domain"]
    resolve_ip = target.get("resolve_ip")
    url = build_probe_url(domain)

    # curl write-out format
    fmt = (
        "%{http_code}|"
        "%{time_connect}|"
        "%{time_appconnect}|"
        "%{time_starttransfer}|"
        "%{time_total}|"
        "%{speed_download}|"
        "%{size_download}|"
        "%{exitcode}|"
        "%{errormsg}"
    )

    cmd = [
        "curl",
        "-s",
        "-o", "/dev/null",
        "-w", fmt,
        "--max-time", str(timeout),
        "-x", f"socks5h://127.0.0.1:{proxy_port}",
    ]

    if resolve_ip:
        cmd.extend(["--resolve", f"{domain}:443:{resolve_ip}"])

    cmd.append(url)

    start_time = time.time()
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout + 2)
        elapsed = time.time() - start_time
        out = res.stdout.strip()
    except subprocess.TimeoutExpired:
        return {
            "domain": domain,
            "resolve_ip": resolve_ip,
            "url": url,
            "http_code": "000",
            "connect_ms": 0,
            "handshake_ms": 0,
            "ttfb_ms": 0,
            "total_ms": int((timeout + 2) * 1000),
            "speed_kbps": 0,
            "exit_code": 28,
            "error_msg": "Subprocess timeout",
            "status": "🔴 BLACKHOLE",
            "diagnosis": "Дроп ТСПУ: сессия зависла без ответа",
        }

    fields = out.split("|")
    if len(fields) < 8:
        return {
            "domain": domain,
            "resolve_ip": resolve_ip,
            "url": url,
            "http_code": "000",
            "connect_ms": 0,
            "handshake_ms": 0,
            "ttfb_ms": 0,
            "total_ms": int(elapsed * 1000),
            "speed_kbps": 0,
            "exit_code": res.returncode or 99,
            "error_msg": res.stderr.strip() or "Unknown error",
            "status": "🔴 FAIL",
            "diagnosis": "Не удалось распарсить ответ curl",
        }

    http_code = fields[0]
    try:
        connect_ms = int(float(fields[1]) * 1000)
        appconnect_s = float(fields[2])
        handshake_ms = int((appconnect_s - float(fields[1])) * 1000) if appconnect_s > 0 else 0
        ttfb_ms = int(float(fields[3]) * 1000)
        total_ms = int(float(fields[4]) * 1000)
        speed_kbps = float(fields[5]) / 1024.0
        size_bytes = int(fields[6])
        exit_code = int(fields[7])
        error_msg = fields[8] if len(fields) > 8 else ""
    except (ValueError, IndexError):
        connect_ms, handshake_ms, ttfb_ms, total_ms = 0, 0, 0, int(elapsed * 1000)
        speed_kbps, size_bytes, exit_code, error_msg = 0, 0, 99, "Metric parse error"

    # Packet behavior diagnosis
    if exit_code == 0 and http_code in ("200", "204", "301", "302", "303", "307", "308"):
        if speed_kbps > 0 and speed_kbps < 200 and size_bytes > 50000:
            status = "🟡 SHAPED"
            diagnosis = "Шейпинг скорости: возможен коллапс TCP CWND из-за потерь флагов -d"
        else:
            status = "🟢 OK"
            diagnosis = f"Чистый хэндшейк (HTTP {http_code}), TLS завершён"
    elif exit_code == 28:
        if handshake_ms == 0:
            status = "🔴 BLACKHOLE"
            diagnosis = "Дроп ТСПУ: ClientHello отправлен, ответа от сервера нет (0 байт)"
        else:
            status = "🔴 TIMEOUT"
            diagnosis = "Таймаут передачи данных после завершения рукопожатия"
    elif exit_code in (35, 56):
        if "reset" in error_msg.lower() or exit_code == 56:
            status = "🔴 RST"
            diagnosis = "TCP RST: принудительный разрыв соединения фильтром ТСПУ"
        else:
            status = "🔴 SSL_ERR"
            diagnosis = "Ошибка TLS: отказ рукопожатия (возможно, фейк долетел до сервера)"
    elif exit_code == 7:
        status = "🔴 REFUSED"
        diagnosis = "Ошибка подключения к локальному прокси ciadpi"
    else:
        status = "🔴 FAIL"
        diagnosis = f"Ошибка curl (код {exit_code}): {error_msg or 'Unknown'}"

    return {
        "domain": domain,
        "resolve_ip": resolve_ip,
        "url": url,
        "http_code": http_code,
        "connect_ms": connect_ms,
        "handshake_ms": handshake_ms,
        "ttfb_ms": ttfb_ms,
        "total_ms": total_ms,
        "speed_kbps": speed_kbps,
        "exit_code": exit_code,
        "error_msg": error_msg,
        "status": status,
        "diagnosis": diagnosis,
    }


class TargetReached(Exception):
    """Raised when target download volume has been reached in benchmark."""
    pass


def benchmark_real_stream(proxy_port, target_mb=15, timeout=25.0):
    """
    Download a real chunk of YouTube video stream through the ByeDPI SOCKS5 proxy
    to test real-world throughput, buffer stability, and TCP CWND behavior.
    """
    import tempfile
    import shutil

    test_video_url = "https://www.youtube.com/watch?v=aqz-KE-bpKQ"
    target_bytes = int(target_mb * 1024 * 1024)

    stats = {
        "downloaded_bytes": 0,
        "speeds": [],
        "start_time": None,
        "end_time": None,
        "stalls": 0,
        "error": None,
    }

    def progress_hook(d):
        now = time.time()
        if d.get("status") == "downloading":
            if stats["start_time"] is None:
                stats["start_time"] = now

            dl = d.get("downloaded_bytes", 0)
            stats["downloaded_bytes"] = dl

            speed = d.get("speed")
            if speed is not None:
                stats["speeds"].append(speed)
                if speed < 100 * 1024 and dl > 500 * 1024:
                    stats["stalls"] += 1

            if dl >= target_bytes:
                stats["end_time"] = now
                raise TargetReached()

    temp_dir = tempfile.mkdtemp(prefix="byedpi_bench_")
    outtmpl = os.path.join(temp_dir, "bench_stream.%(ext)s")

    ydl_opts = {
        "proxy": f"socks5://127.0.0.1:{proxy_port}",
        "format": "135/244/243/396/bestvideo/best",
        "outtmpl": outtmpl,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": timeout,
        "progress_hooks": [progress_hook],
    }

    try:
        try:
            import yt_dlp
        except ImportError:
            return {
                "success": False,
                "error": "Модуль yt-dlp не установлен",
                "downloaded_mb": 0,
                "avg_mbps": 0,
            }

        start_probe = time.time()
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                ydl.download([test_video_url])
            except TargetReached:
                pass
            except Exception as e:
                stats["error"] = str(e)

        end_probe = stats["end_time"] or time.time()
        transfer_duration = end_probe - (stats["start_time"] or start_probe)
        if transfer_duration <= 0:
            transfer_duration = 0.001

        mb_down = stats["downloaded_bytes"] / (1024 * 1024)
        avg_mbps = (stats["downloaded_bytes"] * 8) / (transfer_duration * 1024 * 1024)

        peak_mbps = (max(stats["speeds"]) * 8 / (1024 * 1024)) if stats["speeds"] else avg_mbps
        min_mbps = (min(stats["speeds"]) * 8 / (1024 * 1024)) if stats["speeds"] else avg_mbps

        success = mb_down >= (target_mb * 0.7) and avg_mbps > 0.5

        if avg_mbps >= 50.0:
            quality = "🟢 Идеально для 4K 60fps Ultra HD (без буферизации)"
        elif avg_mbps >= 20.0:
            quality = "🟢 Отлично для 1440p / 1080p60 Full HD"
        elif avg_mbps >= 8.0:
            quality = "🟡 Достаточно для 1080p (возможна задержка старта)"
        elif avg_mbps >= 3.0:
            quality = "🟡 Базовый стриминг 720p (риск просадок при высоком битрейте)"
        else:
            quality = "🔴 Буферизация / Шейпинг (коллапс TCP CWND или потеря пакетов)"

        return {
            "success": success,
            "target_mb": target_mb,
            "downloaded_mb": round(mb_down, 2),
            "duration_sec": round(transfer_duration, 2),
            "avg_mbps": round(avg_mbps, 2),
            "peak_mbps": round(peak_mbps, 2),
            "min_mbps": round(min_mbps, 2),
            "stalls": stats["stalls"],
            "quality": quality,
            "error": stats["error"],
        }
    finally:
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass


def wait_for_port(port, timeout=3.0):
    """Wait until the ciadpi proxy is actively listening on localhost:port."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                return True
        except OSError:
            time.sleep(0.05)
    return False


def generate_markdown_report(strategy_str, port, is_isolated, results, stream_bench=None):
    """Generate structured markdown report."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total_count = len(results)
    passed_count = sum(1 for r in results if "OK" in r["status"])
    pass_pct = round((passed_count / total_count * 100), 1) if total_count > 0 else 0

    valid_handshakes = [r["handshake_ms"] for r in results if r["handshake_ms"] > 0]
    avg_handshake = round(sum(valid_handshakes) / len(valid_handshakes)) if valid_handshakes else 0

    verdict_emoji = "🟢" if pass_pct == 100 else ("🟡" if pass_pct >= 70 else "🔴")
    port_label = f"{port} (Изолированный тестовый экземпляр)" if is_isolated else f"{port} (Активный рабочий прокси)"

    speed_info = ""
    if stream_bench and stream_bench.get("avg_mbps") is not None:
        speed_info = f" | Реальный стрим: **{stream_bench['avg_mbps']} Мбит/с**"

    lines = [
        "# Отчёт тестирования стратегии ByeDPI",
        "",
        f"- **Дата и время:** `{now_str}`",
        f"- **Стратегия:** `{strategy_str or '(без аргументов / прямое проксирование)'}`",
        f"- **Порт:** `{port_label}`",
        f"- **Результат:** {verdict_emoji} **{passed_count}/{total_count} доступно ({pass_pct}%)**"
        + (f" | Ср. TLS хэндшейк: **{avg_handshake} мс**" if avg_handshake else "")
        + speed_info,
        "",
        "## Сводная таблица доступности хостов",
        "",
        "| Хост / Назначение | Статус | HTTP | TLS Handshake | Задержка (TTFB) | Скорость | Диагностика пакетов |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :--- |",
    ]

    for r in results:
        host_display = f"`{r['domain']}`"
        if r.get("resolve_ip"):
            host_display += f"<br/>*(IP: {r['resolve_ip']})*"

        http_val = r["http_code"] if r["http_code"] != "000" else "—"
        hs_val = f"{r['handshake_ms']} мс" if r["handshake_ms"] > 0 else "—"
        ttfb_val = f"{r['ttfb_ms']} мс" if r["ttfb_ms"] > 0 else "—"
        speed_val = f"{round(r['speed_kbps'], 1)} КБ/с" if r["speed_kbps"] > 0 else "—"

        lines.append(
            f"| {host_display} | {r['status']} | {http_val} | {hs_val} | {ttfb_val} | {speed_val} | {r['diagnosis']} |"
        )

    if stream_bench and stream_bench.get("downloaded_mb", 0) > 0:
        lines.extend([
            "",
            "## Реальный стресс-тест видеопотока (YouTube CDN Stream Benchmark)",
            "",
            f"- **Объём переданных видеоданных:** `{stream_bench['downloaded_mb']} МБ` (из запрошенных {stream_bench['target_mb']} МБ)",
            f"- **Длительность загрузки:** `{stream_bench['duration_sec']} сек`",
            f"- **Средняя пропускная способность:** **{stream_bench['avg_mbps']} Мбит/с**",
            f"- **Пиковая скорость CDN:** `{stream_bench['peak_mbps']} Мбит/с` (минимум: `{stream_bench['min_mbps']} Мбит/с`)",
            f"- **Оценка качества:** {stream_bench['quality']}",
        ])
        if stream_bench.get("error"):
            lines.append(f"- ⚠️ **Предупреждение при передаче:** `{stream_bench['error']}`")

    lines.extend([
        "",
        "## Особенности прохождения пакетов (Packet Analysis)",
        "",
    ])

    # Dynamic analysis notes based on results
    blackholes = [r for r in results if "BLACKHOLE" in r["status"]]
    rsts = [r for r in results if "RST" in r["status"]]
    shaped = [r for r in results if "SHAPED" in r["status"]]
    ssl_errs = [r for r in results if "SSL_ERR" in r["status"]]

    if not blackholes and not rsts and not ssl_errs and not shaped and pass_pct == 100:
        lines.append(
            "- ✅ **Полная победа над ТСПУ**: Все целевые хосты (включая локальные GGC-ноды провайдера) завершили TLS Handshake без задержек."
        )
        lines.append(
            "- ✅ **Целостность потока**: Сетевой стек не фиксирует потерь или дропов. Скорость загрузки не ограничивается искусственным сжатием TCP CWND."
        )
    else:
        if blackholes:
            hosts = ", ".join(f"`{b['domain']}`" for b in blackholes)
            lines.append(
                f"- ⚠️ **Дроп ClientHello (Черная дыра ТСПУ)** на: {hosts}. "
                "Реассемблер ТСПУ успешно восстановил SNI из пакетов и заблокировал ответ. "
                "Рекомендация: применить `-m 2` (подмена TLS Minor Version), `-r 1+s` (TLS Record Split) или сместить сплит на 1-й байт домена (`-d1+s`)."
            )
        if rsts:
            hosts = ", ".join(f"`{b['domain']}`" for b in rsts)
            lines.append(
                f"- ⚠️ **Инъекция TCP RST** на: {hosts}. ТСПУ активно сбрасывает соединение при обнаружении сигнатур. "
                "Рекомендация: добавить OOB-модификатор (`-o 1+s`) или разбить SNI на большее число мелких чанков (`-s3+s -s6+s...`)."
            )
        if ssl_errs:
            hosts = ", ".join(f"`{b['domain']}`" for b in ssl_errs)
            lines.append(
                f"- ⚠️ **Отказ TLS Handshake** на: {hosts}. Если используется фейковый ClientHello (`-f` / `-l`), "
                "его TTL (`-t`) слишком велик, и испорченный пакет долетел до сервера Google. "
                "Рекомендация: уменьшить TTL фейка (`-t 2` или `-t 3`)."
            )
        if shaped:
            lines.append(
                "- ⚠️ **Шейпинг скорости**: Обнаружено аномальное замедление. "
                "Вероятная причина: множественные флаги `-d` (disorder) симулируют сильную потерю пакетов (TTL=1), "
                "что приводит к аварийному схлопыванию окна TCP CWND в алгоритмах CUBIC/BBR. "
                "Рекомендация: оставить ровно один `-d1+s`, заменив остальные на чистый `-s` (split)."
            )

    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description="ByeDPI Strategy Tester for macOS")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--current",
        action="store_true",
        help=f"Test currently active proxy on 127.0.0.1:{ACTIVE_PORT}",
    )
    group.add_argument(
        "--config",
        type=str,
        help="ByeDPI strategy flags to test on an isolated temporary port (e.g. '-m2 -d1 -d1+s -r1+s')",
    )

    parser.add_argument(
        "--targets",
        type=str,
        default=DEFAULT_TARGETS_FILE,
        help=f"Path to targets.txt (default: {DEFAULT_TARGETS_FILE})",
    )
    parser.add_argument(
        "--port",
        type=int,
        help="Custom port for testing (default: 1081 for isolated test, 1080 for --current)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help="Timeout per probe in seconds (default: 5.0)",
    )
    parser.add_argument(
        "--speed-test",
        action="store_true",
        help="Perform real YouTube CDN video stream benchmark",
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
        default=30.0,
        help="Timeout in seconds for stream benchmark (default: 30.0)",
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Optional custom report output file path",
    )

    args = parser.parse_args()

    # Load targets
    targets = load_targets(args.targets)
    if not targets:
        print("Error: No targets found in targets file.")
        sys.exit(1)

    ciadpi_proc = None
    is_isolated = False
    test_port = args.port

    if args.current:
        test_port = test_port or ACTIVE_PORT
        strategy_str = get_active_strategy() or "(Активный рабочий прокси)"
        print(f"🔍 Testing active proxy on 127.0.0.1:{test_port}...")
        print(f"⚙️  Active Strategy: {strategy_str}")
    else:
        is_isolated = True
        test_port = test_port or find_free_port(DEFAULT_PORT)
        strategy_str = args.config
        ciadpi_bin = locate_ciadpi()
        print(f"🚀 Spawning isolated ciadpi on 127.0.0.1:{test_port}...")
        print(f"⚙️  Strategy: {strategy_str}")

        cmd_args = [ciadpi_bin, "-i", "127.0.0.1", "-p", str(test_port)] + shlex.split(strategy_str)
        ciadpi_proc = subprocess.Popen(
            cmd_args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            preexec_fn=os.setsid,
        )

        if not wait_for_port(test_port, timeout=3.0):
            err_output = ""
            if ciadpi_proc.poll() is not None:
                _, err_output = ciadpi_proc.communicate()
            print(f"❌ Error: ciadpi failed to bind to 127.0.0.1:{test_port}.")
            if err_output.strip():
                print(f"   Причина ошибки ciadpi: {err_output.strip()}")
            if ciadpi_proc:
                try:
                    os.killpg(os.getpgid(ciadpi_proc.pid), signal.SIGKILL)
                except Exception:
                    pass
            sys.exit(1)

    results = []
    stream_bench = None
    try:
        print(f"📡 Probing {len(targets)} targets (timeout: {args.timeout}s)...")
        for idx, t in enumerate(targets, 1):
            lbl = t["domain"] + (f" ({t['resolve_ip']})" if t.get("resolve_ip") else "")
            print(f"  [{idx}/{len(targets)}] {lbl:45} ... ", end="", flush=True)
            res = probe_host(t, test_port, timeout=args.timeout)
            results.append(res)
            print(f"{res['status']:12} (TLS: {res['handshake_ms']}ms, HTTP {res['http_code']})")

        if args.speed_test:
            print(f"⚡ Running REAL YouTube video stream benchmark ({args.chunk_size} MB)...")
            stream_bench = benchmark_real_stream(test_port, target_mb=args.chunk_size, timeout=args.bench_timeout)
            if stream_bench["downloaded_mb"] > 0:
                print(f"  ✅ Downloaded: {stream_bench['downloaded_mb']} MB in {stream_bench['duration_sec']}s")
                print(f"  ⚡ Throughput: {stream_bench['avg_mbps']} Mbps (Peak: {stream_bench['peak_mbps']} Mbps)")
                print(f"  🎬 Verdict: {stream_bench['quality']}")
            else:
                err_msg = stream_bench.get('error') or 'Could not download media stream'
                print(f"  ❌ Benchmark failed: {err_msg}")

    finally:
        if ciadpi_proc:
            print("🛑 Shutting down isolated test instance...")
            try:
                os.killpg(os.getpgid(ciadpi_proc.pid), signal.SIGTERM)
                ciadpi_proc.wait(timeout=1.0)
            except Exception:
                try:
                    os.killpg(os.getpgid(ciadpi_proc.pid), signal.SIGKILL)
                except Exception:
                    pass

    # Ensure reports directory exists
    os.makedirs(REPORTS_DIR, exist_ok=True)

    report_md = generate_markdown_report(strategy_str, test_port, is_isolated, results, stream_bench)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    history_report_path = os.path.join(REPORTS_DIR, f"test_{timestamp}.md")
    latest_report_path = args.output or os.path.join(REPORTS_DIR, "latest.md")

    with open(latest_report_path, "w", encoding="utf-8") as f:
        f.write(report_md)

    with open(history_report_path, "w", encoding="utf-8") as f:
        f.write(report_md)

    print("\n" + "=" * 60)
    print(f"📄 Report saved to: {latest_report_path}")
    print(f"📄 History report: {history_report_path}")
    print("=" * 60)

    # Print summary
    passed = sum(1 for r in results if "OK" in r["status"])
    total = len(results)
    print(f"Final Score: {passed}/{total} hosts passed ({round(passed/total*100, 1)}%)")

    # Exit code: 0 if all critical passed, 1 if any failure
    sys.exit(0 if passed == total else 2)


if __name__ == "__main__":
    main()
