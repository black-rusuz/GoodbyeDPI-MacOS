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
PORT="1080"
IP="127.0.0.1"

# Чтение аргументов стратегии из файла config
if [[ -f "$CONFIG_FILE" ]]; then
    STRATEGY_ARGS=(${(z)$(tr -d "\r\n" < "$CONFIG_FILE")})
    STRATEGY_DISPLAY=$(tr -d "\r\n" < "$CONFIG_FILE")
else
    STRATEGY_ARGS=(-m 2 -d1 -d1+s -r1+s -s3+s -s6+s -s9+s -s12+s -s15+s -s20+s -s25+s -s30+s -s35+s -a1)
    STRATEGY_DISPLAY="-m 2 -d1 -d1+s -r1+s -s3+s..-s35+s -a1 (дефолт)"
fi

# Автоматически определяем текущую активную сетевую службу (Wi-Fi, Ethernet и т.д.)
IFACE=$(route -n get default 2>/dev/null | awk '/interface:/{print $2}')
if [[ -n "$IFACE" ]]; then
    SERVICE=$(networksetup -listnetworkserviceorder 2>/dev/null | grep -B 1 "Device: $IFACE" | head -n 1 | sed 's/^[^(]*([0-9]*) //')
fi
[[ -z "$SERVICE" ]] && SERVICE="Wi-Fi"

clear

echo "\033[1;32m========================================================\033[0m"
echo "\033[1;32m           🚀 ByeDPI Anti-Censorship Proxy              \033[0m"
echo "\033[1;32m========================================================\033[0m"
echo "  SOCKS5 адрес:     \033[1;33m$IP:$PORT\033[0m"
echo "  Сетевая служба:   \033[1;36m$SERVICE\033[0m"
echo "  Системный прокси: \033[1;32mВКЛЮЧЕН АВТОМАТИЧЕСКИ\033[0m"
echo "  Стратегия:        \033[0;37m$STRATEGY_DISPLAY\033[0m"
echo ""
echo "  \033[1;37mКонфиг:\033[0m           $CONFIG_FILE"
echo "  \033[1;37mДля выключения:\033[0m   просто закройте это окно терминала"
echo "                    или нажмите \033[1;31mCtrl + C\033[0m."
echo "\033[1;32m========================================================\033[0m"
echo ""
echo "\033[0;36m[Журнал соединений в реальном времени]:\033[0m"

# Автоматически включаем системный SOCKS5 прокси
networksetup -setsocksfirewallproxy "$SERVICE" "$IP" "$PORT" 2>/dev/null
networksetup -setsocksfirewallproxystate "$SERVICE" on 2>/dev/null

# Функция корректного выхода и восстановления сети
cleanup() {
    echo ""
    echo "\033[1;33mВыключение системного прокси для $SERVICE...\033[0m"
    networksetup -setsocksfirewallproxystate "$SERVICE" off 2>/dev/null
    if [[ -n "$PID" ]]; then
        kill "$PID" 2>/dev/null
    fi
    echo "\033[1;31m[ByeDPI остановлен, сеть полностью восстановлена]\033[0m"
    exit 0
}

trap cleanup INT TERM HUP EXIT

# Запуск ciadpi с флагом -x 1 и аргументами из конфига
"$BIN" -i "$IP" -p "$PORT" -x 1 "${STRATEGY_ARGS[@]}" &

PID=$!
wait "$PID"
