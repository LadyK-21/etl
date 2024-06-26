"""Script to create a snapshot of dataset.

Data are transcribed from this webpage:

https://polioeradication.org/polio-today/preparing-for-a-polio-free-world/certification/

"""

from pathlib import Path

import click
import pandas as pd

from etl.snapshot import Snapshot

# Version for current snapshot dataset.
SNAPSHOT_VERSION = Path(__file__).parent.name


@click.command()
@click.option(
    "--upload/--skip-upload",
    default=True,
    type=bool,
    help="Upload dataset to Snapshot",
)
def main(upload: bool) -> None:
    # Create a new snapshot.
    snap = Snapshot(f"health/{SNAPSHOT_VERSION}/polio_status.csv")

    df = pd.DataFrame(
        data={
            "who_region": [
                "Africa",
                "Americas",
                "South-East Asia",
                "Europe",
                "Eastern Mediterranean",
                "Western Pacific",
            ],
            "year_certified_polio_free": [
                2020,
                1994,
                2014,
                2002,
                pd.NA,
                2000,
            ],
        }
    )
    snap.create_snapshot(data=df, upload=upload)


if __name__ == "__main__":
    main()
