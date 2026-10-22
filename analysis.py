"""NHS Scotland A&E waiting times: data quality checks and performance analysis.

Run from the project folder:
    python analysis.py

Produces every file in results/ and charts/ from the source extract in data/.
"""

import sqlite3
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parent
SOURCE_FILE = PROJECT_DIR / "data" / "weekly_ae_activity_20261011.csv"
LOOKUP_FILE = PROJECT_DIR / "data" / "hospital_lookup.csv"
RESULTS_DIR = PROJECT_DIR / "results"
CHARTS_DIR = PROJECT_DIR / "charts"

GGC_BOARD = "S08000031"  # NHS Greater Glasgow and Clyde
TARGET_PCT = 95  # Scottish Government four-hour standard, used as a reference line

ATTENDANCES = "NumberOfAttendancesEpisode"
WITHIN_4H = "NumberWithin4HoursEpisode"
OVER_4H = "NumberOver4HoursEpisode"
OVER_8H = "NumberOver8HoursEpisode"
OVER_12H = "NumberOver12HoursEpisode"
COUNT_COLUMNS = [ATTENDANCES, WITHIN_4H, OVER_4H, OVER_8H, OVER_12H]

COLOURS = {"Scotland": "#1f5f8b", "NHS GGC": "#d1782b", "target": "#8a8a8a"}


# --------------------------------------------------------------------------- #
# Load
# --------------------------------------------------------------------------- #
def load_data() -> pd.DataFrame:
    df = pd.read_csv(SOURCE_FILE)
    df["WeekEnding"] = pd.to_datetime(df["WeekEndingDate"].astype(str), format="%Y%m%d")
    return df


def load_lookup() -> dict:
    lookup = pd.read_csv(LOOKUP_FILE)
    return dict(zip(lookup["HospitalCode"], lookup["HospitalName"]))


# --------------------------------------------------------------------------- #
# Data quality
# --------------------------------------------------------------------------- #
def run_quality_checks(df: pd.DataFrame) -> pd.DataFrame:
    key = ["WeekEndingDate", "TreatmentLocation", "AttendanceCategory"]
    checks = {
        "Missing cells": int(df.isna().sum().sum()),
        "Exact duplicate rows": int(df.duplicated().sum()),
        "Duplicate site-week-category keys": int(df.duplicated(key).sum()),
        "Within 4h > attendances": int((df[WITHIN_4H] > df[ATTENDANCES]).sum()),
        "Within 4h + over 4h != attendances": int(
            (df[WITHIN_4H] + df[OVER_4H] != df[ATTENDANCES]).sum()
        ),
        "Over 8h > over 4h": int((df[OVER_8H] > df[OVER_4H]).sum()),
        "Over 12h > over 8h": int((df[OVER_12H] > df[OVER_8H]).sum()),
        "Negative counts": int((df[COUNT_COLUMNS] < 0).sum().sum()),
    }
    result = pd.DataFrame(checks.items(), columns=["Check", "FlaggedRows"])

    duplicates = df[df.duplicated(key, keep=False)].sort_values(key)
    duplicates.drop(columns="WeekEnding").to_csv(RESULTS_DIR / "duplicate_keys.csv", index=False)
    return result


def build_data_dictionary(df: pd.DataFrame) -> pd.DataFrame:
    source = df.drop(columns="WeekEnding")
    return pd.DataFrame(
        {
            "Column": source.columns,
            "DataType": source.dtypes.astype(str).values,
            "MissingValues": source.isna().sum().values,
            "Example": source.iloc[0].values,
        }
    )


# --------------------------------------------------------------------------- #
# Aggregation helpers
# --------------------------------------------------------------------------- #
def all_attendances(df: pd.DataFrame) -> pd.DataFrame:
    """'All' already contains 'Unplanned' and 'New planned'; using only it avoids double counting."""
    return df[df["AttendanceCategory"] == "All"]


def add_rates(frame: pd.DataFrame) -> pd.DataFrame:
    """Rates are ratios of summed counts, never averages of percentages."""
    frame = frame.copy()
    frame["PctWithin4h"] = 100 * frame[WITHIN_4H] / frame[ATTENDANCES]
    frame["PctOver8h"] = 100 * frame[OVER_8H] / frame[ATTENDANCES]
    frame["PctOver12h"] = 100 * frame[OVER_12H] / frame[ATTENDANCES]
    return frame


