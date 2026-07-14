"""
Ouroboros Agent — ядро агента продаж инкассации.

Ранжирует компании, генерирует персонализированные скрипты звонков,
собирает фидбек и запускает ночное обучение через Trainer.

Pipeline: Retriever → Rank → Generate Scripts → [Collect Feedback] → [Night Learning]
"""

import json
import random
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

# Make sibling packages importable when running as script
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from retriever.langflow_pipeline import Retriever
from agent.trainer import Trainer


# ── Defaults ───────────────────────────────────────────────────────────────

SPHERE_WEIGHTS: dict[str, float] = {
    "Аптеки": 1.3,
    "HoReCa": 1.1,
    "Ритейл": 1.0,
    "Строительство": 1.0,
    "Автобизнес": 1.0,
    "АЗС": 1.0,
}

TENDER_BONUS = 5.0  # x5 к весу, если у компании есть тендер

# ── Call script templates (3-4 варианта с подстановкой данных) ──────────────

SCRIPT_TEMPLATES = [
    # 1 — фокус на объёме наличных
    (
        "Здравствуйте! Меня зовут {caller_name}, компания «Инкасс-Сервис». "
        "Видим, что у «{company}» в {region} объём наличных — около {cash:.0f} млн ₽. "
        "Предлагаем инкассацию с зачислением день-в-день — это сэкономит до 15% на кассовых операциях."
    ),
    # 2 — фокус на тендере (используется только при наличии тендера)
    (
        "Добрый день! {caller_name}, «Инкасс-Сервис». "
        "«{company}» участвует в тендере на {tender:.0f} млн ₽ — наши услуги помогут "
        "быстро и безопасно переместить наличные. График подберём под ваш документооборот."
    ),
    # 3 — фокус на сфере и регионе
    (
        "Здравствуйте! {caller_name} из «Инкасс-Сервис». "
        "Работаем с компаниями сферы «{sphere}» по {region} — берём всю логистику наличных. "
        "Для «{company}» с оборотом {cash:.0f} млн ₽ подготовим персональный тариф за 1 день."
    ),
    # 4 — комбинированный (выручка + тендер/документооборот)
    (
        "Добрый день, {caller_name}, «Инкасс-Сервис». "
        "У «{company}» выручка {revenue:.0f} млн ₽ и {tender_note}. "
        "Готовы предложить комплексное обслуживание инкассации — зачисление, пересчёт, страховка. Начнём с тестового маршрута?"
    ),
]

CALLER_NAME = "Анна"  # имя оператора по умолчанию


