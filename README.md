# CampusPulse AI

Учебный помощник для кейса № 2 Build with AI / GDG Astana. Gemini выбирает инструменты, настоящий MCP-сервер получает данные и рассчитывает учебный план. Streamlit показывает результат, источники и журнал выполненных вызовов.

## Ссылки для сдачи

- [Репозиторий проекта](https://github.com/X-0mEGa-X/campuspulse-ai)
- [Презентация, 8 слайдов](output/presentation/CampusPulse-AI.pptx)
- [Скачать исходники ZIP](https://github.com/X-0mEGa-X/campuspulse-ai/archive/refs/heads/main.zip)
- [Сценарий демонстрации](docs/DEMO.md)

Облачное развёртывание в Agent Engine пока не выполнено. Подробнее о текущем состоянии ниже.

## Что готово

- Чат с Gemini 3.8 Flash через бесплатный Gemini Developer API или Vertex AI.
- Шесть MCP-инструментов: время, дедлайн, GitHub Issues, README, поиск по материалам, планирование.
- Задачи с дедлайнами, дневной бюджет времени, расписание и экспорт `.ics`.
- Загрузка PDF/TXT/MD и поиск по содержимому с названием источника.
- Режим «Только инструменты» для проверки MCP без LLM.
- Скрипт развёртывания через `reasoning_engines.ReasoningEngine.create` и клиент удалённого агента.
- 16 автоматических тестов, включая реальные MCP subprocess-сессии и Streamlit AppTest.

**Статус на 19.10.2026:** локальный Gemini и вызовы MCP проверены. Журнал реального запроса находится в `docs/live-run.json`. GitHub API в последней проверке вернул rate limit, и агент явно сообщил об ошибке. Ранее прямой MCP-запрос к GitHub был успешен. **Agent Engine не развёрнут:** Google Cloud требует активный биллинг, который в текущем проекте не удалось подключить. Наличие deploy-скрипта не является подтверждением облачного развёртывания.

## Быстрый запуск

Нужен Python 3.12. На подготовленном компьютере достаточно открыть `START-CampusPulse.cmd`.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
# Укажи GEMINI_API_KEY в локальном .env. Не публикуй этот файл.
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Открой <http://localhost:8501>. Если ключ не настроен, выбери «Только инструменты». Ключ можно получить в [Google AI Studio](https://aistudio.google.com/api-keys). Для некоторых моделей есть [бесплатный уровень с квотами](https://ai.google.dev/gemini-api/docs/pricing). Бесплатный режим может использовать переданные данные для улучшения продуктов Google: не загружай конфиденциальные материалы.

Для уже авторизованного владельца GCP-проекта предусмотрен `scripts/setup_gemini_free.py --project PROJECT_ID`: он включает необходимые API и сохраняет ключ, ограниченный Generative Language API, в `.env`. Он не включает биллинг.

В этой сети основной адрес Gemini сбрасывает соединение. Проверенный локальный `.env` использует `GEMINI_API_ENDPOINT=mtls`, официальный альтернативный адрес Google. Приложение разрешает только два фиксированных домена Google и не отключает проверку сертификатов. На другом компьютере сначала используй `standard`. Источник: [официальный клиент Google](https://github.com/googleapis/google-cloud-python/blob/main/packages/google-ai-generativelanguage/google/ai/generativelanguage_v1beta/services/generative_service/client.py).

## Как показать демо

1. «Учебный план»: добавь две собственные задачи, сроки и оценку времени.
2. «Агент», режим Gemini API: «Составь план для добавленных задач на неделю. Проверь текущее время и учти мой дневной лимит».
3. Раскрой «Журнал действий»: видны имена инструментов, аргументы, результаты и длительность.
4. Скачай `.ics` и импортируй в свой календарь вручную.
5. «Материалы»: загрузи конспект, нажми «Использовать выбранные материалы», затем задай вопрос в чате.
6. Укажи публичный учебный GitHub-репозиторий и попроси проверить задачи. При анонимном rate limit покажи явную ошибку либо повтори после сброса квоты. Не выдавай старые результаты за свежие.

Полный сценарий выступления: [docs/DEMO.md](docs/DEMO.md). Архитектура и соответствие кейсу: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

Протокол выполненных проверок: [docs/VERIFICATION.md](docs/VERIFICATION.md).

## MCP

```powershell
.\.venv\Scripts\python.exe -m campuspulse.mcp_server
```

Транспорт: stdio, клиент и сервер из официального Python MCP SDK. `mcp.json` содержит конфигурацию для запуска из корня проекта в активированной виртуальной среде. Gemini получает схемы через `tools/list`, а не из заранее написанного списка function declarations. Внутренний `load_materials` загружает документы в память отдельного процесса и не предоставляется модели.

## Agent Engine после получения проекта с биллингом

Нужны Google Cloud CLI, активный биллинг, права включать API и создавать ресурсы Vertex AI / Cloud Storage. Запуск следующего раздела может создавать платные ресурсы. Текущий локальный Gemini API этого не требует.

```powershell
gcloud auth application-default login
gcloud auth application-default set-quota-project PROJECT_ID
.\.venv\Scripts\python.exe scripts/configure_cloud.py --project PROJECT_ID
.\.venv\Scripts\python.exe scripts/deploy.py --project PROJECT_ID --bucket gs://UNIQUE_STAGING_BUCKET --dry-run
.\.venv\Scripts\python.exe scripts/deploy.py --project PROJECT_ID --bucket gs://UNIQUE_STAGING_BUCKET
.\.venv\Scripts\python.exe scripts/smoke_cloud.py
```

Регион runtime по умолчанию `us-central1`, endpoint модели `global`. Deploy создаёт закрытый staging bucket с uniform bucket access и упаковывает `campuspulse`. Реальное имя ресурса сохраняется в игнорируемый `deployment.json`. После успешного smoke-теста переключи UI на Agent Engine. Ключ Gemini Developer API в облачный пакет не включается. Текущий скрипт подготовлен и проверен в dry-run, но создание runtime ещё не проверено.

`Dockerfile` позволяет отдельно разместить UI на хостинге с поддержкой контейнеров. Публичный сайт в этой поставке не опубликован. Перед открытым доступом нужны аутентификация, квоты на пользователя и управление секретами.

## Проверки

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
# Отдельная платформа-зависимая проверка: расходует бесплатную квоту Gemini.
.\.venv\Scripts\python.exe scripts/smoke_local.py
```

Тест модели в `tests/test_agent.py` использует управляемые ответы модели и настоящий MCP. Он проверяет протокол и не подменяет live-проверку Gemini.

## Ограничения

- До 30 задач, до 5 документов по 5 МБ. Из PDF читаются первые 40 страниц и до 12 000 символов на документ. OCR не включён.
- Поиск по материалам лексический. Документы и задачи хранятся только в текущей сессии, без базы данных.
- История чата видна в UI, но запрос модели получает только текущие задачи, материалы и текст нового запроса.
- GitHub: открытые Issues из первой страницы API (100 элементов, включая PR), до 30 Issues. Срок извлекается из `Due: YYYY-MM-DD`, `Deadline: ...`, `Дедлайн: ...`, `Срок: ...` или milestone.
- Неизвестные сроки остаются неизвестными. Если оценка времени отсутствует, планировщик использует 60 минут и помечает допущение.
- Учебные окна фиксированы по выбранному началу и бюджету. Пары, личные события, праздники и перерывы автоматически не импортируются.
- Восемь итераций модели и общий лимит 150 секунд. Все инструменты только читают данные или считают. Отправка сообщений и запись в сторонние календари отсутствуют.
- Журнал показывает наблюдаемые действия. Внутренние скрытые рассуждения модели не публикуются.

## Файлы

`app.py` — UI. `campuspulse/agent.py` — цикл Gemini/MCP. `mcp_server.py` — сервер. `tools.py` — источники и расчёты. `scripts/deploy.py` — Agent Engine. `tests/` — проверки. `output/presentation/` — презентация. `docs/` — сценарий и техническое описание.

`.env`, ADC, виртуальная среда и SDK не входят в архив и Git. API-ключ находится только в локальном `.env`.
