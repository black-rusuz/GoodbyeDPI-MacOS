#!/bin/zsh

APP_PATH="$HOME/Applications/ByeDPI.app"

echo "=== Удаление ByeDPI для macOS ==="

# 1. Отключение системного SOCKS5-прокси
echo "Восстановление параметров сети macOS..."
IFACE=$(route -n get default 2>/dev/null | awk '/interface:/{print $2}')
if [[ -n "$IFACE" ]]; then
    SERVICE=$(networksetup -listnetworkserviceorder 2>/dev/null | grep -B 1 "Device: $IFACE" | head -n 1 | sed 's/^[^(]*([0-9]*) //')
fi
[[ -z "$SERVICE" ]] && SERVICE="Wi-Fi"

networksetup -setsocksfirewallproxystate "$SERVICE" off 2>/dev/null || true

# 2. Завершение активных процессов ciadpi
echo "Завершение фоновых процессов ciadpi..."
pkill -x ciadpi 2>/dev/null || true

# 3. Удаление автономного бандла приложения ByeDPI.app
if [[ -d "$APP_PATH" ]]; then
    echo "Удаление приложения $APP_PATH..."
    rm -rf "$APP_PATH"
fi

# 4. Очистка устаревшего каталога ~/.byedpi при его наличии
if [[ -d "$HOME/.byedpi" ]]; then
    echo "Удаление устаревшего каталога ~/.byedpi..."
    rm -rf "$HOME/.byedpi"
fi

echo ""
echo "✅ ByeDPI успешно удалён, исходные параметры сети восстановлены."
