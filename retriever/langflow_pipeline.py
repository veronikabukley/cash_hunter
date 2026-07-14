"""
Retriever — LangFlow-style pipeline for filtering companies from companies.csv.

Implements a pipeline of composable stages (load → filter → sort → return),
mirroring LangFlow's node-based logic in pure Python.
"""

import pandas as pd
from pathlib import Path
from typing import Optional


class Retriever:
    """Retrieve and filter companies by region, sphere, revenue, and cash volume."""

    def __init__(self, csv_path: str = "data/companies.csv"):
        self.csv_path = Path(csv_path)
        self._df: Optional[pd.DataFrame] = None

    # ── Pipeline stages (LangFlow node equivalents) ──────────────────────

    def _load(self) -> pd.DataFrame:
        """Node 1: Load CSV into DataFrame."""
        if self._df is None:
            if not self.csv_path.exists():
                raise FileNotFoundError(
                    f"Файл данных не найден: {self.csv_path}. "
                    f"Проверьте путь или запустите generate_data.py."
                )
            try:
                self._df = pd.read_csv(self.csv_path)
            except pd.errors.ParserError as exc:
                raise ValueError(
                    f"Файл данных повреждён: {self.csv_path}. "
                    f"Ошибка парсинга: {exc}"
                ) from exc
            except Exception as exc:
                raise ValueError(
                    f"Не удалось загрузить данные из {self.csv_path}: {exc}"
                ) from exc
        return self._df.copy()

    def _filter_region(self, df: pd.DataFrame, region: str) -> pd.DataFrame:
        """Node 2: Filter by region (case-insensitive)."""
        if region:
            df = df[df["Регион"].str.lower() == region.lower()]
        return df

    def _filter_sphere(self, df: pd.DataFrame, sphere: Optional[str]) -> pd.DataFrame:
        """Node 3: Filter by sphere if provided (optional)."""
        if sphere:
            df = df[df["Сфера"].str.lower() == sphere.lower()]
        return df

    def _filter_min_revenue(self, df: pd.DataFrame, min_revenue: float) -> pd.DataFrame:
        """Node 4: Keep companies with revenue >= min_revenue."""
        if min_revenue is not None and min_revenue > 0:
            df = df[df["Выручка_млн_руб"] >= min_revenue]
        return df

    def _filter_min_cash(self, df: pd.DataFrame, min_cash: float) -> pd.DataFrame:
        """Node 5: Keep companies with cash volume >= min_cash."""
        if min_cash is not None and min_cash > 0:
            df = df[df["Объём_наличных_млн_руб"] >= min_cash]
        return df

    def _sort(self, df: pd.DataFrame) -> pd.DataFrame:
        """Node 6: Sort by cash volume descending (most cash-rich first)."""
        return df.sort_values("Объём_наличных_млн_руб", ascending=False)

    # ── Pipeline runner ───────────────────────────────────────────────────

    def search(
        self,
        region: str,
        sphere: Optional[str] = None,
        min_revenue: float = 0,
        min_cash: float = 0,
    ) -> pd.DataFrame:
        """
        Run the full filter pipeline.

        Args:
            region:        Required — region name (e.g. 'Москва').
            sphere:        Optional — industry sphere (e.g. 'Ритейл'). None = all spheres.
            min_revenue:   Minimum revenue in million rubles.
            min_cash:      Minimum cash volume in million rubles.

        Returns:
            DataFrame of matching companies, sorted by cash volume (desc).
        """
        df = self._load()
        df = self._filter_region(df, region)
        df = self._filter_sphere(df, sphere)
        df = self._filter_min_revenue(df, min_revenue)
        df = self._filter_min_cash(df, min_cash)
        df = self._sort(df)
        return df


# ── Example usage ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    retriever = Retriever("data/companies.csv")

    print("=" * 70)
    print("Поиск: Москва, выручка > 50 млн ₽")
    print("=" * 70)

    results = retriever.search(
        region="Москва",
        min_revenue=50,
        min_cash=0,
    )

    if results.empty:
        print("Ничего не найдено.")
    else:
        print(f"Найдено компаний: {len(results)}\n")
        columns = [
            "id",
            "Название",
            "Регион",
            "Сфера",
            "Выручка_млн_руб",
            "Доля_наличных_%",
            "Объём_наличных_млн_руб",
        ]
        for _, row in results[columns].iterrows():
            print(
                f"  {row['id']:>3} | {row['Название']:<22} | "
                f"{row['Сфера']:<14} | "
                f"выручка: {row['Выручка_млн_руб']:>10,.1f} | "
                f"наличные: {row['Объём_наличных_млн_руб']:>8,.1f} млн ₽"
            )
        print(f"\nСуммарная выручка: {results['Выручка_млн_руб'].sum():,.1f} млн ₽")
        print(f"Суммарный объём наличных: {results['Объём_наличных_млн_руб'].sum():,.1f} млн ₽")

    # ── Дополнительный пример: Москва + Аптеки, выручка > 100 млн ────────
    print("\n" + "=" * 70)
    print("Поиск: Москва, Аптеки, выручка > 100 млн ₽, наличные > 10 млн ₽")
    print("=" * 70)

    results2 = retriever.search(
        region="Москва",
        sphere="Аптеки",
        min_revenue=100,
        min_cash=10,
    )
    if results2.empty:
        print("Ничего не найдено.")
    else:
        print(f"Найдено компаний: {len(results2)}\n")
        for _, row in results2[columns].iterrows():
            print(
                f"  {row['id']:>3} | {row['Название']:<22} | "
                f"{row['Сфера']:<14} | "
                f"выручка: {row['Выручка_млн_руб']:>10,.1f} | "
                f"наличные: {row['Объём_наличных_млн_руб']:>8,.1f} млн ₽"
            )
