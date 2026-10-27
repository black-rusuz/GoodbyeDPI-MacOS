#!/bin/zsh
set -e

GITHUB_REPO="${BYEDPI_REPO:-https://github.com/rusuz/byedpi}"
APP_DIR="$HOME/Applications"
APP_NAME="ByeDPI.app"
APP_PATH="$APP_DIR/$APP_NAME"

# Определяем режим: локальный (из git-клона) или удаленный (curl | zsh)
if [[ -n "$0" && -f "$(dirname "$0")/run.command" ]]; then
    REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
    IS_CURL=0
else
    IS_CURL=1
    TEMP_DIR=$(mktemp -d /tmp/byedpi_install_XXXXXX)
    REPO_DIR="$TEMP_DIR"
fi

# Очистка временных файлов при выходе в режиме curl
cleanup_temp() {
    if [[ $IS_CURL -eq 1 && -n "$TEMP_DIR" && -d "$TEMP_DIR" ]]; then
        rm -rf "$TEMP_DIR"
    fi
}
trap cleanup_temp EXIT

if [[ $IS_CURL -eq 1 ]]; then
    echo "=== Удаленная установка ByeDPI для macOS (через curl) ==="
    echo "Загрузка репозитория..."
    git clone --recurse-submodules "$GITHUB_REPO" "$REPO_DIR"
else
    echo "=== Локальная сборка и установка ByeDPI для macOS ==="
fi

echo "Рабочая директория сборки: $REPO_DIR"

# 1. Проверка подмодуля с исходниками C
if [[ ! -f "$REPO_DIR/src/Makefile" ]]; then
    echo "Инициализация подмодуля исходников src..."
    if [[ -d "$REPO_DIR/.git" ]]; then
        git -C "$REPO_DIR" submodule update --init --recursive
    else
        echo "Загрузка архива исходников с GitHub..."
        mkdir -p "$REPO_DIR/src"
        curl -fsSL https://github.com/hufrea/byedpi/archive/refs/heads/main.tar.gz | tar -xz -C "$REPO_DIR/src" --strip-components=1
    fi
fi

# 2. Компиляция бинарника ciadpi в папку build/
BUILD_DIR="$REPO_DIR/build"
mkdir -p "$BUILD_DIR"

echo "Компиляция ciadpi под архитектуру вашего Mac..."
make -C "$REPO_DIR/src"
cp "$REPO_DIR/src/ciadpi" "$BUILD_DIR/ciadpi"
chmod +x "$BUILD_DIR/ciadpi"
rm -f "$REPO_DIR/ciadpi" 2>/dev/null || true

chmod +x "$REPO_DIR/run.command"
chmod +x "$REPO_DIR/uninstall.sh" 2>/dev/null || true

# 3. Дефолтный конфиг с историей
if [[ ! -f "$REPO_DIR/config" ]]; then
    echo "Создание файла config с историей..."
    echo "# $(date '+%Y-%m-%d %H:%M:%S') - Начальная проверенная стратегия" > "$REPO_DIR/config"
    echo "-m 2 -d1 -d1+s -r1+s -s3+s -s6+s -s9+s -s12+s -s15+s -s20+s -s25+s -s30+s -s35+s -a1" >> "$REPO_DIR/config"
fi

# 4. Сборка автономного приложения ByeDPI.app в ~/Applications
echo "Формирование автономного приложения $APP_PATH..."
mkdir -p "$APP_DIR"
rm -rf "$APP_PATH"

# AppleScript-загрузчик: переиспользует первичное пустое окно терминала, предотвращая дублирование
osacompile -o "$APP_PATH" -e '
set appPath to POSIX path of (path to me)
set runScript to appPath & "Contents/Resources/run.command"
set wasRunning to application "Terminal" is running
tell application "Terminal"
    activate
    if not wasRunning then
        repeat with i from 1 to 20
            if (count of windows) > 0 then exit repeat
            delay 0.05
        end repeat
        if (count of windows) > 0 and not (busy of window 1) then
            do script quoted form of runScript in window 1
            return
        end if
    end if
    do script quoted form of runScript
end tell
'

# Копируем всё необходимое внутрь бандла приложения
RESOURCES="$APP_PATH/Contents/Resources"
mkdir -p "$RESOURCES"
cp "$BUILD_DIR/ciadpi" "$RESOURCES/ciadpi"
cp "$REPO_DIR/run.command" "$RESOURCES/run.command"
cp "$REPO_DIR/config" "$RESOURCES/config"
cp "$REPO_DIR/uninstall.sh" "$RESOURCES/uninstall.sh" 2>/dev/null || true
chmod +x "$RESOURCES/ciadpi" "$RESOURCES/run.command" "$RESOURCES/uninstall.sh" 2>/dev/null || true

# Устанавливаем иконку терминала
ICON_SRC="/System/Applications/Utilities/Terminal.app/Contents/Resources/Terminal.icns"
if [[ -f "$ICON_SRC" ]]; then
    cp "$ICON_SRC" "$RESOURCES/applet.icns"
    touch "$APP_PATH"
fi

echo ""
echo "✅ ByeDPI успешно скомпилирован в build/ и установлен в $APP_PATH!"
echo "🚀 Запуск: через Launchpad или Spotlight (Cmd + Пробел -> ByeDPI)"
