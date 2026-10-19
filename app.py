from __future__ import annotations

import asyncio
import base64
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from campuspulse.agent import CampusPulseAgent, run_tool, clean_error
from campuspulse.attachments import prepare_attachments, merge_attachments
from campuspulse.calendar_export import to_ics
from campuspulse.chats import (
    MAX_CHATS, MAX_MESSAGES, initialize_chats, save_active_chat, select_chat,
    create_chat, rename_chat, delete_chat, restore_deleted_chat, clear_chat, auto_title_chat,
)
from campuspulse.cloud_client import query_remote
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
ATTACHMENT_TYPES = ["pdf", "docx", "txt", "md", "png", "jpg", "jpeg", "webp"]
initialize_chats(st.session_state)


def change_chat(widget_key):
    st.session_state.rename_requested = False
    selected = st.session_state.get(widget_key)
    if selected not in st.session_state.chats:
        st.session_state[widget_key] = st.session_state.active_chat_id
        return
    select_chat(st.session_state, selected)


def new_chat():
    try:
        create_chat(st.session_state)
        st.session_state.rename_requested = False
        st.session_state.section = "Агент"
    except ValueError as error:
        st.session_state.chat_notice = str(error)


def chat_action():
    action = st.session_state.chat_actions
    if action == "Переименовать":
        st.session_state.rename_requested = True
    elif action == "Удалить чат":
        st.session_state.rename_requested = False
        delete_chat(st.session_state)


def restore_chat():
    try:
        restore_deleted_chat(st.session_state)
    except ValueError as error:
        st.session_state.chat_notice = str(error)


def dismiss_rename():
    st.session_state.rename_requested = False


@st.dialog("Название чата", icon=":material/edit:", on_dismiss=dismiss_rename)
def rename_chat_dialog():
    chat = st.session_state.chats[st.session_state.active_chat_id]
    with st.form("rename_chat_form"):
        title = st.text_input("Новое название", value=chat["title"], max_chars=60)
        if st.form_submit_button("Сохранить название", type="primary"):
            try:
                rename_chat(st.session_state, title)
                st.session_state.rename_requested = False
                st.rerun()
            except ValueError as error:
                st.error(str(error))


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
    st.button("Новый чат", key="new_chat", icon=":material/add:", type="primary",
              width="stretch", on_click=new_chat, disabled=len(st.session_state.chats) >= MAX_CHATS)
    chat_signature = tuple((chat_id, chat["title"]) for chat_id, chat in st.session_state.chats.items())
    if st.session_state.get("chat_signature") != chat_signature:
        st.session_state.chat_signature = chat_signature
        st.session_state.chat_selector_version = st.session_state.get("chat_selector_version", 0) + 1
    selector_key = f"chat_selection_{st.session_state.chat_selector_version}"
    st.session_state.chat_selector_key = selector_key
    # Streamlit sends formatted labels back from the browser. Renew the widget
    # when labels change, and distinguish identical titles with visible numbers.
    chat_titles = {chat_id: f"{index}. {title}" for index, (chat_id, title) in enumerate(chat_signature, 1)}
    chat_ids = list(st.session_state.chats)
    st.selectbox("Текущий чат", chat_ids, key=selector_key, index=chat_ids.index(st.session_state.active_chat_id),
                 format_func=chat_titles.__getitem__, on_change=change_chat, args=(selector_key,),
                 help="У каждого чата свои сообщения, вложения, задачи и план. Чаты хранятся в текущей сессии вкладки.")
    with st.container(horizontal=True):
        st.button("Очистить чат", key="clear_chat", icon=":material/restart_alt:",
                  help="Удалить переписку текущего чата. Задачи, план и вложения останутся.",
                  on_click=clear_chat, args=(st.session_state,), disabled=not st.session_state.messages)
        st.menu_button("Ещё", ["Переименовать", "Удалить чат"], key="chat_actions", on_click=chat_action)
    if st.session_state.get("deleted_chat"):
        st.button("Вернуть удалённый чат", key="restore_chat", icon=":material/undo:", on_click=restore_chat,
                  disabled=len(st.session_state.chats) >= MAX_CHATS)
    if notice := st.session_state.pop("chat_notice", None):
        st.warning(notice)
    if len(st.session_state.chats) >= MAX_CHATS:
        st.caption(f"Открыто {MAX_CHATS} чатов. Удали ненужный, чтобы создать новый.")
    section = st.radio("Рабочее пространство", ["Агент", "Учебный план", "Материалы", "Подключение"], key="section")
    chat_controls = st.container()
    st.space("small")
    with st.expander("Настройки агента", icon=":material/settings:"):
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
           "start_hour": start_hour, "tasks": st.session_state.tasks, "documents": st.session_state.documents,
           "images": st.session_state.images}
