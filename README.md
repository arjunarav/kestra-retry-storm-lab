# Kestra Retry Storm Lab

A reproducible failure-injection lab for comparing three retry-control
strategies in Kestra:

1. Independent execution-local exponential retries.
2. The same retries behind a five-execution flow concurrency limit.
3. A layered policy with a five-execution bulkhead, shared circuit breaker,
   four-permit retry budget, and durable 250 ms dispatch slots.

The lab does not claim to reproduce a production incident. It creates a
controlled eight-second outage against a downstream service that can accept
five requests per second, then measures how 30 Kestra Subflow executions
recover.

## What Runs

- Kestra 1.3.21 with PostgreSQL repository and queue backends.
- PostgreSQL 16.14 for Kestra state, retry coordination, and experiment data.
- A Python 3.12.11 fault-injection API that records every downstream request.
- Six Kestra flows: three client policies and three parent experiment flows.

All base images are pinned by digest. The Python dependency is pinned by exact
version.

## Requirements

- Docker Desktop or Docker Engine with Compose v2.
- At least 3 GB available to Docker.
- Python 3.9 or newer on the host for the experiment runner.

The checked-in resource limits allocate up to 1.9 GB to Kestra, 640 MB to
PostgreSQL, and 256 MB to the mock API.

## Run the Full Experiment

```bash
cp .env.example .env
docker compose up -d --build
python3 -u scripts/run_experiment.py
```

The script waits for Kestra, imports all six flows, runs the three scenarios
sequentially, waits for terminal execution states, and writes:

```text
results/latest-run.json
```

The checked-in evidence from the clean-volume validation is:

```text
results/experiment-results.json
results/summary.csv
results/development-dispatch-gap.json
```

The development artifact records the intermediate run that disproved the
permit-timing design. It is retained because that failed claim led to the
durable dispatch-slot implementation.

The exact numbers vary slightly with local scheduler timing. These invariants
should hold:

- all 30 clients complete in every scenario;
- independent retries have the largest request count and peak;
- the bulkhead lowers the peak but still produces overload responses;
- the layered strategy produces zero overload responses;
- the layered strategy has the lowest retry amplification.

## Open Kestra

- URL: http://127.0.0.1:8082
- Username: `admin@kestra.io`
- Password: `Admin1234`

These credentials are only for the local lab.

The three parent flows are:

- `retry-storm-lab.run-independent-retries`
- `retry-storm-lab.run-bounded-concurrency`
- `retry-storm-lab.run-global-retry-budget`

## Inspect the Evidence

Show the measured summary:

```bash
docker compose exec -T postgres psql -U kestra -d kestra -c \
  "select * from retry_lab.metrics('YOUR_RUN_ID');"
```

Show requests per second:

```bash
docker compose exec -T postgres psql -U kestra -d kestra -c "
select
  second_bucket,
  count(*) as requests,
  count(*) filter (where response_status = 200) as successful,
  count(*) filter (where response_status >= 400) as failed,
  count(*) filter (
    where reason in ('capacity_exceeded', 'overload_cooldown')
  ) as overload
from retry_lab.request_events
where run_id = 'YOUR_RUN_ID'
group by second_bucket
order by second_bucket;"
```

Inspect circuit and admission decisions:

```bash
docker compose exec -T postgres psql -U kestra -d kestra -c "
select action, circuit_state, reason, count(*)
from retry_lab.decision_events
where run_id = 'YOUR_RUN_ID'
group by action, circuit_state, reason
order by action, reason;"
```

## Why the Dispatch Slot Exists

A permit granted by one Kestra SQL task is not the same as a network request
sent at that instant. Under scheduler load, several permitted HTTP tasks can
become runnable together. The first implementation limited permit issuance but
still allowed a later burst.

The final coordinated path reserves a durable dispatch timestamp in
PostgreSQL. The provider adapter waits until that slot before performing the
recorded downstream call. This preserves the shared retry budget across the
task-scheduling boundary.

## Repository Layout

```text
.
├── docker-compose.yml
├── postgres/init/10-retry-lab.sql
├── mock-api/
├── kestra/application.yml
├── flows/
├── scripts/run_experiment.py
├── results/
└── article/
```

## Stop or Reset

Stop containers while preserving data:

```bash
docker compose down
```

Remove only this lab's containers and volumes:

```bash
docker compose down --volumes --remove-orphans
```

## Scope

This is a single-node reference lab, not a throughput benchmark. A production
implementation should partition coordinator state by downstream dependency,
set database lock and statement timeouts, use a secrets manager, retain
provider idempotency keys, and test coordinator failover.

## Article

The paste-ready article and local preview are in `article/`.

```bash
make preview
```

Then open http://127.0.0.1:8788/index.html. The preview provides separate
controls for copying the rendered article, copying Markdown, and downloading
both publication images.

## License

MIT
