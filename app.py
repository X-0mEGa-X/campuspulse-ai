from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from campuspulse.agent import CampusPulseAgent, run_tool, clean_error
from campuspulse.calendar_export import to_ics
from campuspulse.cloud_client import query_remote
from campuspulse.documents import extract_document
from campuspulse.tools import now_in

st.set_page_config(page_title="CampusPulse AI", page_icon=":material/school:", layout="wide")
load_dotenv()
ROOT = Path(__file__).parent
deployment = {}
if (ROOT / "deployment.json").exists():
    deployment = json.loads((ROOT / "deployment.json").read_text(encoding="utf-8"))
project = os.getenv("GOOGLE_CLOUD_PROJECT", "")
resource = os.getenv("AGENT_ENGINE_RESOURCE") or deployment.get("resource_name", "")
model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
for key, value in {"tasks": [], "documents": [], "messages": [], "last_result": None, "plan": None}.items():
    st.session_state.setdefault(key, value)


def show_trace(result: dict, key: str):
    events = result.get("events", [])
    with st.expander(f"Журнал действий ({sum(e['kind'] == 'tool' for e in events)})", icon=":material/account_tree:"):
        st.caption("Фактические вызовы и результаты инструментов. Внутренние рассуждения модели не отображаются.")
        tool_number = 0
        for event in events:
            if event["kind"] == "connect":
                st.caption(f"MCP / stdio · доступно {event['tool_count']} инструментов")
                continue
            tool_number += 1
            st.markdown(f"**{tool_number}. `{event['name']}`** · {event['duration_ms']} мс · {'готово' if event['ok'] else 'ошибка'}")
            with st.expander("Аргументы и результат"):
                st.json({"arguments": event["arguments"], "result": event["output"]})
        st.download_button("Скачать журнал JSON", json.dumps(result, ensure_ascii=False, indent=2),
                           file_name="campuspulse-run.json", mime="application/json", key=f"trace_{key}")


def show_plan(plan: dict, key: str):
    st.subheader("Твой учебный план", icon=":material/calendar_month:")
    a, b, c = st.columns(3)
    a.metric("Запланировано", f"{plan['scheduled_minutes']} мин", border=True)
    b.metric("Учебных блоков", len(plan["sessions"]), border=True)
    c.metric("Задач с нехваткой времени", len(plan["unscheduled"]), border=True)
    if plan["unscheduled"]:
        for item in plan["unscheduled"]:
            reason = "срок уже прошёл" if item["reason"] == "deadline_passed" else "не хватает времени до срока или конца периода"
            st.warning(f"{item['title']}: не распределено {item['minutes']} мин — {reason}.")
    if plan["sessions"]:
        rows = [{"Дата": datetime.fromisoformat(s["start"]).strftime("%d.%m"),
                 "Начало": datetime.fromisoformat(s["start"]).strftime("%H:%M"),
                 "Конец": datetime.fromisoformat(s["end"]).strftime("%H:%M"),
                 "Задача": s["title"], "Минуты": s["minutes"],
                 "Срок": s["due_at"] or "Не указан", "Оценка по умолчанию": s["estimated_by_default"]} for s in plan["sessions"]]
        st.dataframe(rows, hide_index=True, width="stretch", alt="Учебные блоки по дням и времени")
        st.download_button("Скачать в календарь (.ics)", to_ics(plan), file_name="campuspulse-plan.ics",
                           mime="text/calendar", icon=":material/download:", key=f"ics_{key}")
    st.caption(f"Часовой пояс: {plan['timezone']}. Существующие пары и события календаря не импортируются. Проверь план перед импортом.")