class OuroborosAgent:
    """
    Ядро агента продаж инкассации.

    Связывает ретривер (поиск компаний), ранжирование (скоринг),
    генерацию скриптов и сбор фидбека в единый pipeline.
    """

    def __init__(
        self,
        csv_path: str = "data/companies.csv",
        feedback_path: str = "data/feedback.json",
        weights_path: str = "data/weights.json",
    ):
        self.retriever = Retriever(csv_path)
        self.trainer = Trainer(feedback_path, weights_path, csv_path)
        self.feedback_path = Path(feedback_path)

    # ── Ранжирование целей ───────────────────────────────────────────────

    def rank(self, companies: pd.DataFrame) -> pd.DataFrame:
        """
        Рассчитать скоринг и отсортировать компании.

        Формула: score = probability × check_amount × tender_factor × sphere_factor

        - probability:   нормированная доля наличных (больше наличных = выше конверсия)
        - check_amount:  ожидаемый месячный платёж за инкассацию (≈ 2% от объёма наличных)
        - tender_factor: ×5, если у компании есть тендер
        - sphere_factor: Аптеки 1.3, HoReCa 1.1, Ритейл 1.0, остальные 1.0
        """
        if companies.empty:
            return companies

        # Загрузить веса от тренера (могут быть пересчитаны ночным обучением)
        weights = self.trainer.load_weights()
        sphere_weights = {**SPHERE_WEIGHTS, **weights.get("sphere_weights", {})}
        tender_bonus = weights.get("tender_bonus", TENDER_BONUS)

        df = companies.copy()

        # Вероятность: доля наличных в диапазоне [5%, 50%] → [0.1, 1.0]
        df["probability"] = df["Доля_наличных_%"].clip(lower=5, upper=50) / 50.0

        # Сумма чека: ожидаемый месячный платёж (2% от объёма наличных)
        df["check_amount"] = df["Объём_наличных_млн_руб"] * 0.02

        # Бонус за тендер
        df["tender_factor"] = df["Наличие_тендера"].apply(
            lambda x: tender_bonus if str(x).strip().lower() == "да" else 1.0
        )

        # Бонус за сферу
        df["sphere_factor"] = df["Сфера"].map(lambda s: sphere_weights.get(s, 1.0))

        # Итоговый скоринг
        df["score"] = (
            df["probability"]
            * df["check_amount"]
            * df["tender_factor"]
            * df["sphere_factor"]
        )

        return df.sort_values("score", ascending=False).reset_index(drop=True)

    # ── Генерация скриптов ───────────────────────────────────────────────

    def generate_scripts(
        self,
        ranked: pd.DataFrame,
        top_n: int = 5,
        caller_name: str = CALLER_NAME,
    ) -> list[dict]:
        """
        Сгенерировать персонализированные скрипты для Топ-N компаний.

        Выбирает шаблон в зависимости от наличия тендера:
        - есть тендер → шаблон 2 (тендерный) или 4 (комбинированный)
        - нет тендера → шаблон 1 (наличные) или 3 (сфера)

        Возвращает список словарей: {company_id, company_name, score, script}
        """
        if ranked.empty:
            return []

        top = ranked.head(top_n)
        scripts: list[dict] = []

        for _, row in top.iterrows():
            has_tender = str(row["Наличие_тендера"]).strip().lower() == "да"

            if has_tender:
                template = random.choice([SCRIPT_TEMPLATES[1], SCRIPT_TEMPLATES[3]])
                tender_note = f"тендером на {row['Сумма_тендера_млн_руб']:.0f} млн ₽"
            else:
                template = random.choice([SCRIPT_TEMPLATES[0], SCRIPT_TEMPLATES[2]])
                tender_note = "активным документооборотом"

            script = template.format(
                caller_name=caller_name,
                company=row["Название"],
                region=row["Регион"],
                sphere=row["Сфера"],
                revenue=row["Выручка_млн_руб"],
                cash=row["Объём_наличных_млн_руб"],
                tender=row.get("Сумма_тендера_млн_руб", 0),
                tender_note=tender_note,
            )

            scripts.append({
                "company_id": int(row["id"]),
                "company_name": row["Название"],
                "score": round(float(row["score"]), 2),
                "script": script,
            })

        return scripts

    # ── Сбор фидбека ────────────────────────────────────────────────────

    def collect_feedback(
        self,
        company_id: int,
        score: int,
        success: bool,
    ) -> dict:
        """
        Сохранить оценку цели и результат звонка в feedback.json.

        Поля: company_id, score (1-5), success (bool), timestamp (ISO).

        При накоплении 5+ фидбеков автоматически запускает ночное обучение.
        """
        if not 1 <= score <= 5:
            raise ValueError(f"score должен быть 1–5, получено {score}")

        entry = {
            "company_id": company_id,
            "score": score,
            "success": success,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        }

        # Загрузить существующий фидбек
        feedback: list[dict] = []
        if self.feedback_path.exists():
            try:
                with open(self.feedback_path, "r", encoding="utf-8") as f:
                    feedback = json.load(f)
            except (json.JSONDecodeError, OSError):
                # Файл повреждён — создаём новый, не теряем текущий фидбек
                print(f"⚠️ Файл {self.feedback_path} повреждён. Создаём новый.")
                feedback = []

        feedback.append(entry)

        # Сохранить
        self.feedback_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.feedback_path, "w", encoding="utf-8") as f:
            json.dump(feedback, f, ensure_ascii=False, indent=2)

        # Автозапуск ночного обучения при 5+ фидбеках
        min_required = self.trainer.load_weights().get("min_feedback_for_retrain", 5)
        if len(feedback) >= min_required:
            print(f"📊 Накоплено {len(feedback)} фидбеков — запускаю ночное обучение...")
            report = self.trainer.run()
            print(f"✅ Ночное обучение завершено: {report['status']}")

        return entry

    # ── Полный pipeline ──────────────────────────────────────────────────

    def run(
        self,
        region: str,
        sphere: Optional[str] = None,
        min_revenue: float = 0,
        min_cash: float = 0,
        top_n: int = 5,
    ) -> dict:
        """
        Полный pipeline: Retriever → Rank → Generate Scripts.

        Возвращает dict с ранжированным списком и скриптами для Топ-N.
        """
        companies = self.retriever.search(region, sphere, min_revenue, min_cash)

        if companies.empty:
            return {"ranked": [], "scripts": [], "count": 0}

        ranked = self.rank(companies)
        scripts = self.generate_scripts(ranked, top_n=top_n)

        return {
            "ranked": ranked[[
                "id", "Название", "Регион", "Сфера",
                "Выручка_млн_руб", "Объём_наличных_млн_руб",
                "Наличие_тендера", "score",
            ]].to_dict(orient="records"),
            "scripts": scripts,
            "count": len(ranked),
        }


# ── Пример работы ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    agent = OuroborosAgent()

    # Поиск в Москве с выручкой > 50 млн
    result = agent.run(region="Москва", min_revenue=50, min_cash=10)

    print("=" * 70)
    print("Cash Hunter Agent — Москва, выручка > 50 млн, наличные > 10 млн")
    print("=" * 70)
    print(f"\nРанжировано компаний: {result['count']}\n")

    print("ТОП-10 по скорингу:")
    print("-" * 70)
    for i, c in enumerate(result["ranked"][:10], 1):
        tender = "✓" if c["Наличие_тендера"] == "Да" else "—"
        print(
            f"  {i:>2}. {c['Название']:<22} | {c['Сфера']:<14} | "
            f"score: {c['score']:>8.2f} | тендер: {tender}"
        )

    print(f"\n{'=' * 70}")
    print("Скрипты для Топ-5:")
    print("=" * 70)
    for s in result["scripts"]:
        print(f"\n📞 {s['company_name']} (score: {s['score']:.2f})")
        print(f"   {s['script']}")

    # Демо: сбор фидбека
    print(f"\n{'=' * 70}")
    print("Демо: сбор фидбека")
    print("=" * 70)
    if result["ranked"]:
        top_id = result["ranked"][0]["id"]
        fb = agent.collect_feedback(top_id, score=5, success=True)
        print(f"  Сохранён фидбек: {fb}")
