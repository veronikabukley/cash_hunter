"""Cash Hunter — генератор синтетических данных компаний."""
import csv
import random

random.seed(42)

REGIONS = ["Москва", "СПб", "Казань", "Новосибирск", "Екатеринбург", "Ростов-на-Дону"]
SPHERES = ["Ритейл", "Аптеки", "HoReCa", "Строительство", "Автобизнес", "АЗС"]

# Реалистичные диапазоны выручки по сфере (млн руб.)
REVENUE_RANGES = {
    "Ритейл":        (500, 50000),
    "Аптеки":        (200, 15000),
    "HoReCa":        (100, 8000),
    "Строительство": (1000, 30000),
    "Автобизнес":    (50, 5000),
    "АЗС":           (300, 10000),
}

# Типичные доли наличных по сфере (%)
CASH_SHARE_RANGES = {
    "Ритейл":        (15, 35),
    "Аптеки":        (10, 25),
    "HoReCa":        (20, 45),
    "Строительство": (5, 20),
    "Автобизнес":    (25, 50),
    "АЗС":           (10, 30),
}

COMPANY_PREFIXES = {
    "Ритейл":        ["Торг", "Маркет", "Снаб", "Базис", "Орбита"],
    "Аптеки":        ["Фарм", "Здоровье", "Аптека", "Мед", "Вита"],
    "HoReCa":        ["Вкус", "Гурман", "Отель", "Ресторан", "Кафе"],
    "Строительство": ["Строй", "Монолит", "Дом", "Град", "Бетон"],
    "Автобизнес":    ["Авто", "Мотор", "Сервис", "Драйв", "Шина"],
    "АЗС":           ["Нефть", "Топливо", "Заправка", "Бензин", "ГСМ"],
}
COMPANY_SUFFIXES = ["Плюс", "Про", "Групп", "Сервис", "Трейд", "Центр", "Мастер"]


def generate_inn():
    """Генерирует синтетический 10-значный ИНН."""
    return str(random.randint(1000000000, 9999999999))


def generate_name(sphere):
    prefix = random.choice(COMPANY_PREFIXES[sphere])
    suffix = random.choice(COMPANY_SUFFIXES)
    legal = random.choice(["ООО", "АО", "ИП"])
    return f"{legal} «{prefix}{suffix}»"


def generate_company(company_id):
    region = random.choice(REGIONS)
    sphere = random.choice(SPHERES)

    rev_min, rev_max = REVENUE_RANGES[sphere]
    revenue = round(random.uniform(rev_min, rev_max), 2)

    cash_min, cash_max = CASH_SHARE_RANGES[sphere]
    cash_share = round(random.uniform(cash_min, cash_max), 1)

    cash_volume = round(revenue * cash_share / 100, 2)

    has_tender = random.choices(["Да", "Нет"], weights=[35, 65])[0]
    if has_tender == "Да":
        tender_amount = round(random.uniform(1, 500), 2)
    else:
        tender_amount = 0.0

    return {
        "id": company_id,
        "Название": generate_name(sphere),
        "ИНН": generate_inn(),
        "Регион": region,
        "Сфера": sphere,
        "Выручка_млн_руб": revenue,
        "Доля_наличных_%": cash_share,
        "Объём_наличных_млн_руб": cash_volume,
        "Наличие_тендера": has_tender,
        "Сумма_тендера_млн_руб": tender_amount,
    }


def main():
    companies = [generate_company(i + 1) for i in range(150)]
    fieldnames = [
        "id", "Название", "ИНН", "Регион", "Сфера",
        "Выручка_млн_руб", "Доля_наличных_%", "Объём_наличных_млн_руб",
        "Наличие_тендера", "Сумма_тендера_млн_руб",
    ]
    output_path = "data/companies.csv"
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(companies)
    print(f"Создано {len(companies)} компаний → {output_path}")


if __name__ == "__main__":
    main()