def weekly_totals(df: pd.DataFrame) -> pd.DataFrame:
    scotland = df.groupby("WeekEnding")[COUNT_COLUMNS].sum().pipe(add_rates)
    ggc = df[df["HBT"] == GGC_BOARD].groupby("WeekEnding")[COUNT_COLUMNS].sum().pipe(add_rates)
    return scotland.join(ggc, lsuffix="_Scotland", rsuffix="_GGC")


def annual_summary(df: pd.DataFrame) -> pd.DataFrame:
    frame = df.assign(Year=df["WeekEnding"].dt.year)
    out = []
    for area, subset in [("Scotland", frame), ("NHS GGC", frame[frame["HBT"] == GGC_BOARD])]:
        yearly = subset.groupby("Year")[COUNT_COLUMNS].sum().pipe(add_rates)
        yearly["Weeks"] = subset.groupby("Year")["WeekEnding"].nunique()
        yearly.insert(0, "Area", area)
        out.append(yearly.reset_index())
    return pd.concat(out, ignore_index=True).round(2)


def hospital_performance(df: pd.DataFrame, names: dict, weeks: int = 1) -> pd.DataFrame:
    latest = df["WeekEnding"].max()
    start = latest - pd.Timedelta(weeks=weeks - 1)
    window = df[(df["HBT"] == GGC_BOARD) & (df["WeekEnding"] >= start)]
    sites = window.groupby("TreatmentLocation")[COUNT_COLUMNS].sum().pipe(add_rates)
    sites.insert(0, "HospitalName", sites.index.map(names).fillna("Unknown - check lookup"))
    return sites.sort_values("PctWithin4h").round(2)


# --------------------------------------------------------------------------- #
# Charts
# --------------------------------------------------------------------------- #
def style_axis(ax, title, ylabel):
    ax.set_title(title, loc="left", fontsize=13, fontweight="bold")
    ax.set_ylabel(ylabel)
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", alpha=0.3)


def chart_long_term(weekly: pd.DataFrame):
    rolling = weekly[["PctWithin4h_Scotland", "PctWithin4h_GGC"]].rolling(13).mean()
    fig, ax = plt.subplots(figsize=(11, 5))
    ax.plot(weekly.index, weekly["PctWithin4h_Scotland"], color=COLOURS["Scotland"], alpha=0.2, lw=0.8)
    ax.plot(weekly.index, weekly["PctWithin4h_GGC"], color=COLOURS["NHS GGC"], alpha=0.2, lw=0.8)
    ax.plot(rolling.index, rolling["PctWithin4h_Scotland"], color=COLOURS["Scotland"], lw=2.2, label="Scotland (13-week average)")
    ax.plot(rolling.index, rolling["PctWithin4h_GGC"], color=COLOURS["NHS GGC"], lw=2.2, label="NHS GGC (13-week average)")
    ax.axhline(TARGET_PCT, color=COLOURS["target"], ls="--", lw=1)
    ax.text(weekly.index[0], TARGET_PCT + 1, "95% standard", color=COLOURS["target"], fontsize=9)
    ax.set_ylim(40, 100)
    style_axis(ax, "A&E patients seen within four hours, 2015–2026", "% within four hours")
    ax.legend(frameon=False, loc="lower left")
    fig.tight_layout()
    fig.savefig(CHARTS_DIR / "long_term_trend.png", dpi=150)
    plt.close(fig)


def chart_latest_year(weekly: pd.DataFrame):
    recent = weekly.tail(52)
    fig, ax = plt.subplots(figsize=(11, 5))
    ax.plot(recent.index, recent["PctWithin4h_Scotland"], color=COLOURS["Scotland"], lw=2, label="Scotland")
    ax.plot(recent.index, recent["PctWithin4h_GGC"], color=COLOURS["NHS GGC"], lw=2, label="NHS GGC")
    ax.axhline(TARGET_PCT, color=COLOURS["target"], ls="--", lw=1, label="95% standard")
    ax.set_ylim(40, 100)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    style_axis(ax, "A&E patients seen within four hours, latest 52 weeks", "% within four hours")
    ax.legend(frameon=False, loc="lower left")
    fig.tight_layout()
    fig.savefig(CHARTS_DIR / "latest_52_weeks.png", dpi=150)
    plt.close(fig)


