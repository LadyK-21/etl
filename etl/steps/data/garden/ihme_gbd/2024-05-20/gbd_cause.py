"""Load a meadow dataset and create a garden dataset."""

from owid.catalog import Table
from owid.catalog import processing as pr
from shared import add_regional_aggregates

from etl.data_helpers import geo
from etl.helpers import PathFinder, create_dataset

# Get paths and naming conventions for current step.
paths = PathFinder(__file__)
REGIONS = ["North America", "South America", "Europe", "Africa", "Asia", "Oceania"]
AGE_GROUPS_RANGES = {
    "All ages": [0, None],
    "<5 years": [0, 4],
    "5-14 years": [5, 14],
    "15-49 years": [15, 49],
    "50-69 years": [50, 69],
    "70+ years": [70, None],
}


def run(dest_dir: str) -> None:
    #
    # Load inputs.
    #
    # Load meadow dataset.
    ds_meadow = paths.load_dataset("gbd_cause")

    # Read table from meadow dataset.
    tb = ds_meadow["gbd_cause"].reset_index()
    ds_regions = paths.load_dataset("regions")
    #
    # Process data.
    #
    tb = geo.harmonize_countries(df=tb, countries_file=paths.country_mapping_path)
    # Add regional aggregates
    tb = add_regional_aggregates(
        tb=tb,
        ds_regions=ds_regions,
        index_cols=["country", "year", "metric", "measure", "cause", "age"],
        regions=REGIONS,
        age_group_mapping=AGE_GROUPS_RANGES,
    )

    # Split into two tables: one for deaths, one for DALYs
    tb_deaths = tb[tb["measure"] == "Deaths"].copy()
    tb_dalys = tb[tb["measure"] == "DALYs (Disability-Adjusted Life Years)"].copy()
    # Shorten the metric name for DALYs
    tb_dalys["measure"] = "DALYs"

    # Drop the measure column
    tb_deaths = tb_deaths.drop(columns="measure")
    tb_dalys = tb_dalys.drop(columns="measure")

    # Add all forms of violence together - for Deaths only
    tb_deaths = add_all_forms_of_violence(tb_deaths)
    # Format the tables
    tb_deaths = tb_deaths.format(["country", "year", "metric", "age", "cause"], short_name="gbd_cause_deaths")
    tb_dalys = tb_dalys.format(["country", "year", "metric", "age", "cause"], short_name="gbd_cause_dalys")

    #
    # Save outputs.
    #
    # Create a new garden dataset with the same metadata as the meadow dataset.
    ds_garden = create_dataset(
        dest_dir, tables=[tb_deaths, tb_dalys], check_variables_metadata=True, default_metadata=ds_meadow.metadata
    )

    # Save changes in the new garden dataset.
    ds_garden.save()


def add_all_forms_of_violence(tb: Table) -> Table:
    """
    Add all forms of violence together
    """
    violence = ["Interpersonal violence", "Conflict and terrorism", "Police conflict and executions"]

    tb_violence = tb[(tb["cause"].isin(violence)) & (tb["age"] == "Age-standardized")]
    assert all(tb_violence["metric"] == "Rate")
    assert all(
        v in tb_violence["cause"].values for v in violence
    ), "Not all elements of 'violence' are present in tb_violence['cause']"

    tb_violence = tb_violence.groupby(["country", "age", "metric", "year"])["value"].sum().reset_index()
    tb_violence["cause"] = "All forms of violence"

    tb = pr.concat([tb, tb_violence], ignore_index=True)

    return tb
