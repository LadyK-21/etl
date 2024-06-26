"""Process and harmonize EM-DAT natural disasters dataset."""

import datetime
from typing import Any, Dict, List, Tuple

import numpy as np
import owid.catalog.processing as pr
import pandas as pd
from owid.catalog import Dataset, Table, Variable, utils
from owid.datautils.dataframes import map_series

from etl.data_helpers import geo
from etl.helpers import PathFinder, create_dataset

# Get paths and naming conventions for current step.
paths = PathFinder(__file__)

# List of expected disaster types in the raw data to consider, and how to rename them.
# We consider only natural disasters of subgroups Geophysical, Meteorological, Hydrological and Climatological.
# We therefore ignore Extra-terrestrial (of which there is just one meteorite impact event) and Biological subgroups.
# For completeness, add all existing types here, and rename them as np.nan if they should not be used.
# If new types are included on a data update, simply add them here.
EARTHQUAKES_TYPE = "Earthquake"
EXTREME_TEMPERATURE_TYPE = "Extreme temperature"
EXPECTED_DISASTER_TYPES = {
    "Animal incident": np.nan,
    "Drought": "Drought",
    "Earthquake": EARTHQUAKES_TYPE,
    "Epidemic": np.nan,
    "Extreme temperature": EXTREME_TEMPERATURE_TYPE,
    "Flood": "Flood",
    "Fog": "Fog",
    "Glacial lake outburst flood": "Glacial lake outburst flood",
    "Impact": np.nan,
    "Infestation": np.nan,
    # "Landslide (dry)": "Landslide",
    "Mass movement (dry)": "Dry mass movement",
    "Mass movement (wet)": "Wet mass movement",
    "Storm": "Extreme weather",
    "Volcanic activity": "Volcanic activity",
    "Wildfire": "Wildfire",
}

# List of columns to select from raw data, and how to rename them.
COLUMNS = {
    "country": "country",
    "type": "type",
    "total_dead": "total_dead",
    "injured": "injured",
    "affected": "affected",
    "homeless": "homeless",
    "total_affected": "total_affected",
    "reconstruction_costs": "reconstruction_costs",
    "insured_damages": "insured_damages",
    "total_damages": "total_damages",
    "start_year": "start_year",
    "start_month": "start_month",
    "start_day": "start_day",
    "end_year": "end_year",
    "end_month": "end_month",
    "end_day": "end_day",
    # The following columns are kept for the analysis on the share of small, medium and large events.
    "cpi": "cpi",
    "entry_date": "entry_date",
}

# Columns of values related to natural disaster impacts.
IMPACT_COLUMNS = [
    "total_dead",
    "injured",
    "affected",
    "homeless",
    "total_affected",
    "reconstruction_costs",
    "insured_damages",
    "total_damages",
]

# Variables related to costs, measured in thousand current US$ (not adjusted for inflation or PPP).
COST_VARIABLES = ["reconstruction_costs", "insured_damages", "total_damages"]

# Variables to calculate per 100,000 people.
VARIABLES_PER_100K_PEOPLE = [column for column in IMPACT_COLUMNS if column not in COST_VARIABLES] + ["n_events"]

# New natural disaster types corresponding to the sum of all disasters, and the sum of all disasters excluding certain types.
ALL_DISASTERS_TYPE = "all_disasters"
ALL_DISASTERS_EXCLUDING_EARTHQUAKES_TYPE = "all_disasters_excluding_earthquakes"
ALL_DISASTERS_EXCLUDING_EXTREME_TEMPERATURE_TYPE = "all_disasters_excluding_extreme_temperature"

# Aggregate regions to add, following OWID definitions.
REGIONS = {
    # Default continents.
    "Africa": {},
    "Asia": {},
    "Europe": {},
    "European Union (27)": {},
    "North America": {},
    "Oceania": {},
    "South America": {},
    "World": {},
    # Income groups.
    "Low-income countries": {},
    "Upper-middle-income countries": {},
    "Lower-middle-income countries": {},
    "High-income countries": {},
}

# Overlaps found between historical regions and successor countries, that we accept in the data.
# We accept them either because they happened close to the transition, or to avoid needing to introduce new
# countries for which we do not have data (like the Russian Empire).
ACCEPTED_OVERLAPS = [{1911: {"USSR", "Kazakhstan"}}, {1991: {"Georgia", "USSR"}}, {1991: {"West Germany", "Germany"}}]

# List issues found in the data:
# Each element is a tuple with a dictionary that fully identifies the wrong row,
# and another dictionary that specifies the changes.
# Note: Countries here should appear as in the raw data (i.e. not harmonized).
DATA_CORRECTIONS = []


def correct_data_points(tb: Table, corrections: List[Tuple[Dict[Any, Any], Dict[Any, Any]]]) -> Table:
    """Make individual corrections to data points in a table.

    Parameters
    ----------
    tb : Table
        Data to be corrected.
    corrections : List[Tuple[Dict[Any, Any], Dict[Any, Any]]]
        Corrections.

    Returns
    -------
    tb_corrected : Table
        Corrected data.

    """
    tb_corrected = tb.copy()

    for correction in corrections:
        wrong_row, corrected_row = correction

        # Select the row in the table where the wrong data point is.
        # The 'fillna(False)' is added because otherwise rows that do not fulfil the selection will create ambiguity.
        selection = tb_corrected.loc[(tb_corrected[list(wrong_row)] == Variable(wrong_row)).fillna(False).all(axis=1)]
        # Sanity check.
        error = "Either raw data has been corrected, or dictionary selecting wrong row is ambiguous."
        assert len(selection) == 1, error

        # Replace wrong fields by the corrected ones.
        # Note: Changes to categorical fields will not work.
        tb_corrected.loc[selection.index, list(corrected_row)] = list(corrected_row.values())

    return tb_corrected


