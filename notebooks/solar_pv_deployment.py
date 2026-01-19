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
    mo.md(
        """
        ## UK solar PV deployment

        This notebook downloads the latest monthly solar PV deployment dataset from GOV.UK
        and charts the number of installations since 2010, split by capacity band and
        accreditation type. Monthly installs are derived from the cumulative count tables
        in the workbook.
        """
    )
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
        response = requests.get(GOV_UK_PAGE, timeout=30)
        response.raise_for_status()
    except requests.RequestException as exc:
        mo.md(f"Unable to reach GOV.UK for the dataset list: {exc}")
        mo.stop(True)

    links = sorted(set(ods_link_pattern.findall(response.text)))
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
    return latest_ods_url


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
    mo.stop(not data_ready)

    def load_sheets(path):
        try:
            return pd.read_excel(path, sheet_name=None, engine="odf")
        except ImportError as exc:
            mo.md(
                "The `odfpy` dependency is required to read .ods files. "
                "Install it with `pip install odfpy` and re-run the notebook. "
                f"Original error: {exc}"
            )
            mo.stop(True)

    sheets = load_sheets(ods_path)
    return (sheets,)


@app.cell
def _(pd, sheets):
    capacity_sheet_name = (
        "Table_1_by_Capacity_New"
        if "Table_1_by_Capacity_New" in sheets
        else "Table_1_by_Capacity"
    )
    accreditation_sheet_name = "Table_2_by_Accreditation"

    def find_cumulative_header(df: pd.DataFrame) -> int:
        matches = df.apply(
            lambda row: row.astype(str)
            .str.contains("CUMULATIVE COUNT", case=False, na=False)
            .any(),
            axis=1,
        )
        return matches[matches].index[0]

    def extract_monthly_installs(
        df: pd.DataFrame,
        section_label: str,
        category_name: str,
        category_filter: callable,
    ) -> pd.DataFrame:
        header_idx = find_cumulative_header(df)
        header = df.iloc[header_idx]
        table = df.iloc[header_idx + 1 :].copy()
        table.columns = header
        table = table.rename(columns={table.columns[0]: "category"})
        table["category"] = table["category"].astype(str).str.strip()

        section_idx = table.index[table["category"].eq(section_label)][0]
        section = table.loc[section_idx + 1 :].copy()

        month_columns = []
        month_labels = []
        for col in section.columns:
            if col == "category":
                continue
            parsed = pd.to_datetime(str(col), format="%b %Y", errors="coerce")
            if pd.notna(parsed):
                month_columns.append(col)
                month_labels.append(parsed)

        values = section[month_columns].apply(pd.to_numeric, errors="coerce")
        monthly = values.diff(axis=1)
        monthly.iloc[:, 0] = values.iloc[:, 0]

        tidy = monthly.copy()
        tidy.columns = month_labels
        tidy.insert(0, "category", section["category"].values)
        tidy = tidy[tidy["category"].apply(category_filter)]
        tidy = tidy.melt(
            id_vars=["category"],
            var_name="month",
            value_name="installs",
        )
        tidy["month"] = pd.to_datetime(tidy["month"], errors="coerce")
        tidy["installs"] = pd.to_numeric(tidy["installs"], errors="coerce")
        tidy = tidy.dropna(subset=["installs"])
        tidy = tidy.dropna(subset=["month"])
        tidy = tidy[tidy["month"] >= pd.Timestamp("2010-01-01")]
        tidy = tidy.rename(columns={"category": category_name})
        return tidy

    capacity_table = extract_monthly_installs(
        sheets[capacity_sheet_name],
        section_label="UK",
        category_name="capacity_band",
        category_filter=lambda value: "kw" in value.lower() or "mw" in value.lower(),
    )
    accreditation_table = extract_monthly_installs(
        sheets[accreditation_sheet_name],
        section_label="UK",
        category_name="accreditation_type",
        category_filter=lambda value: value.strip().upper() != "TOTAL",
    )

    return (
        accreditation_sheet_name,
        accreditation_table,
        capacity_sheet_name,
        capacity_table,
    )


@app.cell
def _(accreditation_sheet, accreditation_table, capacity_sheet, capacity_table, mo):
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
def _(capacity_table, pd, plt):
    capacity_plot = capacity_table.copy()
    capacity_plot = capacity_plot.sort_values("month")

    fig, ax = plt.subplots(figsize=(10, 6))
    for band, subset in capacity_plot.groupby("capacity_band"):
        ax.plot(subset["month"], subset["installs"], label=str(band))

    ax.set_title("Monthly solar PV installations by capacity band")
    ax.set_xlabel("Month")
    ax.set_ylabel("Number of installations")
    ax.legend(title="Capacity band", bbox_to_anchor=(1.05, 1), loc="upper left")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig
    return


@app.cell
def _(accreditation_table, pd, plt):
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
    return


if __name__ == "__main__":
    app.run()
