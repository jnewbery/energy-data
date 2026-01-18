"""
Title: DRAX BM Unit Export Histograms
Description: Explore half-hourly exported energy distributions for DRAX BM units.
"""

import marimo

__generated_with = "0.19.4"
app = marimo.App(width="full")


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # DRAX BM Unit Export Histograms

    Visualize half-hourly exported energy for each DRAX BM Unit in `ABV_2024_DRAX.csv`.

    Steps:
    1. Load the Aggregated BM Unit (ABV) data from Elexon.
    2. Keep only export (`Import/Export Indicator == 'E'`) rows and clean the numeric columns.
    3. Plot a histogram for each BM Unit to show the spread of exported energy values across the year.
    """)
    return


@app.cell
def _():
    from pathlib import Path
    import marimo as mo
    import pandas as pd
    import matplotlib.pyplot as plt

    plt.style.use('seaborn-v0_8-whitegrid')
    return Path, mo, pd, plt


@app.cell
def _(Path, mo, pd):
    # Fetch ABV_2024.zip from https://www.elexon.co.uk/open-data/ABV_2024.zip,
    # unzip and then filter for rows where the BM Unit Id starts with
    # 'T_DRAXX-'.
    data_path = Path('data/ABV_2024_DRAX.csv')

    expected_columns = [
        'Data Flow ID','Flow Run Date','BM Unit Id','Settlement Date','Settlement Run Type',
        'CDCA Run Number','Date of Aggregation','Settlement Period','Estimate Indicator',
        'Meter Volume','Import/Export Indicator'
    ]

    # Load the CSV; column order is fixed so we only check for missing headers.
    df = pd.read_csv(data_path)
    missing = set(expected_columns) - set(df.columns)
    if missing:
        raise ValueError(f'Missing expected columns: {missing}')

    # Convert key columns into convenient formats.
    df['Settlement Date'] = pd.to_datetime(df['Settlement Date'], format='%Y%m%d')
    df['Settlement Period'] = pd.to_numeric(df['Settlement Period'], errors='coerce').astype('Int64')
    df['Meter Volume'] = pd.to_numeric(df['Meter Volume'], errors='coerce')

    df = df.dropna(subset=['Meter Volume'])
    df = df[df['Settlement Run Type'].str.upper() == 'R1'].copy()
    exports = df[df['Import/Export Indicator'].str.upper() == 'E'].copy()

    target_units = [
        'T_DRAXX-1',
        'T_DRAXX-2',
        'T_DRAXX-3',
        'T_DRAXX-4'
    ]
    available_units = [u for u in target_units if u in exports['BM Unit Id'].unique()]
    missing_units = sorted(set(target_units) - set(available_units))
    summary_lines = []
    if missing_units:
        summary_lines.append(
            f"**Warning:** missing BM Units in dataset: {', '.join(missing_units)}"
        )
    if not available_units:
        raise ValueError('None of the requested BM Units are present in the dataset.')

    exports = exports[exports['BM Unit Id'].isin(available_units)].copy()

    summary_lines.extend(
        [
            f"Total rows: {len(df):,}",
            f"Export rows: {len(exports):,}",
            f"BM Units: {', '.join(available_units)}",
        ]
    )
    _summary = mo.md("\n".join(f"- {line}" for line in summary_lines))
    _summary
    return available_units, exports


@app.cell
def _(available_units, exports, plt):
    units = available_units
    n_units = len(units)
    cols = 1
    rows = n_units

    fig, axes = plt.subplots(rows, cols, figsize=(20, 10 * rows), constrained_layout=True, squeeze=False)
    axes = axes.flatten()

    for idx, unit in enumerate(units):
        ax = axes[idx]
        data = exports.loc[exports['BM Unit Id'] == unit, 'Meter Volume']
        counts, bins, _ = ax.hist(data, bins=50, color='#3B82F6', edgecolor='black')

        ax.set_title(unit, fontsize=14)
        ax.set_xlabel('Meter Volume (MWh) per Settlement Period')
        ax.set_ylabel('Count of Half-Hours')
        ax.grid(True, linestyle='--', alpha=0.5)

    for extra_ax in axes[n_units:]:
        extra_ax.set_visible(False)

    fig.suptitle('Distribution of Exported Energy by DRAX BM Unit (T_DRAXX-1 to T_DRAXX-4, 2024)', fontsize=18, y=1.01)
    per_unit_summary = (
        exports.groupby('BM Unit Id')['Meter Volume']
        .agg(total_export_mwh='sum', intervals='count')
        .reindex(units)
    )
    per_unit_summary['potential_mwh'] = per_unit_summary['intervals'] * 330
    per_unit_summary['capacity_factor'] = round(per_unit_summary['total_export_mwh'] / per_unit_summary['potential_mwh'], 2)

    combined_export = per_unit_summary['total_export_mwh'].sum()
    combined_potential = per_unit_summary['potential_mwh'].sum()
    combined_cf = combined_export / combined_potential if combined_potential else float('nan')
    return combined_cf, combined_export, fig, per_unit_summary


@app.cell
def _(combined_cf, combined_export, fig, mo, per_unit_summary):
    per_unit_table = mo.ui.table(
        per_unit_summary.reset_index().rename(columns={'BM Unit Id': 'BM Unit'})
    )
    combined_summary = mo.md(f"- Combined capacity factor: **{combined_cf:.2%}** ({combined_export:,.0f} MWh delivered)",)
    mo.vstack([fig, per_unit_table, combined_summary])
    return


@app.cell
def _(Path, exports, pd):
    exports_with_time = exports.copy()
    slot_offset_mins = (exports_with_time['Settlement Period'] - 1) * 30
    exports_with_time['interval_start'] = exports_with_time['Settlement Date'] + pd.to_timedelta(slot_offset_mins, unit='m')

    export_totals = (
        exports_with_time.groupby('interval_start', as_index=False)['Meter Volume']
        .sum()
        .rename(columns={'Meter Volume': 'total_export_mwh'})
    )

    per_unit = (
        exports_with_time.pivot_table(
            index='interval_start',
            columns='BM Unit Id',
            values='Meter Volume',
            aggfunc='sum',
            fill_value=0,
        )
        .reset_index()
    )
    per_unit.columns = [
        'interval_start' if col == 'interval_start' else f"{col}_export_mwh"
        for col in per_unit.columns
    ]

    export_profile = export_totals.merge(per_unit, on='interval_start', how='left')

    # Fetch df_fuel_ckan.csv from https://api.neso.energy/dataset/88313ae5-94e4-4ddc-a790-593554d8c6b9/resource/f93d1835-75bc-43e5-84ad-12472b180a98/download/df_fuel_ckan.csv
    ci = (
        pd.read_csv(Path('data/df_fuel_ckan.csv'), parse_dates=['DATETIME'])
        .rename(columns={'DATETIME': 'interval_start', 'CARBON_INTENSITY': 'carbon_intensity_gco2_per_kwh'})
        [['interval_start', 'carbon_intensity_gco2_per_kwh']]
    )

    carbon_export_df = export_profile.merge(ci, on='interval_start', how='left')
    carbon_export_df['weighted_carbon_component'] = (
        carbon_export_df['carbon_intensity_gco2_per_kwh'] * carbon_export_df['total_export_mwh']
    )

    matched = carbon_export_df['carbon_intensity_gco2_per_kwh'].notna().sum()
    preview_cols = [
        'interval_start',
        'total_export_mwh',
        'carbon_intensity_gco2_per_kwh',
        'weighted_carbon_component',
    ]
    return carbon_export_df, export_profile, matched, preview_cols


@app.cell
def _(carbon_export_df, export_profile, matched, mo, preview_cols):
    summary = mo.md(
        "\n".join(
            [
                f"- Intervals with DRAX exports: **{len(export_profile):,}**",
                f"- Intervals matched to carbon intensity data: **{matched:,}**",
            ]
        )
    )
    table = mo.ui.table(carbon_export_df[preview_cols])
    mo.vstack([summary, table])
    return


@app.cell
def _(carbon_export_df, mo):
    valid = carbon_export_df.dropna(subset=['carbon_intensity_gco2_per_kwh'])
    total_export = valid['total_export_mwh'].sum()
    _weighted_sum = valid['weighted_carbon_component'].sum()

    weighted_avg_carbon_intensity = _weighted_sum / total_export if total_export else float('nan')
    mo.md(
        f"Energy-weighted average carbon intensity: **{weighted_avg_carbon_intensity:.2f} gCO₂/kWh**"
    )
    return


@app.cell
def _(Path, mo, pd):
    ci_full = pd.read_csv(Path('data/df_fuel_ckan.csv'), parse_dates=['DATETIME'])
    period_mask = (ci_full['DATETIME'] >= '2023-11-13') & (ci_full['DATETIME'] <= '2024-11-12 23:30:00')
    period_df = ci_full.loc[period_mask].copy()
    period_df = period_df.dropna(subset=['CARBON_INTENSITY', 'GENERATION'])

    _weighted_sum = (period_df['CARBON_INTENSITY'] * period_df['GENERATION']).sum()
    total_generation = period_df['GENERATION'].sum()
    grid_weighted_avg_ci = _weighted_sum / total_generation if total_generation else float('nan')

    mo.md(
        "\n".join(
            [
                "- Grid weighted-average carbon intensity (2023-11-13 to 2024-11-12): "
                f"**{grid_weighted_avg_ci:.2f} gCO₂/kWh**\n",
                f"- Half-hour intervals included: **{len(period_df):,}**",
            ]
        )
    )
    return


if __name__ == "__main__":
    app.run()
