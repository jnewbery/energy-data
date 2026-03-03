"""
Title: Generation Mix
Description: Visualise ENTSO-E actual generation per production type fetched by
             scripts/fetch_entsoe_generation.py.
"""

import marimo

__generated_with = "0.20.2"
app = marimo.App(width="full")


@app.cell
def _():
    import glob
    from pathlib import Path

    import marimo as mo
    import plotly.graph_objects as go
    import polars as pl

    return Path, glob, go, mo, pl


@app.cell
def _(mo):
    mo.md("""
    # Generation Mix

    Visualises electricity generation by fuel type downloaded from the
    [ENTSO-E Transparency Platform](https://transparency.entsoe.eu/) via
    `scripts/fetch_entsoe_generation.py`.

    Use the controls below to pick a country, a date range and a time aggregation level.
    """)
    return


@app.cell
def _(Path, glob, mo, pl):
    _data_dir = Path(__file__).parent.parent / "data"
    _csv_files = sorted(glob.glob(str(_data_dir / "generation_mix_*.csv")))

    mo.stop(
        not _csv_files,
        mo.md(
            "No `generation_mix_*.csv` files found in `data/`. "
            "Run `scripts/fetch_entsoe_generation.py` first."
        ),
    )

    _frames = []
    for _f in _csv_files:
        try:
            _frames.append(pl.read_csv(_f))
        except Exception:
            pass

    _META_COLS = {"datetime_utc", "area", "resolution"}

    _wide = pl.concat(_frames, how="diagonal_relaxed")
    _fuel_cols = [c for c in _wide.columns if c not in _META_COLS]

    all_gen = (
        _wide
        .unpivot(
            on=_fuel_cols,
            index=["datetime_utc", "area", "resolution"],
            variable_name="psr_type_name",
            value_name="quantity_mw",
        )
        .with_columns(
            pl.col("datetime_utc").str.to_datetime(format="%Y-%m-%dT%H:%M:%S%z", time_unit="us")
        )
        .filter(pl.col("quantity_mw").is_not_null())
        .sort(["area", "datetime_utc", "psr_type_name"])
    )
    return (all_gen,)


@app.cell
def _():
    # Consistent colours per ENTSO-E fuel type name
    PSR_COLORS: dict[str, str] = {
        "Biomass":                          "#6D4C41",
        "Fossil Brown coal/Lignite":        "#212121",
        "Fossil Coal-derived gas":          "#78909C",
        "Fossil Gas":                       "#FF7043",
        "Fossil Hard coal":                 "#424242",
        "Fossil Oil":                       "#8D6E63",
        "Fossil Oil shale":                 "#A1887F",
        "Fossil Peat":                      "#4E342E",
        "Geothermal":                       "#F57F17",
        "Hydro Pumped Storage":             "#1565C0",
        "Hydro Run-of-river and poundage":  "#64B5F6",
        "Hydro Water Reservoir":            "#1976D2",
        "Marine":                           "#00695C",
        "Nuclear":                          "#681470",
        "Other renewable":                  "#A5D6A7",
        "Solar":                            "#FFD600",
        "Waste":                            "#9E9E9E",
        "Wind Offshore":                    "#1B5E20",
        "Wind Onshore":                     "#43A047",
        "Other":                            "#BDBDBD",
        "Energy storage":                   "#0288D1",
    }

    # Stacking order: firm/baseload at bottom → variable at top → storage on top
    PSR_STACK_ORDER: list[str] = [
        "Nuclear",
        "Geothermal",
        "Biomass",
        "Hydro Run-of-river and poundage",
        "Hydro Water Reservoir",
        "Marine",
        "Fossil Brown coal/Lignite",
        "Fossil Hard coal",
        "Fossil Coal-derived gas",
        "Fossil Peat",
        "Fossil Oil shale",
        "Fossil Oil",
        "Fossil Gas",
        "Waste",
        "Other renewable",
        "Other",
        "Wind Offshore",
        "Wind Onshore",
        "Solar",
        "Hydro Pumped Storage",
        "Energy storage",
    ]
    return PSR_COLORS, PSR_STACK_ORDER


@app.cell
def _(all_gen, mo):
    _areas = sorted(all_gen["area"].unique().to_list())

    country_picker = mo.ui.dropdown(
        options=_areas,
        value=_areas[0],
        label="Country",
    )

    aggregation_picker = mo.ui.dropdown(
        options={"Hourly": "1h", "Daily": "1d", "Weekly": "1w", "Monthly": "1mo"},
        value="Daily",
        label="Aggregation",
    )

    mo.hstack([country_picker, aggregation_picker], gap=2)
    return aggregation_picker, country_picker


