"""
Title: Import/Export Balance — AT · HU · SK
Description: Aggregates ENTSO-E cross-border physical flows into total imports
             and exports for Austria, Hungary and Slovakia. Shows monthly and
             yearly averages and, where load data is available (HU, SK), the
             share of load that is imported or exported.
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
    # Import/Export Balance: CZ · HU · SK

    Aggregates all ENTSO-E cross-border physical flows for **Czechia**,
    **Hungary** and **Slovakia** into total imports and total exports per
    country.

    - Monthly and yearly **average power (MW)** charts show how much electricity
      crosses each country's borders on average.
    - **% of load** charts show
      what share of national consumption is covered by imports, and what share of
      national generation is exported.

    > Mixed interconnection resolutions (PT15M / PT60M) are harmonised by
    > computing a daily average per interconnection before summing across borders.
    """)
    return


@app.cell
def _(Path, glob, mo, pl):
    _COUNTRIES = {"CZ", "HU", "SK"}
    _data_dir = Path(__file__).parent.parent / "data"
    _files = sorted(glob.glob(str(_data_dir / "cross_border_flows_*.csv")))

    mo.stop(not _files, mo.md("No `cross_border_flows_*.csv` files found in `data/`."))

    _frames = []
    for _f in _files:
        try:
            _df = pl.read_csv(_f)
            if {"out_country", "in_country", "flow_mw"}.issubset(set(_df.columns)):
                _rel = _df.filter(
                    pl.col("out_country").is_in(_COUNTRIES) |
                    pl.col("in_country").is_in(_COUNTRIES)
                )
                if _rel.height > 0:
                    _frames.append(_rel)
        except Exception:
            pass

    all_flows = (
        pl.concat(_frames, how="diagonal_relaxed")
        .with_columns(
            pl.col("datetime_utc").str.to_datetime(
                format="%Y-%m-%dT%H:%M:%S%z", time_unit="us"
            )
        )
        .unique(subset=["datetime_utc", "out_country", "in_country"], keep="first")
        .sort(["out_country", "in_country", "datetime_utc"])
    )
    return (all_flows,)


@app.cell
def _(Path, glob, pl):
    _COUNTRIES = {"CZ", "HU", "SK"}
    _data_dir = Path(__file__).parent.parent / "data"
    _files = sorted(glob.glob(str(_data_dir / "total_load_*.csv")))

    _frames = []
    for _f in _files:
        try:
            _df = pl.read_csv(_f)
            if "area" in _df.columns:
                _rel = _df.filter(pl.col("area").is_in(_COUNTRIES))
                if _rel.height > 0:
                    _frames.append(_rel)
        except Exception:
            pass

    if _frames:
        all_load = (
            pl.concat(_frames, how="diagonal_relaxed")
            .with_columns(
                pl.col("datetime_utc").str.to_datetime(
                    format="%Y-%m-%dT%H:%M:%S%z", time_unit="us"
                )
            )
            .unique(subset=["datetime_utc", "area"], keep="first")
            .sort(["area", "datetime_utc"])
        )
    else:
        all_load = None
    return (all_load,)


