"""Utils for chart revision tool."""
from typing import Any, Dict, List, Tuple

import pandas as pd
import streamlit as st
from pymysql import OperationalError
from rapidfuzz import fuzz
from structlog import get_logger

from apps.utils.map_datasets import get_changed_files, get_grapher_changes
from etl.chart_revision.v3.schema import get_schema_chart_config
from etl.db import config, get_all_datasets, get_connection, get_variables_in_dataset
from etl.version_tracker import VersionTracker

# Logger
log = get_logger()


# @st.cache_data(show_spinner=False)
def get_datasets(new_mode=False) -> pd.DataFrame:
    """Load datasets.

    new_mode: Use VersionTracker
    """
    with st.spinner("Retrieving datasets..."):
        if new_mode:
            return get_datasets_new()
        else:
            return get_datasets_from_db()


def get_datasets_new() -> pd.DataFrame:
    steps_df_grapher, grapher_changes = get_datasets_from_version_tracker()

    # Combine with datasets from database that are not present in ETL
    # Get datasets from Database
    datasets_db = get_datasets_from_db()
    steps_df_grapher = pd.concat([steps_df_grapher, datasets_db], ignore_index=True)
    steps_df_grapher = steps_df_grapher.drop_duplicates(subset="id").drop(columns="updatedAt").astype({"id": int})

    # Add column marking migrations
    steps_df_grapher["migration_new"] = False
    if grapher_changes:
        dataset_ids = [g["new"]["id"] for g in grapher_changes]
        steps_df_grapher.loc[steps_df_grapher["id"].isin(dataset_ids), "migration_new"] = True
        # Add column ranking possible old datasets
        ## Criteria:
        for g in grapher_changes:
            col_name = f"score_{g['new']['id']}"
            ##  - First options should be those detected by grapher_changes ('old' keyword)
            if "old" in g:
                steps_df_grapher.loc[steps_df_grapher["id"] == g["old"]["id"], col_name] = 200
            ##  - Then, we should just fuzzy match the step short_names (and names to account for old datasets not in ETL)
            score_step = steps_df_grapher["step"].apply(lambda x: fuzz.ratio(g["new"]["step"], x))
            score_name = steps_df_grapher["name"].apply(lambda x: fuzz.ratio(g["new"]["name"], x))
            steps_df_grapher[col_name] = (score_step + score_name) / 2

            ## Set own dataset as last
            steps_df_grapher.loc[steps_df_grapher["id"] == g["new"]["id"], col_name] = -1
    st.session_state.is_any_migration = steps_df_grapher["migration_new"].any()
    return steps_df_grapher


@st.cache_data(show_spinner=False)
def get_datasets_from_version_tracker() -> Tuple[pd.DataFrame, List[Dict[str, Any]]]:
    # Get steps_df
    vt = VersionTracker()
    assert vt.connect_to_db, "Can't connnect to database! You need to be connected to run indicator upgrader"
    steps_df = vt.steps_df

    # Get file changes -> Infer dataset migrations
    files_changed = get_changed_files()
    grapher_changes = get_grapher_changes(files_changed, steps_df)

    # Only keep grapher steps
    steps_df_grapher = steps_df.loc[
        steps_df["channel"] == "grapher", ["namespace", "identifier", "step", "db_dataset_name", "db_dataset_id"]
    ]
    # Remove unneded text from 'step' (e.g. '*/grapher/'), no need for fuzzymatch!
    steps_df_grapher["step_reduced"] = steps_df_grapher["step"].str.split("grapher/").str[-1]

    ## Keep only those that are in DB (we need them to be in DB, otherwise indicator upgrade won't work since charts wouldn't be able to reference to non-db-existing indicator IDs)
    steps_df_grapher = steps_df_grapher.dropna(subset="db_dataset_id")
    assert steps_df_grapher.isna().sum().sum() == 0
    ## Column rename
    steps_df_grapher = steps_df_grapher.rename(
        columns={
            "db_dataset_name": "name",
            "db_dataset_id": "id",
        }
    )
    return steps_df_grapher, grapher_changes


def get_datasets_from_db() -> pd.DataFrame:
    """Load datasets."""
    try:
        datasets = get_all_datasets(archived=False)
    except OperationalError as e:
        raise OperationalError(
            f"Could not retrieve datasets. Try reloading the page. If the error persists, please report an issue. Error: {e}"
        )
    else:
        return datasets.sort_values("name")


@st.cache_data(show_spinner=False)
def get_schema() -> Dict[str, Any]:
    """Load datasets."""
    with st.spinner("Retrieving schema..."):
        try:
            schema = get_schema_chart_config()
        except OperationalError as e:
            raise OperationalError(
                f"Could not retrieve the schema. Try reloading the page. If the error persists, please report an issue. Error: {e.__traceback__}"
            )
        else:
            return schema


@st.cache_data(max_entries=1, ttl=60 * 10)
def get_indicators_from_datasets(
    dataset_id_1: int, dataset_id_2: int, show_new_not_in_old: int = False
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Get indicators from two datasets."""
    with get_connection() as db_conn:
        # Get indicators from old dataset that have been used in at least one chart.
        old_indictors = get_variables_in_dataset(db_conn=db_conn, dataset_id=dataset_id_1, only_used_in_charts=True)
        # Get all indicators from new dataset.
        new_indictors = get_variables_in_dataset(db_conn=db_conn, dataset_id=dataset_id_2, only_used_in_charts=False)
        if show_new_not_in_old:
            # Unsure why this was done, but it seems to be wrong.
            # Remove indicators in the new dataset that are not in the old dataset.
            # This can happen if we are matching a dataset to itself in case of renaming variables.
            new_indictors = new_indictors[~new_indictors["id"].isin(old_indictors["id"])]
    return old_indictors, new_indictors


def _check_env() -> bool:
    """Check if environment indicators are set correctly."""
    ok = True
    for env_name in ("GRAPHER_USER_ID", "DB_USER", "DB_NAME", "DB_HOST"):
        if getattr(config, env_name) is None:
            ok = False
            st.warning(st.markdown(f"Environment variable `{env_name}` not found, do you have it in your `.env` file?"))

    if ok:
        st.success("`.env` configured correctly")
    return ok


def _show_environment() -> None:
    """Show environment indicators (streamlit)."""
    # show indicators (from .env)
    st.info(
        f"""
    * **GRAPHER_USER_ID**: `{config.GRAPHER_USER_ID}`
    * **DB_USER**: `{config.DB_USER}`
    * **DB_NAME**: `{config.DB_NAME}`
    * **DB_HOST**: `{config.DB_HOST}`
    """
    )


@st.cache_resource
def _check_env_and_environment() -> None:
    """Check if environment indicators are set correctly."""
    ok = _check_env()
    if ok:
        # check that you can connect to DB
        try:
            with st.spinner():
                _ = get_connection()
        except OperationalError as e:
            st.error(
                "We could not connect to the database. If connecting to a remote database, remember to"
                f" ssh-tunel into it using the appropriate ports and then try again.\n\nError:\n{e}"
            )
            ok = False
        except Exception as e:
            raise e
        else:
            msg = "Connection to the Grapher database was successfull!"
            st.success(msg)
            st.subheader("Environment")
            _show_environment()
