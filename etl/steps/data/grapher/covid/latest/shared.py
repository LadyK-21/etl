"""Load a garden dataset and create a grapher dataset."""

from etl.helpers import PathFinder, create_dataset, grapher_checks


def run(dest_dir: str, paths: PathFinder) -> None:
    #
    # Load inputs.
    #
    # Load garden dataset.
    ds_garden = paths.load_dataset_dependency()

    # Read table from garden dataset.
    tb = ds_garden[paths.short_name]

    #
    # Save outputs.
    #
    # Create a new grapher dataset with the same metadata as the garden dataset.
    ds_grapher = create_dataset(dest_dir, tables=[tb], default_metadata=ds_garden.metadata)

    #
    # Checks.
    #
    grapher_checks(ds_grapher)

    # Save changes in the new grapher dataset.
    ds_grapher.save()