@app.cell
def _(all_flows, all_load, pl):
    """
    Build country_balance_daily: one row per (country, day) with:
      import_mw, export_mw, load_mw (nullable), import_pct, export_pct.

    Strategy:
      1. Aggregate each interconnection to a daily average MW (handles mixed
         resolutions — PT15M, PT60M — without inflating totals).
      2. Sum across all interconnections per country per day.
      3. Join with daily average load; compute percentages.
    """
    _COUNTRIES = ["CZ", "HU", "SK"]

    # Step 1: daily average per interconnection
    _daily_links = (
        all_flows
        .filter(
            pl.col("out_country").is_in(_COUNTRIES) |
            pl.col("in_country").is_in(_COUNTRIES)
        )
        .sort(["out_country", "in_country", "datetime_utc"])
        .group_by_dynamic(
            "datetime_utc", every="1d",
            group_by=["out_country", "in_country"],
        )
        .agg(pl.col("flow_mw").mean())
    )

    # Step 2a: total daily imports per country (sum over all exporting neighbours)
    _imports = (
        _daily_links
        .filter(pl.col("in_country").is_in(_COUNTRIES))
        .group_by(["datetime_utc", "in_country"])
        .agg(pl.col("flow_mw").sum().alias("import_mw"))
        .rename({"in_country": "country"})
    )

    # Step 2b: total daily exports per country (sum over all importing neighbours)
    _exports = (
        _daily_links
        .filter(pl.col("out_country").is_in(_COUNTRIES))
        .group_by(["datetime_utc", "out_country"])
        .agg(pl.col("flow_mw").sum().alias("export_mw"))
        .rename({"out_country": "country"})
    )

    # Step 3: join imports + exports
    _balance = (
        _imports
        .join(_exports, on=["datetime_utc", "country"], how="full", coalesce=True)
        .sort(["country", "datetime_utc"])
    )

    # Step 4: join load and compute percentages
    if all_load is not None:
        _load_daily = (
            all_load
            .sort(["area", "datetime_utc"])
            .group_by_dynamic("datetime_utc", every="1d", group_by="area")
            .agg(pl.col("load_mw").mean())
            .rename({"area": "country"})
        )
        country_balance_daily = (
            _balance
            .join(_load_daily, on=["datetime_utc", "country"], how="left")
            .with_columns([
                (pl.col("import_mw") / pl.col("load_mw") * 100).alias("import_pct"),
                (pl.col("export_mw") / pl.col("load_mw") * 100).alias("export_pct"),
                (
                    (pl.col("import_mw") - pl.col("export_mw")) /
                    pl.col("load_mw") * 100
                ).alias("net_import_pct"),
            ])
        )
    else:
        country_balance_daily = _balance.with_columns([
            pl.lit(None).cast(pl.Float64).alias("load_mw"),
            pl.lit(None).cast(pl.Float64).alias("import_pct"),
            pl.lit(None).cast(pl.Float64).alias("export_pct"),
            pl.lit(None).cast(pl.Float64).alias("net_import_pct"),
        ])
    return (country_balance_daily,)


@app.cell
def _(country_balance_daily, mo):
    _countries = sorted(country_balance_daily["country"].unique().to_list())

    country_picker = mo.ui.multiselect(
        options=_countries,
        value=_countries,
        label="Countries",
    )
    mo.hstack([country_picker], gap=2)
    return (country_picker,)


@app.cell
def _(country_balance_daily, country_picker, mo, pl):
    _filtered_for_range = country_balance_daily.filter(
        pl.col("country").is_in(country_picker.value)
    )
    _min_date = _filtered_for_range["datetime_utc"].min().date()
    _max_date = _filtered_for_range["datetime_utc"].max().date()

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
def _(country_balance_daily, country_picker, date_range_picker, mo, pl):
    _start, _end = date_range_picker.value

    filtered_balance = (
        country_balance_daily
        .filter(
            pl.col("country").is_in(country_picker.value) &
            (pl.col("datetime_utc").dt.date() >= _start) &
            (pl.col("datetime_utc").dt.date() <= _end)
        )
    )

    mo.stop(
        filtered_balance.is_empty(),
        mo.md("No data for the selected countries / date range."),
    )

    monthly_balance = (
        filtered_balance
        .sort(["country", "datetime_utc"])
        .group_by_dynamic("datetime_utc", every="1mo", group_by="country")
        .agg([
            pl.col("import_mw").mean(),
            pl.col("export_mw").mean(),
            pl.col("load_mw").mean(),
            pl.col("import_pct").mean(),
            pl.col("export_pct").mean(),
            pl.col("net_import_pct").mean(),
        ])
        .sort(["country", "datetime_utc"])
    )

    yearly_balance = (
        filtered_balance
        .sort(["country", "datetime_utc"])
        .group_by_dynamic("datetime_utc", every="1y", group_by="country")
        .agg([
            pl.col("import_mw").mean(),
            pl.col("export_mw").mean(),
            pl.col("load_mw").mean(),
            pl.col("import_pct").mean(),
            pl.col("export_pct").mean(),
            pl.col("net_import_pct").mean(),
        ])
        .sort(["country", "datetime_utc"])
    )
    return monthly_balance, yearly_balance


