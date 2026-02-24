"""
Title: European Power Datasheets
Description: Download two European electricity workbooks and parse them into Polars DataFrames.
"""

import marimo

__generated_with = "0.20.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import datetime as dt
    from pathlib import Path

    import marimo as mo
    import pandas as pd
    import polars as pl
    import requests

    return Path, dt, mo, pd, pl, requests


@app.cell
def _(mo):
    mo.md("""
    ## European power data

    This notebook pulls data from two datasets:
    1. EU Energy Statistical Country Datasheets (https://energy.ec.europa.eu/data-and-analysis/eu-energy-statistical-pocketbook-and-country-datasheets_en#country-datasheets)
    2. GHG Emissions Factors for Electricity Consumption (https://data.jrc.ec.europa.eu/dataset/919df040-0252-4e4e-ad82-c054896e1641)

    Parsing runs automatically when the corresponding workbook file exists in `data/`.
    """)
    return


@app.cell
def _():
    EU_DATASHEETS_URL = (
        "https://energy.ec.europa.eu/document/download/"
        "6b6b548d-96f0-401b-84ed-0dc8f85a1110_en?"
        "filename=Energy%20statistical%20country%20datasheets%202025-08%20for%20web.xlsx"
    )
    GHG_FACTORS_URL = (
        "https://jeodpp.jrc.ec.europa.eu/ftp/public/JRC-OpenData/CoM/"
        "EmissionsFactorElectricity/CoM-Emission-factors-for-national-electricity-2024.xlsx"
    )
    return EU_DATASHEETS_URL, GHG_FACTORS_URL


@app.cell
def _(mo):
    download_eu_button = mo.ui.button(
        value=0,
        on_click=lambda value: value + 1,
        label="Download EU country datasheets",
        kind="warn",
    )
    return (download_eu_button,)


@app.cell
def _(EU_DATASHEETS_URL, Path, download_eu_button, dt, mo, requests):
    _data_dir = Path("data")
    _data_dir.mkdir(parents=True, exist_ok=True)
    eu_workbook_path = _data_dir / "eu_energy_country_datasheets_2025_08.xlsx"
    eu_data_ready = eu_workbook_path.exists()

    if bool(download_eu_button.value):
        _response = requests.get(EU_DATASHEETS_URL, timeout=120)
        _response.raise_for_status()
        eu_workbook_path.write_bytes(_response.content)
        eu_data_ready = True

    if eu_data_ready:
        _last_updated_ts = dt.datetime.fromtimestamp(
            eu_workbook_path.stat().st_mtime,
            tz=dt.timezone.utc,
        ).strftime("%Y-%m-%d %H:%M:%S %Z")
        _update_msg = mo.md(
            "EU datasheets workbook saved at "
            f"`data/eu_energy_country_datasheets_2025_08.xlsx` on {_last_updated_ts}."
        )
    else:
        _update_msg = mo.md(
            "EU datasheets workbook not downloaded yet. "
            "Click **Download EU country datasheets**."
        )

    _update_msg
    return eu_data_ready, eu_workbook_path


@app.cell
def _(download_eu_button):
    download_eu_button
    return


@app.cell
def _(mo):
    download_ghg_button = mo.ui.button(
        value=0,
        on_click=lambda value: value + 1,
        label="Download GHG emissions factors",
        kind="warn",
    )
    return (download_ghg_button,)


@app.cell
def _(GHG_FACTORS_URL, Path, download_ghg_button, dt, mo, requests):
    _data_dir = Path("data")
    _data_dir.mkdir(parents=True, exist_ok=True)
    ghg_workbook_path = _data_dir / "com_emission_factors_national_electricity_2024.xlsx"
    ghg_data_ready = ghg_workbook_path.exists()

    if bool(download_ghg_button.value):
        _response = requests.get(GHG_FACTORS_URL, timeout=120)
        _response.raise_for_status()
        ghg_workbook_path.write_bytes(_response.content)
        ghg_data_ready = True

    if ghg_data_ready:
        _last_updated_ts = dt.datetime.fromtimestamp(
            ghg_workbook_path.stat().st_mtime,
            tz=dt.timezone.utc,
        ).strftime("%Y-%m-%d %H:%M:%S %Z")
        _update_msg = mo.md(
            "GHG emissions factors workbook saved at "
            f"`data/com_emission_factors_national_electricity_2024.xlsx` on {_last_updated_ts}."
        )
    else:
        _update_msg = mo.md(
            "GHG emissions factors workbook not downloaded yet. "
            "Click **Download GHG emissions factors**."
        )

    _update_msg
    return ghg_data_ready, ghg_workbook_path


