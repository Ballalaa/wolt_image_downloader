"""Excel ingestion: pulls (url, sku) pairs from the first two columns of a workbook."""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

import pandas as pd


@dataclass(frozen=True)
class Row:
    index: int
    url: str
    sku: str


def parse_workbook(file_bytes: bytes) -> list[Row]:
    try:
        df = pd.read_excel(BytesIO(file_bytes), engine="openpyxl", header=0)
    except Exception as error:  # noqa: BLE001 - surfaced to the caller as-is
        raise ValueError(f"Could not read the Excel file: {error}") from error

    if df.shape[1] < 2:
        raise ValueError(
            "The sheet needs at least two columns: image links in column A, "
            "SKUs in column B."
        )

    url_series = df.iloc[:, 0]
    sku_series = df.iloc[:, 1]

    rows: list[Row] = []
    for position, (url, sku) in enumerate(zip(url_series, sku_series)):
        if pd.isna(url) or pd.isna(sku):
            continue
        url_str = str(url).strip()
        sku_str = str(sku).strip()
        if not url_str or not sku_str:
            continue
        rows.append(Row(index=position, url=url_str, sku=sku_str))

    if not rows:
        raise ValueError(
            "No usable rows found. Check that column A has image links and "
            "column B has SKUs, starting on row 2."
        )

    return rows