@app.cell
def _(go, mo, monthly_balance, pl):
    mo.md("## Monthly averages")
    _COLORS = {"CZ": "#1f77b4", "HU": "#2ca02c", "SK": "#ff7f0e"}

    _fig = go.Figure()
    for _country in sorted(monthly_balance["country"].unique().to_list()):
        _ts = monthly_balance.filter(pl.col("country") == _country).sort("datetime_utc")
        _c = _COLORS.get(_country, "#888")
        _fig.add_trace(go.Scatter(
            x=_ts["datetime_utc"].to_list(),
            y=_ts["import_mw"].to_list(),
            name=f"{_country} imports",
            mode="lines",
            line=dict(color=_c, width=2, dash="dash"),
            hovertemplate=f"<b>{_country} imports</b><br>%{{x|%Y-%m}}<br>%{{y:,.0f}} MW<extra></extra>",
        ))
        _fig.add_trace(go.Scatter(
            x=_ts["datetime_utc"].to_list(),
            y=_ts["export_mw"].to_list(),
            name=f"{_country} exports",
            mode="lines",
            line=dict(color=_c, width=2),
            hovertemplate=f"<b>{_country} exports</b><br>%{{x|%Y-%m}}<br>%{{y:,.0f}} MW<extra></extra>",
        ))

    _fig.update_layout(
        title="Monthly Average Total Imports & Exports (dashed = imports, solid = exports)",
        xaxis_title=None,
        yaxis_title="Average Power (MW)",
        hovermode="x unified",
        height=440,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        margin=dict(l=60, r=20, t=64, b=40),
    )
    _fig
    return


@app.cell
def _(go, mo, monthly_balance, pl):
    _COLORS = {"CZ": "#1f77b4", "HU": "#2ca02c", "SK": "#ff7f0e"}

    _has_pct = monthly_balance.filter(pl.col("import_pct").is_not_null())
    mo.stop(
        _has_pct.is_empty(),
        mo.callout(
            mo.md("Load data is not available for the selected countries — % of load cannot be shown."),
            kind="warn",
        ),
    )

    _fig = go.Figure()
    for _country in sorted(_has_pct["country"].unique().to_list()):
        _ts = _has_pct.filter(pl.col("country") == _country).sort("datetime_utc")
        _c = _COLORS.get(_country, "#888")
        _fig.add_trace(go.Scatter(
            x=_ts["datetime_utc"].to_list(),
            y=_ts["import_pct"].to_list(),
            name=f"{_country} import %",
            mode="lines",
            line=dict(color=_c, width=2, dash="dash"),
            hovertemplate=f"<b>{_country} import %</b><br>%{{x|%Y-%m}}<br>%{{y:.1f}}%<extra></extra>",
        ))
        _fig.add_trace(go.Scatter(
            x=_ts["datetime_utc"].to_list(),
            y=_ts["export_pct"].to_list(),
            name=f"{_country} export %",
            mode="lines",
            line=dict(color=_c, width=2),
            hovertemplate=f"<b>{_country} export %</b><br>%{{x|%Y-%m}}<br>%{{y:.1f}}%<extra></extra>",
        ))

    _fig.update_layout(
        title="Monthly Imports & Exports as % of Load — HU, SK (dashed = imports, solid = exports)",
        xaxis_title=None,
        yaxis_title="% of Load",
        hovermode="x unified",
        height=380,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        margin=dict(l=60, r=20, t=64, b=40),
    )
    _fig
    return


@app.cell
def _(go, mo, monthly_balance, pl):
    _COLORS = {"CZ": "#1f77b4", "HU": "#2ca02c", "SK": "#ff7f0e"}

    _has_pct = monthly_balance.filter(pl.col("net_import_pct").is_not_null())
    mo.stop(_has_pct.is_empty(), mo.md(""))

    _fig = go.Figure()
    for _country in sorted(_has_pct["country"].unique().to_list()):
        _ts = _has_pct.filter(pl.col("country") == _country).sort("datetime_utc")
        _c = _COLORS.get(_country, "#888")
        _fig.add_trace(go.Bar(
            x=_ts["datetime_utc"].to_list(),
            y=_ts["net_import_pct"].to_list(),
            name=_country,
            marker_color=_c,
            hovertemplate=f"<b>{_country}</b><br>%{{x|%Y-%m}}<br>Net import: %{{y:.1f}}%<extra></extra>",
        ))

    _fig.add_hline(y=0, line_dash="dot", line_color="grey", line_width=1)
    _fig.update_layout(
        title="Monthly Net Import Dependency as % of Load — HU, SK (positive = net importer)",
        xaxis_title=None,
        yaxis_title="Net imports / Load (%)",
        hovermode="x unified",
        barmode="group",
        bargap=0.15,
        height=360,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        margin=dict(l=60, r=20, t=64, b=40),
    )
    _fig
    return


