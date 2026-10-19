"""``schema_catalog.adoption_plan``: what turns a model-built tenant schema into the baseline (Phase 14 WS2 2.7).

Catalogues are written by hand here; ``tests/integration/test_migration_trees.py``
reads real ones and runs the plan.
"""
from __future__ import annotations

import pytest

from src.common.tenancy.schema_catalog import AdoptionRefused, adoption_plan, differences


def _catalog(tables=None, enums=None, views=None):
    return {"tables": tables or {}, "enums": enums or {}, "views": views or {}}


def _table(columns, constraints=None, indexes=None):
    return {"columns": columns, "constraints": constraints or {}, "indexes": indexes or {}}


PK = ("p", "PRIMARY KEY (id)")
ID = ("uuid", True, None)


@pytest.mark.parametrize("have, reason", [
    (_catalog({"t": _table({"id": ID}), "extra": _table({"id": ID})}), "table extra"),
    (_catalog({"t": _table({"id": ID, "mine": ("text", False, None)})}), "column t.mine"),
    (_catalog({"t": _table({"id": ("text", True, None)})}), "column t.id: text, the baseline has uuid"),
])
def test_what_only_losing_data_would_fix_is_refused(have, reason):
    want = _catalog({"t": _table({"id": ID})})
    with pytest.raises(AdoptionRefused, match=reason):
        adoption_plan(have, want)


def test_an_enum_with_other_labels_is_refused():
    with pytest.raises(AdoptionRefused, match="enum status"):
        adoption_plan(_catalog(enums={"status": ["a"]}), _catalog(enums={"status": ["a", "b"]}))


def test_the_same_schema_needs_nothing():
    same = _catalog({"t": _table({"id": ID}, {"t_pkey": PK}, {"t_pkey": (True, "CREATE UNIQUE INDEX t_pkey ...")})})
    assert adoption_plan(same, same) == [] and differences(same, same) == []


def test_keys_are_dropped_first_and_added_last_with_the_view_after_them():
    have = _catalog({
        "parent": _table({"id": ID}, {"parent_pkey": PK}),
        "child": _table({"id": ID, "parent_id": ("uuid", False, None)},
                        {"child_pkey": PK, "child_parent_id_fkey": ("f", "FOREIGN KEY (parent_id) REFERENCES parent(id)")},
                        {"ix_old": (False, "CREATE INDEX ix_old ON child USING btree (parent_id)")}),
    })
    want = _catalog({
        "parent": _table({"id": ID}, {"parent_pkey": PK}),
        "child": _table({"id": ID, "parent_id": ("uuid", False, None)},
                        {"child_pkey": PK, "fk_child_parent": ("f", "FOREIGN KEY (parent_id) REFERENCES parent(id) "
                                                                    "ON DELETE SET NULL")},
                        {"idx_child_parent": (False, "CREATE INDEX idx_child_parent ON child USING btree (parent_id)")}),
    }, views={"rollup": {"definition": " SELECT 1;", "indexes": {"rollup_uniq": "CREATE UNIQUE INDEX rollup_uniq ON rollup"}}})
    plan = adoption_plan(have, want)
    assert plan == [
        'ALTER TABLE "child" DROP CONSTRAINT "child_parent_id_fkey"',
        'DROP INDEX "ix_old"',
        "CREATE INDEX idx_child_parent ON child USING btree (parent_id)",
        'ALTER TABLE "child" ADD CONSTRAINT "fk_child_parent" FOREIGN KEY (parent_id) REFERENCES parent(id) '
        "ON DELETE SET NULL",
        'CREATE MATERIALIZED VIEW "rollup" AS  SELECT 1',
        "CREATE UNIQUE INDEX rollup_uniq ON rollup",
    ]


def test_a_missing_table_column_default_and_not_null_are_added():
    have = _catalog({"t": _table({"id": ID, "n": ("integer", False, None)}, {"t_pkey": PK})})
    want = _catalog({
        "t": _table({"id": ID, "n": ("integer", True, "0"), "added": ("text", False, "'x'::text")}, {"t_pkey": PK}),
        "new": _table({"id": ("uuid", True, "gen_random_uuid()"), "state": ("node_state", True, None)},
                      {"new_pkey": PK}, {"new_pkey": (True, "CREATE UNIQUE INDEX new_pkey ON new USING btree (id)")}),
    }, enums={"node_state": ["a", "b"]})
    plan = adoption_plan(have, want)
    assert plan == [
        "CREATE TYPE \"node_state\" AS ENUM ('a', 'b')",
        'CREATE TABLE "new" ("id" uuid DEFAULT gen_random_uuid() NOT NULL, "state" node_state NOT NULL)',
        'ALTER TABLE "new" ADD CONSTRAINT "new_pkey" PRIMARY KEY (id)',
        'ALTER TABLE "t" ALTER COLUMN "n" SET DEFAULT 0',
        'ALTER TABLE "t" ALTER COLUMN "n" SET NOT NULL',
        "ALTER TABLE \"t\" ADD COLUMN \"added\" text DEFAULT 'x'::text",
    ]
    assert len(differences(have, want)) == 4  # n, added, table new, enum node_state