def get_last_day_of_month(year: int, month: int):
    """Get the number of days in a specific month of a specific year.

    Parameters
    ----------
    year : int
        Year.
    month : int
        Month.

    Returns
    -------
    last_day
        Number of days in month.

    """
    if month == 12:
        last_day = 31
    else:
        last_day = (datetime.datetime.strptime(f"{year:04}-{month + 1:02}", "%Y-%m") + datetime.timedelta(days=-1)).day

    return last_day


def prepare_input_data(tb: Table) -> Table:
    """Prepare input data, and fix some known issues."""
    # Select and rename columns.
    tb = tb[list(COLUMNS)].rename(columns=COLUMNS, errors="raise")

    # Add a year column (assume the start of the event).
    tb["year"] = tb["start_year"].copy()

    # Correct wrong data points (defined above in DATA_CORRECTIONS).
    tb = correct_data_points(tb=tb, corrections=DATA_CORRECTIONS)

    # Remove spurious spaces in entities.
    tb["type"] = tb["type"].str.strip()

    # Sanity check
    error = "List of expected disaster types has changed. Consider updating EXPECTED_DISASTER_TYPES."
    assert set(tb["type"]) == set(EXPECTED_DISASTER_TYPES), error

    # Rename disaster types conveniently.
    tb["type"] = map_series(
        series=tb["type"], mapping=EXPECTED_DISASTER_TYPES, warn_on_missing_mappings=True, warn_on_unused_mappings=True
    )

    # Drop rows for disaster types that are not relevant.
    tb = tb.dropna(subset="type").reset_index(drop=True)

    # Ensure "CPI" column is not empty. Currently it is missing the last year and a half
    # (and so is CPI data from World Bank). We forward fill the last rows of data.
    tb_cpi = (
        tb[["year", "cpi"]]
        .sort_values("year")
        .drop_duplicates(subset="year", keep="last")
        .reset_index(drop=True)
        .ffill()
    )
    tb = tb.drop(columns=["cpi"]).merge(tb_cpi, on="year", how="left")

    # Make "entry_date" a datetime column.
    tb["entry_date"] = pd.to_datetime(tb["entry_date"], errors="coerce")

    # Convert costs (given in '000 US$, aka thousand current US$) into current US$.
    for variable in COST_VARIABLES:
        tb[variable] *= 1000

    return tb


def sanity_checks_on_inputs(tb: Table) -> None:
    """Run sanity checks on input data."""
    error = "All values should be positive."
    assert (tb.select_dtypes("number").fillna(0) >= 0).all().all(), error

    error = "Column 'total_affected' should be the sum of columns 'injured', 'affected', and 'homeless'."
    assert (
        tb["total_affected"].fillna(0) == tb[["injured", "affected", "homeless"]].sum(axis=1).fillna(0)
    ).all(), error

    error = "Natural disasters are not expected to last more than 9 years."
    assert (tb["end_year"] - tb["start_year"]).max() < 10, error

    error = "Some of the columns that can't have nan do have one or more nans."
    assert tb[["country", "year", "type", "start_year", "end_year"]].notnull().all().all(), error

    for column in ["year", "start_year", "end_year"]:
        error = f"Column '{column}' has a year prior to 1900 or posterior to current year."
        assert 1900 < tb[column].max() <= datetime.datetime.now().year, error

    error = "Some rows have end_day specified, but not end_month."
    assert tb[(tb["end_month"].isnull()) & (tb["end_day"].notnull())].empty, error

    error = "CPI should be monotonically increasing (at most 11% percentage decreasing, 1% since 1940)."
    _tb = (
        tb[["year", "cpi"]]
        .sort_values("year")
        .drop_duplicates(subset="year", keep="last")
        .reset_index(drop=True)
        .fillna(0)
    )
    _tb["pct_change"] = _tb["cpi"].pct_change().fillna(0) * 100
    assert (_tb["pct_change"] > -11).all(), error
    assert (_tb[_tb["year"] > 1940]["pct_change"] > -1).all(), error


def fix_faulty_dtypes(tb: Table) -> Table:
    """Fix an issue related to column dtypes.

    Dividing a UInt32 by float64 results in a faulty Float64 that does not handle nans properly (which may be a bug:
    https://github.com/pandas-dev/pandas/issues/49818).
    To avoid this, there are various options:
    1. Convert all UInt32 into standard int before dividing by a float. But, if there are nans, int dtype is not valid.
    2. Convert all floats into Float64 before dividing.
    3. Convert all Float64 into float, after dividing.

    We adopt option 3.

    """
    tb = tb.astype({column: float for column in tb[tb.columns[tb.dtypes == "Float64"]]})

    return tb