@app.cell
def _(go, mo, pl, yearly_balance):
    mo.md("## Yearly averages")
    _COLORS = {"CZ": "#1f77b4", "HU": "#2ca02c", "SK": "#ff7f0e"}
    _countries = sorted(yearly_balance["country"].unique().to_list())

    _fig = go.Figure()
    for _country in _countries:
        _ts = yearly_balance.filter(pl.col("country") == _country).sort("datetime_utc")
        _years = _ts["datetime_utc"].dt.year().to_list()
        _c = _COLORS.get(_country, "#888")
        _fig.add_trace(go.Bar(
            x=_years,
            y=_ts["import_mw"].to_list(),
            name=f"{_country} imports",
            marker_color=_c,
            opacity=0.55,
            hovertemplate=f"<b>{_country} imports</b><br>%{{x}}<br>%{{y:,.0f}} MW<extra></extra>",
        ))
        _fig.add_trace(go.Bar(
            x=_years,
            y=_ts["export_mw"].to_list(),
            name=f"{_country} exports",
            marker_color=_c,
            opacity=1.0,
            hovertemplate=f"<b>{_country} exports</b><br>%{{x}}<br>%{{y:,.0f}} MW<extra></extra>",
        ))

    _fig.update_layout(
        title="Yearly Average Total Imports & Exports (light bars = imports, solid = exports)",
        xaxis_title=None,
        yaxis_title="Average Power (MW)",
        hovermode="x unified",
        barmode="group",
        height=400,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        margin=dict(l=60, r=20, t=64, b=40),
    )
    _fig
    return


@app.cell
def _(go, mo, pl, yearly_balance):
    _COLORS = {"CZ": "#1f77b4", "HU": "#2ca02c", "SK": "#ff7f0e"}

    _has_pct = yearly_balance.filter(pl.col("import_pct").is_not_null())
    mo.stop(
        _has_pct.is_empty(),
        mo.callout(
            mo.md("Load data is not available for the selected countries — yearly % of load cannot be shown."),
            kind="warn",
        ),
    )

    _countries_pct = sorted(_has_pct["country"].unique().to_list())
    _fig = go.Figure()
    for _country in _countries_pct:
        _ts = _has_pct.filter(pl.col("country") == _country).sort("datetime_utc")
        _years = _ts["datetime_utc"].dt.year().to_list()
        _c = _COLORS.get(_country, "#888")
        _fig.add_trace(go.Bar(
            x=_years,
            y=_ts["import_pct"].to_list(),
            name=f"{_country} import %",
            marker_color=_c,
            opacity=0.55,
            hovertemplate=f"<b>{_country} import %</b><br>%{{x}}<br>%{{y:.1f}}%<extra></extra>",
        ))
        _fig.add_trace(go.Bar(
            x=_years,
            y=_ts["export_pct"].to_list(),
            name=f"{_country} export %",
            marker_color=_c,
            opacity=1.0,
            hovertemplate=f"<b>{_country} export %</b><br>%{{x}}<br>%{{y:.1f}}%<extra></extra>",
        ))

    _fig.update_layout(
        title="Yearly Imports & Exports as % of Load — HU, SK (light bars = imports, solid = exports)",
        xaxis_title=None,
        yaxis_title="% of Load",
        barmode="group",
        height=380,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        margin=dict(l=60, r=20, t=64, b=40),
    )
    _fig
    return


@app.cell
def _(go, mo, pl, yearly_balance):
    _COLORS = {"CZ": "#1f77b4", "HU": "#2ca02c", "SK": "#ff7f0e"}

    _has_pct = yearly_balance.filter(pl.col("net_import_pct").is_not_null())
    mo.stop(_has_pct.is_empty(), mo.md(""))

    _countries_net = sorted(_has_pct["country"].unique().to_list())
    _fig = go.Figure()
    for _country in _countries_net:
        _ts = _has_pct.filter(pl.col("country") == _country).sort("datetime_utc")
        _years = _ts["datetime_utc"].dt.year().to_list()
        _c = _COLORS.get(_country, "#888")
        _fig.add_trace(go.Bar(
            x=_years,
            y=_ts["net_import_pct"].to_list(),
            name=_country,
            marker_color=_c,
            hovertemplate=f"<b>{_country}</b><br>%{{x}}<br>Net import: %{{y:.1f}}%<extra></extra>",
        ))

    _fig.add_hline(y=0, line_dash="dot", line_color="grey", line_width=1)
    _fig.update_layout(
        title="Yearly Net Import Dependency as % of Load — HU, SK (positive = net importer)",
        xaxis_title=None,
        yaxis_title="Net imports / Load (%)",
        barmode="group",
        height=360,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        margin=dict(l=60, r=20, t=64, b=40),
    )
    _fig
    return


if __name__ == "__main__":
    app.run()
