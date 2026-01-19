"""
Title: UK Solar PV Deployment
Description: Monthly solar PV installations since 2010 by capacity band and accreditation type.
"""

import marimo

__generated_with = "0.19.4"
app = marimo.App(width="medium")


@app.cell
def _():
    import datetime as dt
    from pathlib import Path
    import re

    import marimo as mo
    import matplotlib.pyplot as plt
    import pandas as pd
    import requests
    return Path, dt, mo, pd, plt, re, requests


@app.cell
def _(mo):
    mo.md("""
    ## UK solar PV deployment

    This notebook downloads the latest monthly solar PV deployment dataset from GOV.UK
    and charts the number of installations since 2010, split by capacity band and
    accreditation type.
    """)
    return


@app.cell
def _():
    GOV_UK_PAGE = "https://www.gov.uk/government/statistics/solar-photovoltaics-deployment"
    return (GOV_UK_PAGE,)


@app.cell
def _(GOV_UK_PAGE, dt, mo, re, requests):
    ods_link_pattern = re.compile(r"https?://[^\"']+\.ods")
    month_lookup = {
        "january": 1,
        "february": 2,
        "march": 3,
        "april": 4,
        "may": 5,
        "june": 6,
        "july": 7,
        "august": 8,
        "september": 9,
        "october": 10,
        "november": 11,
        "december": 12,
    }

    try:
        _response = requests.get(GOV_UK_PAGE, timeout=30)
        _response.raise_for_status()
    except requests.RequestException as exc:
        mo.md(f"Unable to reach GOV.UK for the dataset list: {exc}")
        mo.stop(True)

    links = sorted(set(ods_link_pattern.findall(_response.text)))
    filtered_links = [
        link
        for link in links
        if "Solar_photovoltaics_deployment" in link or "solar_photovoltaics_deployment" in link
    ]

    if not filtered_links:
        mo.md("No .ods download links were found on the GOV.UK page.")
        mo.stop(True)

    def parse_dataset_date(url: str) -> dt.date:
        match = re.search(
            r"Solar_photovoltaics_deployment_(?P<month>[A-Za-z]+)_(?P<year>\d{4})",
            url,
        )
        if not match:
            return dt.date.min
        month_name = match.group("month").lower()
        month_num = month_lookup.get(month_name, 1)
        year_num = int(match.group("year"))
        return dt.date(year_num, month_num, 1)

    latest_ods_url = max(filtered_links, key=parse_dataset_date)
    latest_dataset_date = parse_dataset_date(latest_ods_url)
    latest_dataset_label = latest_dataset_date.strftime("%B %Y")

    mo.md(
        f"Latest dataset discovered: [{latest_dataset_label}]({latest_ods_url})."
    )
    return (latest_ods_url,)


@app.cell
def _(mo):
    redownload_button = mo.ui.button(
        value=0,
        on_click=lambda value: value + 1,
        label="Download latest dataset",
        kind="warn",
    )
    return (redownload_button,)


@app.cell
def _(Path, dt, latest_ods_url, mo, redownload_button, requests):
    data_dir = Path("data")
    data_dir.mkdir(parents=True, exist_ok=True)
    ods_path = data_dir / "solar_photovoltaics_deployment.ods"
    data_ready = ods_path.exists()

    if bool(redownload_button.value):
        response = requests.get(latest_ods_url, timeout=60)
        response.raise_for_status()
        ods_path.write_bytes(response.content)
        data_ready = True

    if data_ready:
        last_updated_ts = dt.datetime.fromtimestamp(
            ods_path.stat().st_mtime,
            tz=dt.timezone.utc,
        ).strftime("%Y-%m-%d %H:%M:%S %Z")
        update_msg = mo.md(
            f"Latest dataset saved as `solar_photovoltaics_deployment.ods` on {last_updated_ts}."
        )
    else:
        update_msg = mo.md(
            "Dataset not downloaded yet. Click **Download latest dataset** to fetch the .ods file."
        )

    update_msg
    return data_ready, ods_path


@app.cell
def _(redownload_button):
    redownload_button
    return


@app.cell
def _(data_ready, mo, ods_path, pd):
    mo.stop(not data_ready, "Download data to continue")

    def load_sheets(path):
        try:
            return pd.read_excel(path, sheet_name=None, engine="odf")
        except ImportError as exc:
            mo.md(
                "The `odfpy` dependency is required to read .ods files. "
                "Install it with `pip install odfpy` and re-run the notebook. "
                f"Original error: {exc}"
            )
            mo.stop(True, "Install odfpy")

    sheets = load_sheets(ods_path)
    return (sheets,)


@app.cell
def _(data_ready):
    data_ready
    return


