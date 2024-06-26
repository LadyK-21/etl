#
#  config.py
#

"""
The environment variables and settings here are for publishing options, they're
only important for OWID staff.
"""

import os
import pwd
import re
from os import environ as env
from typing import Optional

import bugsnag
import git
import pandas as pd
import structlog
from dotenv import load_dotenv

from etl.paths import BASE_DIR

log = structlog.get_logger()

ENV_FILE = env.get("ENV_FILE", BASE_DIR / ".env")


def get_username():
    return pwd.getpwuid(os.getuid())[0]


def load_env():
    if env.get("ENV", "").startswith("."):
        raise ValueError(f"ENV was replaced by ENV_FILE, please use ENV_FILE={env['ENV']} ... instead.")

    load_dotenv(ENV_FILE)


def _normalise_branch(branch_name):
    return re.sub(r"[\/\._]", "-", branch_name)


def get_container_name(branch_name):
    normalized_branch = _normalise_branch(branch_name)

    # Strip staging-site- prefix to add it back later
    normalized_branch = normalized_branch.replace("staging-site-", "")

    # Ensure the container name is less than 63 characters
    container_name = f"staging-site-{normalized_branch[:50]}"
    # Remove trailing hyphens
    return container_name.rstrip("-")


load_env()


pd.set_option("future.no_silent_downcasting", True)

# When DEBUG is on
# - run steps in the same process (speeding up ETL)
DEBUG = env.get("DEBUG") in ("True", "true", "1")

# Environment, e.g. production, staging, dev
ENV = env.get("ENV", "dev")
ENV_IS_REMOTE = ENV in ("production", "staging")

# publishing to OWID's public data catalog in R2
R2_BUCKET = "owid-catalog"
R2_SNAPSHOTS_PUBLIC = "owid-snapshots"
R2_SNAPSHOTS_PRIVATE = "owid-snapshots-private"
R2_SNAPSHOTS_PUBLIC_READ = "https://snapshots.owid.io"

# publishing to grapher's MySQL db
GRAPHER_USER_ID = env.get("GRAPHER_USER_ID")
DB_NAME = env.get("DB_NAME", "grapher")
DB_HOST = env.get("DB_HOST", "localhost")
DB_PORT = int(env.get("DB_PORT", "3306"))
DB_USER = env.get("DB_USER", "root")
DB_PASS = env.get("DB_PASS", "")

DB_IS_PRODUCTION = DB_NAME == "live_grapher"

# Special ENV file with access to production DB (read-only), used by chart-diff
ENV_FILE_PROD = os.environ.get("ENV_FILE_PROD")

if "DATA_API_ENV" in env:
    DATA_API_ENV = env["DATA_API_ENV"]
else:
    DATA_API_ENV = env.get("DATA_API_ENV", get_username())

# Production checks
if DATA_API_ENV == "production":
    assert DB_IS_PRODUCTION, "DB_NAME must be set to live_grapher when publishing to production"

if DB_IS_PRODUCTION:
    assert DATA_API_ENV == "production", "DATA_API_ENV must be set to production when publishing to live_grapher"


def load_STAGING() -> Optional[str]:
    # if STAGING is used, override ENV values
    STAGING = env.get("STAGING")

    # ENV_FILE takes precedence over STAGING
    if STAGING and ENV_FILE != BASE_DIR / ".env":
        log.warning("Both ENV_FILE and STAGING is set, STAGING will be ignored.")
        return None
    # if STAGING=1, use branch name
    elif STAGING == "1":
        branch_name = git.Repo(BASE_DIR).active_branch.name
        if branch_name == "master":
            log.warning("You're on master branch, using local env instead of STAGING=master")
            return None
        else:
            return branch_name
    else:
        return STAGING


STAGING = load_STAGING()

# if STAGING is used, override ENV values
if STAGING is not None:
    DB_USER = "owid"
    DB_NAME = "owid"
    DB_PASS = ""
    DB_PORT = 3306
    DB_HOST = get_container_name(STAGING)
    DATA_API_ENV = get_container_name(STAGING)


