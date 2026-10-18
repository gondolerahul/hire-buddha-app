"""The dynamic schema of a business's records (Phase 14 WS4, tech spec §8).

* ``blueprint`` — the versioned description of every object the Data API
  exposes: field types, naming rules, validation (pure);
* ``base_pack`` — the platform's standard objects (account, contact,
  activity, consent), from one definition for both the blueprint and the DDL;
* ``planner`` — change operations → the next blueprint + the DDL plan (pure);
* ``apply`` — runs a plan in the business's database and activates the new
  version; ``store`` — the blueprint and change rows.

Business tables live in the business's own database: platform objects in
schema ``business``, the business's own in schema ``custom``; columns a
business adds to platform objects are prefixed ``x_`` (TD-06).
"""
