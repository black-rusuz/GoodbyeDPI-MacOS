#!/usr/bin/env bash
set -e

# ==============================================================================
# ByeDPI Linux Autotune Runner
# Автономный раннер для пакетного тестирования стратегий в окружении Linux (Docker).
# Автоматически:
#   1. Проверяет доступность Docker.
#   2. Собирает Docker-образ byedpi-tester (если он ещё не собран).
#   3. Компилирует Linux-бинарник build/ciadpi_linux (если он отсутствует).
#   4. Направляет трафик к тестовым IP через физический Wi-Fi шлюз в обход WireGuard.
#   5. Запускает test_batch.py внутри контейнера с передачей любых аргументов CLI.
#   6. Гарантированно очищает маршруты при выходе.
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Проверка прав администратора для управления маршрутизацией macOS
if [ "$EUID" -ne 0 ]; then
    echo "🔐 Для управления точечной маршрутизацией требуются права администратора (sudo)."
    exec sudo "$0" "$@"
fi

# 1. Проверка доступности Docker
if ! docker info >/dev/null 2>&1; then
    echo "❌ Ошибка: Docker daemon не запущен или недоступен."
    echo "👉 Пожалуйста, запустите приложение Docker Desktop и повторите вызов скрипта."
    exit 1
fi

# 2. Автоматическая сборка Docker-образа при его отсутствии
if ! docker image inspect byedpi-tester >/dev/null 2>&1; then
    echo "📦 Docker-образ 'byedpi-tester' не найден. Автоматическая сборка с нуля..."
    docker build -t byedpi-tester -f "$SCRIPT_DIR/Dockerfile" "$ROOT_DIR"
    echo "✅ Docker-образ 'byedpi-tester' успешно создан."
fi

# 3. Автоматическая компиляция Linux-бинарника ciadpi_linux при отсутствии
if [ ! -f "$ROOT_DIR/build/ciadpi_linux" ]; then
    echo "🔨 Linux-бинарник build/ciadpi_linux не найден. Компиляция в контейнере..."
    docker run --rm -v "$ROOT_DIR":/workspace byedpi-tester sh -c \
        "make -C /workspace/src clean && make -C /workspace/src && mkdir -p /workspace/build && cp /workspace/src/ciadpi /workspace/build/ciadpi_linux && chmod +x /workspace/build/ciadpi_linux"
    echo "✅ Linux-бинарник build/ciadpi_linux успешно скомпилирован."
fi

# 4. Проверка наличия strategies.txt при отсутствии аргументов CLI
STRATEGIES_FILE="$SCRIPT_DIR/strategies.txt"
if [ ! -f "$STRATEGIES_FILE" ] && [ $# -eq 0 ]; then
    echo "❌ Ошибка: Файл стратегий '$STRATEGIES_FILE' не найден."
    echo "👉 Создайте файл $STRATEGIES_FILE или передайте аргументы, например: $0 --configs \"<стратегия>\""
    exit 1
fi

# 5. Динамическое извлечение IP-адресов из targets.txt
TARGETS_FILE="$SCRIPT_DIR/targets.txt"
TARGET_IPS=()
if [ -f "$TARGETS_FILE" ]; then
    while read -r line; do
        [[ "$line" =~ ^#.* ]] && continue
        for word in $line; do
            if [[ "$word" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
                TARGET_IPS+=("$word")
            fi
        done
    done < "$TARGETS_FILE"
fi

# Удаление дубликатов IP
if [ ${#TARGET_IPS[@]} -gt 0 ]; then
    TARGET_IPS=($(printf "%s\n" "${TARGET_IPS[@]}" | sort -u))
fi

# Определение физического шлюза Wi-Fi (en0)
GATEWAY=$(ipconfig getoption en0 router 2>/dev/null || echo "192.168.3.1")

echo "================================================================================"
echo " 🚀 ByeDPI Linux Autotune Runner (macOS Host -> Docker -> Physical Wi-Fi)"
echo " Физический шлюз (en0): $GATEWAY"
echo " Защищаемых IP-узлов:    ${#TARGET_IPS[@]}"
echo "================================================================================"

# Функция гарантированной очистки временных маршрутов
cleanup() {
    echo ""
    echo "🧹 Завершение работы: удаление временных маршрутов..."
    for ip in "${TARGET_IPS[@]}"; do
        route -q delete -host "$ip" 2>/dev/null || true
    done
    echo "✅ Все временные маршруты удалены. Сеть в исходном состоянии."
}

trap cleanup EXIT INT TERM

# Добавление точечных маршрутов к шлюзу Wi-Fi в обход VPN
echo "📍 Добавление временных точечных маршрутов к шлюзу $GATEWAY (в обход WireGuard)..."
for ip in "${TARGET_IPS[@]}"; do
    route -q delete -host "$ip" 2>/dev/null || true
    route -q add -host "$ip" "$GATEWAY" >/dev/null 2>&1
    echo "   -> $ip направлен через $GATEWAY"
done

echo ""
echo "🐳 Запуск пакетного тестирования стратегий через test_batch.py в Docker..."
echo "--------------------------------------------------------------------------------"

# Запуск единого test_batch.py в контейнере
docker run --rm --privileged \
    -v "$ROOT_DIR":/workspace \
    byedpi-tester \
    python3 -u /workspace/autotune/test_batch.py "$@"

echo "--------------------------------------------------------------------------------"
echo "🏁 Тестирование завершено."