with st.sidebar:
    st.title("CampusPulse", icon=":material/school:")
    st.caption("AI study companion")
    section = st.radio("Рабочее пространство", ["Агент", "Учебный план", "Материалы", "Подключение"], key="section")
    st.space("small")
    cloud_modes = st.toggle("Показать режимы Google Cloud", value=False,
                            help="Vertex AI и Agent Engine требуют отдельного проекта с активным биллингом.")
    backend_options = ["Gemini API", "Только инструменты"] + (["Vertex AI", "Agent Engine"] if cloud_modes else [])
    if st.session_state.get("backend") not in backend_options:
        st.session_state.backend = "Gemini API" if os.getenv("GEMINI_API_KEY") else "Только инструменты"
    backend = st.selectbox("Режим работы", backend_options,
                           format_func=lambda option: "Gemini API · бесплатная квота" if option == "Gemini API" else option, key="backend")
    if backend == "Gemini API":
        st.caption("Прямое подключение к Gemini Flash. Для ключа на бесплатном тарифе действуют квоты. Приложение не подключает биллинг и не переключается на Vertex AI автоматически.")
    timezone = st.selectbox("Часовой пояс", ["Asia/Almaty", "Asia/Astana", "Asia/Bishkek", "UTC", "Europe/Moscow"], key="timezone")
    # Astana is represented by the canonical IANA zone Asia/Almaty.
    timezone = "Asia/Almaty" if timezone == "Asia/Astana" else timezone
    daily_minutes = st.slider("Минут на учёбу в день", 30, 240, 120, step=15)
    start_hour = st.slider("Начало занятий", 6, 22, 18, format="%d:00")
    st.caption(f"{now_in(timezone).strftime('%d.%m.%Y')} · {timezone}")
    st.caption("Build with AI · GDG Astana")

context = {"timezone": timezone, "daily_minutes": daily_minutes, "days": 7,
           "start_hour": start_hour, "tasks": st.session_state.tasks, "documents": st.session_state.documents}
connection_problem = None
if backend == "Gemini API" and not os.getenv("GEMINI_API_KEY"):
    connection_problem = "Добавь GEMINI_API_KEY из Google AI Studio в .env и перезапусти приложение. Пока можно выбрать «Только инструменты»."
elif backend == "Agent Engine" and not resource:
    connection_problem = "Agent Engine ещё не развёрнут. Для бесплатного локального чата выбери «Gemini API»."
elif backend == "Vertex AI" and not project:
    connection_problem = "Для Vertex AI требуется GOOGLE_CLOUD_PROJECT. Для бесплатного локального чата выбери «Gemini API»."

if section == "Агент":
    st.caption("ТВОЯ НЕДЕЛЯ ПОД КОНТРОЛЕМ")
    st.title("Разберёмся с учёбой.")
    st.markdown("Задания, дедлайны и конспекты — в одном разговоре. Агент обращается к источникам и показывает выполненные действия.")
    with st.container(horizontal=True):
        st.badge(backend, color="blue", icon=":material/cloud:" if backend == "Agent Engine" else ":material/auto_awesome:")
        st.badge(f"{len(st.session_state.tasks)} задач", color="gray")
        st.badge(f"{len(st.session_state.documents)} материалов", color="gray")
    repository = st.text_input("Репозиторий курса", placeholder="https://github.com/owner/course", key="repository")
    context["repository"] = repository
    if backend == "Только инструменты":
        st.info("Gemini в этом режиме не используется. Кнопки ниже вызывают настоящий MCP-сервер по заданному сценарию.")
        left, right = st.columns(2)
        action = None
        if left.button("Получить задачи из GitHub", icon=":material/code:", width="stretch", disabled=not repository):
            action = ("get_github_issues", {"repository": repository})
        if right.button("Проверить MCP и время", icon=":material/verified:", width="stretch"):
            action = ("get_current_time", {"timezone": timezone})
        if action:
            with st.spinner("MCP выполняет запрос…"):
                try:
                    st.session_state.last_result = asyncio.run(run_tool(*action))
                except Exception as error:
                    st.error(clean_error(error))
        if st.session_state.last_result:
            result = st.session_state.last_result
            if result.get("output", {}).get("issues") is not None:
                st.dataframe(result["output"]["issues"], hide_index=True, alt="Актуальные задачи GitHub")
                if st.button("Добавить задачи GitHub в учебный план", key="import_issues"):
                    known = {t.get("source_url") for t in st.session_state.tasks if t.get("source_url")}
                    for item in result["output"]["issues"]:
                        if item["source_url"] not in known and len(st.session_state.tasks) < 30:
                            st.session_state.tasks.append({k: item.get(k) for k in ("title", "due_at", "estimated_minutes", "source_url")})
                    st.toast("Задачи добавлены")
            else:
                st.json(result.get("output", {}))
            show_trace(result, "playground")
    else:
        st.caption("Примеры: «Проверь задания в репозитории и составь план на неделю» · «Объясни тему из конспекта»")
        if connection_problem:
            st.warning(connection_problem)
        if not st.session_state.messages:
            with st.chat_message("assistant", avatar=":material/school:"):
                st.markdown("Привет! Добавь задачи или материалы и расскажи, что нужно успеть. Если укажешь репозиторий курса, я проверю его актуальные задания.")
        for index, msg in enumerate(st.session_state.messages):
            with st.chat_message(msg["role"]):
                st.markdown(msg["text"])
                if msg.get("result"):
                    show_trace(msg["result"], f"message_{index}")
        if message := st.chat_input("Что нужно успеть на этой неделе?", max_chars=12000,
                                    disabled=bool(connection_problem), submit_mode="disable"):
            context["history"] = st.session_state.messages[-10:]
            with st.chat_message("user"):
                st.markdown(message)
            st.session_state.messages.append({"role": "user", "text": message})
            with st.chat_message("assistant"):
                with st.status("Агент обращается к Gemini и инструментам…", expanded=True) as status:
                    st.caption("Получение ответа может занять до двух минут.")
                    try:
                        if backend == "Agent Engine":
                            result = query_remote(resource, message, context)
                        else:
                            result = CampusPulseAgent(project=project if backend == "Vertex AI" else None,
                                                      location=os.getenv("GOOGLE_CLOUD_LOCATION", "global"), model=model).query(message, context)
                    except Exception as error:
                        result = {"answer": clean_error(error, "agent_engine" if backend == "Agent Engine" else "vertex" if backend == "Vertex AI" else "gemini"), "events": [], "ok": False}
                    status.update(label="Ответ готов" if result.get("ok") else "Запрос требует внимания",
                                  state="complete" if result.get("ok") else "error", expanded=False)
                st.markdown(result["answer"])
                show_trace(result, f"message_{len(st.session_state.messages)}")
            st.session_state.messages.append({"role": "assistant", "text": result["answer"], "result": result})
            st.session_state.messages = st.session_state.messages[-12:]
            if result.get("plan"):
                st.session_state.plan = result["plan"]
        if st.session_state.plan:
            show_plan(st.session_state.plan, "chat")
        if st.session_state.messages and st.button("Очистить разговор", icon=":material/restart_alt:"):
            st.session_state.messages = []
            st.rerun()
        st.caption("Агент учитывает текущие задачи, материалы и последние 10 сообщений (до 2000 символов каждое). Очистка разговора удаляет контекст переписки.")

