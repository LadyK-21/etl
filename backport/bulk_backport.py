from typing import Any, cast

import click
import pandas as pd
import structlog
from owid.catalog.utils import underscore
from owid.walden import Catalog as WaldenCatalog
from sqlalchemy.engine import Engine

from etl.db import get_engine

from . import utils
from .backport import backport

log = structlog.get_logger()


@click.command()
@click.option("--dataset-ids", "-d", type=int, multiple=True)
@click.option(
    "--dry-run/--no-dry-run",
    default=False,
    type=bool,
    help="Do not add dataset to a catalog on dry-run",
)
@click.option(
    "--limit",
    default=1000000,
    type=int,
)
@click.option(
    "--upload/--skip-upload",
    default=True,
    type=bool,
    help="Upload dataset to Walden",
)
@click.option(
    "--force/--no-force",
    default=False,
    type=bool,
    help="Force overwrite even if checksums match",
)
@click.option(
    "--prune/--no-prune",
    default=False,
    type=bool,
    help="Prune datasets from walden that are not in DB anymore",
)
def bulk_backport(
    dataset_ids: list[int],
    dry_run: bool,
    limit: int,
    upload: bool,
    force: bool,
    prune: bool,
) -> None:
    engine = get_engine()

    df = _active_datasets(engine, limit=limit)

    if dataset_ids:
        df = df.loc[df.id.isin(dataset_ids)]

    df["short_name"] = df.name.map(underscore)

    log.info("bulk_backport.start", n=len(df))

    ds_row: Any
    for i, ds_row in enumerate(df.itertuples()):
        log.info(
            "bulk_backport",
            dataset_id=ds_row.id,
            name=ds_row.name,
            private=ds_row.isPrivate,
            progress=f"{i + 1}/{len(df)}",
        )
        backport(
            dataset_id=ds_row.id,
            short_name=ds_row.short_name,
            dry_run=dry_run,
            upload=upload,
            force=force,
        )

    if prune:
        _prune_walden_datasets(engine, dry_run)

    log.info("bulk_backport.finished")


def _active_datasets(engine: Engine, limit: int = 1000000) -> pd.DataFrame:
    """Return dataframe of datasets with at least one chart that should be backported."""
    q = """
    select
        id, name, dataEditedAt, metadataEditedAt, isPrivate
    from datasets
    where id in (
        select distinct v.datasetId from chart_dimensions as cd
        join variables as v on cd.variableId = v.id
    ) and not isArchived
    order by rand()
    limit %(limit)s
    """
    return cast(pd.DataFrame, pd.read_sql(q, engine, params={"limit": limit}))


def _prune_walden_datasets(engine: Engine, dry_run: bool) -> None:
    active_dataset_ids = set(_active_datasets(engine)["id"])

    walden_catalog = WaldenCatalog()

    datasets_to_delete = [
        ds
        for ds in walden_catalog.find(namespace="backport")
        if utils.extract_id_from_short_name(ds.short_name) not in active_dataset_ids
    ]

    log.info("bulk_backport.delete", n=len(datasets_to_delete))

    for ds in datasets_to_delete:
        log.info("bulk_backport.delete_dataset", short_name=ds.short_name)

        # delete it from local and remote catalog
        if not dry_run:
            ds.delete()
            ds.delete_from_remote()


if __name__ == "__main__":
    # Example (run against staging DB):
    #   bulk_backport -d 20 -d 21 -d 5426 --dry-run
    bulk_backport()
