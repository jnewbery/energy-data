#!/usr/bin/env python3
"""Fetch Cross-Border Physical Flows (A11) from the ENTSO-E Transparency Platform API.

Usage examples:
    uv run scripts/fetch_entsoe_flows.py --interconnections GB-FR,FR-BE --start 2024-01-01 --end 2024-01-07
    uv run scripts/fetch_entsoe_flows.py  # interactive mode
    ENTSOE_TOKEN=your-token uv run scripts/fetch_entsoe_flows.py --interconnections GB-FR
"""

import argparse
import os
import sys
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta

import polars as pl

from entsoe_utils import (
    ALL_INTERCONNECTIONS,
    BASE_URL,
    EIC_CODES,
    fetch_api,
    format_period,
    get_token,
    resolution_to_minutes,
    yearly_batches,
)


def parse_interconnections(spec: str) -> list[tuple[str, str]]:
    """Parse 'GB-FR,SE_3-DK_1' into [('GB','FR'), ('SE_3','DK_1')]."""
    pairs = []
    known = set(EIC_CODES.keys())
    for part in spec.upper().split(","):
        part = part.strip()
        # Try splitting at each hyphen to find a valid (out, in) pair
        matched = False
        for i in range(1, len(part)):
            if part[i] == "-":
                out_c = part[:i]
                in_c = part[i + 1:]
                if out_c in known and in_c in known:
                    pairs.append((out_c, in_c))
                    matched = True
                    break
        if not matched:
            print(f"Warning: could not parse '{part}'. Known area codes: {', '.join(sorted(known))}", file=sys.stderr)
    return pairs


def select_interconnections_interactive() -> list[tuple[str, str]]:
    print(f"\nAll known ENTSO-E cross-border interconnections ({len(ALL_INTERCONNECTIONS)} total).")
    print("You can filter by typing a country/area code prefix (e.g. 'GB', 'NO', 'IT').")
    print("Or press Enter to see all.\n")
    filter_str = input("Filter (optional): ").strip().upper()

    filtered = [
        (o, i) for o, i in ALL_INTERCONNECTIONS
        if not filter_str or filter_str in o or filter_str in i
    ]

    if not filtered:
        print(f"No interconnections match '{filter_str}'.", file=sys.stderr)
        sys.exit(1)

    print()
    for idx, (out_c, in_c) in enumerate(filtered, 1):
        out_desc = EIC_CODES[out_c][1] if out_c in EIC_CODES else out_c
        in_desc = EIC_CODES[in_c][1] if in_c in EIC_CODES else in_c
        print(f"  {idx:3}. {out_c:<12} → {in_c:<12}  ({out_desc} → {in_desc})")

    print()
    print("Enter numbers (e.g. 1,3,5) or free-form pairs (e.g. GB-FR,FR-DE), or both:")
    raw = input("Selection: ").strip()
    if not raw:
        print("No interconnections selected.", file=sys.stderr)
        sys.exit(1)

    result: list[tuple[str, str]] = []
    for token in raw.split(","):
        token = token.strip()
        if token.isdigit():
            idx = int(token) - 1
            if 0 <= idx < len(filtered):
                result.append(filtered[idx])
            else:
                print(f"Warning: index {token} out of range, skipping.", file=sys.stderr)
        else:
            result.extend(parse_interconnections(token))
    return result


def fetch_flows(
    token: str,
    out_domain: str,
    in_domain: str,
    period_start: str,
    period_end: str,
    retries: int = 3,
    timeout: int = 120,
) -> ET.Element | None:
    return fetch_api(
        token,
        {
            "documentType": "A11",
            "out_Domain": out_domain,
            "in_Domain": in_domain,
            "periodStart": period_start,
            "periodEnd": period_end,
        },
        retries=retries,
        timeout=timeout,
    )



def parse_flows_xml(
    root: ET.Element,
    out_country: str,
    in_country: str,
    out_domain: str,
    in_domain: str,
) -> list[dict]:
    ns_raw = root.tag.split("}")[0].lstrip("{") if "}" in root.tag else ""
    ns = f"{{{ns_raw}}}" if ns_raw else ""

    rows = []
    for ts in root.findall(f".//{ns}TimeSeries"):
        for period in ts.findall(f".//{ns}Period"):
            start_el = period.find(f"{ns}timeInterval/{ns}start")
            resolution_el = period.find(f"{ns}resolution")
            if start_el is None or resolution_el is None:
                continue

            start_str = start_el.text.strip()  # e.g. "2023-08-23T22:00Z"
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
                        "out_domain": out_domain,
                        "in_domain": in_domain,
                        "out_country": out_country,
                        "in_country": in_country,
                        "flow_mw": quantity,
                        "resolution": resolution,
                    }
                )
    return rows


def save_csv(rows: list[dict], out_country: str, in_country: str, start: date, end: date) -> str:
    filename = f"cross_border_flows_{out_country}_{in_country}_{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}.csv"
    output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
    os.makedirs(output_dir, exist_ok=True)
    filepath = os.path.join(output_dir, filename)
    df = pl.DataFrame(rows)
    df = df.sort("datetime_utc")
    df.write_csv(filepath)
    return filepath


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch ENTSO-E Cross-Border Physical Flows (A11) and save as CSV.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--token",
        help="ENTSO-E security token (overrides ENTSOE_TOKEN env var)",
    )
    parser.add_argument(
        "--interconnections",
        help="Comma-separated list of interconnections, e.g. GB-FR,FR-DE",
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

    # Resolve interconnections
    if args.interconnections:
        interconnections = parse_interconnections(args.interconnections)
    else:
        interconnections = select_interconnections_interactive()

    if not interconnections:
        print("No valid interconnections specified.", file=sys.stderr)
        sys.exit(1)

    # Resolve date range
    today = date.today()
    if args.end:
        end_date = date.fromisoformat(args.end)
    else:
        end_date = today

    if args.start:
        start_date = date.fromisoformat(args.start)
    else:
        start_date = end_date - timedelta(days=7)

    batches = yearly_batches(start_date, end_date)
    if len(batches) > 1:
        print(f"Note: date range spans {len(batches)} years; will make {len(batches)} API requests per interconnection.")

    print(f"\nFetching flows from {start_date} to {end_date} (UTC)")
    print(f"Interconnections: {', '.join(f'{o}-{i}' for o, i in interconnections)}\n")

    for out_country, in_country in interconnections:
        out_domain = EIC_CODES[out_country][0]
        in_domain = EIC_CODES[in_country][0]

        all_rows: list[dict] = []
        failed = False
        for batch_start, batch_end in batches:
            label = f"{batch_start}–{batch_end}" if len(batches) > 1 else ""
            print(f"  Fetching {out_country} → {in_country}{' ' + label if label else ''}...", end=" ", flush=True)

            root = fetch_flows(
                token, out_domain, in_domain,
                format_period(batch_start),
                format_period(batch_end + timedelta(days=1)),
            )
            if root is None:
                print("FAILED")
                failed = True
                break

            rows = parse_flows_xml(root, out_country, in_country, out_domain, in_domain)
            if not rows:
                print("no data")
            else:
                print(f"{len(rows)} rows")
                all_rows.extend(rows)

        if failed or not all_rows:
            if not failed:
                print(f"  → no data returned for {out_country}-{in_country}")
            continue

        filepath = save_csv(all_rows, out_country, in_country, start_date, end_date)
        print(f"  → saved {len(all_rows)} total rows → {filepath}")

    print("\nDone.")


if __name__ == "__main__":
    main()
