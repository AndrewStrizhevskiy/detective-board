from common import DOCS, IMG, new

FILE = DOCS["РСП"][0]


def make():
    d = new("РСП", "программного комплекса")

    d.h(1, "Общие сведения о программе")
    d.p("Руководство предназначено для системного программиста, который устанавливает, настраивает, проверяет и обслуживает комплекс. "
        "Назначение, состав и логическая структура программы описаны в «Описании программы» (ОП); работа оператора – в «Руководстве оператора» (РО); перечень проверок и протоколов – в «Программе и методике испытаний» (ПМИ).")
    d.table("Что нужно для работы", ["Компонент", "Версия / требование", "Где проверить"],
        [["ОС", "целевая: Linux x86_64; разработка: macOS", "`docs/team/CLEAN_INSTALL.md`"],
         ["Python", ">= 3.12 (в офлайн-архиве 3.12.15)", "`pyproject.toml`"],
         ["uv и just", "uv создаёт окружение по `uv.lock`; just запускает рецепты `justfile`", "ADR-0001"],
         ["Ollama", "локально, порт 11434 (в архиве – 0.35.0)", "`scripts/preflight.py`"],
         ["Модели Ollama", "`bge-m3`, `qwen3:4b-instruct`, `qwen3:4b`; идентификаторы – в `docs/team/models.md`", "`ollama list`"],
         ["Данные", "`data/index/db.sqlite`, `data/index/sentences.sqlite`, `data/graph/graph.sqlite` (в git не хранятся)", "`just run` печатает состояние файлов"],
         ["Node.js", "только для `just test-web`", "`justfile`"]],
        [1.6, 3.6, 2.5])

    d.h(1, "Структура программы")
    d.p("Каталоги репозитория: `src/detective_board/` (пакет), `web/` (интерфейс), `data/` (корпус, чанки, курируемые факты; бинарные индексы создаются или приходят из архива), `eval/` (оценка), `scripts/` (корпус, сервер, упаковка, спайк), `tests/`, `docs/`, `prompts/` (промпты извлечения). "
        "Структура пакета и потоки данных – ОП, раздел «Описание логической структуры».")
    d.figure(IMG + "deploy.png", "Схема развёртывания: предвычисление на GPU-сервере и работа на ноутбуке", 11, 14)

    d.h(1, "Настройка программы")
    d.h(2, "Установка из исходников (с сетью)")
    d.p("Первая установка требует сети (загрузка пакетов и моделей).")
    d.code("""git clone https://github.com/AndrewStrizhevskiy/detective-board.git
cd detective-board
just setup                 # uv sync --group dev
ollama pull bge-m3 && ollama pull qwen3:4b-instruct && ollama pull qwen3:4b
ollama list                # сравнить столбец ID с docs/team/models.md""")
    d.p("Корпус и производные данные: `scripts/corpus/fetch.py` скачивает сборники Проекта Гутенберг (список `COLLECTIONS` в скрипте, источники – `data/LICENSES.md`) в `data/raw/`, `scripts/corpus/ingest.py` очищает их и режет на рассказы и 596 чанков (`data/clean/`, `data/chunks.jsonl`); "
        "лицензионные сведения – `data/LICENSES.md`. Чанки и очищенные рассказы уже лежат в репозитории.")
    d.code("""uv run python scripts/corpus/fetch.py     # только если нужны исходные тексты
uv run python scripts/corpus/ingest.py
just index                                 # data/index/db.sqlite: чанки + FTS5 + векторы bge-m3
just sentences                             # data/index/sentences.sqlite (индекс предложений)
just graph                                 # data/graph/graph.sqlite из кэша извлечения + нормализация""")
    d.p("`just index` без готового кэша эмбеддингов занимает около 22 минут на целевом ноутбуке (0,46 чанка/с, `docs/spike/results/embed-20261022-180354.md`); индекс предложений – около 20 минут на CPU и 5–10 минут на GPU (`justfile`, `docs/team/SERVER_RUNBOOK.md`). "
        "Извлечение 596 чанков на ноутбуке заняло бы около 30 часов (оценка `docs/PRD.md`), поэтому кэш извлечения приходит с GPU-сервера или из архива; `just graph` при полном кэше не вызывает модель (все обращения – попадания в кэш).")
    d.p("Курируемые демонстрационные факты загружаются в граф отдельной командой `python -m detective_board.extract.curated` (параметры – `--help`); без них вопрос о Garcia/Wisteria Lodge не даст находки (`docs/team/CLEAN_INSTALL.md`, «If something fails»).")
    d.h(2, "Запуск")
    d.code("""just run                  # проверка Ollama и моделей (scripts/preflight.py), затем API + UI на http://127.0.0.1:8000
just run --fake           # без Ollama и без файлов данных: фиктивная модель и три фрагмента
uv run python -m detective_board.api --host 127.0.0.1 \\
    --port 8000 [--config FILE] [--fake]""")
    d.p("`scripts/preflight.py` завершается кодом 2 и печатает, чего нет: недоступна Ollama (`ollama serve`) или не загружена модель (`ollama pull <модель>`). "
        "Привязка не к loopback-адресу допускается, но печатается предупреждение: API не аутентифицирует пользователей.")
    d.h(2, "Конфигурация")
    d.p("Приоритет источников: значения по умолчанию < TOML-файл (`--config` или `DETECTIVE_BOARD_CONFIG`) < переменные окружения `DETECTIVE_BOARD_<ПОЛЕ>` < аргументы командной строки. Неизвестные ключи – ошибка.")
    d.table("Основные поля (`src/detective_board/api/config.py`, `docs/api.md`)", ["Поле", "По умолчанию", "Назначение"],
        [["`host`, `port`", "127.0.0.1, 8000", "адрес и порт API"],
         ["`index_path`, `graph_path`", "`data/index/db.sqlite`, `data/graph/graph.sqlite`", "файлы данных"],
         ["`facts_path`, `facts_allow`", "пусто", "JSON FactBase для MCP-инструментов; при пустом значении используется граф"],
         ["`ollama_host`", "http://localhost:11434", "адрес Ollama"],
         ["`llm_model`, `embed_model`, `embed_dim`", "qwen3:4b-instruct, bge-m3, 1024", "модели; настройки эмбеддингов должны совпадать с построенным индексом (иначе хранилище откажется работать)"],
         ["`num_ctx`, `keep_alive`", "4096, 30m", "контекст модели и время удержания в памяти"],
         ["`warmup`", "true", "фоновый прогрев моделей при старте"],
         ["`[agent]` (`DETECTIVE_BOARD_AGENT_<ИМЯ>`)", "см. `agent/config.py`", "пороги агента: `top_k` 4, `min_score` 0,018, `min_support` 0,25, `answer_mode` extractive, `rule_first` true, `translate_questions` true, `use_llm_router` false, `tool_timeout_s` 5, `temperature` 0, `seed` 42 и др."],
         ["`DETECTIVE_BOARD_TOOL_DEADLINE_S`", "4", "серверный предел времени вызова MCP-инструмента"]],
        [2.5, 2.2, 3])
    d.p("Значения порогов агента (`min_score`, `min_support`, `min_claim_overlap`) предварительные; промпт выбора предложений заморожен: любое изменение требует повторного измерения (ADR-0009, `docs/STATUS.md`).")

    d.h(1, "Проверка программы")
    d.table("Команды проверки", ["Команда", "Что проверяет", "Условие"],
        [["`just test`", "быстрый детерминированный набор pytest (без `live` и `e2e`)", "без Ollama; **[Измерено]** 986 passed за 9,6 с на коммите 16122fc"],
         ["`just test-cov`", "то же с порогом покрытия 80 % на `src/detective_board`", "CI"],
         ["`just lint`, `just fmt`, `just typecheck`", "ruff (проверка/формат) и pyright", "—"],
         ["`just test-web`", "логика интерфейса (`tests/web_js/*.test.mjs`, встроенный раннер Node)", "нужен Node.js; два живых теста пропускаются без `DB_URL`"],
         ["`just test-live`", "тесты `live`", "нужна запущенная Ollama и модели; в CI не запускаются"],
         ["`just eval --short`", "8 вопросов dev, фиктивная модель, образцовый индекс, без сети (задание CI `eval-short`)", "—"],
         ["`./verify_offline.sh --require-offline`", "проверка распакованного офлайн-архива (контрольные суммы, окружение, тесты, Ollama, API, контрольные вопросы)", "на целевом ноутбуке без сети"]],
        [2.5, 3.2, 2])
    d.p("Подробный перечень проверок, ожидаемые результаты и протоколы – в ПМИ.")

    d.h(1, "Дополнительные возможности")
    d.h(2, "Офлайн-архив")
    d.p("Архив содержит всё для работы без сети: репозиторий на теге, записи `web/replay`, индексы и граф, uv, сборку Python, кэш uv, бинарник Ollama и три модели, `MANIFEST` и `SHA256SUMS`. Собирается на Linux x86_64 (платформа цели):")
    d.code("""scripts/pack_offline.sh --tag rc4 --out ~/dist [--with-8b] [--dry-run]""")
    d.p("Скрипт отказывается собирать архив, если не хватает модели или файла данных, и сверяет идентификаторы моделей с `docs/team/models.md`. **[Измерено]** архив rc4 (коммит 76f45ad): 6,2 ГБ, sha256 `16854b3d…e2ca3` (полностью – `docs/perf/clean-install-20261029.md`).")
    d.p("Установка на целевой ноутбук (подробно – `docs/team/CLEAN_INSTALL.md`):")
    d.code("""cp /media/$USER/<носитель>/detective-board-offline-<ref>.tar* ~/
cd ~ && sha256sum -c detective-board-offline-<ref>.tar.sha256
tar -xf detective-board-offline-<ref>.tar && cd detective-board-offline-<ref>
./verify_offline.sh --require-offline                # ожидается RESULT: PASS

# запуск (два терминала)
OLLAMA_MODELS="$PWD/ollama-models" OLLAMA_HOST=127.0.0.1:11434 \\
    ollama/bin/ollama serve
export PATH="$PWD/bin:$PATH" UV_OFFLINE=1 UV_PYTHON_DOWNLOADS=never \\
    UV_CACHE_DIR="$PWD/uv-cache" UV_LINK_MODE=copy
cd detective-board
uv run --no-sync python scripts/preflight.py
uv run --no-sync python -m detective_board.api       # http://127.0.0.1:8000""")
    d.p("Перед установкой остановите системную Ollama (`sudo systemctl stop ollama`) и убедитесь, что порты 8765 и 11435 (проверка) и 8000 и 11434 (работа) свободны. "
        "Критерий готовности по `CLEAN_INSTALL.md` – успешное прохождение на двух разных ноутбуках с записью в `docs/perf/clean-install-<дата>.md`; **выполнено на одной машине**, на второй **[Не выполнено]** (issue #8).")
    d.h(2, "Использование GPU-сервера")
    d.p("GPU-сервер используется только для предварительных вычислений: извлечение графа (qwen3:4b, промпт extract-2.1), проход присутствия, сравнения моделей на 12 размеченных фрагментах, индекс предложений, длинные оценки. "
        "Это пакетный вывод готовых открытых моделей; обучения и дообучения нет. Во время показа сервер не нужен. Доступ к серверу (SSH, Tailscale, диагностика сети) описан в отдельном репозитории `gpu-server-access`; в настоящий комплект учётные данные и адреса не включены.")
    d.p("Порядок работ (по `docs/team/SERVER_RUNBOOK.md`; на машине общего пользования не хранить учётные данные GitHub, не оставлять ключи и токены, по окончании остановить вручную запущенную Ollama и убрать рабочую копию, если администратор просит):")
    d.code("""scripts/make_server_archive.sh                 # на ноутбуке: detective-board.tar.gz из HEAD + COMMIT, проверка в чистой копии
scp detective-board.tar.gz USER@SERVER:~/      # или через USB
# на сервере, внутри tmux:
scripts/server_bootstrap.sh --with-8b          # проверки, uv, Ollama, настройки, модели, тесты, подтверждение GPU
scripts/server_run_all.sh                      # детерминизм -> проба параллельности -> gold12 -> полный прогон -> граф -> отчёт
scripts/server_progress.sh                     # из второго окна: прогресс по шардам, ETA
uv run python -m detective_board.index.sentences
scripts/server_presence.sh --verify --samples 3   # проход присутствия на демонстрационных рассказах""")
    d.p("Возврат результатов (в git не коммитятся): `data/cache/extract-cache.sqlite`, `data/graph/graph.sqlite`, `data/index/sentences.sqlite`, `data/cache/server/` (отчёт, журналы). "
        "Параллельная работа: `OLLAMA_NUM_PARALLEL` (по умолчанию в bootstrap 4) и `OLLAMA_KEEP_ALIVE`. Прогон возобновляем: повторный запуск той же команды продолжает с кэша. "
        "Шардирование: `scripts/extract_shards.py plan N`, `scripts/extract_shard.sh k N [модель]`, слияние кэшей `scripts/merge_extract_cache.py merge|verify|count`; `just graph qwen3:4b 20 \"data/cache/extract-cache-qwen3_4b-shard*.sqlite\"` объединяет шарды и строит граф.")
    d.p("**[Измерено]** по прогону 27.10.2026 (`docs/spike/results/graph-sanity-20261028.md`): 596 из 596 чанков, около 3,2 с на чанк при 4 потоках на RTX 4070. Выходы на разном оборудовании и версиях Ollama не побайтно совпадают (сравнено 3 чанка, ни один не идентичен), поэтому кэши ноутбука и сервера не смешивались; демонстрационный граф построен только по серверному прогону.")
    d.h(2, "Оценка качества")
    d.code("""just eval --short                 # CI-подмножество, без сети
just eval --split dev             # реальный стек
just eval --split test            # один раз на замороженную конфигурацию; отказ при незакоммиченных изменениях
just pre-reveal                   # тест «до раскрытия»; нужна Ollama""")
    d.p("Протокол: результаты dev фиксируются коммитом до запуска test; пороги подбираются только на dev (`eval/golden/split.json`, проверка `scripts/eval/split_check.py`); test-срез запускается один раз на замороженную конфигурацию, повторный запуск для того же коммита и конфигурации отказывает; "
        "к каждому числу прикладываются SHA и хэш конфигурации. Тяжёлые прогоны – на GPU-сервере; на целевом ноутбуке осмысленна только задержка.")

    d.h(1, "Сообщения системному программисту")
    d.table("Диагностика", ["Сообщение / симптом", "Причина", "Действие"],
        [["`preflight: Ollama is not reachable at …`", "Ollama не запущена или другой адрес", "`ollama serve`; `DETECTIVE_BOARD_OLLAMA_HOST`"],
         ["`preflight: model missing: <модель>`", "модель не загружена", "`ollama pull <модель>`"],
         ["`just run` завершился кодом 2 без запуска сервера", "нет файла индекса `data/index/db.sqlite`", "`just index` или распаковать архив; состояние файлов печатается при старте"],
         ["Хранилище отказывается открыть индекс", "настройки эмбеддингов не совпадают с построенным индексом", "привести `embed_model`, `embed_dim`, префиксы в соответствие"],
         ["`/api/health`: `degraded`", "недоступна Ollama, модель, индекс, граф или MCP-процесс", "прочитать поля ответа; при падении подпроцесса MCP метка инструмента `timeline-alibi[in-process]`"],
         ["`sha256sum -c` FAILED", "копия архива повреждена", "скопировать заново"],
         ["`uv sync offline` FAIL (Network connectivity is disabled…)", "в кэше нет колеса для платформы", "архив собран на другой платформе: пересобрать на Linux x86_64"],
         ["`ollama` FAIL «address already in use»", "работает системная Ollama", "`sudo systemctl stop ollama` или `--ollama-port N`"],
         ["`ollama: model IDs differ`", "упакованы другие сборки моделей", "пересобрать архив"],
         ["`api` FAIL на c001", "в графе нет курируемых фактов Wisteria Lodge", "использовать демонстрационный `graph.sqlite` или загрузить курируемые факты"],
         ["`network: the internet is reachable`", "сеть не отключена", "отключить сеть"],
         ["HTTP 429 `busy`", "идёт другой запуск", "дождаться или остановить"],
         ["Коды ошибок API", "`invalid_input` 400, `not_found` 404, `unsupported_media_type` 415, `too_large` 413, `busy` 429, `internal` 500", "детали в журнале; тело ответа не содержит трассы стека и путей"]],
        [2.8, 2.5, 2.4])
    d.change_sheet()
    return d
