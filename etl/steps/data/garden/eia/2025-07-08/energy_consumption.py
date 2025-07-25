"""Garden step for EIA total energy consumption."""

from etl.data_helpers import geo
from etl.helpers import PathFinder

# Get paths and naming conventions for current step.
paths = PathFinder(__file__)

# Conversion factor from terajoules to terawatt-hours.
TJ_TO_TWH = 1 / 3600

# Columns to use from meadow table, and how to rename them.
COLUMNS = {"country": "country", "year": "year", "values": "energy_consumption"}

# Regions aggregates to create.
REGIONS = {
    # Default continents.
    "Africa": {},
    "Asia": {},
    "Europe": {},
    "North America": {},
    "Oceania": {},
    "South America": {},
    # Income groups.
    "Low-income countries": {},
    "Upper-middle-income countries": {},
    "Lower-middle-income countries": {},
    "High-income countries": {},
    # Other special regions.
    # The European Union is already included in the original data, and coincides exactly with the following:
    # "European Union (27)": {{"additional_members": ["East Germany", "West Germany", "Czechoslovakia"]}},
}

# Known overlaps between historical regions and successor countries.
# NOTE: They are not removed from the data when constructing the aggregate for Europe, but the contribution of Aruba is
# negligible, so the double-counting is not relevant.
KNOWN_OVERLAPS = [{year: {"Aruba", "Netherlands Antilles"} for year in range(1986, 2024)}]


def run() -> None:
    #
    # Load data.
    #
    # Load EIA dataset and read its main table.
    ds_meadow = paths.load_dataset("energy_consumption")
    tb_meadow = ds_meadow.read("energy_consumption")

    # Load regions dataset.
    ds_regions = paths.load_dataset("regions")

    # Load income groups dataset.
    ds_income_groups = paths.load_dataset("income_groups")

    #
    # Process data.
    #
    # Select and rename columns conveniently.
    tb = tb_meadow[list(COLUMNS)].rename(columns=COLUMNS, errors="raise")

    # Harmonize country names.
    tb = geo.harmonize_countries(
        df=tb,
        countries_file=paths.country_mapping_path,
        warn_on_missing_countries=True,
        warn_on_unused_countries=True,
        excluded_countries_file=paths.excluded_countries_path,
    )

    # Convert terajoules to terawatt-hours.
    tb["energy_consumption"] *= TJ_TO_TWH

    # Create aggregate regions.
    tb = geo.add_regions_to_table(
        tb,
        ds_regions=ds_regions,
        regions=REGIONS,
        ds_income_groups=ds_income_groups,
        min_num_values_per_year=1,
        ignore_overlaps_of_zeros=True,
        accepted_overlaps=KNOWN_OVERLAPS,
    )

    # Set an appropriate index and sort conveniently.
    tb = tb.format(keys=["country", "year"])

    #
    # Save outputs.
    #
    # Create a new garden dataset.
    ds_garden = paths.create_dataset(tables=[tb])
    ds_garden.save()