@app.cell
def _(download_ghg_button):
    download_ghg_button
    return


@app.cell
def _(pd, pl):
    def normalize_columns(columns):
        names = []
        seen = {}
        for idx, raw_name in enumerate(columns, start=1):
            base = str(raw_name).strip()
            if not base or base.lower() == "nan":
                base = f"column_{idx}"
            count = seen.get(base, 0) + 1
            seen[base] = count
            names.append(base if count == 1 else f"{base}_{count}")
        return names

    def build_series(column_name, values):
        try:
            return pl.Series(column_name, values, strict=False)
        except pl.exceptions.PolarsError:
            # Mixed temporal/string columns can fail strict temporal coercion; fall back to text.
            normalized = [None if value is None else str(value) for value in values]
            return pl.Series(column_name, normalized, dtype=pl.Utf8, strict=False)

    def parse_workbook(workbook_path):
        sheets = pd.read_excel(workbook_path, sheet_name=None)
        sheet_frames = []
        sheet_stats = []

        for sheet_name, sheet_pdf in sheets.items():
            cleaned = sheet_pdf.dropna(how="all").dropna(axis=1, how="all").copy()
            if cleaned.empty:
                continue
            cleaned.columns = normalize_columns(cleaned.columns)
            cleaned = cleaned.astype("object").where(cleaned.notna(), None)
            sheet_df = pl.DataFrame(
                {
                    column_name: build_series(column_name, cleaned[column_name].tolist())
                    for column_name in cleaned.columns
                }
            ).with_columns(pl.lit(sheet_name).alias("sheet_name"))
            sheet_frames.append(sheet_df)
            sheet_stats.append(
                {
                    "sheet_name": sheet_name,
                    "rows": sheet_df.height,
                    "columns": sheet_df.width - 1,
                }
            )

        if not sheet_frames:
            return None, None

        parsed_df = pl.concat(sheet_frames, how="diagonal_relaxed")
        parsed_sheets = pl.DataFrame(sheet_stats).sort("rows", descending=True)
        return parsed_df, parsed_sheets

    return (parse_workbook,)


@app.cell
def _(eu_data_ready, eu_workbook_path, mo, parse_workbook):
    mo.stop(not eu_data_ready, "Download the EU datasheets workbook to continue.")

    european_power_df, european_power_sheets = parse_workbook(eu_workbook_path)
    mo.stop(european_power_df is None, "No non-empty sheets were found in the EU workbook.")
    return european_power_df, european_power_sheets


@app.cell
def _(european_power_df, european_power_sheets, mo):
    mo.md(f"""
    EU datasheets parsed: {european_power_sheets.height} sheets, "
        f"{european_power_df.height:,} rows, {european_power_df.width:,} columns.
    """)
    return


@app.cell
def _(european_power_df, european_power_sheets):
    european_power_sheets, european_power_df.head(20)
    return


@app.cell
def _(ghg_data_ready, ghg_workbook_path, mo, parse_workbook):
    mo.stop(not ghg_data_ready, "Download the GHG emissions factors workbook to continue.")

    ghg_emissions_factors_df, ghg_emissions_sheets = parse_workbook(ghg_workbook_path)
    mo.stop(
        ghg_emissions_factors_df is None,
        "No non-empty sheets were found in the GHG workbook.",
    )
    return ghg_emissions_factors_df, ghg_emissions_sheets


@app.cell
def _(ghg_emissions_factors_df, ghg_emissions_sheets, mo):
    mo.md(f"""
    GHG factors parsed: {ghg_emissions_sheets.height} sheets, "
        f"{ghg_emissions_factors_df.height:,} rows, {ghg_emissions_factors_df.width:,} columns.
    """)
    return


@app.cell
def _(ghg_emissions_factors_df, ghg_emissions_sheets):
    ghg_emissions_sheets, ghg_emissions_factors_df.head(20)
    return


if __name__ == "__main__":
    app.run()
