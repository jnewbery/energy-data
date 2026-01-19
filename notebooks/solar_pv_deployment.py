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
    accreditation type. Monthly deployments are derived from the cumulative counts
    in the source workbook.
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
        if "Solar_photovoltaics_deployment" in link
        or "solar_photovoltaics_deployment" in link
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

    mo.md(f"Latest dataset discovered: [{latest_dataset_label}]({latest_ods_url}).")
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
            "Latest dataset saved as `solar_photovoltaics_deployment.ods` on "
            f"{last_updated_ts}."
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
def _(pd, re, sheets):
    def normalize_sheet(df: pd.DataFrame) -> pd.DataFrame:
        trimmed = df.dropna(how="all").reset_index(drop=True)
        trimmed = trimmed.loc[:, trimmed.notna().any()]
        return trimmed

    def find_header_row(df: pd.DataFrame, header_text: str) -> int | None:
        for idx in range(min(len(df), 40)):
            row_text = " ".join(str(value).lower() for value in df.iloc[idx].values)
            if header_text in row_text:
                return idx
        return None

    def parse_month_label(label: str) -> pd.Timestamp | None:
        if label is None:
            return None
        text = str(label).strip()
        match = re.match(r"^([A-Za-z]{3,9})\s*(\d{4})$", text)
        if not match:
            return None
        month_text, year_text = match.groups()
        for fmt in ("%b%Y", "%B%Y"):
            try:
                return pd.to_datetime(f"{month_text}{year_text}", format=fmt)
            except ValueError:
                continue
        return None

    def extract_cumulative_deployments(
        df: pd.DataFrame,
        category_name: str,
        region: str = "UK",
    ) -> pd.DataFrame | None:
        df = normalize_sheet(df)
        header_row = find_header_row(df, "cumulative count")
        if header_row is None:
            return None
        header_values = [
            str(value).strip() if pd.notna(value) else ""
            for value in df.iloc[header_row].values
        ]
        if not header_values:
            return None
        if not header_values[0]:
            header_values[0] = "category"
        df = df.iloc[header_row + 1 :].copy()
        df.columns = header_values
        first_col = header_values[0]
        df = df.rename(columns={first_col: "category"})

        region_labels = {"GB", "NI", "UK"}
        region_values = []
        current_region = None
        for _, row in df.iterrows():
            category = str(row["category"]).strip()
            other_values = row.drop(labels=["category"]).apply(
                lambda value: str(value).strip() if pd.notna(value) else ""
            )
            if category in region_labels and all(value == "" for value in other_values):
                current_region = category
                region_values.append(None)
            else:
                region_values.append(current_region)
        df["region"] = region_values
        df = df[df["region"] == region]
        df["category"] = df["category"].astype(str).str.strip()
        df = df[df["category"] != ""]
        df = df[
            ~df["category"].str.lower().str.startswith(
                ("total", "pre 2009", "of which")
            )
        ]

        month_map = {}
        for col in df.columns:
            if col in ("category", "region"):
                continue
            parsed = parse_month_label(col)
            if parsed is not None:
                month_map[col] = parsed
        if not month_map:
            return None
        value_cols = list(month_map.keys())

        tidy = df[["category"] + value_cols].melt(
            id_vars=["category"],
            var_name="month",
            value_name="cumulative",
        )
        tidy["month"] = tidy["month"].map(month_map)
        tidy = tidy.dropna(subset=["month"])
        tidy["cumulative"] = (
            tidy["cumulative"].astype(str).str.replace(",", "", regex=False)
        )
        tidy["cumulative"] = pd.to_numeric(tidy["cumulative"], errors="coerce")
        tidy = tidy.dropna(subset=["cumulative"])
        tidy = tidy.sort_values(["category", "month"])
        tidy["deployments"] = tidy.groupby("category")["cumulative"].diff()
        tidy["deployments"] = tidy["deployments"].fillna(tidy["cumulative"])
        tidy = tidy[tidy["month"] >= "2010-01-01"]
        tidy = tidy.rename(columns={"category": category_name})
        return tidy[["month", category_name, "deployments"]]

    def pick_sheet(all_sheets: dict[str, pd.DataFrame], names: list[str]) -> str | None:
        for name in names:
            for sheet_name in all_sheets:
                if name in sheet_name.lower():
                    return sheet_name
        return None

    capacity_sheet = pick_sheet(
        sheets,
        ["table_1_by_capacity_new", "table_1_by_capacity"],
    )
    accreditation_sheet = pick_sheet(sheets, ["table_2_by_accreditation"])

    capacity_table = (
        extract_cumulative_deployments(sheets[capacity_sheet], "capacity_band")
        if capacity_sheet
        else None
    )
    accreditation_table = (
        extract_cumulative_deployments(
            sheets[accreditation_sheet],
            "accreditation_type",
        )
        if accreditation_sheet
        else None
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
            "Could not locate the expected cumulative count tables. "
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
def _(ax, capacity_table, plt, subset):
    capacity_plot = capacity_table.copy()
    capacity_plot = capacity_plot.sort_values("month")

    _fig, _ax = plt.subplots(figsize=(10, 6))
    for _band, _subset in capacity_plot.groupby("capacity_band"):
        ax.plot(subset["month"], _subset["deployments"], label=str(_band))

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
        ax.plot(subset["month"], subset["deployments"], label=str(accreditation))

    ax.set_title("Monthly solar PV installations by accreditation type")
    ax.set_xlabel("Month")
    ax.set_ylabel("Number of installations")
    ax.legend(title="Accreditation", bbox_to_anchor=(1.05, 1), loc="upper left")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig
    return ax, subset


if __name__ == "__main__":
    app.run()
