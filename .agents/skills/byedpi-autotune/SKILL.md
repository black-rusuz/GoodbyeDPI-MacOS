---
name: byedpi-autotune
description: >-
  Automated testing, diagnostic analysis, and parameter tuning for ByeDPI (ciadpi) on macOS and Linux (Docker)
  against TSPU DPI blocking of YouTube. Use when testing YouTube availability, investigating video
  buffering or playback freezes, diagnosing TCP drops or RSTs, or selecting optimal ByeDPI strategies.
---

# ByeDPI AutoTune Skill (Linux Docker & macOS)

Этот навык обучает агента автономно тестировать доступность YouTube, диагностировать поведение сетевых пакетов на уровне ТСПУ и подбирать оптимальные комбинации параметров для `ciadpi` (ByeDPI) без лишних проверочных команд в терминале.

---

## ⚡ Иерархия методов тестирования (Приоритеты агента)

Агент обязан следовать строгому приоритету при подборе и проверке стратегий:

### 🥇 Приоритет №1 (Основной рабочий режим): Групповой тест в Linux Docker
**Основной и главный инструмент агента** — групповое пакетное тестирование в окружении Linux:
```bash
./autotune/run_linux_autotune.sh --quiet
```
или со стресс-тестом CDN видеопотока на финалистах:
```bash
./autotune/run_linux_autotune.sh --speed-test --top-speed 3
```
- **Почему это приоритет №1:**
  1. **Обход VPN/WireGuard:** скрипт автоматически прописывает точечные маршруты через физический Wi-Fi шлюз (`en0`), исключая влияние системных VPN и направляя трафик напрямую к ТСПУ провайдера.
  2. **Полный арсенал Linux-бинарника:** `ciadpi_linux` поддерживает продвинутые связки с автопереключением (`-A t`, `-T 0.8`), фейковыми пакетами (`-f -1`), подменой SNI (`-n ya.ru`) и кэшем (`-L s`).
  3. **Сравнительный анализ:** сразу прогоняет пул кандидатов из `autotune/strategies.txt`, формирует отчёт [`reports/batch_latest.md`](file:///Users/rusuz/Projects/byedpi/autotune/reports/batch_latest.md) и возвращает структурированный результат (при `--json`).

---

### 🔬 Допускается для быстрой проверки гипотез: Одиночный тест `test_config.py`
Одиночное тестирование конкретной конфигурации через `test_config.py` разрешено **только** для быстрой точечной проверки гипотезы перед формированием новой серии стратегий:
```bash
python3 autotune/test_config.py --config "<гипотеза>"
```
- **Сценарий использования:** если агент хочет точечно проверить, работает ли определённый сплит (например, `-m2 -r1+s -s2+s`), чтобы на его основе **сгенерировать новый набор стратегий для последующего группового тестирования**.
- После подтверждения гипотезы агент добавляет варианты в [`autotune/strategies.txt`](file:///Users/rusuz/Projects/byedpi/autotune/strategies.txt) и переходит к приоритетному групповому тестированию через `./autotune/run_linux_autotune.sh`.

---

### 🥉 Резервный режим: Нативный пакетный тест на macOS
```bash
python3 autotune/test_batch.py
```
Используется только в случае недоступности Docker или для специфичной проверки стратегий, строго ограниченных возможностями сетевого стека macOS.

---

## 🛑 Синтаксис флагов: Linux (`ciadpi_linux`) vs macOS (`ciadpi`)

> [!IMPORTANT]
> Из-за различий в сетевых стеках ядра ядро Linux поддерживает сырую инъекцию пакетов, а macOS — нет:
> - **В Linux (Docker):** разрешены флаги `-f` (fake), `-n` (fake-sni), `-T` (timeout auto-trigger), `-S` (MD5 signature), `-Y` (drop SACK), `-A` (auto), `-L` (auto-mode).
> - **В macOS (`build/ciadpi`):** флаги `-f`, `-n`, `-T`, `-S`, `-Y` отключены препроцессором (`#ifdef __linux__`). Попытка их запуска на macOS завершается ошибкой `ciadpi: invalid option -- X` с кодом 254.

### Допустимые кросс-платформенные флаги (macOS + Linux):
* `-s, --split <pos_t>` — сплит пакета (смещения: `+s` — SNI, `+h` — HTTP host, `+e` — конец, `+m` — середина, например `-s3+s`).
* `-d, --disorder <pos_t>` — split и отправка в обратном порядке (TTL=1 для первого сегмента + retransmit).
* `-o, --oob <pos_t>` — split и отправка байта как Out-Of-Band (TCP Urgent, флаг URG).
* `-q, --disoob <pos_t>` — обратный порядок + OOB данные.
* `-r, --tlsrec <pos_t>` — расщепление записи TLS Record Layer (например `-r1+s`).
* `-m, --tlsminor <ver>` — подмена TLS Minor Version в заголовке ClientHello (например `-m2`).
* `-a, --udp-fake <count>` — количество UDP фейков для подавления QUIC (например `-a1`).
* `-l, --fake-data <path|:str>` — кастомный payload фейкового пакета (файл или `:сырые_байты`).
* `-t, --ttl <num>` — TTL для фейковых пакетов (по умолчанию 8; для YouTube/GGC безопасно строго `2` или `3`).
* `-O, --fake-offset <pos_t>` — смещение начала данных фейка.
* `-Q, --fake-tls-mod <flag>` — модификация фейкового TLS ClientHello: `rand`, `orig`, `msize=<int>`.
* `-e, --oob-data <char>` — кастомный символ OOB (по умолчанию `a`).
* `-H, --hosts <file|:str>` — список хостов (белый список).
* `-b, --buf-size <size>` — размер сокетного буфера.

### Флаги, эксклюзивные для Linux (`build/ciadpi_linux` в Docker):
* `-f, --fake <pos_t>` — генерация фейкового TCP-пакета (например, `-f -1` или `-f 1`).
* `-n, --fake-sni <str>` — подмена имени SNI в фейке (например, `-n ya.ru`).
* `-T, --timeout <sec>` — таймаут ожидания ответа, после которого срабатывает `--auto`.
* `-A, --auto <mode>` — автопереключение стратегии (`t` — torst, `r` — redirect).
* `-L, --auto-mode <mode>` — режим автопереключения (`s` — swop с кэшированием в память).

---

## 📁 Структура модуля `autotune/`

```text
autotune/
├── targets.txt             # Список ключевых доменов и IP для тестирования
├── strategies.txt          # Пользовательский пул тестируемых стратегий (под .gitignore)
├── test_config.py          # Единый скрипт тестирования метрик и диагностики пакетов
├── test_batch.py           # Пакетный бенчмарк и ранжирование пула стратегий
├── run_linux_autotune.sh   # Приоритетный раннер: запуск тестов в Linux Docker с обходом WireGuard
├── Dockerfile              # Docker-образ byedpi-tester (Debian, curl, python3, build-tools)
└── reports/                # Каталог отчётов (под .gitignore)
    ├── .gitkeep
    ├── latest.md           # Результат одиночного прогона test_config.py
    ├── batch_latest.md     # Сводный рейтинг пакетного тестирования test_batch.py
    └── test_*.md           # Исторический архив отчётов
```

Справочные материалы навыка:
* [tspu_mechanics.md](./references/tspu_mechanics.md) — физика буфера сборки ТСПУ, TTL-хопы и алгоритмы TCP CUBIC.
* [strategies.md](./references/strategies.md) — проверенные базовые комбинации флагов.

---

## 🚀 Порядок работы агента при подборе стратегии

### Шаг 1. Формирование пула гипотез и анализ контекста
1. **Изучить историю последних отчётов в `autotune/reports/`** ([`batch_latest.md`](file:///Users/rusuz/Projects/byedpi/autotune/reports/batch_latest.md), [`latest.md`](file:///Users/rusuz/Projects/byedpi/autotune/reports/latest.md) и свежие архивные отчёты):
   - Определить, какие стратегии уже проверялись и какие симптомы блокировок (`BLACKHOLE`, `RST`, `SSL_ERR`, `SHAPED`) на них возникали.
   - Не повторять заведомо проигрышные комбинации.
   - Взять за базис наиболее скоростные и стабильные варианты из предыдущих сессий.
2. **Проанализировать текущий `config`** или ввод пользователя.
3. **Сформулировать гипотезы** о влиянии комбинаций флагов на основе `tspu_mechanics.md` и контекста отчётов.
4. **При необходимости точечно проверить единичную гипотезу**:
   ```bash
   python3 autotune/test_config.py --config "<гипотеза>"
   ```
5. **Сформировать семейство конкурирующих стратегий** и записать их в [`autotune/strategies.txt`](file:///Users/rusuz/Projects/byedpi/autotune/strategies.txt).

### Шаг 2. Запуск приоритетного группового тестирования в Linux
Запустить автономный Docker-раннер с флагом `--speed-test` для финалистов:
```bash
./autotune/run_linux_autotune.sh --speed-test --top-speed 3
```
- Скрипт сам поднимет маршруты через физический Wi-Fi, запустит контейнер, отсеет нерабочие варианты на Фазе 1 (скрининг) и замерит реальную скорость стрима YouTube (Мбит/с) на Фазе 2.

### Шаг 3. Анализ отчёта и симптомов ТСПУ

| Наблюдаемый симптом в отчёте | Причина на уровне ТСПУ | Что изменить в параметрах стратегии |
| :--- | :--- | :--- |
| `🔴 BLACKHOLE` (0 байт, TLS Handshake = 0 мс) на `googlevideo.com` или `GGC IP` | Буфер ТСПУ склеил пакеты и выделил домен; сессия отправлена в дроп | 1. Добавить `-m 2` (подмена TLS Minor Version)<br/>2. Добавить `-d1+s` (disorder на 1-й байт SNI)<br/>3. Добавить `-r 1+s` (TLS Record Split)<br/>4. В Linux: добавить связку с фейком `-A t -f -1 -n ya.ru` |
| `🔴 RST` (TCP Connection reset by peer) | Активный сброс соединения фильтром сигнатур | 1. Добавить OOB-байт: `-o 1+s`<br/>2. Увеличить частоту нарезки SNI: `-s3+s -s6+s -s9+s -s12+s` |
| `🔴 SSL_ERR` при использовании фейка (`-l` / `-f`) | Фейковый пакет долетел до реального сервера Google GGC | Понизить TTL фейка до `-t 2` или `-t 3`, либо убрать фейк и перейти на чистый сплит/disorder |
| `🟡 SHAPED` или скорость CDN < 300 КБ/с при 100% OK | Множественные флаги `-d` дропаются с TTL=1, стек считает это потерей пакетов и схлопывает TCP CWND | Оставить строго **один** `-d1+s`, остальные позиции перевести на чистый сплит `-s` |

### Шаг 4. Выбор и применение победившей стратегии
1. Ознакомиться со сводным рейтингом в [`reports/batch_latest.md`](file:///Users/rusuz/Projects/byedpi/autotune/reports/batch_latest.md).
2. Продемонстрировать пользователю сводную таблицу сравнения протестированных вариантов.
3. Если победившая стратегия совместима с активным сервисом macOS, предложить применить её в `config`.
4. При подтверждении пользователем записать строку в `config`.
