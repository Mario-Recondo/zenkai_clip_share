# To Be Fixed

Deferred issues to address at a future time. Each entry uses the format:
**Title** · **Date logged** · issue description · suggested fix · validity caveat.

---

## Orphan-reaper schedule registration may assume `django_q` tables exist

**Date logged:** 2026-06-18

**Issue**
`clips/apps.py` registers a daily "reap-orphan-media" `django_q` Schedule from the
`clips` app's `post_migrate` handler (`_ensure_orphan_reaper_schedule`), which
imports `django_q.models.Schedule` and writes a row. In `INSTALLED_APPS`, `clips`
is listed before `django_q`. Codex flagged this as a startup/migration hazard:
if the `clips` post-migrate handler runs before the `django_q_schedule` table
exists, a fresh `migrate` could fail.

**Assessment (why this is deferred, not urgent)**
For a normal full `python manage.py migrate`, this is most likely a non-issue:
Django emits `post_migrate` once, at the end of the migrate command, after *all*
apps' migrations have been applied — so `django_q_schedule` already exists by the
time the `clips` handler fires, regardless of `INSTALLED_APPS` order. The realistic
failure path is narrow: a targeted `python manage.py migrate clips` against a
brand-new database where `django_q` was never migrated. Low likelihood, but a
defensive guard would make it bulletproof.

**Codex's suggested fix**
> Register the schedule only after all migrations are complete or guard the
> handler on `django_q` table availability. At minimum, avoid touching `Schedule`
> from the `clips` app's own `post_migrate` signal.

Concretely: wrap the `Schedule.objects.update_or_create(...)` in a check that the
`django_q_schedule` table exists (e.g. via `connection.introspection.table_names()`),
or move schedule registration to a management command / the `django_q` app's own
post_migrate, so it never depends on app ordering.

**Validity caveat**
This suggestion reflects the code and Django behavior as of the date logged. By
the time we fix this, the schedule-registration approach, `INSTALLED_APPS`
ordering, the `django_q` version, or the relevant Django `post_migrate` semantics
may have changed — re-verify the issue still reproduces and that the suggested fix
still applies before implementing.
