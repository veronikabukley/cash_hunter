---
name: cash-hunter
description: "Work with the Cash Hunter project (github.com/veronikabukley/cash_hunter) — a Python/FastAPI/Streamlit prototype that finds and ranks companies with cash turnover for cold-calling on cash-collection (инкассация) services. Use this skill whenever the user references the Cash Hunter repo, asks to install/run/test it, mentions its components (Retriever, OuroborosAgent, Trainer, CRM stub, dashboard), asks about its scoring formula, or wants to extend/debug/demo it. Covers setup, the 4-step run sequence, the test suite, the internal Python API (Retriever.search, OuroborosAgent.rank/generate_scripts/collect_feedback, Trainer.run), the CRM REST endpoints, and known limitations documented in test_report.md and CONSTITUTION.md. Trigger even for partial mentions like 'запусти cash hunter', 'протестируй ретривер', 'добавь фильтр по тендеру'."
---

# Cash Hunter

Прототип (MVP, хакатон) поиска и ранжирования компаний с наличным оборотом для холодных
звонков по услугам инкассации. Стек: Python 3.10+, pandas, FastAPI/uvicorn, Streamlit.

## Архитектура (pipeline)

```
Retriever (фильтрация) → OuroborosAgent.rank (скоринг) → generate_scripts (тексты для звонка)
    → collect_feedback → Trainer.run (ночной пересчёт весов по фидбеку)
```

| Модуль | Файл | Роль |
|---|---|---|
| Retriever | `retriever/langflow_pipeline.py` | Фильтрует `data/companies.csv` по региону/сфере/выручке/наличным |
| OuroborosAgent | `agent/ouroboros.py` | Скоринг, генерация скриптов звонков, сбор фидбека |
| Trainer | `agent/trainer.py` | Пересчитывает веса сфер по накопленному фидбеку |
| CRM stub | `server/mcp_stub.py` | FastAPI, CRUD для лидов, порт **8000**, докс на `/docs` |
| Dashboard | `dashboard/streamlit_app.py` | Streamlit UI для менеджера, порт **8501** |
| Данные | `data/companies.csv` | 150 компаний, 6 регионов, 6 сфер |

Скоринг: `score = probability × check_amount × tender_factor × sphere_factor`
(`tender_factor` = 5.0 при наличии тендера, иначе 1.0; `sphere_factor`: Аптеки 1.3, HoReCa 1.1,
остальные 1.0). Формула и веса зашиты в `agent/ouroboros.py` (`SPHERE_WEIGHTS`, `TENDER_BONUS`).

## Установка и запуск

Каждый `bash_tool`-вызов — новый шелл: фоновые процессы (`&`) не переживают между вызовами.
Всегда стартовать сервер и делать что-то с ним **в одной команде**, либо использовать
`nohup ... &` и полагаться на то, что процесс не привязан к текущему шеллу.

```bash
git clone https://github.com/veronikabukley/cash_hunter.git && cd cash_hunter

python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt              # pandas, streamlit, fastapi, uvicorn, openai

python generate_data.py                      # только если data/companies.csv отсутствует — обычно уже в репо

# CRM-сервер и дашборд — держать в одном bash-вызове, если нужна проверка ответа
(python -m server.mcp_stub > /tmp/crm.log 2>&1 &) && sleep 3 && curl -s localhost:8000/health

(streamlit run dashboard/streamlit_app.py --server.headless true --server.port 8501 > /tmp/st.log 2>&1 &) && sleep 5 && curl -s -o /dev/null -w "%{http_code}\n" localhost:8501
```

Дашборд: http://localhost:8501 · CRM API + Swagger: http://localhost:8000/docs

## Тесты

```bash
python test_scenarios.py            # всё: 6 тестов + 4 error-теста + демо
python test_scenarios.py --tests    # только 6 тестовых сценариев (нужен запущенный CRM-сервер, порт 8000)
python test_scenarios.py --errors   # обработка ошибок (пустые результаты, битый CSV, CRM офлайн)
python test_scenarios.py --demo     # прогон для презентации
```

`--tests` обращается к CRM stub — запусти `server.mcp_stub` в фоне заранее (см. выше), иначе
шаг с созданием лида в CRM упадёт. Актуальный результат прогона на момент последней проверки:
6/6 тестов и демо проходят; в error-тестах 3/4 чистые, один ловит `KeyError` вместо более
понятного сообщения об ошибке при повреждённом CSV (см. «Известные ограничения»).

## Работа с Python API напрямую

```python
from retriever.langflow_pipeline import Retriever
from agent.ouroboros import OuroborosAgent

retriever = Retriever("data/companies.csv")
companies = retriever.search(region="Москва", sphere="Ритейл", min_revenue=50, min_cash=0)
# search() НЕ поддерживает фильтр по тендеру — только region/sphere/min_revenue/min_cash

agent = OuroborosAgent(csv_path="data/companies.csv")
ranked = agent.rank(companies)                       # добавляет колонку score, сортирует
scripts = agent.generate_scripts(ranked.head(3))      # персонализированные тексты звонков
agent.collect_feedback(lead_id=1, outcome="success")  # пишет в data/feedback.json

from agent.trainer import Trainer
trainer = Trainer("data/feedback.json", "data/weights.json", "data/companies.csv")
report = trainer.run(force=True)   # без force запускается только при 5+ накопленных фидбеках
```

## CRM REST API (`server/mcp_stub.py`, порт 8000)

| Метод | Путь | Назначение |
|---|---|---|
| GET | `/health` | проверка живости |
| POST | `/create_lead` | создать лид (201) |
| GET | `/leads` | список лидов |
| GET | `/leads/{id}` | один лид |
| PUT | `/update_lead/{id}` | обновить лид |
| DELETE | `/leads/{id}` | удалить лид |

Хранилище — плоский JSON-файл через `_read_leads`/`_write_leads`, не БД; годится только для
демо/тестов, не для конкурентного доступа.


## CONSTITUTION.md

В репозитории есть `CONSTITUTION.md`, описывающий концепцию агента-«Ouroboros», который
самостоятельно эволюционирует код через цикл `ooo ralph "..."` / `ooo confirm` / `ooo evaluate`
(Git-коммиты, автооткат, evolution_log.json и т.д.). **Ничего из этого не реализовано в текущем
коде** — нет ни CLI `ooo`, ни автогенерации коммитов, ни `evolution_log.json`. Это документ о
целевой архитектуре (roadmap/DREAM), а не о работающем функционале. Если пользователь просит
что-то из Конституции — явно уточнить, что это пока не реализовано, и не выдавать концепт за
существующую фичу.
