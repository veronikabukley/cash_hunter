"""
Trainer — модуль ночного обучения для агента Ouroboros.

Анализирует накопленный фидбек звонков, пересчитывает веса сфер для
ранжирования (увеличивает вес там, где больше успешных звонков) и
сохраняет обновлённые веса.

Запускается:
  - автоматически при накоплении 5+ фидбеков (из OuroborosAgent.collect_feedback)
  - вручную: python -m agent.trainer  (или trainer.run(force=True))
"""

import json
from datetime import datetime
from pathlib import Path

import pandas as pd


# ── Дефолтные веса ──────────────────────────────────────────────────────────

DEFAULT_WEIGHTS: dict = {
    "sphere_weights": {
        "Аптеки": 1.3,
        "HoReCa": 1.1,
        "Ритейл": 1.0,
        "Строительство": 1.0,
        "Автобизнес": 1.0,
        "АЗС": 1.0,
    },
    "tender_bonus": 5.0,
    "min_feedback_for_retrain": 5,
    "last_updated": None,
    "update_count": 0,
}

# Защита от runaway значений
MIN_WEIGHT = 0.5
MAX_WEIGHT = 3.0


class Trainer:
    """
    Ночное обучение: пересчёт весов ранжирования по фидбеку звонков.

    Стратегия:
    - Сферы с успешностью выше среднего получают пропорциональный буст
    - Сферы с успешностью ниже среднего — мягкое снижение
    - 70% текущий вес + 30% корректировка (плавность, защита от резких скачков)
    - Веса ограничены диапазоном [0.5, 3.0]
    """

    def __init__(
        self,
        feedback_path: str = "data/feedback.json",
        weights_path: str = "data/weights.json",
        companies_path: str = "data/companies.csv",
    ):
        self.feedback_path = Path(feedback_path)
        self.weights_path = Path(weights_path)
        self.companies_path = Path(companies_path)

    # ── Загрузка / сохранение ───────────────────────────────────────────

    def load_weights(self) -> dict:
        """Загрузить текущие веса из файла, или вернуть дефолты."""
        if self.weights_path.exists():
            with open(self.weights_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return json.loads(json.dumps(DEFAULT_WEIGHTS))  # deep copy

    def save_weights(self, weights: dict) -> None:
        """Сохранить обновлённые веса в файл."""
        self.weights_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.weights_path, "w", encoding="utf-8") as f:
            json.dump(weights, f, ensure_ascii=False, indent=2)

    def load_feedback(self) -> list[dict]:
        """Загрузить все записи фидбека."""
        if not self.feedback_path.exists():
            return []
        with open(self.feedback_path, "r", encoding="utf-8") as f:
            return json.load(f)

    # ── Анализ ──────────────────────────────────────────────────────────

    def analyze_feedback(self) -> dict[str, dict]:
        """
        Анализ фидбека: успешность звонков по сферам.

        Возвращает dict: сфера → {total, successes, success_rate, avg_score}
        """
        feedback = self.load_feedback()
        if not feedback:
            return {}

        # Загрузить компании для маппинга company_id → сфера
        companies_df = pd.read_csv(self.companies_path)
        id_to_sphere = dict(zip(companies_df["id"], companies_df["Сфера"]))

        sphere_stats: dict[str, dict] = {}

        for entry in feedback:
            cid = entry["company_id"]
            sphere = id_to_sphere.get(cid, "Unknown")
            success = entry.get("success", False)
            score = entry.get("score", 0)

            if sphere not in sphere_stats:
                sphere_stats[sphere] = {
                    "total": 0,
                    "successes": 0,
                    "scores": [],
                }

            sphere_stats[sphere]["total"] += 1
            if success:
                sphere_stats[sphere]["successes"] += 1
            sphere_stats[sphere]["scores"].append(score)

        # Вычислить ставки
        for stats in sphere_stats.values():
            stats["success_rate"] = (
                stats["successes"] / stats["total"] if stats["total"] > 0 else 0
            )
            stats["avg_score"] = (
                sum(stats["scores"]) / len(stats["scores"])
                if stats["scores"]
                else 0
            )
            del stats["scores"]

        return sphere_stats

    def recalculate_weights(self) -> dict:
        """
        Пересчитать веса сфер на основе успешности звонков.

        Логика:
        - Вычислить среднюю успешность по всем сферам с фидбеком
        - Для каждой сферы: adjustment = success_rate / avg_rate
        - Новый вес = 0.7 × текущий + 0.3 × текущий × adjustment
        - Клампинг в [0.5, 3.0]
        """
        weights = self.load_weights()
        sphere_weights = weights.get(
            "sphere_weights", DEFAULT_WEIGHTS["sphere_weights"]
        )
        stats = self.analyze_feedback()

        if not stats:
            return weights

        # Средняя успешность по всем сферам с фидбеком
        rates = [s["success_rate"] for s in stats.values()]
        avg_rate = sum(rates) / len(rates) if rates else 0

        new_sphere_weights: dict[str, float] = {}

        for sphere, current_weight in sphere_weights.items():
            s = stats.get(sphere)

            if s is None or s["total"] < 1:
                # Нет фидбека для этой сферы — вес не меняем
                new_sphere_weights[sphere] = round(current_weight, 4)
                continue

            # Корректировка: отношение успешности сферы к средней
            adjustment = s["success_rate"] / avg_rate if avg_rate > 0 else 1.0

            # Плавный бленд: 70% текущий + 30% корректировка
            new_weight = current_weight * 0.7 + current_weight * adjustment * 0.3

            # Клампинг
            new_weight = max(MIN_WEIGHT, min(MAX_WEIGHT, new_weight))
            new_sphere_weights[sphere] = round(new_weight, 4)

        weights["sphere_weights"] = new_sphere_weights
        return weights

    # ── Главный запуск ──────────────────────────────────────────────────

    def run(self, force: bool = False) -> dict:
        """
        Запустить ночное обучение.

        Args:
            force: True — запустить принудительно.
                   False — только при накоплении 5+ фидбеков.

        Возвращает отчёт dict: status, feedback_count, sphere_stats, new_weights.
        """
        feedback = self.load_feedback()
        min_required = self.load_weights().get("min_feedback_for_retrain", 5)

        if not force and len(feedback) < min_required:
            return {
                "status": "skipped",
                "reason": f"Недостаточно фидбеков: {len(feedback)}/{min_required}",
                "feedback_count": len(feedback),
            }

        stats = self.analyze_feedback()
        new_weights = self.recalculate_weights()

        new_weights["last_updated"] = datetime.now().isoformat(timespec="seconds")
        new_weights["update_count"] = new_weights.get("update_count", 0) + 1

        self.save_weights(new_weights)

        return {
            "status": "trained",
            "feedback_count": len(feedback),
            "sphere_stats": stats,
            "new_weights": new_weights["sphere_weights"],
            "update_count": new_weights["update_count"],
        }


# ── Пример работы ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    trainer = Trainer(
        feedback_path="data/feedback.json",
        weights_path="data/weights.json",
        companies_path="data/companies.csv",
    )

    report = trainer.run()

    print("=" * 70)
    print("Trainer — Ночное обучение")
    print("=" * 70)
    print(json.dumps(report, ensure_ascii=False, indent=2))
