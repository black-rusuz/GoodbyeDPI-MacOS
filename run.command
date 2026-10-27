#!/bin/zsh

DIR="$(cd "$(dirname "$0")" && pwd)"

# Поиск исполняемого файла: в папке build/ (при разработке) либо рядом со скриптом (внутри ByeDPI.app)
if [[ -f "$DIR/build/ciadpi" ]]; then
    BIN="$DIR/build/ciadpi"
elif [[ -f "$DIR/ciadpi" ]]; then
    BIN="$DIR/ciadpi"
else
    echo "\033[1;31mОшибка: исполняемый файл ciadpi не найден. Запустите ./install.sh для сборки.\033[0m"
    exit 1
fi

CONFIG_FILE="$DIR/config"
PORT="${BYEDPI_PORT:-1080}"
IP="127.0.0.1"
MAX_HISTORY=300
CIADPI_PID=""

# Чтение последней непустой строки конфигурации (текущей стратегии)
get_active_strategy() {
    if [[ -f "$CONFIG_FILE" ]]; then
        grep -v "^[[:space:]]*$" "$CONFIG_FILE" 2>/dev/null | tail -n 1
    fi
}

# Подсчёт количества сохранённых стратегий в истории
get_history_count() {
    if [[ -f "$CONFIG_FILE" ]]; then
        grep -v "^[[:space:]]*$" "$CONFIG_FILE" 2>/dev/null | wc -l | tr -d ' '
    else
        echo "0"
    fi
}

# Добавление стратегии в историю с ограничением объёма файла до MAX_HISTORY строк
save_strategy() {
    local strat="$1"
    echo "$strat" >> "$CONFIG_FILE"
    
    local total_lines=$(grep -v "^[[:space:]]*$" "$CONFIG_FILE" 2>/dev/null | wc -l | tr -d ' ')
    if (( total_lines > MAX_HISTORY )); then
        local tmp="$CONFIG_FILE.tmp"
        tail -n "$MAX_HISTORY" "$CONFIG_FILE" > "$tmp" && mv "$tmp" "$CONFIG_FILE"
    fi
}

# Вывод сохранённой истории стратегий по ключу --history или -h
if [[ "$1" == "--history" || "$1" == "-h" ]]; then
    echo "=== История стратегий ($CONFIG_FILE) ==="
    cat "$CONFIG_FILE"
    exit 0
fi

# Загрузка активной стратегии из файла конфигурации
ACTIVE_STRATEGY=$(get_active_strategy)
if [[ -z "$ACTIVE_STRATEGY" ]]; then
    echo "\033[1;31mОшибка: файл конфигурации $CONFIG_FILE пуст или не найден.\033[0m"
    echo "Добавьте в $CONFIG_FILE хотя бы одну рабочую стратегию."
    exit 1
fi

