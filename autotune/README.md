# ByeDPI AutoTune: Инструменты тестирования и подбора стратегий

Комплекс утилит автоматического тестирования, диагностики сетевых пакетов на уровне ТСПУ (DPI) и бенчмаркинга параметров [`ciadpi`](file:///Users/rusuz/Projects/byedpi/build/ciadpi) (ByeDPI) на macOS и Linux (Docker).

Модуль позволяет исследовать доступность сервисов YouTube и Google, замерять реальную пропускную способность видеопотока CDN и безопасно тестировать любые стратегии десинхронизации TCP/TLS на изолированном порту без остановки рабочего прокси.

---

## 🏗 Архитектура модуля

Система построена по принципу разделения ответственности и кросс-платформенности:

```text
autotune/
├── targets.txt             # Контрольные домены, CDN и принудительно зафиксированные IP узлов GGC
├── strategies.txt          # Пользовательский пул тестируемых стратегий (под .gitignore)
├── test_config.py          # Core Engine: одиночное тестирование, метрики TLS/HTTP, стрим-тест CDN
├── test_batch.py           # Batch Orchestrator: массовый запуск кандидатов, двухфазный отсев, JSON/MD отчёты
├── run_linux_autotune.sh   # Автономный раннер для тестирования в Linux Docker с обходом WireGuard
├── Dockerfile              # Рецепт легковесного Debian-контейнера byedpi-tester
└── reports/                # Каталог отчётов (latest.md, batch_latest.md, архив по таймстемпу)
```

1. **[`test_config.py`](file:///Users/rusuz/Projects/byedpi/autotune/test_config.py) (Core Engine)**:
   - Инкапсулирует полное всестороннее тестирование конкретной стратегии.
   - Автоматически находит свободный порт и запускает изолированный экземпляр [`ciadpi`](file:///Users/rusuz/Projects/byedpi/build/ciadpi) (на macOS) или `ciadpi_linux` (внутри Linux/Docker).
   - Собирает гранулярные метрики через `curl` (DNS, Connect, Handshake, TTFB, HTTP status).
   - Выполняет стресс-тест реального стрима YouTube CDN (`--speed-test`).
   - Предоставляет программный API `evaluate_strategy(...)` для импорта другими скриптами.
2. **[`test_batch.py`](file:///Users/rusuz/Projects/byedpi/autotune/test_batch.py) (Batch Orchestrator)**:
   - Запускает тестирование пачки стратегий из [`strategies.txt`](file:///Users/rusuz/Projects/byedpi/autotune/strategies.txt), внешнего файла, CLI-аргументов или `stdin`.
   - Реализует **двухфазный бенчмарк**:
     - *Фаза 1 (Скрининг):* Быстрый отбор по доступности контрольных точек из [`targets.txt`](file:///Users/rusuz/Projects/byedpi/autotune/targets.txt).
     - *Фаза 2 (Стресс-тест финалистов):* Замер реальной скорости CDN в Мбит/с только для топ-N лучших выживших стратегий (`--speed-test`).
   - Выводит итоговую таблицу рейтинга с медалями 🥇🥈🥉, сохраняет сводный Markdown-отчёт и поддерживает машинный формат `--json` для интеграции с AI-агентом.
3. **[`run_linux_autotune.sh`](file:///Users/rusuz/Projects/byedpi/autotune/run_linux_autotune.sh) (Docker Runner)**:
   - Полностью автоматизирует поднятие Docker-окружения с нуля без ручных настроек.
   - Временно прописывает точечные маршруты к тестовым IP через физический Wi-Fi шлюз macOS (`en0`) в обход системного WireGuard/VPN.
   - Запускает [`test_batch.py`](file:///Users/rusuz/Projects/byedpi/autotune/test_batch.py) внутри контейнера и гарантированно удаляет маршруты при завершении.

---

## 📁 Содержимое каталога

| Файл / Каталог | Описание |
| :--- | :--- |
| [`test_config.py`](file:///Users/rusuz/Projects/byedpi/autotune/test_config.py) | Единое ядро тестирования конкретной стратегии (CLI + модуль Python) |
| [`test_batch.py`](file:///Users/rusuz/Projects/byedpi/autotune/test_batch.py) | Пакетный бенчмарк и ранжирование пула стратегий |
| [`run_linux_autotune.sh`](file:///Users/rusuz/Projects/byedpi/autotune/run_linux_autotune.sh) | Автономный запуск пакетного тестирования под Linux в Docker |
| [`Dockerfile`](file:///Users/rusuz/Projects/byedpi/autotune/Dockerfile) | Описание Docker-образа `byedpi-tester` (Debian, curl, python3, gcc, make) |
| [`strategies.txt`](file:///Users/rusuz/Projects/byedpi/autotune/strategies.txt) | Список пользовательских стратегий для тестирования (в `.gitignore`) |
| [`targets.txt`](file:///Users/rusuz/Projects/byedpi/autotune/targets.txt) | Список целевых доменов, диспетчера потоков и кэш-нод GGC (включая проблемные IP) |
| [`reports/`](file:///Users/rusuz/Projects/byedpi/autotune/reports) | Каталог отчётов: [`latest.md`](file:///Users/rusuz/Projects/byedpi/autotune/reports/latest.md), [`batch_latest.md`](file:///Users/rusuz/Projects/byedpi/autotune/reports/batch_latest.md) и исторический архив |

---

## 🐧 Тестирование под Linux в Docker (Автономный запуск с нуля)

### Зачем нужен запуск в Linux?
Сетевой стек macOS (XNU/BSD) на уровне ядра не поддерживает ряд низкоуровневых операций с сокетами. Поэтому флаги десинхронизации с сырой инъекцией пакетов отключены препроцессором в коде macOS:
- **Доступно только в Linux (`ciadpi_linux`):**
  - `-f, --fake <pos>` — генерация и инъекция фейковых TCP-пакетов.
  - `-n, --fake-sni <str>` — подмена домена SNI внутри фейка (например, `-n ya.ru`).
  - `-T, --timeout <sec>` — авто-срабатывание десинхронизации при задержке ответа от сервера.
  - `-S, --md5sig` — инъекция опции TCP MD5 Signature для фейков.
  - `-Y, --drop-sack` — сброс пакетов с расширением SACK.
  - `-L s` — кэширование и автоматическая смена параметров при детектировании блокировок (`swop`).

### Как это устроено под капотом (Zero Knowledge Guide):
Вам **не нужно** разбираться в командах Docker или вручную собирать контейнеры. Скрипт [`run_linux_autotune.sh`](file:///Users/rusuz/Projects/byedpi/autotune/run_linux_autotune.sh) делает всё самостоятельно:
1. **Проверяет запуск Docker:** если Docker Desktop не открыт, скрипт подскажет запустить его.
2. **Собирает образ с нуля:** если образа `byedpi-tester` нет в системе, скрипт соберёт его автоматически по [`Dockerfile`](file:///Users/rusuz/Projects/byedpi/autotune/Dockerfile).
3. **Компилирует бинарник под Linux:** если файл `build/ciadpi_linux` отсутствует, скрипт скомпилирует его внутри контейнера из исходников в `src/`.
4. **Обходит WireGuard/VPN:** на время тестов направляет сетевые пакеты к тестовым IP через физический шлюз вашего домашнего роутера (`ipconfig getoption en0 router`), чтобы замерить реальную блокировку ТСПУ провайдера.
5. **Безопасная очистка:** при завершении работы (или нажатии `Ctrl+C`) скрипт через системный `trap` автоматически удаляет все временные маршруты, возвращая сеть в первоначальное состояние.

### Запуск Linux-тестов:
Запустите скрипт из корня проекта:
```bash
./autotune/run_linux_autotune.sh
```
*(Скрипт запросит пароль `sudo` для добавления временных статических маршрутов).*

#### Примеры дополнительных параметров:
Любые аргументы передаются прямо в `test_batch.py`:

```bash
# Стресс-тест CDN видеопотока для лучших финалистов
./autotune/run_linux_autotune.sh --speed-test

# Тихий режим (только финальная таблица)
./autotune/run_linux_autotune.sh --quiet

# Вывод в формате JSON для AI-агента
./autotune/run_linux_autotune.sh --json

# Тестирование конкретного набора параметров
./autotune/run_linux_autotune.sh --configs "-m 2 -d1 -d1+s -r1+s -s3+s -a1" "-f -1 -t 3 -n ya.ru -r 1+s"
```

---

## ⚙️ Управление стратегиями: `strategies.txt`

Файл [`strategies.txt`](file:///Users/rusuz/Projects/byedpi/autotune/strategies.txt) используется как основной список стратегий по умолчанию. Он добавлен в `.gitignore`, поэтому вы можете свободно редактировать его без риска закоммитить черновики.

### Формат файла:
- `Название стратегии: параметры_ciadpi` (рекомендуется для наглядного отчёта)
- либо просто строка аргументов `параметры_ciadpi`
- Строки с `#` и пустые строки игнорируются.

Пример содержимого:
```text
База GGC (чистый сплит + minor): -m 2 -d1 -d1+s -r1+s -s3+s -s6+s -s9+s -s12+s -s15+s -s20+s -a1
Связка GGC -> Fake ya.ru (T 0.8s): -m 2 -d1 -d1+s -r1+s -s3+s -s6+s -s9+s -s12+s -s15+s -s20+s -a1 -T 0.8 -A t -f -1 -t 3 -n ya.ru -r 1+s
```

---

## 🚀 Нативное тестирование на macOS: `test_config.py` и `test_batch.py`

Если вам не требуются специфичные для Linux фейковые пакеты (`-f`, `-n`), тесты можно запускать прямо в macOS без Docker:

### Одиночное тестирование (`test_config.py`):
```bash
# Проверить текущий активный рабочий прокси
python3 autotune/test_config.py --current

# Проверить текущий прокси с тестом скорости YouTube 4K
python3 autotune/test_config.py --current --speed-test

# Протестировать стратегию на изолированном порту
python3 autotune/test_config.py --config "-m 2 -r 1+s -s 2+s -s 4+s -s 7+s -a 1" --speed-test
```

### Пакетный бенчмарк (`test_batch.py`):
```bash
# Протестировать все стратегии из strategies.txt
python3 autotune/test_batch.py

# С замером скорости видеопотока финалистов
python3 autotune/test_batch.py --speed-test --top-speed 3

# Быстрый тест произвольного списка из CLI
python3 autotune/test_batch.py --configs "-m2 -r1+s -s2+s -a1" "-m2 -d1+s:2:0 -r1+s -s3+s -a1"
```

---

## 🎯 Список контрольных хостов: `targets.txt`

Файл [`targets.txt`](file:///Users/rusuz/Projects/byedpi/autotune/targets.txt) содержит полный контрольный профиль сервисов Google:
- **Веб-интерфейс и шлюзы:** `www.youtube.com`, `m.youtube.com`, `youtu.be`
- **Статика и обложки:** `i.ytimg.com`, `yt3.ggpht.com`
- **Внутренний API:** `youtubei.googleapis.com`, `jnn-pa.googleapis.com`
- **Диспетчер потоков Google CDN:** `redirector.googlevideo.com 74.125.131.198`
- **Кэш-ноды GGC Ростелекома (принудительная проверка проблемных IP):**
  - `rr1---sn-xapuu8g0-gv8e.googlevideo.com 185.154.74.236`
  - `rr2---sn-xapuu8g0-gv8e.googlevideo.com 185.154.74.237`
- **Зарубежные CDN Google:** `173.194.151.68`, `74.125.110.134`

---

## 🛑 Памятка по синтаксису флагов `ciadpi`

> [!WARNING]
> Параметры от утилит `zapret`, `winws` или `GoodbyeDPI` **несовместимы** с `ciadpi` напрямую! Запуск с неподдерживаемым флагом приводит к падению с кодом `254` (`ciadpi: invalid option`).

| Флаг | Платформа | Назначение | Пример |
| :--- | :---: | :--- | :--- |
| `-s, --split <pos>` | macOS / Linux | Сплит пакета (`+s` — SNI, `+h` — host, `+e` — конец, `+m` — середина) | `-s2+s -s4+s -s7+s` |
| `-d, --disorder <pos>` | macOS / Linux | Сплит и отправка сегментов в обратном порядке | `-d1+s` |
| `-o, --oob <pos>` | macOS / Linux | Сплит со вставкой байта Out-Of-Band (TCP Urgent) | `-o1+s` |
| `-r, --tlsrec <pos>` | macOS / Linux | Расщепление записи TLS Record Layer | `-r1+s` |
| `-m, --tlsminor <ver>` | macOS / Linux | Подмена TLS Minor Version (`2` для TLS 1.2, `3` для TLS 1.3) | `-m2` |
| `-a, --udp-fake <cnt>` | macOS / Linux | Количество UDP-фейков для блокировки QUIC | `-a1` |
| `-f, --fake <pos>` | **Только Linux** | Инъекция фейкового TCP-пакета | `-f -1` или `-f 1` |
| `-n, --fake-sni <str>` | **Только Linux** | Подмена SNI в фейковом пакете | `-n ya.ru` |
| `-t, --ttl <num>` | **Только Linux** | TTL фейковых пакетов (безопасно: `2` или `3`) | `-t 3` |
| `-T, --timeout <sec>` | **Только Linux** | Таймаут ожидания ответа, триггер для опции `--auto` | `-T 0.8` |
| `-A, --auto <mode>` | **Только Linux** | Авто-переключение стратегии (`t` — torst, `r` — redirect) | `-A t` |
| `-L, --auto-mode <m>` | **Только Linux** | Режим работы авто-переключения (`s` — swop с кэшированием) | `-L s` |

---

## 🩺 Диагностика симптомов ТСПУ

| Статус в отчёте | Причина на уровне ТСПУ | Что исправить в параметрах |
| :--- | :--- | :--- |
| `🔴 BLACKHOLE`<br/>*(0 байт, Handshake = 0 мс)* | Буфер ТСПУ склеил сегменты, выделил SNI и сбросил сессию | 1. Добавить `-m 2` (спуфинг Minor Version)<br/>2. Сместить сплит на 1-й байт SNI (`-d1+s` или `-s1+s`)<br/>3. Добавить нарезку TLS-записи: `-r 1+s` |
| `🔴 RST`<br/>*(Connection reset by peer)* | Активный сброс соединения инъекцией RST при обнаружении сигнатур | 1. Добавить OOB-байт: `-o 1+s`<br/>2. Увеличить частоту нарезки SNI: `-s3+s -s6+s -s9+s -s12+s` |
| `🔴 SSL_ERR`<br/>*(Handshake failure)* | Фейковый пакет долетел до сервера Google из-за завышенного TTL | Снизить TTL фейка (`-t 2` или `-t 3`), либо перейти на чистый `-s` / `-d` |
| `🟡 SHAPED`<br/>*(Скорость < 300 КБ/с)* | Множественные `-d` (disorder) дропаются с TTL=1, стек схлопывает TCP CWND | Использовать строго **один** `-d1+s`, остальные точки резать чистым `-s` (split) |