@app.cell
def _(pd, sheets):
    def normalize_sheet(df: pd.DataFrame) -> pd.DataFrame:
        trimmed = df.dropna(how="all").reset_index(drop=True)
        trimmed = trimmed.loc[:, trimmed.notna().any()]
        return trimmed

    def find_header_row(df: pd.DataFrame, required_terms: list[str]) -> int | None:
        for idx in range(min(len(df), 30)):
            row_text = " ".join(str(value).lower() for value in df.iloc[idx].values)
            if "month" in row_text and all(term in row_text for term in required_terms):
                return idx
        return None

    def extract_monthly_table(
        df: pd.DataFrame,
        required_terms: list[str],
        category_name: str,
    ) -> pd.DataFrame | None:
        df = normalize_sheet(df)
        header_row = find_header_row(df, required_terms)
        if header_row is None:
            return None
        df.columns = [str(value).strip() for value in df.iloc[header_row].values]
        df = df.iloc[header_row + 1 :].copy()
        date_col = next(
            (
                col
                for col in df.columns
                if "month" in col.lower() or "date" in col.lower()
            ),
            None,
        )
        if date_col is None:
            return None
        df = df.rename(columns={date_col: "month"})
        df["month"] = pd.to_datetime(df["month"], errors="coerce")
        df = df[df["month"].notna()]
        df = df[df["month"] >= "2010-01-01"]
        value_cols = [col for col in df.columns if col != "month"]
        if not value_cols:
            return None
        tidy = df.melt(
            id_vars=["month"],
            value_vars=value_cols,
            var_name=category_name,
            value_name="installs",
        )
        tidy["installs"] = pd.to_numeric(tidy["installs"], errors="coerce")
        tidy = tidy.dropna(subset=["installs"])
        return tidy

    def find_table_by_terms(
        all_sheets: dict[str, pd.DataFrame],
        terms: list[str],
        category_name: str,
    ) -> tuple[str | None, pd.DataFrame | None]:
        for name, sheet in all_sheets.items():
            if all(term in name.lower() for term in terms):
                table = extract_monthly_table(sheet, terms, category_name)
                if table is not None:
                    return name, table
        for name, sheet in all_sheets.items():
            table = extract_monthly_table(sheet, terms, category_name)
            if table is not None:
                return name, table
        return None, None

    capacity_sheet, capacity_table = find_table_by_terms(
        sheets,
        ["capacity"],
        "capacity_band",
    )
    accreditation_sheet, accreditation_table = find_table_by_terms(
        sheets,
        ["accreditation"],
        "accreditation_type",
    )
    return (
        accreditation_sheet,
        accreditation_table,
        capacity_sheet,
        capacity_table,
    )


@app.cell
def _(
    accreditation_sheet,
    accreditation_table,
    capacity_sheet,
    capacity_table,
    mo,
):
    if capacity_table is None or accreditation_table is None:
        mo.md(
            "Could not locate the expected monthly tables. "
            "Check the sheet names and update the parsing rules if the layout changed."
        )
        mo.stop(True)

    mo.md(
        "\n".join(
            [
                f"Using capacity table from sheet: `{capacity_sheet}`.",
                f"Using accreditation table from sheet: `{accreditation_sheet}`.",
            ]
        )
    )
    return


@app.cell
def _(capacity_table, plt, subset):
    capacity_plot = capacity_table.copy()
    capacity_plot = capacity_plot.sort_values("month")

    _fig, _ax = plt.subplots(figsize=(10, 6))
    for _band, _subset in capacity_plot.groupby("capacity_band"):
        _ax.plot(subset["month"], _subset["installs"], label=str(_band))

    _ax.set_title("Monthly solar PV installations by capacity band")
    _ax.set_xlabel("Month")
    _ax.set_ylabel("Number of installations")
    _ax.legend(title="Capacity band", bbox_to_anchor=(1.05, 1), loc="upper left")
    _ax.grid(True, alpha=0.3)
    _fig.tight_layout()
    _fig
    return


@app.cell
def _(accreditation_table, plt):
    accreditation_plot = accreditation_table.copy()
    accreditation_plot = accreditation_plot.sort_values("month")

    fig, ax = plt.subplots(figsize=(10, 6))
    for accreditation, subset in accreditation_plot.groupby("accreditation_type"):
        ax.plot(subset["month"], subset["installs"], label=str(accreditation))

    ax.set_title("Monthly solar PV installations by accreditation type")
    ax.set_xlabel("Month")
    ax.set_ylabel("Number of installations")
    ax.legend(title="Accreditation", bbox_to_anchor=(1.05, 1), loc="upper left")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig
    return (subset,)


if __name__ == "__main__":
    app.run()