# Поддержка передачи новой стратегии прямо через позиционные аргументы CLI
if [[ $# -gt 0 ]]; then
    NEW_STRAT="$*"
    if [[ "$NEW_STRAT" != "$ACTIVE_STRATEGY" ]]; then
        save_strategy "$NEW_STRAT"
        ACTIVE_STRATEGY="$NEW_STRAT"
    fi
fi

STRATEGY_ARGS=(${(z)ACTIVE_STRATEGY})

# Определение активного сетевого подключения по умолчанию (Wi-Fi, Ethernet и др.)
IFACE=$(route -n get default 2>/dev/null | awk '/interface:/{print $2}')
if [[ -n "$IFACE" ]]; then
    SERVICE=$(networksetup -listnetworkserviceorder 2>/dev/null | grep -B 1 "Device: $IFACE" | head -n 1 | sed 's/^[^(]*([0-9]*) //')
fi
[[ -z "$SERVICE" ]] && SERVICE="Wi-Fi"

# Запуск и горячий перезапуск ciadpi с гарантированным освобождением порта
start_ciadpi() {
    # Завершаем дочерний процесс текущей сессии
    if [[ -n "$CIADPI_PID" ]]; then
        kill -9 "$CIADPI_PID" 2>/dev/null || true
        wait "$CIADPI_PID" 2>/dev/null || true
        CIADPI_PID=""
    fi

    # Очищаем порт от зависших экземпляров ciadpi
    pkill -9 -x ciadpi 2>/dev/null || true
    pkill -9 -f ciadpi 2>/dev/null || true
    for stale_pid in ${(f)$(lsof -ti tcp:$PORT -sTCP:LISTEN 2>/dev/null)}; do
        kill -9 "$stale_pid" 2>/dev/null || true
    done

    typeset -i retry=0
    while lsof -i tcp:$PORT -sTCP:LISTEN >/dev/null 2>&1 && (( retry++ < 10 )); do
        sleep 0.05
    done

    # Старт нового фонового процесса
    "$BIN" -i "$IP" -p "$PORT" "${STRATEGY_ARGS[@]}" >/dev/null 2>&1 &
    CIADPI_PID=$!
}

# Отрисовка лаконичного интерфейса со сводкой состояния
render_ui() {
    clear
    local count=$(get_history_count)
    echo "\033[1;32m========================================================\033[0m"
    echo "\033[1;32m                 ByeDPI macOS Proxy                     \033[0m"
    echo "\033[1;32m========================================================\033[0m"
    echo "  Статус:             \033[1;32m🟢 Активен (трафик защищён)\033[0m"
    echo "  SOCKS5-прокси:      \033[1;33m$IP:$PORT\033[0m"
    echo "  Сетевая служба:     \033[1;36m$SERVICE (системный прокси включён)\033[0m"
    echo "  История стратегий:  \033[1;37m$count / $MAX_HISTORY\033[0m"
    echo ""
    echo "  \033[1;37mТекущая стратегия:\033[0m"
    echo "  \033[1;36m$ACTIVE_STRATEGY\033[0m"
    echo ""
    echo "  \033[1;37mКонфигурация:\033[0m       $CONFIG_FILE"
    echo "  \033[1;37mЗавершение:\033[0m         закройте окно терминала или нажмите \033[1;31mCtrl+C\033[0m"
    echo "\033[1;32m========================================================\033[0m"
    if [[ -n "$1" ]]; then
        echo "  $1"
        echo "\033[1;32m========================================================\033[0m"
    fi
    echo "  \033[1;33mВведите новые параметры или листайте историю стрелками ↑ / ↓:\033[0m"
}

# Восстановление конфигурации сети macOS при завершении работы
cleanup() {
    echo ""
    echo "\033[1;33mОтключение системного прокси для $SERVICE...\033[0m"
    networksetup -setsocksfirewallproxystate "$SERVICE" off 2>/dev/null
    if [[ -n "$CIADPI_PID" ]]; then
        kill -9 "$CIADPI_PID" 2>/dev/null || true
    fi
    pkill -9 -x ciadpi 2>/dev/null || true
    echo "\033[1;32m[ByeDPI остановлен, исходные параметры сети восстановлены]\033[0m"
    exit 0
}

trap cleanup INT TERM HUP EXIT

# Активация системного SOCKS5-прокси
networksetup -setsocksfirewallproxy "$SERVICE" "$IP" "$PORT" 2>/dev/null
networksetup -setsocksfirewallproxystate "$SERVICE" on 2>/dev/null

# Немедленный запуск сервиса
start_ciadpi
render_ui

# Подключение файла конфигурации к механизму истории Zsh
fc -p "$CONFIG_FILE" "$MAX_HISTORY" "$MAX_HISTORY"

# Интерактивный цикл с навигацией по истории стрелками ↑ / ↓ через ZLE
while true; do
    USER_INPUT=""
    if vared -p "  > " -h USER_INPUT; then
        USER_INPUT=$(echo "$USER_INPUT" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
        if [[ -n "$USER_INPUT" && "$USER_INPUT" != "$ACTIVE_STRATEGY" ]]; then
            save_strategy "$USER_INPUT"
            print -s "$USER_INPUT"
            ACTIVE_STRATEGY="$USER_INPUT"
            STRATEGY_ARGS=(${(z)ACTIVE_STRATEGY})
            start_ciadpi
            render_ui "\033[1;32m✓ Новая стратегия сохранена и успешно применена!\033[0m"
        else
            render_ui
        fi
    else
        break
    fi
done
