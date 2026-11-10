# ByeDPI AutoTune: Инструменты тестирования и подбора стратегий

Комплекс утилит автоматического тестирования, диагностики сетевых пакетов на уровне ТСПУ (DPI) и бенчмаркинга параметров [`ciadpi`](file:///Users/rusuz/Projects/byedpi/build/ciadpi) (ByeDPI) на macOS.

Модуль позволяет исследовать доступность сервисов YouTube и Google, замерять реальную пропускную способность видеопотока CDN и безопасно тестировать любые стратегии десинхронизации TCP/TLS на изолированном порту без остановки рабочего прокси.

---

## 🏗 Архитектура модуля

Система построена по принципу разделения ответственности:

```text
autotune/
├── targets.txt         # Контрольные домены, CDN и принудительно зафиксированные IP узлов GGC
├── test_config.py      # Core Engine: одиночное тестирование, детальные метрики TLS/HTTP, стрим-тест CDN
├── test_batch.py       # Batch Orchestrator: массовый запуск кандидатов, двухфазный отсев, JSON/Markdown сводка
└── reports/            # Каталог отчётов (latest.md, batch_latest.md, архив по таймстемпу)
```

1. **[`test_config.py`](file:///Users/rusuz/Projects/byedpi/autotune/test_config.py) (Core Engine)**:
   - Инкапсулирует полное всестороннее тестирование конкретной стратегии.
   - Управляет жизненным циклом процесса [`ciadpi`](file:///Users/rusuz/Projects/byedpi/build/ciadpi) на изолированном порту.
   - Собирает гранулярные метрики через `curl` (DNS, Connect, Handshake, TTFB, HTTP status).
   - Выполняет стресс-тест реального стрима YouTube CDN (`--speed-test`).
   - Предоставляет программный API `evaluate_strategy(...)` для импорта другими скриптами.
2. **[`test_batch.py`](file:///Users/rusuz/Projects/byedpi/autotune/test_batch.py) (Batch Orchestrator)**:
   - Принимает пачку стратегий из файла, аргументов CLI, `stdin` или использует встроенный пул пресетов.
   - Реализует **двухфазный бенчмарк**:
     - *Фаза 1 (Скрининг):* Быстрый отбор по доступности контрольных точек из [`targets.txt`](file:///Users/rusuz/Projects/byedpi/autotune/targets.txt).
     - *Фаза 2 (Стресс-тест финалистов):* Замер реальной скорости CDN в Мбит/с только для топ-N лучших выживших стратегий.
   - Выводит итоговую таблицу рейтинга с медалями 🥇🥈🥉, сохраняет сводный Markdown-отчёт и поддерживает вывод в машинном формате `--json` для интеграции с AI-агентом.

---

## 📁 Содержимое каталога

| Файл / Каталог | Описание |
| :--- | :--- |
| [`test_config.py`](file:///Users/rusuz/Projects/byedpi/autotune/test_config.py) | Единое ядро тестирования конкретной стратегии (CLI + модуль Python) |
| [`test_batch.py`](file:///Users/rusuz/Projects/byedpi/autotune/test_batch.py) | Пакетный бенчмарк и ранжирование пула стратегий |
| [`targets.txt`](file:///Users/rusuz/Projects/byedpi/autotune/targets.txt) | Список целевых доменов, диспетчера потоков и кэш-нод GGC (включая привязку к проблемным IP) |
| [`reports/`](file:///Users/rusuz/Projects/byedpi/autotune/reports) | Каталог отчётов: [`latest.md`](file:///Users/rusuz/Projects/byedpi/autotune/reports/latest.md), `batch_latest.md` и исторический архив |

---

## 🚀 Одиночное тестирование: `test_config.py`

### Примеры использования:

#### 1. Проверить работу текущего активного прокси
```bash
python3 autotune/test_config.py --current
```

#### 2. Проверить текущий прокси со стресс-тестом реального видеопотока
```bash
python3 autotune/test_config.py --current --speed-test
```

#### 3. Протестировать новую стратегию на изолированном порту
```bash
python3 autotune/test_config.py --config "-m 2 -r 1+s -s 2+s -s 4+s -s 7+s -s 11+s -s 16+s -s 21+s -a 1" --speed-test
```

#### 4. Использование в Python-коде (модульный API):
```python
from autotune.test_config import evaluate_strategy

result = evaluate_strategy(
    strategy_str="-m 2 -r 1+s -s 2+s -s 4+s -a 1",
    speed_test=True,
    verbose=False,
)
print(f"Доступность: {result['pass_pct']}%, Стрим: {result['stream_bench']['avg_mbps']} Мбит/с")
```

### Флаги командной строки `test_config.py`:

| Флаг | Тип | Описание |
| :--- | :--- | :--- |
| `--current` | флаг | Проверить текущий запущенный прокси (порт 1080) |
| `--config "<строка>"` | строка | Запустить и протестировать стратегию на изолированном порту (1081+) |
| `--speed-test` | флаг | Запустить стресс-тест реального видеопотока YouTube CDN |
| `--chunk-size <MB>` | число | Объём загружаемого фрагмента видео в МБ (по умолчанию: `15`) |
| `--bench-timeout <сек>` | число | Таймаут бенчмарка скорости в секундах (по умолчанию: `30.0`) |
| `--targets <путь>` | путь | Путь к альтернативному файлу хостов (по умолчанию: `autotune/targets.txt`) |
| `--port <порт>` | число | Принудительно задать порт подключения/запуска |
| `--timeout <сек>` | число | Таймаут одного зондирования (по умолчанию: `5.0`) |
| `--output <путь>` | путь | Сохранить отчёт по указанному пути вместо `reports/latest.md` |

---

## ⚡ Пакетный бенчмарк: `test_batch.py`

### Источники передачи конфигураций:

#### 1. Встроенный набор стратегий по умолчанию
Если аргументы не указаны, скрипт тестирует встроенный пул из 10 актуальных комбинаций (Progressive Split, Micro-split, Disorder Safe, OOB и др.):
```bash
python3 autotune/test_batch.py
```

#### 2. Загрузка из файла со стратегиями
Файл может содержать как чистые строки параметров, так и строки с названиями через двоеточие (`Название: флаги`):
```bash
python3 autotune/test_batch.py --file my_strategies.txt
```

#### 3. Передача списка через аргументы CLI
```bash
python3 autotune/test_batch.py --configs \
  "-m2 -r1+s -s2+s -s4+s -a1" \
  "-m2 -d1+s:2:0 -r1+s -s3+s -a1" \
  "-m2 -o1+s -r1+s -s2+s -a1"
```

#### 4. Передача через пайплайн (stdin)
```bash
cat my_candidates.txt | python3 autotune/test_batch.py --file -
```

---

### Двухфазный отбор с замером скорости видеопотока:

Флаг `--speed-test` активирует Фазу 2 — замер реальной скорости стриминга (Мбит/с) на серверах YouTube для финалистов:
```bash
python3 autotune/test_batch.py --speed-test --top-speed 3
```
- Сначала все кандидаты проходят быстрый скрининг по доступности хостов.
- Только топ-3 лучших финалиста допускаются к нагрузочному тесту видеопотока.
- Это сокращает время выполнения в 3–5 раз по сравнению со сплошным бенчмарком.

---

### Режим интеграции с AI-агентом (`--json`):

Для автоматического анализа результатов без парсинга текстовых таблиц:
```bash
python3 autotune/test_batch.py --file candidates.txt --json
```
Возвращает валидный структурированный JSON-массив результатов с метриками, кодами статусов и симптомами ТСПУ.

---

## 🎯 Список хостов: `targets.txt`

Файл [`targets.txt`](file:///Users/rusuz/Projects/byedpi/autotune/targets.txt) содержит полный профиль контрольных точек:

- **Web UI и шлюзы:** `www.youtube.com`, `m.youtube.com`, `youtu.be`
- **Статика и обложки:** `i.ytimg.com`, `yt3.ggpht.com`
- **Внутренний API:** `youtubei.googleapis.com`, `jnn-pa.googleapis.com`
- **Видеопотоки CDN (GoogleVideo):** `redirector.googlevideo.com`, `rr1---sn-xapuu8g0-gv8e.googlevideo.com`
- **Диспетчер потоков с привязкой к IP:**
  ```text
  redirector.googlevideo.com 74.125.131.198
  ```
- **Локальные кэш-серверы GGC (Ростелеком) с принудительной проверкой IP:**
  ```text
  rr1---sn-xapuu8g0-gv8e.googlevideo.com 185.154.74.236
  rr2---sn-xapuu8g0-gv8e.googlevideo.com 185.154.74.237
  ```
- **Зарубежные CDN-узлы GoogleVideo:**
  ```text
  r4---sn-aj5go5-53.googlevideo.com 173.194.151.68
  r1---sn-5goeen7y.googlevideo.com 74.125.110.134
  ```

---

## 🛑 Памятка по синтаксису флагов: `ciadpi` vs `zapret` / `GoodbyeDPI`

> [!WARNING]
> Параметры от утилит `zapret`, `winws` или `GoodbyeDPI` **несовместимы** с `ciadpi` напрямую! Запуск с неподдерживаемым флагом приводит к моментальному падению процесса с кодом `254` (`ciadpi: invalid option`).

### Допустимые флаги десинхронизации `ciadpi`:

| Флаг | Назначение | Пример использования |
| :--- | :--- | :--- |
| `-s, --split <pos_t>` | Сплит пакета по смещению (`+s` — SNI, `+h` — host, `+e` — конец, `+m` — середина) | `-s2+s -s4+s -s7+s` |
| `-d, --disorder <pos_t>` | Сплит и отправка сегментов в обратном порядке (TTL=1 для первого сегмента) | `-d1+s` |
| `-o, --oob <pos_t>` | Сплит со вставкой байта Out-Of-Band (TCP Urgent) | `-o1+s` |
| `-q, --disoob <pos_t>` | Обратный порядок вместе с OOB | `-q1+s` |
| `-r, --tlsrec <pos_t>` | Расщепление записи на уровне TLS Record Layer | `-r1+s` |
| `-m, --tlsminor <ver>` | Подмена Minor Version в ClientHello (`2` для TLS 1.2, `3` для TLS 1.3) | `-m2` |
| `-a, --udp-fake <count>` | Количество UDP-фейков для блокировки протокола QUIC (принуждение к TCP) | `-a1` |
| `-l, --fake-data <path\|:str>` | Кастомный payload фейкового пакета (файл или сырая строка `:...`) | `-l :fake` |
| `-t, --ttl <num>` | TTL для исходящих фейковых пакетов (безопасно: `2` или `3`) | `-t 3` |
| `-O, --fake-offset <pos_t>` | Смещение начала данных фейкового пакета | `-O 1+s` |
| `-Q, --fake-tls-mod <flag>` | Модификатор TLS ClientHello в фейках (`rand`, `orig`, `msize=<int>`) | `-Q orig` |
| `-e, --oob-data <char>` | Байт данных OOB (по умолчанию `a`) | `-e a` |

---

## 🩺 Диагностика симптомов ТСПУ

| Статус в отчёте | Причина на уровне ТСПУ | Что исправить в параметрах |
| :--- | :--- | :--- |
| `🔴 BLACKHOLE`<br/>*(0 байт, Handshake = 0 мс)* | Буфер ТСПУ успешно склеил TCP-сегменты, выделил SNI и дропнул сессию | 1. Добавить `-m 2` (спуфинг TLS Minor Version)<br/>2. Сместить сплит на 1-й байт SNI (`-d1+s` или `-s1+s`)<br/>3. Добавить нарезку TLS-записи: `-r 1+s` |
| `🔴 RST`<br/>*(Connection reset by peer)* | Активный сброс соединения инъекцией RST при распознавании сигнатуры | 1. Добавить OOB-байт: `-o 1+s`<br/>2. Увеличить частоту нарезки SNI: `-s3+s -s6+s -s9+s -s12+s` |
| `🔴 SSL_ERR`<br/>*(Handshake failure при фейках)* | Фейковый пакет долетел до сервера Google из-за завышенного TTL | Снизить TTL фейка (`-t 2` или `-t 3`), либо отказаться от фейков в пользу чистого `-s` / `-d` |
| `🟡 SHAPED`<br/>*(Скорость < 300 КБ/с при 100% OK)* | Множественные `-d` (disorder) дропаются с TTL=1; стек считает это потерей пакетов и схлопывает TCP CWND | Использовать строго **один** `-d1+s`, остальные точки резать чистым `-s` (split) |

---

## 📊 Пример актуальной стабильной стратегии

Стратегия с прогрессивным сплитом SNI и подавлением QUIC (показывает стабильные 140+ Мбит/с на YouTube 4K):

```bash
-m 2 -r 1+s -s 2+s -s 4+s -s 7+s -s 11+s -s 16+s -s 21+s -a 1
```
