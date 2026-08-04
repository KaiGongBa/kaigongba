# Phase 3I split deployment

This directory is the deployment contract for separating StaffDeck from the
transaction core. It does not replace the current `app.kaigongba.net`
all-in-one unit until the production cutover is explicitly approved.

## Processes and ownership

| Process | Entrypoint | Database ownership | Private dependency |
| --- | --- | --- | --- |
| StaffDeck API | `app.staffdeck_main:app` | agents, Skills, tools, knowledge and SOP definitions | transaction identity API |
| Transaction core | `app.transaction_main:app` | organizations, market, requirements, quotes, agreements, orders, delivery and disputes | StaffDeck v1 internal API |

Both databases currently use the same Alembic history so rollback stays
predictable. Each process uses a different physical database and must only read
the other domain through the versioned internal API. A later migration may
prune unused tables after the boundary has remained stable for one release.

Redis is the shared runtime for cross-process rate limits and worker leases. PostgreSQL
remains the business source of truth; Redis is never used as the only copy of orders,
payments, disputes, deliverables or Agent task receipts.

The shared `APP_SECRET` signs user access tokens. `INTERNAL_SERVICE_SECRET` is
separate and authenticates service-to-service requests. Do not expose
`/api/internal/` through the public reverse proxy. Production should additionally
restrict the two internal listeners by security group or loopback/private network.

## Start order

1. Back up both databases and object storage metadata.
2. Run Alembic upgrade as a one-shot deployment task against each database.
3. Start transaction core with `transaction.env.example` as the configuration shape.
4. Start StaffDeck API with `staffdeck.env.example` as the configuration shape.
5. Route `/api/auth`, `/api/marketplace`, `/api/transactions`, `/api/executions`,
   `/api/collaboration` and `/api/disputes` to transaction core. Route the existing
   StaffDeck API paths to StaffDeck. Deny `/api/internal/` at the public proxy.
6. Verify health, login, enterprise agents and marketplace install targets.

Applications start with `DATABASE_STARTUP_MODE=validate`; they fail closed when
the database revision is not at Alembic head. They never run `create_all` or seed
data in staging/production.

## Local acceptance

```sh
scripts/phase3i_infra_up.sh
scripts/phase3i_verify_postgres.sh
scripts/phase3i_verify_minio.sh
scripts/phase5a_verify_redis.sh
scripts/phase3i_verify_split_services.sh
```

The split-service verifier checks that the StaffDeck test database contains no
copy of the acceptance user. It logs in through transaction core, calls a
StaffDeck user API using remote identity validation, and calls a transaction API
that resolves AI employees through StaffDeck.

## Rollback

1. Stop public traffic to the new split listeners.
2. Restore the previous all-in-one unit and configuration without changing the
   existing `app.kaigongba.net` DNS record.
3. If the release introduced a backward-compatible migration, keep the database
   at head. Otherwise downgrade exactly one reviewed revision on each database.
4. Point order-file configuration back to the previous Provider only after all
   new uploads are copied and their SHA-256 metadata is verified.
5. Run login, order read, file download and dispute read smoke tests before
   reopening traffic.

Never roll a database back merely because an application process failed to
start; configuration and service health must be diagnosed first.
