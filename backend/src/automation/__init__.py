"""Event-driven automation (Phase 14 WS3, tech spec §7; functional spec §3).

Anything that happens becomes an event in the tenant's database; triggers
decide which agent runs; a scheduler owns time; agents can schedule, emit and
wait. This package grows module by module:

* ``filters``   — the safe JSON filter language a trigger matches events with (§7.5)
* ``templates`` — sandboxed input templates that turn an event into a run's input
* ``schedules`` — cron and timer maths in the business's time zone, DST rules, catch-up (§7.7)
* ``events``    — event ids (UUIDv7), types and dedupe keys (§7.2)
* ``guards``    — the safety rails' decisions: chain depth, overlap, agent limits (§7.8, §7.10)

The store, router, scheduler process, waits and tools come with the tenant
tables (WS3 3.2+), on top of WS2's tenant sessions.
"""
