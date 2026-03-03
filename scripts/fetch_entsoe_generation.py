#!/usr/bin/env python3
"""Fetch Actual Generation per Production Type (A75) from the ENTSO-E Transparency Platform API.

Usage examples:
    uv run scripts/fetch_entsoe_generation.py --areas AT,CZ,SK --start 2024-01-01 --end 2024-01-07
    uv run scripts/fetch_entsoe_generation.py  # interactive mode
    ENTSOE_TOKEN=your-token uv run scripts/fetch_entsoe_generation.py --areas FR
"""

import argparse
import os
import sys
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta

import polars as pl

from entsoe_utils import (
    BASE_URL,
    EIC_CODES,
    PSR_TYPE_NAMES,
    fetch_api,
    format_period,
    get_token,
    resolution_to_minutes,
    yearly_batches,
)


def parse_areas(spec: str) -> list[str]:
    """Parse 'AT,CZ,SK' into ['AT', 'CZ', 'SK'], validating each code."""
    known = set(EIC_CODES.keys())
    areas = []
    for part in spec.upper().split(","):
        part = part.strip()
        if part in known:
            areas.append(part)
        else:
            print(f"Warning: unknown area code '{part}'. Known codes: {', '.join(sorted(known))}", file=sys.stderr)
    return areas


def select_areas_interactive() -> list[str]:
    print(f"\nAll known ENTSO-E bidding zones / control areas ({len(EIC_CODES)} total).")
    print("You can filter by typing part of the area code or description (e.g. 'NO', 'Italy').")
    print("Or press Enter to see all.\n")
    filter_str = input("Filter (optional): ").strip().upper()

    filtered = [
        (code, desc) for code, (_, desc) in EIC_CODES.items()
        if not filter_str or filter_str in code.upper() or filter_str in desc.upper()
    ]

    if not filtered:
        print(f"No areas match '{filter_str}'.", file=sys.stderr)
        sys.exit(1)

    print()
    for idx, (code, desc) in enumerate(filtered, 1):
        print(f"  {idx:3}. {code:<12}  {desc}")

    print()
    print("Enter numbers (e.g. 1,3,5) or area codes (e.g. AT,CZ), or both:")
    raw = input("Selection: ").strip()
    if not raw:
        print("No areas selected.", file=sys.stderr)
        sys.exit(1)

    result: list[str] = []
    for token in raw.split(","):
        token = token.strip()
        if token.isdigit():
            idx = int(token) - 1
            if 0 <= idx < len(filtered):
                result.append(filtered[idx][0])
            else:
                print(f"Warning: index {token} out of range, skipping.", file=sys.stderr)
        else:
            result.extend(parse_areas(token))
    return result


def parse_generation_xml(root: ET.Element, area: str) -> list[dict]:
    """Parse GL_MarketDocument XML into a list of row dicts (long/tidy format)."""
    ns_raw = root.tag.split("}")[0].lstrip("{") if "}" in root.tag else ""
    ns = f"{{{ns_raw}}}" if ns_raw else ""

    rows = []
    for ts in root.findall(f".//{ns}TimeSeries"):
        # Identify the fuel type for this TimeSeries
        psr_el = ts.find(f".//{ns}psrType")
        psr_type = psr_el.text.strip() if psr_el is not None else "UNKNOWN"
        psr_name = PSR_TYPE_NAMES.get(psr_type, psr_type)

        for period in ts.findall(f".//{ns}Period"):
            start_el = period.find(f"{ns}timeInterval/{ns}start")
            resolution_el = period.find(f"{ns}resolution")
            if start_el is None or resolution_el is None:
                continue

            start_str = start_el.text.strip()
            try:
                start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
            except ValueError:
                continue

            resolution = resolution_el.text.strip()
            interval_minutes = resolution_to_minutes(resolution)

            for point in period.findall(f"{ns}Point"):
                pos_el = point.find(f"{ns}position")
                qty_el = point.find(f"{ns}quantity")
                if pos_el is None or qty_el is None:
                    continue
                position = int(pos_el.text)
                quantity = float(qty_el.text)
                point_dt = start_dt + timedelta(minutes=(position - 1) * interval_minutes)
                rows.append(
                    {
                        "datetime_utc": point_dt.isoformat(),
                        "area": area,
                        "psr_type": psr_type,
                        "psr_type_name": psr_name,
                        "quantity_mw": quantity,
                        "resolution": resolution,
                    }
                )
    return rows


def save_csv(rows: list[dict], area: str, start: date, end: date) -> str:
    filename = f"generation_mix_{area}_{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}.csv"
    output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
    os.makedirs(output_dir, exist_ok=True)
    filepath = os.path.join(output_dir, filename)
    df = (
        pl.DataFrame(rows)
        # Sum across multiple TimeSeries with the same (datetime, area, psr_type)
        .group_by(["datetime_utc", "area", "psr_type_name", "resolution"])
        .agg(pl.col("quantity_mw").sum())
        .pivot(
            on="psr_type_name",
            index=["datetime_utc", "area", "resolution"],
            values="quantity_mw",
            aggregate_function="sum",
        )
        .sort("datetime_utc")
    )
    df.write_csv(filepath)
    return filepath


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch ENTSO-E Actual Generation per Production Type (A75) and save as CSV.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--token",
        help="ENTSO-E security token (overrides ENTSOE_TOKEN env var)",
    )
    parser.add_argument(
        "--areas",
        help="Comma-separated list of area codes, e.g. AT,CZ,SK",
    )
    parser.add_argument(
        "--start",
        help="Start date (YYYY-MM-DD, UTC). Defaults to 7 days ago.",
    )
    parser.add_argument(
        "--end",
        help="End date (YYYY-MM-DD, UTC). Defaults to today.",
    )
    args = parser.parse_args()

    token = get_token(args.token)

    if args.areas:
        areas = parse_areas(args.areas)
    else:
        areas = select_areas_interactive()

    if not areas:
        print("No valid areas specified.", file=sys.stderr)
        sys.exit(1)

    today = date.today()
    end_date = date.fromisoformat(args.end) if args.end else today
    start_date = date.fromisoformat(args.start) if args.start else end_date - timedelta(days=7)

    batches = yearly_batches(start_date, end_date)
    if len(batches) > 1:
        print(f"Note: date range spans {len(batches)} years; will make {len(batches)} API requests per area.")

    print(f"\nFetching generation mix from {start_date} to {end_date} (UTC)")
    print(f"Areas: {', '.join(areas)}\n")

    for area in areas:
        in_domain = EIC_CODES[area][0]

        all_rows: list[dict] = []
        failed = False
        for batch_start, batch_end in batches:
            label = f"{batch_start}–{batch_end}" if len(batches) > 1 else ""
            print(f"  Fetching {area}{' ' + label if label else ''}...", end=" ", flush=True)

            root = fetch_api(
                token,
                {
                    "documentType": "A75",
                    "processType": "A16",
                    "in_Domain": in_domain,
                    "periodStart": format_period(batch_start),
                    "periodEnd": format_period(batch_end + timedelta(days=1)),
                },
            )
            if root is None:
                print("FAILED")
                failed = True
                break

            rows = parse_generation_xml(root, area)
            if not rows:
                print("no data")
            else:
                print(f"{len(rows)} rows")
                all_rows.extend(rows)

        if failed or not all_rows:
            if not failed:
                print(f"  → no data returned for {area}")
            continue

        filepath = save_csv(all_rows, area, start_date, end_date)
        print(f"  → saved {len(all_rows)} total rows → {filepath}")

    print("\nDone.")


if __name__ == "__main__":
    main()
