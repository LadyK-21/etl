#
#  test_command.py
#

"""
Test components of the etl command-line tool.
"""

import time
import pytest

from etl import command as cmd


def test_timed_run():
    time_taken = cmd.timed_run(lambda: time.sleep(0.05))
    assert abs(time_taken - 0.05) < 0.01


@pytest.fixture()
def dag():
    return {"data-private://a": {"data://b"}, "data://e": {"data://f"}}


def test_filter_private_steps(dag):
    assert cmd._filter_private_steps(dag) == {"data://e": {"data://f"}}


def test_validate_private_steps(dag):
    cmd._validate_private_steps(dag)

    # public step with private dependency should raise an error
    dag = dict(
        dag,
        **{
            "data://c": {"data-private://d"},
        }
    )
    with pytest.raises(ValueError):
        cmd._validate_private_steps(dag)