def chart_long_waits(annual: pd.DataFrame):
    scotland = annual[annual["Area"] == "Scotland"]
    fig, ax = plt.subplots(figsize=(11, 5))
    ax.bar(scotland["Year"] - 0.2, scotland["PctOver8h"], width=0.4, color="#e0a96d", label="Waited over 8 hours")
    ax.bar(scotland["Year"] + 0.2, scotland["PctOver12h"], width=0.4, color="#a33b20", label="Waited over 12 hours")
    ax.set_xticks(scotland["Year"])
    style_axis(ax, "Long A&E waits in Scotland by year", "% of attendances")
    ax.legend(frameon=False, loc="upper left")
    fig.tight_layout()
    fig.savefig(CHARTS_DIR / "long_waits.png", dpi=150)
    plt.close(fig)


def chart_hospitals(sites: pd.DataFrame, week_label: str):
    ordered = sites.sort_values("PctWithin4h")
    fig, ax = plt.subplots(figsize=(10, 4.5))
    bars = ax.barh(ordered["HospitalName"], ordered["PctWithin4h"], color=COLOURS["Scotland"])
    ax.bar_label(bars, labels=[f"{v:.1f}%" for v in ordered["PctWithin4h"]], padding=4, fontsize=9)
    ax.axvline(TARGET_PCT, color=COLOURS["target"], ls="--", lw=1)
    ax.set_xlim(0, 105)
    ax.set_xlabel("% within four hours")
    ax.set_title(f"NHS GGC hospitals, week ending {week_label}", loc="left", fontsize=13, fontweight="bold")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(CHARTS_DIR / "ggc_hospitals_latest_week.png", dpi=150)
    plt.close(fig)


# --------------------------------------------------------------------------- #
# Database
# --------------------------------------------------------------------------- #
def build_database(df: pd.DataFrame):
    """Builds results/nhs_ae.db so analysis.sql can be run in any SQLite client."""
    with sqlite3.connect(RESULTS_DIR / "nhs_ae.db") as conn:
        df.drop(columns="WeekEnding").to_sql("ae_waiting_times", conn, if_exists="replace", index=False)
        pd.read_csv(LOOKUP_FILE).to_sql("hospital_lookup", conn, if_exists="replace", index=False)


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main():
    RESULTS_DIR.mkdir(exist_ok=True)
    CHARTS_DIR.mkdir(exist_ok=True)

    df = load_data()
    names = load_lookup()

    quality = run_quality_checks(df)
    quality.to_csv(RESULTS_DIR / "quality_checks.csv", index=False)
    build_data_dictionary(df).to_csv(RESULTS_DIR / "data_dictionary.csv", index=False)

    data = all_attendances(df)
    weekly = weekly_totals(data)
    annual = annual_summary(data)
    sites_week = hospital_performance(data, names, weeks=1)
    sites_quarter = hospital_performance(data, names, weeks=13)

    weekly.round(2).to_csv(RESULTS_DIR / "weekly_scotland_vs_ggc.csv")
    annual.to_csv(RESULTS_DIR / "annual_summary.csv", index=False)
    sites_week.to_csv(RESULTS_DIR / "ggc_hospitals_latest_week.csv")
    sites_quarter.to_csv(RESULTS_DIR / "ggc_hospitals_last_13_weeks.csv")

    week_label = data["WeekEnding"].max().strftime("%-d %B %Y")
    chart_long_term(weekly)
    chart_latest_year(weekly)
    chart_long_waits(annual)
    chart_hospitals(sites_week, week_label)
    build_database(df)

    latest = weekly.iloc[-1]
    print(f"Rows loaded: {len(df):,} | weeks: {df['WeekEnding'].nunique()} | latest week: {week_label}")
    print(f"Scotland: {latest['PctWithin4h_Scotland']:.1f}% within 4h of {latest[ATTENDANCES + '_Scotland']:,.0f}")
    print(f"NHS GGC:  {latest['PctWithin4h_GGC']:.1f}% within 4h of {latest[ATTENDANCES + '_GGC']:,.0f}")
    print("\nQuality checks:\n" + quality.to_string(index=False))
    print("\nAnnual summary (% within 4h):")
    print(annual.pivot(index="Year", columns="Area", values="PctWithin4h").to_string())
    print("\nGGC hospitals, last 13 weeks:")
    print(sites_quarter[["HospitalName", ATTENDANCES, "PctWithin4h", "PctOver12h"]].to_string())
    print(f"\nOutputs written to {RESULTS_DIR.name}/ and {CHARTS_DIR.name}/")


if __name__ == "__main__":
    main()
