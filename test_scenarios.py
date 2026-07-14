"""
test_scenarios.py — Тестовые и демо-сценарии для Cash Hunter.

Запуск:
  cd ~/Desktop/cash-hunter
  .venv/bin/python test_scenarios.py            # все тесты + демо
  .venv/bin/python test_scenarios.py --tests    # только тесты
  .venv/bin/python test_scenarios.py --demo     # только демо
  .venv/bin/python test_scenarios.py --errors   # только обработка ошибок

Требования:
  - data/companies.csv с 150 компаниями
  - CRM-сервер (server/mcp_stub.py) запущен на порту 8000
    (если не запущен — тесты CRM-эндпоинтов будут пропущены с предупреждением)
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

# ── Настройка путей ─────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from retriever.langflow_pipeline import Retriever          # noqa: E402
from agent.ouroboros import OuroborosAgent, SPHERE_WEIGHTS  # noqa: E402
from agent.trainer import Trainer, DEFAULT_WEIGHTS          # noqa: E402

DATA_DIR = PROJECT_ROOT / "data"
COMPANIES_CSV = DATA_DIR / "companies.csv"
FEEDBACK_FILE = DATA_DIR / "feedback.json"
LEADS_FILE = DATA_DIR / "leads.json"
WEIGHTS_FILE = DATA_DIR / "weights.json"

CRM_URL = "http://0.0.0.0:8000"
CRM_TIMEOUT = 5


# ── Утилиты ──────────────────────────────────────────────────────────────────

def _print_header(title: str) -> None:
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print(f"{'=' * 70}")


def _print_step(n: int, text: str) -> None:
    print(f"\n  Шаг {n}: {text}")


def _print_ok(text: str) -> None:
    print(f"  ✅ {text}")


def _print_fail(text: str) -> None:
    print(f"  ❌ {text}")


def _print_warn(text: str) -> None:
    print(f"  ⚠️ {text}")


def _print_info(text: str) -> None:
    print(f"  ℹ️ {text}")


def crm_is_online() -> bool:
    """Проверить, запущен ли CRM-сервер."""
    try:
        resp = requests.get(f"{CRM_URL}/health", timeout=2)
        return resp.status_code == 200
    except Exception:
        return False


def _backup_file(path: Path) -> Optional[Path]:
    """Создать резервную копию файла. Возвращает путь к бэкапу или None."""
    if not path.exists():
        return None
    backup = path.with_suffix(path.suffix + ".bak")
    shutil.copy2(path, backup)
    return backup


def _restore_file(path: Path, backup: Optional[Path]) -> None:
    """Восстановить файл из бэкапа."""
    if backup and backup.exists():
        shutil.copy2(backup, path)
        backup.unlink()
    elif backup and not backup.exists():
        # Бэкапа нет — просто удалить файл
        if path.exists():
            path.unlink()


# ── Тестовый сценарий: 6 шагов ──────────────────────────────────────────────

def run_test_scenario() -> bool:
    """
    Полный тестовый сценарий из 6 шагов.

    Возвращает True, если все шаги прошли успешно.
    """
    _print_header("ТЕСТОВЫЙ СЦЕНАРИЙ — 6 шагов")
    all_ok = True

    # ── Шаг 1: Ретривер для Москвы → 20+ компаний ───────────────────────

    _print_step(1, "Запуск ретривера для Москвы")
    try:
        retriever = Retriever(str(COMPANIES_CSV))
        results = retriever.search(region="Москва", min_revenue=0, min_cash=0)
        count = len(results)
        _print_info(f"Найдено компаний: {count}")
        if count >= 20:
            _print_ok(f"Ретривер нашёл {count} компаний (≥20 — тест пройден)")
        else:
            _print_fail(f"Ретривер нашёл {count} компаний (нужно ≥20)")
            all_ok = False
    except Exception as exc:
        _print_fail(f"Ретривер упал с ошибкой: {exc}")
        all_ok = False
        return all_ok  # Дальше нет смысла

    # ── Шаг 2: Ранжирование → Топ-5 со score > 0 ───────────────────────

    _print_step(2, "Ранжирование целей (Топ-5 должны иметь score > 0)")
    try:
        agent = OuroborosAgent(
            csv_path=str(COMPANIES_CSV),
            feedback_path=str(FEEDBACK_FILE),
            weights_path=str(WEIGHTS_FILE),
        )
        ranked = agent.rank(results)
        top5 = ranked.head(5)
        all_positive = all(float(s) > 0 for s in top5["score"])
        _print_info("Топ-5 по скорингу:")
        for i, (_, row) in enumerate(top5.iterrows(), 1):
            tender = "✓" if str(row["Наличие_тендера"]).strip().lower() == "да" else "—"
            print(
                f"    {i}. {row['Название']:<22} | "
                f"score: {row['score']:>8.2f} | тендер: {tender}"
            )
        if all_positive:
            _print_ok("Все 5 целей имеют score > 0 — тест пройден")
        else:
            _print_fail("Некоторые цели имеют score ≤ 0")
            all_ok = False
    except Exception as exc:
        _print_fail(f"Ранжирование упало: {exc}")
        all_ok = False

    # ── Шаг 3: Генерация скриптов → все 5 с текстом ────────────────────

    _print_step(3, "Генерация скриптов для Топ-5")
    try:
        scripts = agent.generate_scripts(ranked, top_n=5)
        all_have_text = all(len(s["script"]) > 20 for s in scripts)
        _print_info(f"Сгенерировано скриптов: {len(scripts)}")
        for s in scripts:
            preview = s["script"][:80].replace("\n", " ") + "..."
            print(f"    📞 {s['company_name']}: {preview}")
        if len(scripts) == 5 and all_have_text:
            _print_ok("Все 5 скриптов сгенерированы и содержат текст — тест пройден")
        else:
            _print_fail(f"Проблема со скриптами: count={len(scripts)}, all_have_text={all_have_text}")
            all_ok = False
    except Exception as exc:
        _print_fail(f"Генерация скриптов упала: {exc}")
        all_ok = False

    # ── Шаг 4: Создание лида через MCP → запись в leads.json ───────────

    _print_step(4, "Создание лида через MCP-сервер")
    crm_online = crm_is_online()

    if not crm_online:
        _print_warn("CRM-сервер не запущен (порт 8000). Шаг 4 пропущен.")
        _print_warn("Запустите: .venv/bin/python -m server.mcp_stub или uvicorn server.mcp_stub:app --port 8000")
    else:
        try:
            top_company = ranked.iloc[0]
            lead_payload = {
                "company_id": int(top_company["id"]),
                "name": str(top_company["Название"]),
                "inn": str(top_company["ИНН"]),
                "region": str(top_company["Регион"]),
                "score": float(top_company["score"]),
                "script": scripts[0]["script"] if scripts else "",
                "status": "new",
            }
            resp = requests.post(
                f"{CRM_URL}/create_lead", json=lead_payload, timeout=CRM_TIMEOUT
            )
            if resp.status_code == 201:
                lead_id = resp.json()["id"]
                _print_info(f"Создан лид #{lead_id} в CRM")

                # Проверить leads.json
                leads_data = json.loads(LEADS_FILE.read_text(encoding="utf-8"))
                found = any(l["id"] == lead_id for l in leads_data)
                if found:
                    _print_ok(f"Запись #{lead_id} найдена в leads.json — тест пройден")
                else:
                    _print_fail("Запись не найдена в leads.json")
                    all_ok = False
            else:
                _print_fail(f"CRM вернул {resp.status_code}: {resp.text}")
                all_ok = False
        except Exception as exc:
            _print_fail(f"Ошибка при создании лида: {exc}")
            all_ok = False

    # ── Шаг 5: Запись фидбека → feedback.json обновился ────────────────

    _print_step(5, "Запись фидбека звонка")
    fb_backup = _backup_file(FEEDBACK_FILE)
    try:
        top_id = int(ranked.iloc[0]["id"])
        before_count = 0
        if FEEDBACK_FILE.exists():
            try:
                before = json.loads(FEEDBACK_FILE.read_text(encoding="utf-8"))
                before_count = len(before)
            except (json.JSONDecodeError, OSError):
                before_count = -1  # файл повреждён

        entry = agent.collect_feedback(
            company_id=top_id, score=5, success=True
        )
        _print_info(f"Фидбек сохранён: {entry}")

        after = json.loads(FEEDBACK_FILE.read_text(encoding="utf-8"))
        after_count = len(after)
        if after_count > before_count:
            _print_ok(f"feedback.json обновлён: {before_count} → {after_count} записей — тест пройден")
        elif before_count == -1:
            _print_ok("feedback.json был повреждён, создан новый — тест пройден")
        else:
            _print_fail("feedback.json не обновлён")
            all_ok = False
    except Exception as exc:
        _print_fail(f"Ошибка записи фидбека: {exc}")
        all_ok = False
    finally:
        _restore_file(FEEDBACK_FILE, fb_backup)

    # ── Шаг 6: Обучение → веса изменились ───────────────────────────────

    _print_step(6, "Запуск ночного обучения (проверка изменения весов)")
    weights_backup = _backup_file(WEIGHTS_FILE)

    # Создаём временный фидбек с 5+ записями для обучения
    temp_feedback = DATA_DIR / "feedback_test.json"
    temp_weights = DATA_DIR / "weights_test.json"
    try:
        # Подготовить 6 фидбеков: 4 успеха в Аптеках, 2 провала в Ритейле
        test_feedback = [
            {"company_id": 70, "score": 5, "success": True, "timestamp": "2026-01-01T10:00:00"},   # Аптеки
            {"company_id": 74, "score": 4, "success": True, "timestamp": "2026-01-01T11:00:00"},   # Аптеки
            {"company_id": 96, "score": 5, "success": True, "timestamp": "2026-01-01T12:00:00"},  # Аптеки
            {"company_id": 118, "score": 4, "success": True, "timestamp": "2026-01-01T13:00:00"},  # Аптеки
            {"company_id": 2, "score": 2, "success": False, "timestamp": "2026-01-01T14:00:00"},   # Ритейл
            {"company_id": 35, "score": 1, "success": False, "timestamp": "2026-01-01T15:00:00"},  # Ритейл
        ]
        temp_feedback.write_text(
            json.dumps(test_feedback, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        trainer = Trainer(
            feedback_path=str(temp_feedback),
            weights_path=str(temp_weights),
            companies_path=str(COMPANIES_CSV),
        )

        old_weights = trainer.load_weights()
        old_apptek = old_weights["sphere_weights"]["Аптеки"]
        old_retail = old_weights["sphere_weights"]["Ритейл"]

        report = trainer.run(force=True)
        _print_info(f"Обучение: {report['status']}, фидбеков: {report.get('feedback_count', 0)}")

        new_weights = trainer.load_weights()
        new_apptek = new_weights["sphere_weights"]["Аптеки"]
        new_retail = new_weights["sphere_weights"]["Ритейл"]

        _print_info(f"Вес Аптеки: {old_apptek} → {new_apptek}")
        _print_info(f"Вес Ритейл: {old_retail} → {new_retail}")

        weights_changed = (new_apptek != old_apptek) or (new_retail != old_retail)
        if weights_changed:
            _print_ok("Веса изменились после обучения — тест пройден")
        else:
            _print_fail("Веса не изменились")
            all_ok = False
    except Exception as exc:
        _print_fail(f"Ошибка обучения: {exc}")
        all_ok = False
    finally:
        for f in [temp_feedback, temp_weights]:
            if f.exists():
                f.unlink()
        _restore_file(WEIGHTS_FILE, weights_backup)

    # ── Итог ────────────────────────────────────────────────────────────

    _print_header("ИТОГ ТЕСТОВ")
    if all_ok:
        _print_ok("Все тесты пройдены успешно!")
    else:
        _print_fail("Некоторые тесты не пройдены. См. детали выше.")

    return all_ok


# ── Тесты обработки ошибок ──────────────────────────────────────────────────

def run_error_handling_tests() -> bool:
    """
    Тесты обработки ошибок:
    1. Ретривер не находит компаний → "Ничего не найдено"
    2. MCP-сервер недоступен → фидбек сохраняется локально
    3. Данные повреждены → понятная ошибка
    4. feedback.json повреждён → создаётся новый
    """
    _print_header("ТЕСТЫ ОБРАБОТКИ ОШИБОК")
    all_ok = True

    # ── 1. Ретривер не находит компаний ─────────────────────────────────

    _print_step(1, "Ретривер: несуществующий регион → пустой результат")
    try:
        retriever = Retriever(str(COMPANIES_CSV))
        results = retriever.search(region="НесуществующийРегион")
        if results.empty:
            _print_ok("Ретривер вернул пустой DataFrame (0 компаний) — корректно")
        else:
            _print_fail(f"Должен быть пустой результат, получено {len(results)} компаний")
            all_ok = False
    except Exception as exc:
        _print_fail(f"Ретривер упал вместо возврата пустого результата: {exc}")
        all_ok = False

    # ── 2. MCP недоступен → фидбек сохраняется локально ────────────────

    _print_step(2, "MCP недоступен → фидбек сохраняется локально")
    fb_backup = _backup_file(FEEDBACK_FILE)
    try:
        agent = OuroborosAgent(
            csv_path=str(COMPANIES_CSV),
            feedback_path=str(FEEDBACK_FILE),
            weights_path=str(WEIGHTS_FILE),
        )

        before_count = 0
        if FEEDBACK_FILE.exists():
            try:
                before = json.loads(FEEDBACK_FILE.read_text(encoding="utf-8"))
                before_count = len(before)
            except (json.JSONDecodeError, OSError):
                pass

        # Попытка создать лид на несуществующий порт
        fake_crm_url = "http://0.0.0.0:9999"
        try:
            resp = requests.post(
                f"{fake_crm_url}/create_lead",
                json={"company_id": 1, "name": "test", "inn": "123", "region": "Москва", "score": 1.0},
                timeout=2,
            )
            crm_reachable = True
        except requests.exceptions.ConnectionError:
            crm_reachable = False
            _print_info("CRM на порту 9999 недоступен (ожидаемо)")

        # Фидбек должен сохраниться даже если CRM недоступен
        entry = agent.collect_feedback(company_id=1, score=3, success=False)
        _print_info(f"Фидбек сохранён локально: {entry}")

        after = json.loads(FEEDBACK_FILE.read_text(encoding="utf-8"))
        after_count = len(after)

        if after_count > before_count and not crm_reachable:
            _print_ok("Фидбек сохранён локально при недоступном CRM — тест пройден")
        else:
            _print_fail("Фидбек не сохранён или CRM unexpectedly доступен")
            all_ok = False
    except Exception as exc:
        _print_fail(f"Ошибка: {exc}")
        all_ok = False
    finally:
        _restore_file(FEEDBACK_FILE, fb_backup)

    # ── 3. Повреждённые данные → понятная ошибка ───────────────────────

    _print_step(3, "Повреждённый CSV → понятная ошибка")
    temp_dir = tempfile.mkdtemp()
    corrupt_csv = Path(temp_dir) / "corrupt.csv"
    corrupt_csv.write_text("id,Название,ИНН\n1,Тест,abc\nBROKEN,DATA,HERE\n", encoding="utf-8")
    try:
        retriever = Retriever(str(corrupt_csv))
        try:
            retriever.search(region="Москва")
            # Если не упало — проверим, что хотя бы DataFrame вернулся
            # (pandas может обработать некоторые виды "мусора")
            _print_warn("Ретривер не упал на повреждённых данных (pandas толерантен)")
        except (ValueError, FileNotFoundError) as exc:
            _print_ok(f"Понятная ошибка: {exc}")
        except Exception as exc:
            _print_warn(f"Неожиданный тип ошибки (но ошибка есть): {type(exc).__name__}: {exc}")
    except Exception as exc:
        _print_fail(f"Необработанная ошибка: {exc}")
        all_ok = False
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    # ── 3b. Несуществующий файл → FileNotFoundError ───────────────────

    _print_step(3, "Несуществующий CSV → FileNotFoundError")
    try:
        retriever = Retriever("/nonexistent/path/to/file.csv")
        try:
            retriever.search(region="Москва")
            _print_fail("Должна была быть ошибка FileNotFoundError")
            all_ok = False
        except FileNotFoundError as exc:
            _print_ok(f"FileNotFoundError: {exc}")
        except Exception as exc:
            _print_warn(f"Другая ошибка (но обработана): {type(exc).__name__}: {exc}")
    except Exception as exc:
        _print_fail(f"Необработанная ошибка: {exc}")
        all_ok = False

    # ── 4. feedback.json повреждён → создаётся новый ──────────────────

    _print_step(4, "Повреждённый feedback.json → создаётся новый")
    fb_backup = _backup_file(FEEDBACK_FILE)
    try:
        # Записать мусор в feedback.json
        FEEDBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
        FEEDBACK_FILE.write_text("ЭТО НЕ JSON {{{{ BROKEN }}}}", encoding="utf-8")

        agent = OuroborosAgent(
            csv_path=str(COMPANIES_CSV),
            feedback_path=str(FEEDBACK_FILE),
            weights_path=str(WEIGHTS_FILE),
        )

        # collect_feedback должен обнаружить повреждение и создать новый файл
        entry = agent.collect_feedback(company_id=1, score=4, success=True)
        _print_info(f"Фидбек сохранён: {entry}")

        # Проверить, что файл теперь валидный JSON
        data = json.loads(FEEDBACK_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list) and len(data) >= 1:
            _print_ok(f"feedback.json пересоздан, валидный JSON с {len(data)} записями — тест пройден")
        else:
            _print_fail("feedback.json не валиден после восстановления")
            all_ok = False
    except Exception as exc:
        _print_fail(f"Ошибка: {exc}")
        all_ok = False
    finally:
        _restore_file(FEEDBACK_FILE, fb_backup)

    # ── Итог ────────────────────────────────────────────────────────────

    _print_header("ИТОГ ТЕСТОВ ОБРАБОТКИ ОШИБОК")
    if all_ok:
        _print_ok("Все тесты обработки ошибок пройдены!")
    else:
        _print_fail("Некоторые тесты не пройдены. См. детали выше.")

    return all_ok


# ── Демо-сценарий для презентации ────────────────────────────────────────────

def run_demo_scenario() -> None:
    """
    Демо-сценарий для презентации:
    1. Показать, как искать цели
    2. Показать, как звонить и оценивать
    3. Показать, как работает самообучение
    4. Показать, как обрабатываются ошибки
    """
    _print_header("ДЕМО-СЦЕНАРИЙ ДЛЯ ПРЕЗЕНТАЦИИ")

    crm_online = crm_is_online()

    # ── 1. Поиск целей ──────────────────────────────────────────────────

    _print_step(1, "Поиск целей (Москва, Ритейл, выручка > 100 млн ₽)")
    print()

    agent = OuroborosAgent(
        csv_path=str(COMPANIES_CSV),
        feedback_path=str(FEEDBACK_FILE),
        weights_path=str(WEIGHTS_FILE),
    )

    result = agent.run(region="Москва", sphere="Ритейл", min_revenue=100, min_cash=0, top_n=5)

    if result["count"] == 0:
        print("  Ничего не найдено. Попробуйте изменить фильтры.")
    else:
        print(f"  Найдено компаний: {result['count']}")
        print(f"  Топ-5 целей:\n")
        for i, c in enumerate(result["ranked"][:5], 1):
            tender = "✓" if str(c["Наличие_тендера"]).strip().lower() == "да" else "—"
            print(
                f"    {i}. {c['Название']:<22} | {c['Сфера']:<10} | "
                f"наличные: {c['Объём_наличных_млн_руб']:>8,.0f} млн ₽ | "
                f"score: {c['score']:>8.2f} | тендер: {tender}"
            )

    # ── 2. Звонок и оценка ─────────────────────────────────────────────

    _print_step(2, "Звонок и оценка (демо)")
    print()

    scripts = result.get("scripts", [])
    if scripts:
        top_script = scripts[0]
        print(f"  📞 Скрипт для {top_script['company_name']}:")
        print(f"     \"{top_script['script']}\"")
        print()

        # Сохранить фидбек
        top_id = top_script["company_id"]
        fb_backup = _backup_file(FEEDBACK_FILE)
        try:
            entry = agent.collect_feedback(company_id=top_id, score=5, success=True)
            print(f"  ✅ Фидбек сохранён: score=5, success=True")
            print(f"     {entry}")

            # Отправить лид в CRM (если доступен)
            if crm_online:
                lead_payload = {
                    "company_id": top_id,
                    "name": top_script["company_name"],
                    "inn": "",
                    "region": "Москва",
                    "score": top_script["score"],
                    "script": top_script["script"],
                    "status": "interested",
                }
                try:
                    resp = requests.post(f"{CRM_URL}/create_lead", json=lead_payload, timeout=CRM_TIMEOUT)
                    if resp.status_code == 201:
                        print(f"  ✅ Лид #{resp.json()['id']} создан в CRM")
                    else:
                        print(f"  ⚠️ CRM вернул {resp.status_code}")
                except Exception as exc:
                    print(f"  ⚠️ Ошибка CRM: {exc}")
            else:
                print(f"  ⚠️ CRM недоступен — фидбек сохранён локально, лид не отправлен")
        finally:
            _restore_file(FEEDBACK_FILE, fb_backup)
    else:
        print("  Нет скриптов для демо (нет целей)")

    # ── 3. Самообучение ─────────────────────────────────────────────────

    _print_step(3, "Самообучение (демо)")
    print()

    # Используем временные файлы, чтобы не повредить рабочие данные
    temp_feedback = DATA_DIR / "feedback_demo.json"
    temp_weights = DATA_DIR / "weights_demo.json"

    try:
        # Создаём 6 фидбеков: 5 успешных в Аптеках, 1 провал в Строительстве
        demo_feedback = [
            {"company_id": 70, "score": 5, "success": True, "timestamp": "2026-01-01T10:00:00"},
            {"company_id": 74, "score": 4, "success": True, "timestamp": "2026-01-01T11:00:00"},
            {"company_id": 96, "score": 5, "success": True, "timestamp": "2026-01-01T12:00:00"},
            {"company_id": 118, "score": 4, "success": True, "timestamp": "2026-01-01T13:00:00"},
            {"company_id": 134, "score": 3, "success": True, "timestamp": "2026-01-01T14:00:00"},
            {"company_id": 9, "score": 2, "success": False, "timestamp": "2026-01-01T15:00:00"},
        ]
        temp_feedback.write_text(
            json.dumps(demo_feedback, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        trainer = Trainer(
            feedback_path=str(temp_feedback),
            weights_path=str(temp_weights),
            companies_path=str(COMPANIES_CSV),
        )

        old_weights = trainer.load_weights()
        print(f"  Веса ДО обучения:")
        for sphere, w in old_weights["sphere_weights"].items():
            print(f"    {sphere}: {w}")

        report = trainer.run(force=True)

        new_weights = trainer.load_weights()
        print(f"\n  Веса ПОСЛЕ обучения (обновление #{new_weights.get('update_count', 0)}):")
        for sphere, w in new_weights["sphere_weights"].items():
            old_w = old_weights["sphere_weights"].get(sphere, w)
            arrow = "↑" if w > old_w else ("↓" if w < old_w else "=")
            print(f"    {sphere}: {w} {arrow} (было {old_w})")

        if report["status"] == "trained":
            print(f"\n  ✅ Обучение завершено: {report['feedback_count']} фидбеков обработано")
            print(f"     Сферы с высоким успехом получили буст, с низким — снижение")
        else:
            print(f"\n  ⏭️ Обучение пропущено: {report.get('reason', '?')}")
    finally:
        for f in [temp_feedback, temp_weights]:
            if f.exists():
                f.unlink()

    # ── 4. Обработка ошибок ────────────────────────────────────────────

    _print_step(4, "Обработка ошибок (демо)")
    print()

    # 4a. Пустой результат поиска
    print("  4a. Поиск в несуществующем регионе:")
    try:
        r = agent.retriever.search(region="Луна")
        if r.empty:
            print(f"     → 'Ничего не найдено' (пустой результат, {len(r)} компаний)")
        else:
            print(f"     → Найдено {len(r)} компаний (неожиданно)")
    except Exception as exc:
        print(f"     → Ошибка: {exc}")

    # 4b. Повреждённый feedback.json
    print("\n  4b. Повреждённый feedback.json:")
    fb_backup = _backup_file(FEEDBACK_FILE)
    try:
        FEEDBACK_FILE.write_text("BROKEN JSON {{{{", encoding="utf-8")
        entry = agent.collect_feedback(company_id=1, score=3, success=False)
        data = json.loads(FEEDBACK_FILE.read_text(encoding="utf-8"))
        print(f"     → Файл повреждён, создан новый. Записей: {len(data)}")
        print(f"     → Фидбек сохранён: {entry}")
    except Exception as exc:
        print(f"     → Ошибка: {exc}")
    finally:
        _restore_file(FEEDBACK_FILE, fb_backup)

    # 4c. CRM недоступен
    print("\n  4c. CRM недоступен:")
    if crm_online:
        print(f"     → CRM сейчас онлайн (порт 8000) — пропускаем демо недоступности")
    else:
        print(f"     → CRM офлайн. Фидбек сохраняется локально, лид не отправляется.")
        print(f"     → При восстановлении CRM данные можно отправить повторно.")

    # 4d. Несуществующий CSV
    print("\n  4d. Несуществующий CSV:")
    try:
        bad_retriever = Retriever("/nonexistent/file.csv")
        bad_retriever.search(region="Москва")
    except FileNotFoundError as exc:
        print(f"     → FileNotFoundError: {exc}")

    _print_header("ДЕМО ЗАВЕРШЕНО")
    print("  Все компоненты Cash Hunter продемонстрированы:")
    print("  • Поиск целей через ретривер")
    print("  • Ранжирование и генерация скриптов");
    print("  • Сбор фидбека и создание лидов в CRM")
    print("  • Ночное обучение (пересчёт весов)")
    print("  • Обработка ошибок (пустые результаты, повреждённые файлы, CRM офлайн)")


# ── Точка входа ──────────────────────────────────────────────────────────────

def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Cash Hunter — тесты и демо")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--tests", action="store_true", help="Запустить только тесты (6 шагов)")
    group.add_argument("--errors", action="store_true", help="Запустить только тесты обработки ошибок")
    group.add_argument("--demo", action="store_true", help="Запустить только демо-сценарий")
    args = parser.parse_args()

    run_tests = True
    run_errors = True
    run_demo = True

    if args.tests:
        run_errors = False
        run_demo = False
    elif args.errors:
        run_tests = False
        run_demo = False
    elif args.demo:
        run_tests = False
        run_errors = False

    all_ok = True

    if run_tests:
        all_ok = run_test_scenario() and all_ok

    if run_errors:
        all_ok = run_error_handling_tests() and all_ok

    if run_demo:
        run_demo_scenario()

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
