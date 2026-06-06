# The Retry Storm Was the Outage: Coordinating Retry Budgets in Kestra

## Thirty correct retry loops produced 231 requests for 30 successful calls. The fix required shared admission and control at the network boundary.

An eight-second downstream outage ended. The traffic did not.

Thirty Kestra executions were each running a bounded exponential retry policy. Every execution eventually succeeded, but together they issued 231 requests for 30 successful operations. Recovery traffic peaked at 30 requests per second against a service that could accept five. After the scheduled outage cleared, retries generated another 70 overload responses.

The final policy completed the same 30 operations with 44 requests, held the peak to four requests per second, and produced no overload responses. The design used four distinct controls: a concurrency bulkhead, a shared circuit breaker, a retry admission budget, and durable dispatch pacing.

The last control was the important surprise. Limiting when Kestra executions received permission to retry did not limit when their HTTP tasks reached the provider.

This is a controlled failure-injection lab, not a production incident. The complete Docker package, Kestra flows, PostgreSQL functions, mock provider, runner, and result artifacts are available at [github.com/arjunarav/kestra-retry-storm-lab](https://github.com/arjunarav/kestra-retry-storm-lab).

## The Experiment

Each scenario launches 30 Kestra `Subflow` executions against the same stateful provider simulation:

- Scheduled outage: 8 seconds
- Healthy capacity: 5 requests per second
- Service latency: 250 milliseconds
- Overload cooldown: 1.5 seconds
- Expected successful clients: 30

Before `outage_until`, the provider returns `503 scheduled_outage`. After recovery, the sixth request in one wall-clock second returns `503 capacity_exceeded` and starts the cooldown. Requests during that cooldown return `503 overload_cooldown`.

This makes excess recovery traffic part of the failure model. A strategy that floods the provider after recovery extends the outage it is trying to escape.

The provider locks the scenario row before calculating capacity and records every actual request in PostgreSQL. The coordinator separately records every `CALL`, `PROBE`, `DEFER`, and `COMPLETE` decision. Metrics therefore come from durable provider and coordinator events, not parsed logs.

The three policies differ only in the child flow:

1. Execution-local exponential retries.
2. The same retries behind a five-execution concurrency limit.
3. A five-execution bulkhead plus a shared circuit, four admissions per second, and dispatch slots spaced 250 milliseconds apart.

The four-request budget deliberately leaves one request per second of headroom. Recovery traffic should not consume the provider's entire stated capacity.

![Architecture of the three Kestra retry-control strategies](./architecture.png)

The clean validation used Kestra 1.3.21, PostgreSQL 16.14, Python 3.12.11, and Docker Engine 29.5.2 on ARM64. Container images are pinned by digest and the Python dependency is pinned by exact version.

## Local Backoff Is Not Global Coordination

The baseline uses Kestra's HTTP Request retry policy:

```yaml
- id: call_downstream
  type: io.kestra.plugin.core.http.Request
  uri: "http://mock-api:8080/work?run_id={{ inputs.run_id }}&client_id={{ inputs.client_id }}"
  method: GET
  timeout: PT5S
  retry:
    type: exponential
    interval: PT1S
    maxInterval: PT4S
    delayFactor: 2
    maxAttempts: 12
    maxDuration: PT2M
```

This is reasonable for one execution. The scope is the problem. Each execution observes only its own failure and schedules only its own retry. Thirty executions start together, fail together, and wake in waves. Exponential backoff changes the interval between waves; it does not coordinate the members of a wave.

The baseline intentionally omits jitter. Jitter would reduce synchronization, but it would not establish a shared five-request limit. Independent clients can still exceed downstream capacity after their wake-ups spread out.

Execution `5bLjJFkgP7jbAvZzCxBMnv` completed all clients but generated 231 requests, 201 failures, a 30 RPS peak, and 18.451 seconds of recovery delay after the scheduled outage ended.

A success-only dashboard would call that run healthy. The provider experienced 7.70 calls for every completed client.

## A Bulkhead Is Not a Rate Limit

The second policy adds a Kestra flow concurrency limit:

```yaml
concurrency:
  behavior: QUEUE
  limit: 5
```

This reduced total requests from 231 to 100 and the peak from 30 to 10 RPS. It still produced 40 overload responses.

Concurrency limits active executions. It does not limit how many HTTP calls those executions can complete in one second. Five executions with 250-millisecond calls can collectively exceed five requests per second, and their retries can still align.

The bulkhead was useful, but it solved a different problem: work in flight. The provider still needed a shared decision about retry admission and final dispatch rate.

## The Shared Recovery State

The layered policy keeps orchestration in Kestra and places the atomic shared decision in PostgreSQL. One coordinator row per run stores:

```text
state                 CLOSED | OPEN | HALF_OPEN
consecutive_failures  circuit threshold input
next_probe_at         earliest recovery probe
probe_owner           execution holding the probe lease
probe_lease_until     recovery from a dead probe owner
token_bucket          start of the fixed admission window
tokens_used           admissions in that window
next_dispatch_at      durable network pacing cursor
```

Despite the column name, `token_bucket` is the start of a fixed one-second window, not a classical refillable token bucket.

Each client calls `acquire_permission()`. The function locks the row with `SELECT ... FOR UPDATE` and returns:

```text
CALL      circuit closed and budget available
PROBE     this client owns the half-open probe
DEFER     circuit open, probe active, or budget exhausted
COMPLETE  client already completed
```

The circuit opens after three failures. While open, executions defer instead of calling the provider. After three seconds, one execution receives a probe lease. A successful probe closes the circuit; a failed probe reopens it.

The lease is not optional bookkeeping. If the half-open execution disappears, another client can recover the expired lease instead of leaving the circuit permanently stuck.

One state-machine bug survived row locking. Calls already in flight when the circuit opened returned later and repeatedly pushed `next_probe_at` forward. The code was serialized but semantically wrong. The final transition records those late failures as `in_flight_failure_after_open` without reopening the circuit again.

That distinction is why the coordinator has an append-only decision ledger. A deferred attempt, a failed network call, and a circuit transition are different events even if a task-count dashboard makes them look similar.

## The Permit-to-Dispatch Gap

The first coordinated implementation allowed at most four permits per second in PostgreSQL. It passed one run.

The clean-volume rerun peaked at nine RPS and generated 25 overload responses. Permitted executions had waited for Kestra workers, then several HTTP tasks became runnable together:

```text
SQL grants permit
  -> Kestra schedules the next task
  -> a worker becomes available
  -> the HTTP request is sent
```

Permit time and network time were not interchangeable.

The fix was a durable dispatch cursor. Before the provider call, the adapter reserves a timestamp under the same coordinator lock:

```sql
select circuit_state.next_dispatch_at
into v_next_dispatch_at
from retry_lab.circuit_state
where circuit_state.run_id = p_run_id
for update;

v_dispatch_at := greatest(v_now, v_next_dispatch_at);

update retry_lab.circuit_state
set next_dispatch_at =
  v_dispatch_at
  + ((1000.0 / v_retry_budget_rps) * interval '1 millisecond')
where circuit_state.run_id = p_run_id;
```

At four requests per second, reservations are 250 milliseconds apart. If Kestra releases multiple tasks together, the adapter waits for their distinct slots before recording and performing the downstream call.

Admission answers whether an attempt may happen. Dispatch pacing answers when it may cross the network boundary. A production implementation could enforce that second control in an API gateway, queue consumer, or rate-limiting proxy. The key is to enforce it where timing becomes real.

## The Kestra Control Loop

The coordinated child flow uses `LoopUntil` rather than automatic HTTP retries. A `503` is passed to `record_result()` as state-machine input:

```yaml
- id: coordinate_recovery
  type: io.kestra.plugin.core.flow.LoopUntil
  condition: "{{ outputs.check_completion.row.completed == true }}"
  failOnMaxReached: true
  checkFrequency:
    interval: PT0.1S
    maxDuration: PT3M
    maxIterations: 360
  tasks:
    - id: acquire_permission
      type: io.kestra.plugin.jdbc.postgresql.Query
      fetchType: FETCH_ONE
      sql: |
        select *
        from retry_lab.acquire_permission(
          '{{ inputs.run_id }}',
          '{{ inputs.client_id }}'
        );

    - id: route_permission
      type: io.kestra.plugin.core.flow.If
      condition: >-
        {{
          outputs.acquire_permission.row.action == 'CALL'
          or outputs.acquire_permission.row.action == 'PROBE'
        }}
```

The complete checked-in flow contains the HTTP call, `record_result()` query, defer sleep, and completion check. It bounds the loop at three minutes and 360 iterations. The probe lease has its own three-second bound because loop exhaustion and probe-owner loss are separate failure modes.

The lab uses a fixed 400-millisecond defer sleep for readable YAML. Production code should honor the returned `wait_ms` deadline or use event-driven wake-up rather than polling every coordinator at the same interval.

## Results

![Measured results from the three clean Kestra executions](./results.png)

**Independent retries:** 231 requests, 201 failures, 30 peak RPS, 7.70 requests per success, 70 overload responses, and 18.451 seconds of recovery delay.

**Five-execution bulkhead:** 100 requests, 70 failures, 10 peak RPS, 3.33 requests per success, 40 overload responses, and 16.974 seconds of recovery delay.

**Layered policy:** 44 requests, 14 failures, 4 peak RPS, 1.47 requests per success, zero overload responses, and 11.685 seconds of recovery delay.

All three policies completed all 30 clients. The layered run, execution `2plUaoV3Ds5hiykILUsghw`, opened or reopened the circuit twice, granted two probes, and deferred 45 attempts.

Compared with independent retries, it reduced actual provider traffic by about 81 percent. That percentage belongs to this workload, not to retry systems in general. The decision-relevant result is structural:

- Backoff controlled one execution but amplified aggregate recovery traffic.
- Concurrency reduced the blast radius but did not enforce provider rate.
- Shared admission stopped calls during known failure.
- Dispatch pacing absorbed scheduler jitter at the external boundary.

The objective was not minimum latency at any cost. It was recovery without causing another outage. Reserving provider headroom still completed sooner because the service was not repeatedly pushed back into cooldown.

## Production Boundary

This package is production-shaped, not a drop-in global retry service.

Coordinator state should be partitioned by downstream dependency, tenant, and possibly operation class. One global row would serialize unrelated traffic and become a bottleneck.

PostgreSQL gives the permission path a clear linearization point, but it also becomes part of the availability model. Production behavior must define what happens if the coordinator is unavailable: fail closed, use a deliberately bounded degraded mode, or route through a separate admission service. Falling back to unrestricted retries defeats the design.

The fixed-window budget may need replacement with a token bucket, sliding window, weighted permits, or adaptive limits. First attempts and retries may also need separate budgets so recovery traffic does not starve healthy work.

The adapter waits for future dispatch slots, which is acceptable for this lab but inefficient at high throughput. A gateway or queue consumer can own scheduled dispatch without holding one request thread per future slot.

Finally, retry control does not make side effects idempotent. If a timeout can hide a committed write, the workflow still needs an idempotency key or a query-and-reconcile path before repeating it.

Before adding a retry now, I ask two questions: who else will retry at the same time, and where is the final dispatch rate enforced?

## Reproduce the Run

The repository contains the exact six Kestra flows, PostgreSQL schema and functions, mock provider, validation runner, intermediate failed result, and final result artifacts.

```bash
git clone https://github.com/arjunarav/kestra-retry-storm-lab.git
cd kestra-retry-storm-lab
cp .env.example .env
docker compose up -d --build
python3 -u scripts/run_experiment.py
```

The runner imports all flows, executes the three scenarios sequentially, rejects failed parent executions, and writes `results/latest-run.json`. The published measurements came from a rebuild after `docker compose down --volumes --remove-orphans`, so schema creation and flow initialization were included in the validation.

Kestra is available locally at `http://127.0.0.1:8082` with the demo credentials documented in the repository.

## References

- [Kestra flow concurrency documentation](https://kestra.io/docs/workflow-components/concurrency)
- [Kestra task retries documentation](https://kestra.io/docs/workflow-components/retries)
- [Kestra HTTP Request task](https://kestra.io/plugins/core/http/io.kestra.plugin.core.http.request)
- [Kestra LoopUntil task](https://kestra.io/plugins/core/flow/io.kestra.plugin.core.flow.loopuntil)
- [Kestra PostgreSQL Docker Compose example](https://kestra.io/docs/installation/docker-compose)
- [PostgreSQL explicit locking](https://www.postgresql.org/docs/16/explicit-locking.html)
- [AWS Builders' Library: Timeouts, retries, and backoff with jitter](https://aws.amazon.com/builders-library/timeouts-retries-and-backoff-with-jitter/)

## Author Note

I built and reran this Docker lab from clean volumes, using AI assistance that I reviewed and finalized.