@app.cell
def _(all_gen, country_picker, mo, pl):
    _country_data = all_gen.filter(pl.col("area") == country_picker.value)
    _min_date = _country_data["datetime_utc"].min().date()
    _max_date = _country_data["datetime_utc"].max().date()

    date_range_picker = mo.ui.date_range(
        start=_min_date,
        stop=_max_date,
        value=(_min_date, _max_date),
        label="Date range",
        full_width=True,
    )
    date_range_picker
    return (date_range_picker,)


@app.cell
def _(aggregation_picker, all_gen, country_picker, date_range_picker, mo, pl):
    _start, _end = date_range_picker.value

    filtered_gen = (
        all_gen
        .filter(
            (pl.col("area") == country_picker.value) &
            (pl.col("datetime_utc").dt.date() >= _start) &
            (pl.col("datetime_utc").dt.date() <= _end)
        )
    )

    mo.stop(
        filtered_gen.is_empty(),
        mo.md(f"No data for **{country_picker.value}** in the selected date range."),
    )

    _agg = aggregation_picker.value
    agg_gen = (
        filtered_gen
        .sort("datetime_utc")
        .group_by_dynamic("datetime_utc", every=_agg, group_by="psr_type_name")
        .agg(pl.col("quantity_mw").mean())
        .sort(["psr_type_name", "datetime_utc"])
    )
    return agg_gen, filtered_gen


@app.cell
def _(PSR_COLORS: dict[str, str], PSR_STACK_ORDER: list[str], agg_gen, country_picker, go, pl):
    # Only show fuel types with any non-zero generation
    _active_types = (
        agg_gen
        .group_by("psr_type_name")
        .agg(pl.col("quantity_mw").sum())
        .filter(pl.col("quantity_mw") > 0)
    )

    # Sort by stacking order (firm at bottom, variable at top)
    _order_map = {name: i for i, name in enumerate(PSR_STACK_ORDER)}
    _sorted_names = sorted(
        _active_types["psr_type_name"].to_list(),
        key=lambda n: _order_map.get(n, len(PSR_STACK_ORDER)),
    )

    _fig = go.Figure()
    for _name in _sorted_names:
        _ts = agg_gen.filter(pl.col("psr_type_name") == _name).sort("datetime_utc")
        _fig.add_trace(go.Scatter(
            x=_ts["datetime_utc"].to_list(),
            y=_ts["quantity_mw"].to_list(),
            name=_name,
            mode="lines",
            line=dict(width=0.5, color=PSR_COLORS.get(_name, "#999")),
            fillcolor=PSR_COLORS.get(_name, "#999"),
            stackgroup="one",
            hovertemplate=f"<b>{_name}</b><br>%{{x|%Y-%m-%d}}<br>%{{y:,.0f}} MW<extra></extra>",
        ))

    _fig.update_layout(
        title=f"Generation Mix — {country_picker.value}",
        xaxis_title=None,
        yaxis_title="Generation (MW)",
        hovermode="x unified",
        height=480,
        legend=dict(orientation="v", x=1.01, y=1),
        margin=dict(l=60, r=180, t=48, b=40),
    )
    _fig
    return


@app.cell
def _(
    PSR_COLORS: dict[str, str],
    agg_gen,
    country_picker,
    date_range_picker,
    go,
    pl,
):
    _start, _end = date_range_picker.value

    _summary = (
        agg_gen
        .group_by("psr_type_name")
        .agg(pl.col("quantity_mw").mean().alias("avg_mw"))
        .filter(pl.col("avg_mw") > 0)
        .sort("avg_mw", descending=True)
    )

    _total = _summary["avg_mw"].sum()
    _summary = _summary.with_columns(
        (pl.col("avg_mw") / _total * 100).round(1).alias("share_pct")
    )

    _fig2 = go.Figure(go.Bar(
        x=_summary["avg_mw"].to_list(),
        y=_summary["psr_type_name"].to_list(),
        orientation="h",
        marker_color=[PSR_COLORS.get(n, "#999") for n in _summary["psr_type_name"].to_list()],
        text=[f"{v:.1f}%" for v in _summary["share_pct"].to_list()],
        textposition="outside",
        hovertemplate="<b>%{y}</b><br>Avg: %{x:,.0f} MW<extra></extra>",
    ))
    _fig2.update_layout(
        title=f"Average Generation Mix — {country_picker.value} ({_start} to {_end})",
        xaxis_title="Average MW",
        yaxis=dict(autorange="reversed"),
        height=max(300, 40 * len(_summary)),
        margin=dict(l=220, r=80, t=48, b=40),
    )
    _fig2
    return


@app.cell
def _(filtered_gen, mo, pl):
    mo.md("### Raw data"), mo.ui.table(
        filtered_gen
        .with_columns(pl.col("datetime_utc").dt.strftime("%Y-%m-%d %H:%M %Z"))
        .select(["datetime_utc", "area", "psr_type_name", "quantity_mw", "resolution"])
        .sort(["datetime_utc", "psr_type_name"]),
        page_size=20,
    )
    return


if __name__ == "__main__":
    app.run()