chat_id = st.session_state.active_chat_id
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
        st.badge(f"{len(st.session_state.documents) + len(st.session_state.images)} материалов", color="gray")
    repository = st.text_input("Репозиторий курса", placeholder="https://github.com/owner/course", key="repository", persist_state="session")
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
                if msg.get("attachments"):
                    st.caption("Вложения: " + ", ".join(msg["attachments"]))
                if msg.get("result"):
                    show_trace(msg["result"], f"message_{index}")
        if submission := st.chat_input("Что нужно успеть на этой неделе?", key=f"message_{chat_id}", max_chars=12000,
                                       accept_file="multiple", file_type=ATTACHMENT_TYPES, max_upload_size=5,
                                       disabled=bool(connection_problem), submit_mode="disable"):
            message = submission.text.strip() or "Посмотри прикреплённые материалы и кратко объясни, что в них."
            files = submission.files
            if files:
                try:
                    incoming = prepare_attachments([(file.name, file.getvalue()) for file in files])
                    merged = merge_attachments({"documents": st.session_state.documents,
                                                "images": st.session_state.images}, incoming)
                    st.session_state.documents, st.session_state.images = merged["documents"], merged["images"]
                    context.update(merged)
                except ValueError as error:
                    st.error(str(error))
                    st.stop()
            context["history"] = st.session_state.messages[-10:]
            auto_title_chat(st.session_state, message)
            with st.chat_message("user"):
                st.markdown(message)
                if files:
                    st.caption("Вложения: " + ", ".join(file.name for file in files))
            st.session_state.messages.append({"role": "user", "text": message,
                                             "attachments": [file.name for file in files]})
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
            st.session_state.messages = st.session_state.messages[-MAX_MESSAGES:]
            if result.get("plan"):
                st.session_state.plan = result["plan"]
                st.session_state.last_plan_trace = result
                st.toast("Расписание и календарь готовы в разделе «Учебный план».", icon=":material/calendar_month:")
            save_active_chat(st.session_state)
            st.rerun()
        with chat_controls:
            if st.session_state.plan:
                st.caption("Расписание и скачивание календаря — в разделе «Учебный план».")
            with st.expander("Чат и вложения", icon=":material/tune:"):
                st.caption("Прикрепи файл или фото кнопкой + у поля сообщения. PDF, DOCX, TXT, MD, JPG, PNG, WebP; до 5 файлов по 5 МБ, не более 3 фото и 10 МБ суммарно. При запросе вложения передаются в Google.")
                if (st.session_state.documents or st.session_state.images) and st.button("Убрать все вложения", icon=":material/close:"):
                    st.session_state.documents, st.session_state.images = [], []
                    st.rerun()
                st.caption(f"В сессии доступно до {MAX_CHATS} отдельных чатов, в каждом хранятся последние {MAX_MESSAGES} сообщений. Агент получает только задачи и материалы текущего чата и его последние 10 сообщений (до 2000 символов каждое).")
                st.caption("Чаты хранятся в памяти текущей вкладки и сбрасываются после её закрытия или перезапуска приложения. Очистка чата удаляет только переписку. Через «Ещё» можно переименовать или удалить чат целиком.")

elif section == "Учебный план":
    st.title("Освободи время для главного.")
    st.markdown("Добавь задачи для текущего чата. Планировщик распределит работу до дедлайнов и покажет, что не помещается.")
    with st.form(f"add_task_{chat_id}", clear_on_submit=True):
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
    elif not st.session_state.plan:
        st.caption("Пока нет задач. Добавь первую выше или импортируй актуальные Issues из GitHub в разделе «Агент».")
    if st.session_state.plan:
        show_plan(st.session_state.plan, "planner")
        if st.session_state.get("last_plan_trace"):
            show_trace(st.session_state.last_plan_trace, "planner")

elif section == "Материалы":
    st.title("Конспекты, которые помогают.")
    st.markdown("Загрузи PDF, DOCX, TXT, Markdown или фото. Текст доступен для поиска, а фотографии Gemini рассматривает непосредственно в чате.")
    st.caption("До 5 файлов по 5 МБ, до 3 фото и 10 МБ суммарно. Из PDF читаются первые 40 страниц, из текстовых файлов — до 12000 символов. Страницы сканированного PDF приложи как JPG или PNG. HEIC нужно сначала сохранить как JPG.")
    uploaded = st.file_uploader("Учебные материалы", key=f"materials_{chat_id}", type=ATTACHMENT_TYPES, accept_multiple_files=True, max_upload_size=5)
    st.caption("Материалы хранятся в памяти сессии. При запросе текст и фотографии передаются в Google. Кнопка ниже заменяет текущий набор материалов.")
    if st.button("Использовать выбранные материалы", disabled=not uploaded, type="primary"):
        if len(uploaded) > 5:
            st.error("Выбери не более 5 файлов.")
        else:
            try:
                prepared = prepare_attachments([(f.name, f.getvalue()) for f in uploaded])
                st.session_state.documents, st.session_state.images = prepared["documents"], prepared["images"]
                st.success("Материалы добавлены. Перейди в «Агент» и задай вопрос; файлы повторно прикреплять не нужно.")
            except Exception as error:
                st.error(f"Не удалось прочитать файл: {error}")
    for doc in st.session_state.documents:
        with st.expander(doc["name"], icon=":material/description:"):
            if doc["truncated"]:
                st.warning("Используется только начало документа из-за ограничения объёма.")
            st.text(doc["text"][:3000])
    for photo in st.session_state.images:
        with st.expander(photo["name"], icon=":material/image:"):
            st.image(base64.b64decode(photo["data"]), width="stretch", alt=f"Прикреплённое изображение {photo['name']}")
    if st.session_state.images:
        st.info("Вопросы по фотографиям задавай в разделе «Агент». Поиск ниже работает только по текстовым документам.")
    query = st.text_input("Проверить поиск по материалам", key=f"search_{chat_id}", placeholder="Например: алгоритм Дейкстры")
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
    if (st.session_state.documents or st.session_state.images) and st.button("Убрать материалы из сессии"):
        st.session_state.documents, st.session_state.images = [], []
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

save_active_chat(st.session_state)
if st.session_state.get("rename_requested", False):
    rename_chat_dialog()
