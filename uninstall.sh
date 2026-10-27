#!/bin/zsh

APP_PATH="$HOME/Applications/ByeDPI.app"

echo "=== Удаление ByeDPI для macOS ==="

# 1. Отключение системного прокси macOS
echo "Отключение системного прокси macOS..."
IFACE=$(route -n get default 2>/dev/null | awk '/interface:/{print $2}')
if [[ -n "$IFACE" ]]; then
    SERVICE=$(networksetup -listnetworkserviceorder 2>/dev/null | grep -B 1 "Device: $IFACE" | head -n 1 | sed 's/^[^(]*([0-9]*) //')
fi
[[ -z "$SERVICE" ]] && SERVICE="Wi-Fi"

networksetup -setsocksfirewallproxystate "$SERVICE" off 2>/dev/null || true

# 2. Остановка работающих процессов ciadpi
echo "Остановка процессов ciadpi..."
pkill -x ciadpi 2>/dev/null || true

# 3. Удаление автономного приложения ByeDPI.app
if [[ -d "$APP_PATH" ]]; then
    echo "Удаление приложения $APP_PATH..."
    rm -rf "$APP_PATH"
fi

# 4. Очистка старой директории ~/.byedpi, если она осталась
if [[ -d "$HOME/.byedpi" ]]; then
    echo "Удаление старой папки ~/.byedpi..."
    rm -rf "$HOME/.byedpi"
fi

echo ""
echo "✅ ByeDPI полностью удален, а настройки сети macOS восстановлены в исходное состояние!"