elif section == "Учебный план":
    st.title("Освободи время для главного.")
    st.markdown("Добавь задачи. Планировщик распределит работу до дедлайнов и покажет, что не помещается.")
    with st.form("add_task", clear_on_submit=True):
        title = st.text_input("Название задачи", placeholder="Подготовить лабораторную по Python", max_chars=200)
        first, second, third = st.columns(3)
        due_date = first.date_input("Дата сдачи", value=now_in(timezone).date() + timedelta(days=3))
        estimate = second.number_input("Оценка времени, минуты", min_value=15, max_value=1440, value=90, step=15)
        no_deadline = third.checkbox("Срок пока неизвестен")
        if st.form_submit_button("Добавить задачу", type="primary", icon=":material/add:"):
            if not title.strip():
                st.error("Введи название задачи.")
            elif len(st.session_state.tasks) >= 30:
                st.error("Для прототипа доступно не более 30 задач.")
            else:
                st.session_state.tasks.append({"title": title.strip(), "due_at": None if no_deadline else due_date.isoformat(),
                                               "estimated_minutes": estimate, "source_url": None})
                st.session_state.plan = None
    if st.session_state.tasks:
        st.dataframe(st.session_state.tasks, hide_index=True, column_config={
            "title": "Задача", "due_at": "Дедлайн", "estimated_minutes": "Минуты", "source_url": st.column_config.LinkColumn("Источник")},
            alt="Задачи для планирования")
        with st.container(horizontal=True):
            generate = st.button("Составить план через MCP", type="primary", icon=":material/calendar_add_on:")
            if st.button("Очистить задачи", icon=":material/restart_alt:"):
                st.session_state.tasks, st.session_state.plan = [], None
                st.rerun()
        if generate:
            with st.spinner("Распределяю учебные блоки…"):
                try:
                    result = asyncio.run(run_tool("plan_study_week", {k: context[k] for k in ("tasks", "daily_minutes", "days", "timezone", "start_hour")}))
                    st.session_state.plan = result.get("plan")
                    st.session_state.last_plan_trace = result
                    if not result["ok"]:
                        st.error(str(result["output"]))
                except Exception as error:
                    st.error(clean_error(error))
    else:
        st.caption("Пока нет задач. Добавь первую выше или импортируй актуальные Issues из GitHub в разделе «Агент».")
    if st.session_state.plan:
        show_plan(st.session_state.plan, "planner")
        if st.session_state.get("last_plan_trace"):
            show_trace(st.session_state.last_plan_trace, "planner")

