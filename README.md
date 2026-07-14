# Cash Hunter

Поиск и ранжирование компаний с наличным оборотом для холодных звонков по услугам инкассации.

## Возможности

- **Retriever** — фильтрация компаний по региону, сфере, выручке, объёму наличных
- **Agent** — ранжирование целей (вероятность × чек × бонусы за тендер и сферу), генерация скриптов звонков
- **Trainer** — ночное обучение: пересчёт весов по фидбеку звонков
- **CRM stub** — FastAPI-сервер с CRUD для лидов (port 8000)
- **Dashboard** — Streamlit-интерфейс для менеджера (port 8501)
- **Тесты** — 6 сценариев + 4 теста обработки ошибок + демо-режим

## Запуск (4 шага)

```bash
# 1. Создать виртуальное окружение и установить зависимости
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt

# 2. Сгенерировать данные (если data/companies.csv отсутствует)
python generate_data.py

# 3. Запустить CRM-сервер
python -m server.mcp_stub

# 4. В новом терминале — запустить дашборд
source .venv/bin/activate && streamlit run dashboard/streamlit_app.py
```

→ Дашборд: http://localhost:8501 · CRM API: http://localhost:8000/docs

## Тесты

```bash
python test_scenarios.py          # все тесты + демо
python test_scenarios.py --tests  # только тесты
python test_scenarios.py --errors # только обработка ошибок
python test_scenarios.py --demo   # демо для презентации
```

## Структура

```
cash-hunter/
├── agent/
│   ├── ouroboros.py          # ядро: ранжирование, скрипты, фидбек
│   └── trainer.py            # ночное обучение
├── retriever/
│   └── langflow_pipeline.py  # Retriever: фильтрация компаний
├── server/
│   └── mcp_stub.py           # FastAPI CRM stub (port 8000)
├── dashboard/
│   └── streamlit_app.py      # Streamlit UI (port 8501)
├── data/
│   └── companies.csv         # 150 компаний, 6 регионов, 6 сфер
├── test_scenarios.py         # тесты и демо
└── requirements.txt
```

## Скоринг

```
score = probability × check_amount × tender_factor × sphere_factor

tender_factor: 5.0 (если есть тендер) / 1.0 (нет)
sphere_factor: Аптеки 1.3 · HoReCa 1.1 · Ритейл 1.0 · остальные 1.0
```

## Стек

Python 3.10+ · pandas · Streamlit · FastAPI · uvicorn · openai
