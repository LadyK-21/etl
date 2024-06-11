"""This script has been autogenerated by `walkthrough walden`.

Download the csv of this data from - https://databank.worldbank.org/source/health-nutrition-and-population-statistics/Series/SH.STA.PNVC.ZS#

We then upload it to walden here
"""

from pathlib import Path

import click

from owid.walden import Dataset, add_to_catalog

LOCAL_PATH = "/Users/fionaspooner/Downloads/Data_Extract_From_Health_Nutrition_and_Population_Statistics/498e8f9a-80c9-438c-9d3f-b6ee4f772052_Data.csv"


@click.command()
@click.option(
    "--upload/--skip-upload",
    default=True,
    type=bool,
    help="Upload dataset to Walden",
)
def main(upload: bool) -> None:
    metadata = Dataset.from_yaml(Path(__file__).parent / "postnatal_care.meta.yml")

    add_to_catalog(metadata=metadata, filename=LOCAL_PATH, upload=upload)


if __name__ == "__main__":
    main()