def calculate_start_and_end_dates(tb: Table) -> Table:
    """Calculate start and end dates of disasters.

    The original data had year, month and day of start and end, and some of those fields were missing. This function
    deals with those missing fields and creates datetime columns for start and end of events.

    """
    tb = tb.copy()

    # When start month is not given, assume the beginning of the year.
    tb["start_month"] = tb["start_month"].fillna(1)
    # When start day is not given, assume the beginning of the month.
    tb["start_day"] = tb["start_day"].fillna(1)

    # When end month is not given, assume the end of the year.
    tb["end_month"] = tb["end_month"].fillna(12)

    # When end day is not given, assume the last day of the month.
    last_day_of_month = pd.Series(
        [get_last_day_of_month(year=row["end_year"], month=row["end_month"]) for _, row in tb.iterrows()]
    )
    tb["end_day"] = tb["end_day"].fillna(last_day_of_month)

    # Create columns for start and end dates.
    tb["start_date"] = (
        tb["start_year"].astype(str)
        + "-"
        + tb["start_month"].astype(str).str.zfill(2)
        + "-"
        + tb["start_day"].astype(str).str.zfill(2)
    )
    tb["end_date"] = (
        tb["end_year"].astype(str)
        + "-"
        + tb["end_month"].astype(str).str.zfill(2)
        + "-"
        + tb["end_day"].astype(str).str.zfill(2)
    )

    # Convert dates into datetime objects.
    # Note: This may fail if one of the dates is wrong, e.g. September 31 (if so, check error message for row index).
    tb["start_date"] = pd.to_datetime(tb["start_date"])
    tb["end_date"] = pd.to_datetime(tb["end_date"])

    error = "Events can't have an end_date prior to start_date."
    assert (tb["end_date"] >= tb["start_date"]).all(), error

    return tb


def calculate_yearly_impacts(tb: Table) -> Table:
    """Equally distribute the impact of disasters lasting longer than one year among the individual years, as separate
    events.

    Many disasters last more than one year. Therefore, we need to spread their impact among the different years.
    Otherwise, if we assign the impact of a disaster to, say, the first year, we may overestimate the impacts on a
    particular country-year.
    Hence, for events that started and ended in different years, we distribute their impact equally across the
    time spanned by the disaster.

    """
    tb = tb.copy()

    # There are many rows that have no data on impacts of disasters.
    # I suppose those are known disasters for which we don't know the impact.
    # Given that we want to count overall impact, fill them with zeros (to count them as disasters that had no victims).
    tb[IMPACT_COLUMNS] = tb[IMPACT_COLUMNS].fillna(0)

    # Select rows of disasters that last more than one year.
    multi_year_rows_mask = tb["start_date"].dt.year != tb["end_date"].dt.year
    multi_year_rows = tb[multi_year_rows_mask].reset_index(drop=True)

    # Go row by row, and create a new disaster event with the impact normalized by the fraction of days it happened
    # in a specific year.
    added_events = Table().copy_metadata(tb)
    for _, row in multi_year_rows.iterrows():
        # Start table for new event.
        new_event = Table(row).transpose().reset_index(drop=True).copy_metadata(tb)
        # Years spanned by the disaster.
        years = np.arange(row["start_date"].year, row["end_date"].year + 1).tolist()
        # Calculate the total number of days spanned by the disaster (and add 1 day to include the day of the end date).
        days_total = (row["end_date"] + pd.DateOffset(1) - row["start_date"]).days

        for year in years:
            if year == years[0]:
                # Get number of days.
                days_affected_in_year = (pd.Timestamp(year=year + 1, month=1, day=1) - row["start_date"]).days
                # Fraction of days affected this year.
                days_fraction = days_affected_in_year / days_total
                # Impacts this years.
                impacts = pd.DataFrame(row[IMPACT_COLUMNS] * days_fraction).transpose().astype(int)
                # Ensure "total_affected" is the sum of "injured", "affected" and "homeless".
                # Note that the previous line may have introduced rounding errors.
                impacts["total_affected"] = impacts["injured"] + impacts["affected"] + impacts["homeless"]
                # Start a series that counts the impacts accumulated over the years.
                cumulative_impacts = impacts
                # Normalize data by the number of days affected in this year.
                new_event.loc[:, IMPACT_COLUMNS] = impacts.values
                # Correct year and dates.
                new_event["year"] = year
                new_event["end_date"] = pd.Timestamp(year=year, month=12, day=31)
            elif years[0] < year < years[-1]:
                # The entire year was affected by the disaster.
                # Note: Ignore leap years.
                days_fraction = 365 / days_total
                # Impacts this year.
                impacts = pd.DataFrame(row[IMPACT_COLUMNS] * days_fraction).transpose().astype(int)
                # Ensure "total_affected" is the sum of "injured", "affected" and "homeless".
                # Note that the previous line may have introduced rounding errors.
                impacts["total_affected"] = impacts["injured"] + impacts["affected"] + impacts["homeless"]
                # Add impacts to the cumulative impacts series.
                cumulative_impacts += impacts  # type: ignore
                # Normalize data by the number of days affected in this year.
                new_event.loc[:, IMPACT_COLUMNS] = impacts.values
                # Correct year and dates.
                new_event["year"] = year
                new_event["start_date"] = pd.Timestamp(year=year, month=1, day=1)
                new_event["end_date"] = pd.Timestamp(year=year, month=12, day=31)
            else:
                # Assign all remaining impacts to the last year.
                impacts = (pd.Series(row[IMPACT_COLUMNS]) - cumulative_impacts).astype(int)  # type: ignore
                new_event.loc[:, IMPACT_COLUMNS] = impacts.values
                # Correct year and dates.
                new_event["year"] = year
                new_event["start_date"] = pd.Timestamp(year=year, month=1, day=1)
                new_event["end_date"] = row["end_date"]
            added_events = pr.concat([added_events, new_event], ignore_index=True).copy()

    # Remove multi-year rows from main dataframe, and add those rows after separating events year by year.
    tb_yearly = pr.concat([tb[~(multi_year_rows_mask)], added_events], ignore_index=True)  # type: ignore

    # Sort conveniently.
    tb_yearly = tb_yearly.sort_values(["country", "year", "type"]).reset_index(drop=True)

    return tb_yearly


