"""
Cash Hunter — Streamlit Dashboard для менеджера по продажам инкассации.

Связывает Retriever (поиск), OuroborosAgent (ранжирование, скрипты),
Trainer (ночное обучение) и MCP CRM Stub (создание лидов) в один UI.

Запуск:
  cd ~/Desktop/cash-hunter
  .venv/bin/streamlit run dashboard/streamlit_app.py --server.port 8501
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import requests
import streamlit as st

# ── Пути и импорты ───────────────────────────────────────────────────────────

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from retriever.langflow_pipeline import Retriever  # noqa: E402
from agent.ouroboros import OuroborosAgent  # noqa: E402
from agent.trainer import Trainer  # noqa: E402

DATA_DIR = _PROJECT_ROOT / "data"
CRM_URL = "http://0.0.0.0:8000"

REGIONS = ["Москва", "Санкт-Петербург", "Казань", "Новосибирск", "Екатеринбург", "Ростов-на-Дону"]
SPHERES = ["Ритейл", "Аптеки", "HoReCa", "Строительство", "Автобизнес", "АЗС"]


# ── Кэширование тяжёлых объектов ────────────────────────────────────────────


@st.cache_resource
def get_agent() -> OuroborosAgent:
    """Создать агента один раз и кэшировать."""
    return OuroborosAgent(
        csv_path=str(DATA_DIR / "companies.csv"),
        feedback_path=str(DATA_DIR / "feedback.json"),
        weights_path=str(DATA_DIR / "weights.json"),
    )


@st.cache_resource
def get_trainer() -> Trainer:
    """Создать тренера для аналитики и ручного запуска."""
    return Trainer(
        feedback_path=str(DATA_DIR / "feedback.json"),
        weights_path=str(DATA_DIR / "weights.json"),
        companies_path=str(DATA_DIR / "companies.csv"),
    )


# ── Вспомогательные функции ─────────────────────────────────────────────────


def load_feedback_list() -> list[dict]:
    """Загрузить все записи фидбека из файла."""
    p = DATA_DIR / "feedback.json"
    if not p.exists():
        return []
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        # Файл повреждён — возвращаем пустой список
        return []


def crm_create_lead(payload: dict) -> tuple[bool, str]:
    """
    Отправить лид в MCP-сервер CRM.

    Returns (success, message).
    """
    try:
        resp = requests.post(f"{CRM_URL}/create_lead", json=payload, timeout=5)
        if resp.status_code == 201:
            data = resp.json()
            return True, f"Лид #{data['id']} создан в CRM"
        return False, f"CRM error {resp.status_code}: {resp.text}"
    except requests.exceptions.ConnectionError:
        return False, "CRM-сервер недоступен (порт 8000)"
    except Exception as exc:
        return False, f"Ошибка CRM: {exc}"


def get_stats() -> dict:
    """Посчитать статистику звонков."""
    fb = load_feedback_list()
    total = len(fb)
    success = sum(1 for f in fb if f.get("success"))
    conv = round(success / total * 100, 1) if total else 0.0
    return {"total": total, "success": success, "conversion": conv}


def get_inn(company_id: int) -> str:
    """Получить ИНН компании по id из CSV."""
    import pandas as pd
    df = pd.read_csv(DATA_DIR / "companies.csv")
    row = df[df["id"] == company_id]
    if row.empty:
        return ""
    return str(row.iloc[0]["ИНН"])


# ── Инициализация session_state ─────────────────────────────────────────────

if "search_results" not in st.session_state:
    st.session_state.search_results = None
if "feedback_form_id" not in st.session_state:
    st.session_state.feedback_form_id = None


# ── Заголовок страницы ──────────────────────────────────────────────────────

st.set_page_config(page_title="Cash Hunter", page_icon="🎯", layout="wide")
st.title("🎯 Cash Hunter — Цели дня")
st.caption("Поиск и ранжирование компаний для звонков по инкассации")

# ── Боковая панель: фильтры + аналитика ─────────────────────────────────────

with st.sidebar:
    st.header("🔧 Фильтры")

    region = st.selectbox("Регион", REGIONS, index=0)
    sphere = st.selectbox("Сфера", ["(все)"] + SPHERES, index=0)
    min_revenue = st.number_input(
        "Мин. выручка (млн ₽)", min_value=0, value=50, step=10
    )
    min_cash = st.number_input(
        "Мин. объём наличных (млн ₽)", min_value=0, value=10, step=5
    )

    sphere_param = None if sphere == "(все)" else sphere

    if st.button("🔍 Найти цели", type="primary", use_container_width=True):
        agent = get_agent()
        result = agent.run(
            region=region,
            sphere=sphere_param,
            min_revenue=min_revenue,
            min_cash=min_cash,
            top_n=5,
        )
        st.session_state.search_results = result
        st.session_state.feedback_form_id = None

    st.divider()

    # ── Аналитика ─────────────────────────────────────────────────────────

    st.header("📊 Аналитика")
    stats = get_stats()
    col1, col2, col3 = st.columns(3)
    col1.metric("Звонков", stats["total"])
    col2.metric("Успешных", stats["success"])
    col3.metric("Конверсия", f"{stats['conversion']}%")

    st.divider()

    # ── Ручной запуск ночного обучения ──────────────────────────────────

    st.header("🧠 Ночное обучение")
    if st.button("Запустить ночное обучение", use_container_width=True):
        trainer = get_trainer()
        report = trainer.run(force=True)
        if report["status"] == "trained":
            st.success(
                f"✅ Обучение завершено! "
                f"Фидбеков: {report['feedback_count']}, "
                f"обновление #{report['update_count']}"
            )
            with st.expander("Новые веса сфер"):
                for sphere_name, weight in report.get("new_weights", {}).items():
                    st.write(f"  **{sphere_name}**: {weight}")
        else:
            st.warning(f"⏭️ {report.get('reason', 'Недостаточно данных')}")

    # ── Статус CRM ───────────────────────────────────────────────────────

    st.divider()
    st.header("🔗 CRM статус")
    try:
        health = requests.get(f"{CRM_URL}/health", timeout=2).json()
        st.success("CRM: онлайн")
    except Exception:
        st.error("CRM: офлайн (порт 8000)")


# ── Основная область: Топ-5 целей ────────────────────────────────────────────

results = st.session_state.search_results

if results is None:
    st.info("👈 Нажмите «Найти цели» на боковой панели, чтобы начать.")
    st.stop()

if results["count"] == 0:
    st.warning("Ничего не найдено. Попробуйте изменить фильтры — снизить минимальную выручку или объём наличных.")
    st.stop()

st.subheader(f"Топ-5 целей ({results['count']} компаний найдено)")

for idx, company in enumerate(results["ranked"][:5]):
    score = company["score"]
    tender = "✓" if str(company.get("Наличие_тендера", "")).strip().lower() == "да" else "—"

    with st.container(border=True):
        col_name, col_sphere, col_region, col_cash, col_score = st.columns(
            [3, 2, 2, 2, 1]
        )

        col_name.markdown(f"### {idx + 1}. {company['Название']}")
        col_sphere.write(f"**Сфера:** {company['Сфера']}")
        col_region.write(f"**Регион:** {company['Регион']}")
        col_cash.write(
            f"**Наличные:** {company['Объём_наличных_млн_руб']:,.0f} млн ₽"
        )
        col_score.metric("Рейтинг", f"{score:.1f}")

        # Скрипт для звонка
        scripts = results.get("scripts", [])
        script_text = next(
            (s["script"] for s in scripts if s["company_id"] == company["id"]),
            "",
        )
        if script_text:
            with st.expander("📞 Скрипт звонка"):
                st.write(script_text)

        if tender == "✓":
            tender_sum = company.get("Сумма_тендера_млн_руб", 0)
            st.caption(f"🏆 Тендер на {tender_sum:,.0f} млн ₽")

        # Кнопка "Звонок выполнен"
        btn_key = f"call_done_{company['id']}"
        if st.button("📞 Звонок выполнен", key=btn_key):
            st.session_state.feedback_form_id = company["id"]

        # ── Форма оценки звонка ──────────────────────────────────────────

        if st.session_state.feedback_form_id == company["id"]:
            with st.form(key=f"feedback_form_{company['id']}"):
                st.markdown("#### Оценка звонка")

                result_radio = st.radio(
                    "Результат",
                    ["Заинтересован", "Не заинтересован"],
                    key=f"result_{company['id']}",
                )
                quality = st.slider(
                    "Оценка качества цели",
                    min_value=1,
                    max_value=5,
                    value=3,
                    key=f"quality_{company['id']}",
                )
                comment = st.text_area(
                    "Комментарий (опционально)",
                    value="",
                    key=f"comment_{company['id']}",
                    height=80,
                )

                col_submit, col_cancel = st.columns([1, 1])
                submitted = col_submit.form_submit_button("Сохранить", type="primary")
                cancelled = col_cancel.form_submit_button("Отмена")

            if submitted:
                success = result_radio == "Заинтересован"

                # 1. Сохранить фидбек через агента
                agent = get_agent()
                try:
                    agent.collect_feedback(
                        company_id=company["id"],
                        score=quality,
                        success=success,
                    )
                    fb_msg = "✅ Фидбек сохранён"
                except Exception as exc:
                    fb_msg = f"❌ Ошибка фидбека: {exc}"
                    success = False

                # 2. Отправить лид в CRM
                lead_payload = {
                    "company_id": company["id"],
                    "name": company["Название"],
                    "inn": get_inn(company["id"]),
                    "region": company["Регион"],
                    "score": float(company["score"]),
                    "script": script_text,
                    "status": "interested" if success else "rejected",
                }
                crm_ok, crm_msg = crm_create_lead(lead_payload)

                # 3. Уведомление
                if "✅" in fb_msg and crm_ok:
                    st.success(f"{fb_msg} | {crm_msg}")
                elif "✅" in fb_msg and not crm_ok:
                    st.warning(f"{fb_msg} | ⚠️ {crm_msg}")
                else:
                    st.error(f"{fb_msg} | {crm_msg}")

                st.session_state.feedback_form_id = None
                st.rerun()

            if cancelled:
                st.session_state.feedback_form_id = None
                st.rerun()
