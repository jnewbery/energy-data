import marimo

__generated_with = "0.19.4"
app = marimo.App(width="medium")


@app.cell
def _():
    import datetime as dt

    from pathlib import Path
    import polars as pl
    import matplotlib.pyplot as plt
    return Path, dt, pl, plt


@app.cell
def _(Path, requests):
    data_dir = Path("data")
    data_dir.mkdir(parents=True, exist_ok=True)
    csv_path = data_dir / "gb_carbon_intensity.csv"
    source_url = (
        "https://api.neso.energy/dataset/f406810a-1a36-48d2-b542-1dfb1348096e/"
        "resource/0e5fde43-2de7-4fb4-833d-c7bca3b658b0/download/"
        "gb_carbon_intensity.csv"
    )
    if not csv_path.exists():
        response = requests.get(source_url, timeout=30)
        response.raise_for_status()
        csv_path.write_bytes(response.content)
    return (csv_path,)


@app.cell
def _(csv_path, pl):
    raw = pl.read_csv(csv_path)
    cleaned = (
        raw.with_columns(
            pl.col("datetime")
            .str.strptime(pl.Datetime, strict=False)
            .alias("datetime"),
            pl.col("actual").cast(pl.Float64).alias("actual"),
        )
        .filter(pl.col("actual").is_not_null())
        .with_columns(pl.col("datetime").dt.truncate("1mo").alias("month"))
    )
    monthly_avg = (
        cleaned.group_by("month")
        .agg(pl.col("actual").mean().alias("avg_actual"))
        .sort("month")
    )
    return (monthly_avg,)


@app.cell
def _(monthly_avg, pl):
    max_month = monthly_avg.select(pl.col("month").max()).item()
    start_month = max_month.replace(year=max_month.year - 5)
    last_five_years = monthly_avg.filter(pl.col("month") >= start_month)
    return (last_five_years,)


@app.cell
def _(last_five_years, pl):
    seasonal = (
        last_five_years.with_columns(
            pl.col("month").dt.month().alias("month_num"),
            pl.col("month").dt.year().alias("year_num"),
        )
        .with_columns(
            pl.when(pl.col("month_num").is_in([12, 1, 2]))  # Winter is December / January / February
            .then(pl.lit("winter"))
            .when(pl.col("month_num").is_in([6, 7, 8]))  # Winter is June / July / August
            .then(pl.lit("summer"))
            .otherwise(pl.lit("spring_autumn"))  # Spring/Autumn is everything else
            .alias("season"),
            pl.when(pl.col("month_num").eq(12))
            .then(pl.col("year_num"))
            .when(pl.col("month_num").is_in([1, 2]))
            .then(pl.col("year_num") - 1)
            .otherwise(pl.col("year_num"))
            .alias("season_year"),
        )
        .group_by(["season", "season_year"])
        .agg(pl.col("avg_actual").mean().alias("avg_actual"))
        .sort(["season", "season_year"])
    )
    return (seasonal,)


@app.cell
def _(pl, seasonal):
    def linear_regression(xs, ys):
        n = len(xs)
        if n < 2:
            return 0.0, ys[0] if ys else 0.0
        mean_x = sum(xs) / n
        mean_y = sum(ys) / n
        numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
        denominator = sum((x - mean_x) ** 2 for x in xs)
        slope = numerator / denominator if denominator else 0.0
        intercept = mean_y - slope * mean_x
        return slope, intercept

    regression_info = {}
    for _season in ["winter", "summer", "spring_autumn"]:
        subset = seasonal.filter(pl.col("season") == _season)
        xs = subset.get_column("season_year").to_list()
        ys = subset.get_column("avg_actual").to_list()
        _slope, _intercept = linear_regression(xs, ys)
        regression_info[_season] = {
            "season_years": xs,
            "avg_actual": ys,
            "slope": _slope,
            "intercept": _intercept,
        }
    return (regression_info,)


@app.cell
def _(dt, last_five_years, pl, plt, regression_info, seasonal):
    season_colors = {
        "winter": "tab:blue",
        "summer": "gold",
        "spring_autumn": "tab:green",
    }
    monthly_with_season = last_five_years.with_columns(
        pl.when(pl.col("month").dt.month().is_in([12, 1, 2]))
        .then(pl.lit("winter"))
        .when(pl.col("month").dt.month().is_in([6, 7, 8]))
        .then(pl.lit("summer"))
        .otherwise(pl.lit("spring_autumn"))
        .alias("season")
    )
    month_list = monthly_with_season.get_column("month").to_list()
    values = monthly_with_season.get_column("avg_actual").to_list()
    colors = [
        season_colors[season]
        for season in monthly_with_season.get_column("season").to_list()
    ]

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.bar(month_list, values, color=colors, width=10, label="Monthly average")

    representative_months = {
        "winter": [(1, 1)],
        "summer": [(7, 0)],
        "spring_autumn": [(4, 0), (10, 0)],
    }
    for _season, color in season_colors.items():
        season_data = seasonal.filter(pl.col("season") == _season)
        years = season_data.get_column("season_year").to_list()
        values = season_data.get_column("avg_actual").to_list()
        for _month, year_offset in representative_months[_season]:
            ax.scatter(
                [dt.date(year + year_offset, _month, 1) for year in years],
                values,
                label=f"{_season.replace('_', '/').title()} avg",
                color=color,
                edgecolors="black",
                linewidths=0.8,
                zorder=3,
            )
        _slope = regression_info[_season]["slope"]
        _intercept = regression_info[_season]["intercept"]
        if years:
            line_x = [min(years), max(years)]
            line_y = [_slope * x + _intercept for x in line_x]
            for _month, year_offset in representative_months[_season]:
                ax.plot(
                    [dt.date(year + year_offset, _month, 1) for year in line_x],
                    line_y,
                    linestyle="--",
                    color=color,
                    alpha=0.7,
                    label=f"{_season.replace('_', '/').title()} trend",
                )

    ax.set_title("GB grid carbon intensity monthly averages")
    ax.set_xlabel("Date")
    ax.set_ylabel("gCO₂/kWh")
    ax.grid(True, axis="y", alpha=0.3)
    legend_handles = [
        plt.Rectangle((0, 0), 1, 1, color=color)
        for color in season_colors.values()
    ]
    ax.legend(
        legend_handles,
        ["Winter", "Summer", "Spring/Autumn"],
        loc="best",
        ncol=3,
    )
    fig.autofmt_xdate()
    fig
    return


@app.cell
def _(regression_info):
    season_month = {
        "winter": 1,
        "spring_autumn": 4,
        "summer": 7,
    }
    predictions_2026 = []
    for season, month in season_month.items():
        season_year = 2026 if month == 12 else 2025 if month in (1, 2) else 2026
        slope = regression_info[season]["slope"]
        intercept = regression_info[season]["intercept"]
        predictions_2026.append((season, slope * season_year + intercept))
    for season, value in predictions_2026:
        print(f"{season}: {value:.2f} gCO₂/kWh")
    return


@app.cell
def _(monthly_avg):
    monthly_avg
    return


@app.cell
def _(seasonal):
    seasonal
    return


if __name__ == "__main__":
    app.run()
