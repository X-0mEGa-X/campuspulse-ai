# Проверка поставки, 19 октября 2026

| Проверка | Результат |
|---|---|
| pytest | 16 passed, последний запуск 10.62 с |
| MCP initialize / tools/list / tools/call | Успешно, реальный subprocess stdio |
| GitHub Issues через MCP | Первый запрос успешен; последующий вернул anonymous rate limit |
| Gemini Developer API | Реальный ответ модели получен без активного Cloud billing |
| Gemini выбирает MCP tools | get_current_time и get_github_issues, сохранено в live-run.json |
| Планирование через Gemini в браузере | get_current_time и plan_study_week, оба успешны |
| Результат примера | 2 задачи по 90 минут, 4 блока, 180 минут, остаток 0 |
| Agent Engine deploy --dry-run | Конфигурация и импорт SDK проверены |
| Agent Engine create / remote smoke | Не выполнялись: billingEnabled=false |
| Презентация | 8 слайдов, проверены пакет, геометрия, шрифты и импорт |
| GitHub | Исходники опубликованы в X-0mEGa-X/campuspulse-ai, ветка main |

Скриншоты реальных проверок: [план](images/plan.png), [ответ Gemini](images/agent.png), [журнал вызовов](images/trace.png).

Автотест протокола использует управляемую модель и настоящий MCP. Он не выдаётся за live-тест Gemini. Сохранённый live-run.json содержит ответ с ошибкой GitHub rate limit и не является свежим списком задач.

Презентация не проверялась в настольном Microsoft PowerPoint. Все слайды визуально просмотрены в рендере Artifact Tool.
