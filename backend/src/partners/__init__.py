"""The partner programme (Phase 15 WS15-8, tech design §11; REQ-PT-*).

Silver partners refer customers (no access to their data) and Gold partners
resell and deliver (scoped, audited access through grants). Partners earn
commission on the cash their customers pay — never on recruiting or on
partnership fees (K-12) — distributed over at most three levels with a pool
cap, a margin guard, holdback and clawback; statements are monthly.

* ``models`` — the tables; ``tree`` — company tree and role rules (T8-1);
  ``scope`` — which tenants a partner has (T8-3); ``access`` — grants (T8-4);
* ``applications`` — applying, underwriting, the lifecycle (T8-5);
  ``fees`` — the annual partnership fee (T8-6);
* ``rules``, ``commission`` — the commission engine (T8-7); ``charges`` —
  setup and customisation fees (T8-8); ``leads`` (T8-9); ``statements`` —
  statements and payouts (T8-10); ``assignments`` — reassignment and
  termination (T8-11); ``simulator`` (T8-13); ``jobs``; the routers.
"""
