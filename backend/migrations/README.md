# Database migration policy

Run Alembic from `backend/` with `DATABASE_URL` set to a PostgreSQL URL using the `asyncpg` driver.
When the variable is omitted, Alembic uses the local Compose database on `localhost:5432`.

```bash
uv run alembic upgrade head
uv run alembic check
```

Production and shared-environment schema changes are forward-only by default. Take a database backup
before every upgrade; create a corrective forward migration if a deployed migration fails after
commit. Do not run destructive downgrades against data that must be retained.

The initial revision has a downgrade for isolated development and automated tests. It drops all
tables and the `app`, `ts`, and `ml` schemas, so it is safe only for an empty or disposable database.
It deliberately retains the `pgcrypto` and `timescaledb` extensions because extensions can be shared
with other database objects. The integration suite tests `upgrade -> downgrade base -> upgrade` in a
temporary database.