# if running against live, use s3://owid-api, otherwise use s3://owid-api-staging
# Cloudflare workers running on https://api.ourworldindata.org/ and https://api-staging.owid.io/ will use them
if DATA_API_ENV == "production":
    BAKED_VARIABLES_PATH = "s3://owid-api/v1/indicators"
    DATA_API_URL = "https://api.ourworldindata.org/v1/indicators"
else:
    BAKED_VARIABLES_PATH = f"s3://owid-api-staging/{DATA_API_ENV}/v1/indicators"
    DATA_API_URL = f"https://api-staging.owid.io/{DATA_API_ENV}/v1/indicators"


def variable_data_url(variable_id):
    return f"{DATA_API_URL}/{variable_id}.data.json"


def variable_metadata_url(variable_id):
    return f"{DATA_API_URL}/{variable_id}.metadata.json"


# run ETL steps with debugger on exception
IPDB_ENABLED = False

# number of workers for checking dirty steps, we need to parallelize this
# because we're making a lot of HTTP requests
DIRTY_STEPS_WORKERS = int(env.get("DIRTY_STEPS_WORKERS", 5))

# default number of processes for running steps if not using --workers
# it is 1 by default because we usually can't run multiple steps in parallel in dev
RUN_STEPS_WORKERS = int(env.get("RUN_STEPS_WORKERS", 1))

# number of workers for grapher inserts to DB
# NOTE: make sure the product of run processes and grapher workers is constant
GRAPHER_INSERT_WORKERS = int(env.get("GRAPHER_WORKERS", max(10, int(40 / RUN_STEPS_WORKERS))))

# only upsert indicators matching this filter, this is useful for fast development
# of data pages for a single indicator
GRAPHER_FILTER = env.get("GRAPHER_FILTER", None)

# if set, don't delete indicators from MySQL, only append / update new ones
# you can use this to only process subset of indicators in your step to
# speed up development. It's up to you how you define filtering logic in your step
SUBSET = env.get("SUBSET", None)

# forbid any individual step from consuming more than this much memory
# (only enforced on Linux)
MAX_VIRTUAL_MEMORY_LINUX = 32 * 2**30  # 32 GB

# increment this to force a full rebuild of all datasets
ETL_EPOCH = 5

# any garden or grapher dataset after this date will have strict mode enabled
STRICT_AFTER = "2023-06-25"

SLACK_API_TOKEN = env.get("SLACK_API_TOKEN")

# if True, commit and push updates to YAML files coming from admin
ETL_API_COMMIT = env.get("ETL_API_COMMIT") in ("True", "true", "1")

# if True, commit and push updates from fasttrack
FASTTRACK_COMMIT = env.get("FASTTRACK_COMMIT") in ("True", "true", "1")

ADMIN_HOST = env.get("ADMIN_HOST", f"http://staging-site-{STAGING}" if STAGING else "http://localhost:3030")

# Tailscale address of Admin, this cannot be just `http://owid-admin-prod`
# because that would resolve to LXC container instead of the actual server
TAILSCALE_ADMIN_HOST = "http://owid-admin-prod.tail6e23.ts.net"

BUGSNAG_API_KEY = env.get("BUGSNAG_API_KEY")

OPENAI_API_KEY = env.get("OPENAI_API_KEY", None)

OWIDBOT_ACCESS_TOKEN = env.get("OWIDBOT_ACCESS_TOKEN", None)

# OWIDBOT app
OWIDBOT_APP_PRIVATE_KEY_PATH = env.get("OWIDBOT_APP_PRIVATE_KEY_PATH", None)
# get it from https://github.com/settings/apps/owidbot-app
OWIDBOT_APP_CLIENT_ID = env.get("OWIDBOT_APP_CLIENT_ID", None)
# get it from https://github.com/settings/installations
OWIDBOT_APP_INSTALLATION_ID = env.get("OWIDBOT_APP_INSTALLATION_ID", None)


def enable_bugsnag() -> None:
    if BUGSNAG_API_KEY:
        bugsnag.configure(
            api_key=BUGSNAG_API_KEY,
        )  # type: ignore
