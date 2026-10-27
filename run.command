#!/bin/zsh

DIR="$(cd "$(dirname "$0")" && pwd)"

# Поиск бинарника: в build/ (локальный репозиторий) либо в текущей папке (внутри ByeDPI.app)
if [[ -f "$DIR/build/ciadpi" ]]; then
    BIN="$DIR/build/ciadpi"
elif [[ -f "$DIR/ciadpi" ]]; then
    BIN="$DIR/ciadpi"
else
    echo "\033[1;31mОшибка: бинарник ciadpi не найден! Запустите ./install.sh для сборки.\033[0m"
    exit 1
fi

CONFIG_FILE="$DIR/config"
PORT="${BYEDPI_PORT:-1080}"
IP="127.0.0.1"
CIADPI_PID=""

# Функция получения последней активной стратегии из файла (пропуская комментарии и пустые строки)
get_active_strategy() {
    if [[ -f "$CONFIG_FILE" ]]; then
        grep -v "^[[:space:]]*#" "$CONFIG_FILE" 2>/dev/null | grep -v "^[[:space:]]*$" | tail -n 1
    fi
}

# Функция подсчета записей в истории
get_history_count() {
    if [[ -f "$CONFIG_FILE" ]]; then
        grep -v "^[[:space:]]*#" "$CONFIG_FILE" 2>/dev/null | grep -v "^[[:space:]]*$" | wc -l | tr -d ' '
    else
        echo "0"
    fi
}

# Добавление новой стратегии в историю с временной меткой
append_strategy() {
    local strat="$1"
    local timestamp=$(date "+%Y-%m-%d %H:%M:%S")
    echo "\n# $timestamp" >> "$CONFIG_FILE"
    echo "$strat" >> "$CONFIG_FILE"
}

# Если передана команда просмотра истории
if [[ "$1" == "--history" || "$1" == "-h" ]]; then
    echo "=== История стратегий ($CONFIG_FILE) ==="
    cat "$CONFIG_FILE"
    exit 0
fi

# Автоматически определяем текущую активную сетевую службу (Wi-Fi, Ethernet и т.д.)
IFACE=$(route -n get default 2>/dev/null | awk '/interface:/{print $2}')
if [[ -n "$IFACE" ]]; then
    SERVICE=$(networksetup -listnetworkserviceorder 2>/dev/null | grep -B 1 "Device: $IFACE" | head -n 1 | sed 's/^[^(]*([0-9]*) //')
fi
[[ -z "$SERVICE" ]] && SERVICE="Wi-Fi"

# Функция запуска / перезапуска ciadpi
start_ciadpi() {
    # 1. Завершаем предыдущий запущенный экземпляр
    if [[ -n "$CIADPI_PID" ]]; then
        kill -9 "$CIADPI_PID" 2>/dev/null || true
        wait "$CIADPI_PID" 2>/dev/null || true
        CIADPI_PID=""
    fi

    # 2. Принудительно освобождаем порт от любых зависших ciadpi
    pkill -9 -x ciadpi 2>/dev/null || true
    for stale_pid in ${(f)$(lsof -ti tcp:$PORT -sTCP:LISTEN 2>/dev/null)}; do
        kill -9 "$stale_pid" 2>/dev/null || true
    done

    typeset -i retry=0
    while lsof -i tcp:$PORT -sTCP:LISTEN >/dev/null 2>&1 && (( retry++ < 10 )); do
        sleep 0.05
    done

    # 3. Запуск нового экземпляра в фоне
    "$BIN" -i "$IP" -p "$PORT" "${STRATEGY_ARGS[@]}" >/dev/null 2>&1 &
    CIADPI_PID=$!
}

# Функция отображения красивого интерфейса-саммари
render_ui() {
    clear
    local count=$(get_history_count)
    echo "\033[1;32m========================================================\033[0m"
    echo "\033[1;32m           🚀 ByeDPI Anti-Censorship Proxy              \033[0m"
    echo "\033[1;32m========================================================\033[0m"
    echo "  Статус:           \033[1;32m🟢 РАБОТАЕТ И ЗАЩИЩАЕТ ТРАФИК\033[0m"
    echo "  SOCKS5 адрес:     \033[1;33m$IP:$PORT\033[0m"
    echo "  Сетевая служба:   \033[1;36m$SERVICE (системный прокси активен)\033[0m"
    echo "  Записей в истории:\033[1;37m $count\033[0m"
    echo ""
    echo "  \033[1;37mАктивная стратегия:\033[0m"
    echo "  \033[1;36m$ACTIVE_STRATEGY\033[0m"
    echo ""
    echo "  \033[1;37mФайл конфига:\033[0m     $CONFIG_FILE"
    echo "  \033[1;37mДля выключения:\033[0m   закройте окно терминала или нажмите \033[1;31mCtrl+C\033[0m"
    echo "\033[1;32m========================================================\033[0m"
    if [[ -n "$1" ]]; then
        echo "  $1"
        echo "\033[1;32m========================================================\033[0m"
    fi
    echo "  \033[1;33mВставьте новую стратегию и нажмите Enter для смены:\033[0m"
    printf "> "
}

# Функция корректного выхода и восстановления сети
cleanup() {
    echo ""
    echo "\033[1;33mВыключение системного прокси для $SERVICE...\033[0m"
    networksetup -setsocksfirewallproxystate "$SERVICE" off 2>/dev/null
    if [[ -n "$CIADPI_PID" ]]; then
        kill -9 "$CIADPI_PID" 2>/dev/null || true
    fi
    pkill -9 -x ciadpi 2>/dev/null || true
    echo "\033[1;31m[ByeDPI остановлен, настройки сети восстановлены]\033[0m"
    exit 0
}

trap cleanup INT TERM HUP EXIT

# Если аргументы переданы через командную строку (например: run.command -m 2 ...)
if [[ $# -gt 0 ]]; then
    NEW_STRAT="$*"
    append_strategy "$NEW_STRAT"
    ACTIVE_STRATEGY="$NEW_STRAT"
else
    ACTIVE_STRATEGY=$(get_active_strategy)
    if [[ -z "$ACTIVE_STRATEGY" ]]; then
        ACTIVE_STRATEGY="-m 2 -d1 -d1+s -r1+s -s3+s -s6+s -s9+s -s12+s -s15+s -s20+s -s25+s -s30+s -s35+s -a1"
        append_strategy "$ACTIVE_STRATEGY"
    fi
fi

STRATEGY_ARGS=(${(z)ACTIVE_STRATEGY})

# Включаем системный прокси macOS
networksetup -setsocksfirewallproxy "$SERVICE" "$IP" "$PORT" 2>/dev/null
networksetup -setsocksfirewallproxystate "$SERVICE" on 2>/dev/null

# Мгновенный запуск прокси без задержек
start_ciadpi
render_ui

# Интерактивный цикл: слушает ввод новой стратегии в течение всей работы программы
while true; do
    if read -r USER_INPUT; then
        USER_INPUT=$(echo "$USER_INPUT" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
        if [[ -n "$USER_INPUT" ]]; then
            append_strategy "$USER_INPUT"
            ACTIVE_STRATEGY="$USER_INPUT"
            STRATEGY_ARGS=(${(z)ACTIVE_STRATEGY})
            start_ciadpi
            render_ui "\033[1;32m✓ Стратегия успешно обновлена на лету и применена!\033[0m"
        else
            render_ui
        fi
    else
        break
    fi
done