elif section == "Материалы":
    st.title("Конспекты, которые помогают.")
    st.markdown("Загрузи PDF, TXT или Markdown. Агент сможет найти нужный фрагмент и объяснить тему со ссылкой на источник.")
    st.caption("До 5 файлов по 5 МБ. Из PDF читаются первые 40 страниц, из каждого файла — до 12000 символов. OCR для сканов не включён.")
    uploaded = st.file_uploader("Учебные материалы", type=["pdf", "txt", "md"], accept_multiple_files=True)
    st.caption("Материалы хранятся в памяти сессии. При запросе к Gemini текст передаётся в Google. Используй материалы, которыми можно делиться.")
    if st.button("Использовать выбранные материалы", disabled=not uploaded, type="primary"):
        if len(uploaded) > 5:
            st.error("Выбери не более 5 файлов.")
        else:
            try:
                st.session_state.documents = [extract_document(f.name, f.getvalue()) for f in uploaded]
                st.success("Материалы готовы для поиска.")
            except Exception as error:
                st.error(f"Не удалось прочитать файл: {error}")
    for doc in st.session_state.documents:
        with st.expander(doc["name"], icon=":material/description:"):
            if doc["truncated"]:
                st.warning("Используется только начало документа из-за ограничения объёма.")
            st.text(doc["text"][:3000])
    query = st.text_input("Проверить поиск по материалам", placeholder="Например: алгоритм Дейкстры")
    if st.button("Найти через MCP", disabled=not query or not st.session_state.documents):
        try:
            with st.spinner("Ищу в материалах…"):
                result = asyncio.run(run_tool("search_study_materials", {"query": query}, st.session_state.documents))
            matches = result["output"].get("matches", [])
            if not matches:
                st.info("Совпадений нет. Попробуй слова, которые есть в документе.")
            for match in matches:
                st.markdown(f"**{match['source']}**")
                st.text(match["excerpt"])
            show_trace(result, "materials")
        except Exception as error:
            st.error(clean_error(error))
    if st.session_state.documents and st.button("Убрать материалы из сессии"):
        st.session_state.documents = []
        st.rerun()

else:
    st.title("Подключение и архитектура")
    st.markdown("**Streamlit → Gemini → MCP → источники и расчёты → учебный план**")
    st.markdown("Gemini выбирает инструменты. MCP-сервер выполняет запросы GitHub, поиск по материалам и расчёт расписания. Agent Engine предоставляет облачный API агента.")
    st.json({"project": project or "не задан", "model": model, "model_location": os.getenv("GOOGLE_CLOUD_LOCATION", "global"),
             "agent_engine": resource or "не развёрнут", "mcp_transport": "stdio", "tools": 6})
    st.caption("Наличие настроек не означает, что соединение проверено. Успешный ответ в чате подтверждает доступ для данного запроса.")
    if connection_problem:
        st.warning(connection_problem)
    if st.button("Проверить бесплатный Gemini", disabled=not os.getenv("GEMINI_API_KEY")):
        with st.spinner("Проверяю Gemini API и вызов MCP…"):
            result = CampusPulseAgent(model=model).query("Проверь текущее время через инструмент. Ответь одним предложением.", {"timezone": timezone})
        if result.get("ok"):
            st.success(result["answer"])
        else:
            st.error(result["answer"])
        show_trace(result, "connection")
    if st.button("Проверить MCP", type="primary"):
        try:
            result = asyncio.run(run_tool("get_current_time", {"timezone": timezone}))
            (st.success if result["ok"] else st.error)(result["answer"])
            st.json(result["output"])
        except Exception as error:
            st.error(clean_error(error))
    st.subheader("Ограничения прототипа")
    st.markdown("- GitHub: открытые задачи из первой страницы API, до 30 результатов.\n- Дедлайны извлекаются из `Due: YYYY-MM-DD` или milestone.\n- Поиск по конспектам работает по ключевым словам.\n- В плане нет автоматического импорта расписания пар.\n- Агент ограничен 8 шагами, файлы и задачи живут только в сессии.\n- Журнал показывает вызовы инструментов и их результаты.")
    st.link_button("Консоль проекта Google Cloud", f"https://console.cloud.google.com/home/dashboard?project={project}")
