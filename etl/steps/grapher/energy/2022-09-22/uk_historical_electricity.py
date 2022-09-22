from owid import catalog

from etl import grapher_helpers as gh
from etl.helpers import Names

# Naming conventions.
N = Names(__file__)


def run(dest_dir: str) -> None:
    # Create new empty grapher dataset, using metadata from the garden dataset.
    dataset = catalog.Dataset.create_empty(dest_dir, gh.adapt_dataset_metadata_for_grapher(N.garden_dataset.metadata))
    # Load table from garden dataset.
    table = N.garden_dataset["uk_historical_electricity"].reset_index()
    # Adapt table for grapher.
    table = gh.adapt_table_for_grapher(table)
    # Add table to new grapher dataset.
    dataset.add(table)
    # Save new dataset.
    dataset.save()