def create_tables_of_event_sizes(tb: Table, ds_regions: Dataset, ds_income_groups: Dataset) -> Tuple[Table, Table]:
    # We can try to replicate the chart from Guha-Sapir et al. (2004).
    # According to them:
    # * The human impact of a natural disaster is considered by CRED as "small" when the number of deaths was lower than
    #   or equal to 5, the number of people affected was lower than or equal to 1,500, or the amount of reported
    #   economic damages was lower than or equal to US$8 million, adjusted to 2003 dollars.
    # * The human impact of a natural disaster was considered "large" when the number of deaths was greater than or
    #   equal to 50, the number of people affected was greater than or equal to 150,000, or the amount of reported
    #   economic damages was greater than or equal to US$200 million, adjusted to 2003 dollars.
    # I suppose that "medium" would be any disaster that falls in between these two categories.
    # Their economic cost thresholds, in 2003 dollars, should be converted to the inflation-adjusted equivalent.
    # Given that they include CPI in their original data, we use that to adjust for inflation.
    # Their latest CPI value is for 2022. We can use that as a reference.
    # Note that they include a column "Entry Date" in their original data. We could use it to try to replicate the
    # original chart.
    tb_yearly = tb[["country", "year", "total_dead", "total_affected", "total_damages", "entry_date", "cpi"]].copy()
    # To try to replicate the original chart in the paper, we could select the data that was in the database at the time
    # of publication. However, I can't fully replicate their results.
    # tb_yearly = tb_yearly[tb_yearly["entry_date"] <= "2004-01-01"].reset_index(drop=True)

    # For this study, the three relevant impact columns are "total_dead", "total_affected", and "total_damages".
    # Only about 23% of the events have all of those impact columns informed.
    # 100 * len(tb[(tb["total_dead"].notnull()) & (tb["total_affected"].notnull()) & (tb["total_damages"].notnull())]) / len(tb)
    # This means that we can't fill with zeros. Even events with 3 million deaths may have "total_damages" empty.
    # tb[(tb["total_damages"].isnull())]["total_dead"].max()
    # So empty rows do not mean "insignificant": They simply mean "not informed" (and can be small or large).
    # Therefore, we can't fill with zeros.

    # On top of that, there is about a 6% of events that have no information about impact metrics.
    # 100 * len(tb[(tb["total_dead"].isnull()) & (tb["total_affected"].isnull()) & (tb["total_damages"].isnull())]) / len(tb)
    # This happens, e.g. in Spain 1991, where there is a "Wildfire" event without any impact metric.
    # We can assign a special label to those events, e.g. "unknown".
    event_sizes = ["unknown", "small", "medium", "large"]

    # Add column for the threshold of small and large economic damages, adjusted for inflation.
    cpi_2003 = tb_yearly[tb_yearly["year"] == 2003]["cpi"].unique()
    assert len(cpi_2003) == 1
    cpi_2003 = cpi_2003[0]
    tb_yearly["small_economic_threshold"] = 8e6 * tb_yearly["cpi"] / cpi_2003
    tb_yearly["large_economic_threshold"] = 200e6 * tb_yearly["cpi"] / cpi_2003
    # Create a column for each kind of event depending on its size.
    for event_size in event_sizes:
        new_column = f"is_{event_size}_event"
        tb_yearly[new_column] = False
        tb_yearly[new_column] = tb_yearly[new_column].copy_metadata(tb_yearly["total_dead"])
    # Create a column that identifies unknown (uninformed) events.
    tb_yearly["is_unknown_event"] = (
        (tb_yearly["total_dead"].isnull())
        & (tb_yearly["total_affected"].isnull())
        & (tb_yearly["total_damages"].isnull())
    )
    # Create a column that identifies large events.
    # These are any informed event for which either there were many deaths, or many affected, or many damages (with the
    # thresholds defined above).
    tb_yearly["is_large_event"] = (~tb_yearly["is_unknown_event"]) & (
        (tb_yearly["total_dead"].fillna(0) >= 50)
        | (tb_yearly["total_affected"].fillna(0) >= 150000)
        | (tb_yearly["total_damages"].fillna(0) >= tb_yearly["large_economic_threshold"])
    )
    # Create a column that identifies small events.
    # These are informed events for which none of the impact metrics is above certain thresholds (defined above).
    tb_yearly["is_small_event"] = (
        (~tb_yearly["is_unknown_event"])
        & (tb_yearly["total_dead"].fillna(0) <= 5)
        & (tb_yearly["total_affected"].fillna(0) <= 1500)
        & (tb_yearly["total_damages"].fillna(0) <= tb_yearly["small_economic_threshold"])
    )
    # Create a column that identifies medium events.
    # These are events that do not fall in any of the other categories.
    tb_yearly["is_medium_event"] = ~(
        tb_yearly["is_unknown_event"] | tb_yearly["is_small_event"] | tb_yearly["is_large_event"]
    )
    # Check that each event is classified in at least one event type.
    assert (
        tb_yearly["is_unknown_event"]
        | tb_yearly["is_small_event"]
        | tb_yearly["is_medium_event"]
        | tb_yearly["is_large_event"]
    ).all()
    # Check that each event is classified in only one event type.
    assert set(tb_yearly[["is_unknown_event", "is_small_event", "is_medium_event", "is_large_event"]].sum(axis=1)) == {
        1
    }

    # Group by country and year to get the total number of small, medium and large events for each country and year.
    tb_yearly = tb_yearly.groupby(["country", "year"], as_index=False, observed=True).agg(
        {f"is_{event_size}_event": "sum" for event_size in event_sizes}
    )
    tb_yearly = tb_yearly.rename(
        columns={f"is_{event_size}_event": f"n_{event_size}_events" for event_size in event_sizes}, errors="raise"
    )
    # Add a column for the total number of events each country-year.
    tb_yearly["n_events"] = tb_yearly[[f"n_{event_size}_events" for event_size in event_sizes]].sum(axis=1)
    # Add a column with the global total.
    _tb_global = (
        tb_yearly.drop(columns="country")
        .groupby("year", as_index=False, observed=True)
        .sum()
        .assign(**{"country": "World"})
    )
    tb_yearly = pr.concat([tb_yearly, _tb_global], ignore_index=True)

    # Add region aggregates.
    tb_yearly = geo.add_regions_to_table(
        tb=tb_yearly,
        regions=REGIONS,
        index_columns=["country", "year"],
        ds_regions=ds_regions,
        ds_income_groups=ds_income_groups,
        accepted_overlaps=ACCEPTED_OVERLAPS,
    )

    # Create a table with the total decadal count of events.
    tb_decadal = tb_yearly.copy()
    tb_decadal["decade"] = (tb_decadal["year"] // 10) * 10
    tb_decadal = (
        tb_decadal.groupby(["country", "decade"], as_index=False, observed=True)
        .sum()
        .drop(columns="year")
        .rename(columns={"decade": "year"}, errors="raise")
    )

    # On both yearly and decadal tables, create columns for the share of each event type.
    for event_size in event_sizes:
        tb_yearly[f"share_{event_size}_events"] = 100 * tb_yearly[f"n_{event_size}_events"] / tb_yearly["n_events"]
        tb_decadal[f"share_{event_size}_events"] = 100 * tb_decadal[f"n_{event_size}_events"] / tb_decadal["n_events"]

    # Sanity checks.
    error = "The sum of the shares of events should be 100% (or within 1%)."
    assert (
        abs(tb_yearly[[column for column in tb_yearly.columns if "share" in column]].sum(axis=1) - 100) < 1
    ).all(), error
    assert (
        abs(tb_decadal[[column for column in tb_decadal.columns if "share" in column]].sum(axis=1) - 100) < 1
    ).all(), error

    # # Plot the share of large events as a bar chart.
    # import plotly.express as px
    # columns_sorted = ["year", "share_unknown_events", "share_large_events", "share_medium_events", "share_small_events"]
    # tb_plot = tb_decadal[tb_decadal["country"]=="World"][columns_sorted].melt(
    #     id_vars="year", var_name="event_size", value_name="share"
    # )
    # fig = px.bar(
    #     tb_plot,
    #     x="year",
    #     y="share",
    #     color="event_size",
    #     color_discrete_map={"share_unknown_events": "grey", "share_small_events": "yellow", "share_medium_events": "orange", "share_large_events": "red"},
    #     title="Share of unknown, small, medium, and large events",
    #     labels={"year": "Year", "share": "Share of events (%)", "event_size": "Event size"},
    # )
    # fig.show()

    # Format new tables conveniently.
    tb_yearly = tb_yearly.format(short_name="natural_disasters_yearly_impact")
    tb_decadal = tb_decadal.format(short_name="natural_disasters_decadal_impact")

    return tb_yearly, tb_decadal


def calculate_n_events_over_a_threshold_of_deaths(
    tb: Table, ds_regions: Dataset, ds_income_groups: Dataset
) -> Tuple[Table, Table]:
    # Calculate the number of events with more than a certain threshold of deaths.
    # With this, we can notice that "big events" (with over 5000 victims) have been roughly constant over the years.
    # However, "small events" (with less than 200 victims) have been increasing over the years.
    # This suggests that small events are underrepresented in early data, and the increase is due to better reporting.

    # For each threshold of deaths, create a table counting the number of events with more than that threshold
    # for each country-year.
    tb_counts = [
        tb[tb["total_dead"].fillna(0) > threshold]
        .groupby(["country", "year"], as_index=False, observed=True)["total_dead"]
        .count()
        .rename(columns={"total_dead": f"n_events_with_over_{threshold}_deaths"}, errors="raise")
        for threshold in [200, 500, 1000, 2000, 5000]
    ]
    # Add a table with the number of events for which total_dead is unknown.
    tb_unknown = (
        tb[tb["total_dead"].isnull()]
        .groupby(["country", "year"], as_index=False, observed=True)["total_dead"]
        .size()
        .rename(columns={"size": "n_events_with_unknown_deaths"}, errors="raise")
    )
    tb_counts.append(tb_unknown)
    # Merge all tables into one.
    tb_yearly = pr.multi_merge(tb_counts, on=["country", "year"], how="outer")

    # Fill missing values with zeros.
    for column in tb_yearly.drop(columns=["country", "year"]).columns:
        tb_yearly[column] = tb_yearly[column].fillna(0)

    # Add region aggregates.
    tb_yearly = geo.add_regions_to_table(
        tb=tb_yearly,
        regions=REGIONS,
        index_columns=["country", "year"],
        ds_regions=ds_regions,
        ds_income_groups=ds_income_groups,
        accepted_overlaps=[],
    )

    # Create a table with the decadal count of events.
    tb_decadal = tb_yearly.copy()
    tb_decadal["decade"] = (tb_decadal["year"] // 10) * 10
    tb_decadal = (
        tb_decadal.groupby(["country", "decade"], as_index=False, observed=True)
        .sum()
        .drop(columns="year")
        .rename(columns={"decade": "year"}, errors="raise")
    )

    # # Plot the curves of the number of global events causing more than a certain threshold of deaths.
    # import plotly.express as px
    # fig = px.line(
    #     tb_yearly[tb_yearly["country"]=="World"].drop(columns="country").melt(id_vars="year", var_name="threshold", value_name="n_events"),
    #     x="year",
    #     y="n_events",
    #     color="threshold",
    #     title="Number of events causing more than a certain threshold of deaths",
    #     labels={"year": "Year", "n_events": "Number of events", "threshold": "Threshold"},
    # )
    # fig.show()

    # Format tables conveniently.
    tb_yearly = tb_yearly.format(short_name="natural_disasters_yearly_deaths")
    tb_decadal = tb_decadal.format(short_name="natural_disasters_decadal_deaths")

    return tb_yearly, tb_decadal


def get_total_count_of_yearly_impacts(tb: Table) -> Table:
    """Get the total count of impacts in the year, ignoring the individual events.

    We are not interested in each individual event, but the number of events of each kind and their impacts.
    This function will produce the total count of impacts per country, year and type of disaster.

    """
    # Get the total count of impacts per country, year and type of disaster.
    counts = (
        tb.reset_index()
        .groupby(["country", "year", "type"], observed=True)
        .agg({"index": "count"})
        .reset_index()
        .rename(columns={"index": "n_events"})
    )
    # Copy metadata from any other column into the new column of counts of events.
    counts["n_events"] = counts["n_events"].copy_metadata(tb["total_dead"])
    # Ensure columns have the right type.
    tb = tb.astype(
        {column: int for column in tb.columns if column not in ["country", "year", "type", "start_date", "end_date"]}
    )
    # Get the sum of impacts per country, year and type of disaster.
    tb = tb.groupby(["country", "year", "type"], observed=True).sum(numeric_only=True, min_count=1).reset_index()
    # Add the column of the number of events.
    tb = tb.merge(counts, on=["country", "year", "type"], how="left")

    return tb


def create_a_new_type_for_all_disasters_combined(tb: Table) -> Table:
    """Add a new disaster type that has the impact of all other disasters combined.

    Among big disaster years, the majority of deaths are the result of earthquakes.
    Hence, we create an indicator of deaths from all disasters excluding earthquakes.

    EM-DAT may not be very complete or accurate when counting extreme heat deaths.
    It's almost exclusively Europe that is covered.
    Hence, we create an additional indicator excluding extreme heat, so comparisons across regions are more equal.

    """
    # Add indicators for all disasters combined.
    all_disasters = (
        tb.groupby(["country", "year"], observed=True, as_index=False)
        .sum(numeric_only=True, min_count=1)
        .assign(**{"type": ALL_DISASTERS_TYPE})
    )

    # Add indicators for all disasters combined excluding earthquakes.
    all_disasters_excluding_earthquakes = (
        tb[tb["type"] != EARTHQUAKES_TYPE]
        .groupby(["country", "year"], observed=True, as_index=False)
        .sum(numeric_only=True, min_count=1)
        .assign(**{"type": ALL_DISASTERS_EXCLUDING_EARTHQUAKES_TYPE})
    )

    # Add indicators for all disasters combined excluding extreme temperature.
    all_disasters_excluding_extreme_temperature = (
        tb[tb["type"] != EXTREME_TEMPERATURE_TYPE]
        .groupby(["country", "year"], observed=True, as_index=False)
        .sum(numeric_only=True, min_count=1)
        .assign(**{"type": ALL_DISASTERS_EXCLUDING_EXTREME_TEMPERATURE_TYPE})
    )

    # Concatenate original data with new indicators.
    tb = (
        pr.concat(
            [tb, all_disasters, all_disasters_excluding_earthquakes, all_disasters_excluding_extreme_temperature],
            ignore_index=True,
        )
        .sort_values(["country", "year", "type"])
        .reset_index(drop=True)
    )

    return tb


def create_additional_variables(tb: Table, ds_population: Dataset, tb_gdp: Table) -> Table:
    """Create additional variables, namely damages per GDP, and impacts per 100,000 people."""
    # Add population to table.
    tb = geo.add_population_to_table(tb=tb, ds_population=ds_population)

    # Combine natural disasters with GDP data.
    tb = tb.merge(tb_gdp.rename(columns={"ny_gdp_mktp_cd": "gdp"}), on=["country", "year"], how="left")
    # Prepare cost variables.
    for variable in COST_VARIABLES:
        # Create variables of costs (in current US$) as a share of GDP (in current US$).
        tb[f"{variable}_per_gdp"] = tb[variable] / tb["gdp"] * 100

    # Add rates per 100,000 people.
    for column in VARIABLES_PER_100K_PEOPLE:
        tb[f"{column}_per_100k_people"] = tb[column] * 1e5 / tb["population"]

    # Fix issue with faulty dtypes (see more details in the function's documentation).
    tb = fix_faulty_dtypes(tb=tb)

    return tb


def create_decadal_average_data(tb: Table) -> Table:
    """Create data of average impacts over periods of 10 years.

    For example (as explained in the footer of the natural disasters explorer), the value for 1900 of any column should
    represent the average of that column between 1900 and 1909.

    """
    tb_decadal = tb.copy()

    # Ensure each country has data for all years (and fill empty rows with zeros).
    # Otherwise, the average would be performed only across years for which we have data.
    # For example, if we have data only for 1931 (and no other year in the 1930s) we want that data point to be averaged
    # over all years in the decade (assuming they are all zero).
    # Note that, for the current decade, since it's not complete, we want to average over the number of current years
    # (not the entire decade).

    # List all countries, years and types in the data.
    countries = sorted(set(tb_decadal["country"]))
    years = np.arange(tb_decadal["year"].min(), tb_decadal["year"].max() + 1).tolist()
    types = sorted(set(tb_decadal["type"]))

    # Create a new index covering all combinations of countries, years and types.
    new_indexes = pd.MultiIndex.from_product([countries, years, types], names=["country", "year", "type"])

    # Reindex data so that all countries and types have data for each year (filling with zeros when there's no data).
    tb_decadal = tb_decadal.set_index(["country", "year", "type"]).reindex(new_indexes, fill_value=0).reset_index()

    # For each year, calculate the corresponding decade (e.g. 1951 -> 1950, 1929 -> 1920).
    tb_decadal["decade"] = (tb_decadal["year"] // 10) * 10

    # Group by that country-decade-type and get the mean for each column.
    tb_decadal = (
        tb_decadal.drop(columns=["year"])
        .groupby(["country", "decade", "type"], observed=True)
        .mean(numeric_only=True)
        .reset_index()
        .rename(columns={"decade": "year"})
    )

    return tb_decadal


def sanity_checks_on_outputs(tb: Table, is_decade: bool, ds_regions: Dataset) -> None:
    """Run sanity checks on output (yearly or decadal) data.

    Parameters
    ----------
    tb : Table
        Output (yearly or decadal) data.
    is_decade : bool
        True if tb is decadal data; False if it is yearly data.
    ds_regions : Dataset
        Regions dataset.

    """
    # Common sanity checks for yearly and decadal data.
    error = "All values should be positive."
    assert (tb.select_dtypes("number").fillna(0) >= 0).all().all(), error

    error = (
        "List of expected disaster types has changed. "
        "Consider updating EXPECTED_DISASTER_TYPES (or renaming ALL_DISASTERS_TYPE)."
    )
    expected_disaster_types = (
        [ALL_DISASTERS_TYPE]
        + [
            utils.underscore(EXPECTED_DISASTER_TYPES[disaster])
            for disaster in EXPECTED_DISASTER_TYPES
            if not pd.isna(EXPECTED_DISASTER_TYPES[disaster])
        ]
        + [ALL_DISASTERS_EXCLUDING_EARTHQUAKES_TYPE, ALL_DISASTERS_EXCLUDING_EXTREME_TEMPERATURE_TYPE]
    )
    assert set(tb["type"]) == set(expected_disaster_types), error

    columns_that_should_not_have_nans = [
        "country",
        "year",
        "type",
        "total_dead",
        "injured",
        "affected",
        "homeless",
        "total_affected",
        "reconstruction_costs",
        "insured_damages",
        "total_damages",
        "n_events",
    ]
    error = "There are unexpected nans in data."
    assert tb[columns_that_should_not_have_nans].notnull().all(axis=1).all(), error

    # Get names of historical regions in the data.
    regions = ds_regions["regions"].reset_index()
    historical_regions_in_data = set(regions[regions["is_historical"]]["name"]) & set(tb["country"])

    # Sanity checks only for yearly data.
    if not is_decade:
        all_countries = sorted(set(tb["country"]) - set(REGIONS) - historical_regions_in_data)

        # Check that the aggregate of all countries and disasters leads to the same numbers we have for the world.
        # This check would not pass when adding historical regions (since we know there are some overlaps between data
        # from historical and successor countries). So check for a specific year.
        year_to_check = 2022
        all_disasters_for_world = tb[
            (tb["country"] == "World") & (tb["year"] == year_to_check) & (tb["type"] == ALL_DISASTERS_TYPE)
        ].reset_index(drop=True)
        all_disasters_check = (
            tb[
                (tb["country"].isin(all_countries))
                & (tb["year"] == year_to_check)
                & (
                    ~tb["type"].isin(
                        [
                            ALL_DISASTERS_TYPE,
                            ALL_DISASTERS_EXCLUDING_EARTHQUAKES_TYPE,
                            ALL_DISASTERS_EXCLUDING_EXTREME_TEMPERATURE_TYPE,
                        ]
                    )
                )
            ]
            .groupby("year")
            .sum(numeric_only=True)
            .reset_index()
        )

        cols_to_check = [
            "total_dead",
            "injured",
            "affected",
            "homeless",
            "total_affected",
            "reconstruction_costs",
            "insured_damages",
            "total_damages",
        ]
        error = f"Aggregate for the World in {year_to_check} does not coincide with the sum of all countries."
        assert all_disasters_for_world[cols_to_check].equals(all_disasters_check[cols_to_check]), error

        error = "Column 'total_affected' should be the sum of columns 'injured', 'affected', and 'homeless'."
        assert (
            tb["total_affected"].fillna(0) >= tb[["injured", "affected", "homeless"]].sum(axis=1).fillna(0)
        ).all(), error

        # Another sanity check would be that certain disasters (e.g. an earthquake) cannot last for longer than 1 day.
        # However, for some disasters we don't have exact day, or even exact month, just the year.

        # List of columns whose value should not be larger than population.
        columns_to_inspect = [
            "total_dead",
            "total_dead_per_100k_people",
        ]
        error = "One disaster should not be able to cause the death of the entire population of a country in one year."
        for column in columns_to_inspect:
            informed_rows = tb[column].notnull() & tb["population"].notnull()
            assert (tb[informed_rows][column] <= tb[informed_rows]["population"]).all(), error


def run(dest_dir: str) -> None:
    #
    # Load inputs.
    #
    # Load natural disasters dataset from meadow and read its main table.
    ds_meadow = paths.load_dataset("natural_disasters")
    tb_meadow = ds_meadow["natural_disasters"].reset_index()

    # Load WDI dataset, read its main table and select variable corresponding to GDP (in current US$).
    ds_wdi = paths.load_dataset("wdi")
    tb_gdp = ds_wdi["wdi"][["ny_gdp_mktp_cd"]].reset_index()

    # Load regions dataset.
    ds_regions = paths.load_dataset("regions")

    # Load income groups dataset.
    ds_income_groups = paths.load_dataset("income_groups")

    # Load population dataset.
    ds_population = paths.load_dataset("population")

    #
    # Process data.
    #
    # Prepare input data (prepare time columns, convert cost variables to dollars, and fix some known issues).
    tb = prepare_input_data(tb=tb_meadow)

    # Sanity checks.
    sanity_checks_on_inputs(tb=tb)

    # Harmonize country names.
    tb = geo.harmonize_countries(
        df=tb, countries_file=paths.country_mapping_path, warn_on_missing_countries=True, warn_on_unused_countries=True
    )

    # Create a (yearly and decadal) table with the number and share of small, medium and large events.
    tb_yearly_sizes, tb_decadal_sizes = create_tables_of_event_sizes(
        tb=tb, ds_regions=ds_regions, ds_income_groups=ds_income_groups
    )

    # Calculate the number of events over a certain threshold of casualties.
    # This is useful to notice a possible underestimate of small events in early data.
    tb_yearly_deaths, tb_decadal_deaths = calculate_n_events_over_a_threshold_of_deaths(
        tb=tb, ds_regions=ds_regions, ds_income_groups=ds_income_groups
    )

    # Calculate start and end dates of disasters.
    tb = calculate_start_and_end_dates(tb=tb)

    # Drop unnecessary columns.
    tb = tb.drop(
        columns=["start_year", "start_month", "start_day", "end_year", "end_month", "end_day", "entry_date", "cpi"],
        errors="raise",
    )

    # Distribute the impacts of disasters lasting longer than a year among separate yearly events.
    tb = calculate_yearly_impacts(tb=tb)

    # Get total count of impacts per year (regardless of the specific individual events during the year).
    tb = get_total_count_of_yearly_impacts(tb=tb)

    # Add a new category (or "type") corresponding to the total of all natural disasters.
    tb = create_a_new_type_for_all_disasters_combined(tb=tb)

    # Add region aggregates.
    tb = geo.add_regions_to_table(
        tb=tb,
        regions=REGIONS,
        index_columns=["country", "year", "type"],
        ds_regions=ds_regions,
        ds_income_groups=ds_income_groups,
        accepted_overlaps=ACCEPTED_OVERLAPS,
    )

    # Add damages per GDP, and rates per 100,000 people.
    tb = create_additional_variables(tb=tb, ds_population=ds_population, tb_gdp=tb_gdp)

    # Change disaster types to snake, lower case.
    tb["type"] = tb["type"].replace({value: utils.underscore(value) for value in tb["type"].unique()})

    # Create data aggregated (using a simple mean) in intervals of 10 years.
    tb_decadal = create_decadal_average_data(tb=tb)

    # Run sanity checks on output yearly data.
    sanity_checks_on_outputs(tb=tb, is_decade=False, ds_regions=ds_regions)

    # Run sanity checks on output decadal data.
    sanity_checks_on_outputs(tb=tb_decadal, is_decade=True, ds_regions=ds_regions)

    # Set an appropriate index to yearly data and sort conveniently.
    tb = tb.format(keys=["country", "year", "type"], sort_columns=True, short_name="natural_disasters_yearly")

    # Set an appropriate index to decadal data and sort conveniently.
    tb_decadal = tb_decadal.format(
        keys=["country", "year", "type"], sort_columns=True, short_name="natural_disasters_decadal"
    )

    #
    # Save outputs.
    #
    # Create new garden dataset.
    ds_garden = create_dataset(
        dest_dir,
        tables=[tb, tb_decadal, tb_yearly_sizes, tb_decadal_sizes, tb_yearly_deaths, tb_decadal_deaths],
        default_metadata=ds_meadow.metadata,
        check_variables_metadata=True,
    )
    ds_garden.save()
