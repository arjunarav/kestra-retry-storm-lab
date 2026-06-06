create schema if not exists retry_lab;

create table retry_lab.scenario_runs (
  run_id text primary key,
  strategy text not null check (strategy in ('independent', 'bounded', 'global_budget')),
  started_at timestamptz not null,
  outage_until timestamptz not null,
  capacity_rps integer not null check (capacity_rps > 0),
  overload_cooldown_ms integer not null check (overload_cooldown_ms > 0),
  retry_budget_rps integer not null check (retry_budget_rps > 0),
  expected_clients integer not null check (expected_clients > 0),
  overload_until timestamptz,
  status text not null default 'RUNNING'
);

create table retry_lab.client_state (
  run_id text not null references retry_lab.scenario_runs(run_id) on delete cascade,
  client_id text not null,
  completed boolean not null default false,
  attempt_count integer not null default 0,
  last_status integer,
  completed_at timestamptz,
  updated_at timestamptz not null default clock_timestamp(),
  primary key (run_id, client_id)
);

create table retry_lab.request_events (
  id bigserial primary key,
  run_id text not null references retry_lab.scenario_runs(run_id) on delete cascade,
  client_id text not null,
  requested_at timestamptz not null,
  second_bucket timestamptz not null,
  response_status integer not null,
  reason text not null
);

create index request_events_run_bucket_idx
  on retry_lab.request_events(run_id, second_bucket);

create table retry_lab.circuit_state (
  run_id text primary key references retry_lab.scenario_runs(run_id) on delete cascade,
  state text not null check (state in ('CLOSED', 'OPEN', 'HALF_OPEN')),
  consecutive_failures integer not null default 0,
  opened_at timestamptz,
  next_probe_at timestamptz,
  probe_owner text,
  probe_lease_until timestamptz,
  token_bucket timestamptz not null,
  tokens_used integer not null default 0,
  next_dispatch_at timestamptz not null,
  updated_at timestamptz not null default clock_timestamp()
);

create table retry_lab.decision_events (
  id bigserial primary key,
  run_id text not null references retry_lab.scenario_runs(run_id) on delete cascade,
  client_id text not null,
  decided_at timestamptz not null default clock_timestamp(),
  action text not null,
  circuit_state text not null,
  reason text not null,
  response_status integer
);

create index decision_events_run_action_idx
  on retry_lab.decision_events(run_id, action);

create or replace function retry_lab.start_run(
  p_run_id text,
  p_strategy text,
  p_expected_clients integer default 30,
  p_outage_seconds integer default 8,
  p_capacity_rps integer default 5,
  p_overload_cooldown_ms integer default 1500,
  p_retry_budget_rps integer default 5
)
returns table (
  run_id text,
  strategy text,
  started_at timestamptz,
  outage_until timestamptz
)
language plpgsql
as $$
declare
  v_started_at timestamptz := clock_timestamp();
begin
  if p_strategy not in ('independent', 'bounded', 'global_budget') then
    raise exception 'unsupported strategy: %', p_strategy;
  end if;

  delete from retry_lab.scenario_runs where scenario_runs.run_id = p_run_id;

  insert into retry_lab.scenario_runs (
    run_id,
    strategy,
    started_at,
    outage_until,
    capacity_rps,
    overload_cooldown_ms,
    retry_budget_rps,
    expected_clients
  )
  values (
    p_run_id,
    p_strategy,
    v_started_at,
    v_started_at + make_interval(secs => p_outage_seconds),
    p_capacity_rps,
    p_overload_cooldown_ms,
    p_retry_budget_rps,
    p_expected_clients
  );

  insert into retry_lab.client_state (run_id, client_id)
  select p_run_id, 'client-' || lpad(client_number::text, 2, '0')
  from generate_series(1, p_expected_clients) as clients(client_number);

  insert into retry_lab.circuit_state (
    run_id,
    state,
    token_bucket,
    next_dispatch_at
  )
  values (
    p_run_id,
    'CLOSED',
    date_trunc('second', v_started_at),
    v_started_at
  );

  return query
  select
    scenario_runs.run_id,
    scenario_runs.strategy,
    scenario_runs.started_at,
    scenario_runs.outage_until
  from retry_lab.scenario_runs
  where scenario_runs.run_id = p_run_id;
end;
$$;

create or replace function retry_lab.provider_request(
  p_run_id text,
  p_client_id text
)
returns table (
  response_status integer,
  reason text,
  requested_at timestamptz
)
language plpgsql
as $$
declare
  v_run retry_lab.scenario_runs%rowtype;
  v_now timestamptz := clock_timestamp();
  v_bucket timestamptz := date_trunc('second', v_now);
  v_bucket_count integer;
  v_status integer;
  v_reason text;
begin
  select *
  into v_run
  from retry_lab.scenario_runs
  where scenario_runs.run_id = p_run_id
  for update;

  if not found then
    raise exception 'unknown run_id: %', p_run_id;
  end if;

  if v_now < v_run.outage_until then
    v_status := 503;
    v_reason := 'scheduled_outage';
  elsif v_run.overload_until is not null and v_now < v_run.overload_until then
    v_status := 503;
    v_reason := 'overload_cooldown';
  else
    select count(*)
    into v_bucket_count
    from retry_lab.request_events
    where request_events.run_id = p_run_id
      and request_events.second_bucket = v_bucket;

    if v_bucket_count >= v_run.capacity_rps then
      update retry_lab.scenario_runs
      set overload_until =
        v_now + (v_run.overload_cooldown_ms * interval '1 millisecond')
      where scenario_runs.run_id = p_run_id;

      v_status := 503;
      v_reason := 'capacity_exceeded';
    else
      v_status := 200;
      v_reason := 'accepted';
    end if;
  end if;

  insert into retry_lab.request_events (
    run_id,
    client_id,
    requested_at,
    second_bucket,
    response_status,
    reason
  )
  values (
    p_run_id,
    p_client_id,
    v_now,
    v_bucket,
    v_status,
    v_reason
  );

  return query select v_status, v_reason, v_now;
end;
$$;

create or replace function retry_lab.mark_client_complete(
  p_run_id text,
  p_client_id text
)
returns void
language sql
as $$
  update retry_lab.client_state
  set
    completed = true,
    attempt_count = (
      select count(*)
      from retry_lab.request_events
      where request_events.run_id = p_run_id
        and request_events.client_id = p_client_id
    ),
    last_status = 200,
    completed_at = clock_timestamp(),
    updated_at = clock_timestamp()
  where client_state.run_id = p_run_id
    and client_state.client_id = p_client_id;
$$;

create or replace function retry_lab.acquire_permission(
  p_run_id text,
  p_client_id text
)
returns table (
  action text,
  wait_ms integer,
  circuit_state text,
  reason text
)
language plpgsql
as $$
declare
  v_now timestamptz := clock_timestamp();
  v_bucket timestamptz := date_trunc('second', v_now);
  v_circuit retry_lab.circuit_state%rowtype;
  v_client retry_lab.client_state%rowtype;
  v_budget integer;
  v_action text;
  v_wait_ms integer := 0;
  v_reason text;
begin
  select *
  into v_client
  from retry_lab.client_state
  where client_state.run_id = p_run_id
    and client_state.client_id = p_client_id
  for update;

  if not found then
    raise exception 'unknown client % for run %', p_client_id, p_run_id;
  end if;

  select retry_budget_rps
  into v_budget
  from retry_lab.scenario_runs
  where scenario_runs.run_id = p_run_id;

  select *
  into v_circuit
  from retry_lab.circuit_state
  where circuit_state.run_id = p_run_id
  for update;

  if v_client.completed then
    v_action := 'COMPLETE';
    v_reason := 'client_already_completed';
  else
    if v_circuit.token_bucket < v_bucket then
      update retry_lab.circuit_state
      set
        token_bucket = v_bucket,
        tokens_used = 0,
        updated_at = v_now
      where circuit_state.run_id = p_run_id
      returning * into v_circuit;
    end if;

    if v_circuit.state = 'OPEN' then
      if v_circuit.next_probe_at is not null and v_now < v_circuit.next_probe_at then
        v_action := 'DEFER';
        v_wait_ms := greatest(
          100,
          floor(extract(epoch from (v_circuit.next_probe_at - v_now)) * 1000)::integer
        );
        v_reason := 'circuit_open';
      elsif v_circuit.tokens_used >= v_budget then
        v_action := 'DEFER';
        v_wait_ms := greatest(
          100,
          floor(extract(epoch from ((v_bucket + interval '1 second') - v_now)) * 1000)::integer
        );
        v_reason := 'retry_budget_exhausted';
      else
        update retry_lab.circuit_state
        set
          state = 'HALF_OPEN',
          probe_owner = p_client_id,
          probe_lease_until = v_now + interval '3 seconds',
          tokens_used = tokens_used + 1,
          updated_at = v_now
        where circuit_state.run_id = p_run_id
        returning * into v_circuit;

        v_action := 'PROBE';
        v_reason := 'half_open_probe_granted';
      end if;
    elsif v_circuit.state = 'HALF_OPEN' then
      if v_circuit.probe_owner = p_client_id
         and v_circuit.probe_lease_until > v_now then
        v_action := 'PROBE';
        v_reason := 'probe_owner_retry';
      elsif v_circuit.probe_lease_until <= v_now then
        update retry_lab.circuit_state
        set
          state = 'OPEN',
          next_probe_at = v_now,
          probe_owner = null,
          probe_lease_until = null,
          updated_at = v_now
        where circuit_state.run_id = p_run_id
        returning * into v_circuit;

        v_action := 'DEFER';
        v_wait_ms := 100;
        v_reason := 'expired_probe_lease';
      else
        v_action := 'DEFER';
        v_wait_ms := greatest(
          100,
          floor(extract(epoch from (v_circuit.probe_lease_until - v_now)) * 1000)::integer
        );
        v_reason := 'probe_in_flight';
      end if;
    elsif v_circuit.tokens_used >= v_budget then
      v_action := 'DEFER';
      v_wait_ms := greatest(
        100,
        floor(extract(epoch from ((v_bucket + interval '1 second') - v_now)) * 1000)::integer
      );
      v_reason := 'retry_budget_exhausted';
    else
      update retry_lab.circuit_state
      set
        tokens_used = tokens_used + 1,
        updated_at = v_now
      where circuit_state.run_id = p_run_id
      returning * into v_circuit;

      v_action := 'CALL';
      v_reason := 'closed_circuit_budget_granted';
    end if;
  end if;

  insert into retry_lab.decision_events (
    run_id,
    client_id,
    action,
    circuit_state,
    reason
  )
  values (
    p_run_id,
    p_client_id,
    v_action,
    v_circuit.state,
    v_reason
  );

  return query select v_action, v_wait_ms, v_circuit.state, v_reason;
end;
$$;

create or replace function retry_lab.record_result(
  p_run_id text,
  p_client_id text,
  p_response_status integer
)
returns table (
  completed boolean,
  circuit_state text,
  consecutive_failures integer
)
language plpgsql
as $$
declare
  v_now timestamptz := clock_timestamp();
  v_circuit retry_lab.circuit_state%rowtype;
  v_completed boolean;
  v_action text;
  v_reason text;
begin
  select *
  into v_circuit
  from retry_lab.circuit_state
  where circuit_state.run_id = p_run_id
  for update;

  update retry_lab.client_state
  set
    attempt_count = attempt_count + 1,
    last_status = p_response_status,
    completed = p_response_status between 200 and 299,
    completed_at = case
      when p_response_status between 200 and 299 then v_now
      else completed_at
    end,
    updated_at = v_now
  where client_state.run_id = p_run_id
    and client_state.client_id = p_client_id
  returning client_state.completed into v_completed;

  if p_response_status between 200 and 299 then
    update retry_lab.circuit_state
    set
      state = 'CLOSED',
      consecutive_failures = 0,
      opened_at = null,
      next_probe_at = null,
      probe_owner = null,
      probe_lease_until = null,
      updated_at = v_now
    where circuit_state.run_id = p_run_id
    returning * into v_circuit;

    v_action := 'RESULT_SUCCESS';
    v_reason := 'downstream_call_succeeded';
  elsif v_circuit.state = 'HALF_OPEN'
        and v_circuit.probe_owner = p_client_id then
    update retry_lab.circuit_state as current_circuit
    set
      state = 'OPEN',
      consecutive_failures = current_circuit.consecutive_failures + 1,
      opened_at = v_now,
      next_probe_at = v_now + interval '3 seconds',
      probe_owner = null,
      probe_lease_until = null,
      updated_at = v_now
    where current_circuit.run_id = p_run_id
    returning * into v_circuit;

    v_action := 'CIRCUIT_REOPENED';
    v_reason := 'half_open_probe_failed';
  elsif v_circuit.state = 'OPEN' then
    v_action := 'RESULT_FAILURE';
    v_reason := 'in_flight_failure_after_open';
  else
    update retry_lab.circuit_state as current_circuit
    set
      consecutive_failures = current_circuit.consecutive_failures + 1,
      state = case
        when current_circuit.consecutive_failures + 1 >= 3 then 'OPEN'
        else current_circuit.state
      end,
      opened_at = case
        when current_circuit.consecutive_failures + 1 >= 3 then v_now
        else current_circuit.opened_at
      end,
      next_probe_at = case
        when current_circuit.consecutive_failures + 1 >= 3 then v_now + interval '3 seconds'
        else current_circuit.next_probe_at
      end,
      updated_at = v_now
    where current_circuit.run_id = p_run_id
    returning * into v_circuit;

    v_action := case
      when v_circuit.state = 'OPEN' then 'CIRCUIT_OPENED'
      else 'RESULT_FAILURE'
    end;
    v_reason := case
      when v_circuit.state = 'OPEN' then 'failure_threshold_reached'
      else 'downstream_call_failed'
    end;
  end if;

  insert into retry_lab.decision_events (
    run_id,
    client_id,
    action,
    circuit_state,
    reason,
    response_status
  )
  values (
    p_run_id,
    p_client_id,
    v_action,
    v_circuit.state,
    v_reason,
    p_response_status
  );

  return query
  select v_completed, v_circuit.state, v_circuit.consecutive_failures;
end;
$$;

create or replace function retry_lab.client_completed(
  p_run_id text,
  p_client_id text
)
returns table (completed boolean)
language sql
stable
as $$
  select client_state.completed
  from retry_lab.client_state
  where client_state.run_id = p_run_id
    and client_state.client_id = p_client_id;
$$;

create or replace function retry_lab.reserve_dispatch_slot(p_run_id text)
returns table (
  dispatch_at timestamptz,
  wait_ms integer
)
language plpgsql
as $$
declare
  v_now timestamptz := clock_timestamp();
  v_dispatch_at timestamptz;
  v_next_dispatch_at timestamptz;
  v_retry_budget_rps integer;
  v_wait_ms integer;
begin
  select scenario_runs.retry_budget_rps
  into v_retry_budget_rps
  from retry_lab.scenario_runs
  where scenario_runs.run_id = p_run_id;

  if not found then
    raise exception 'unknown run_id: %', p_run_id;
  end if;

  select circuit_state.next_dispatch_at
  into v_next_dispatch_at
  from retry_lab.circuit_state
  where circuit_state.run_id = p_run_id
  for update;

  v_dispatch_at := greatest(v_now, v_next_dispatch_at);
  v_wait_ms := greatest(
    0,
    ceil(extract(epoch from (v_dispatch_at - v_now)) * 1000)::integer
  );

  update retry_lab.circuit_state
  set
    next_dispatch_at =
      v_dispatch_at
      + ((1000.0 / v_retry_budget_rps) * interval '1 millisecond'),
    updated_at = v_now
  where circuit_state.run_id = p_run_id;

  return query select v_dispatch_at, v_wait_ms;
end;
$$;

create or replace function retry_lab.metrics(p_run_id text)
returns table (
  run_id text,
  strategy text,
  expected_clients integer,
  completed_clients bigint,
  total_requests bigint,
  successful_requests bigint,
  failed_requests bigint,
  scheduled_outage_requests bigint,
  capacity_exceeded_requests bigint,
  overload_cooldown_requests bigint,
  peak_requests_per_second bigint,
  retry_amplification numeric,
  run_duration_ms bigint,
  recovery_delay_ms bigint,
  circuit_open_events bigint,
  probe_calls bigint,
  deferred_attempts bigint
)
language sql
stable
as $$
  with selected_run as (
    select *
    from retry_lab.scenario_runs
    where scenario_runs.run_id = p_run_id
  ),
  request_summary as (
    select
      count(*) as total_requests,
      count(*) filter (where response_status between 200 and 299) as successful_requests,
      count(*) filter (where response_status >= 400) as failed_requests,
      count(*) filter (where reason = 'scheduled_outage') as scheduled_outage_requests,
      count(*) filter (where reason = 'capacity_exceeded') as capacity_exceeded_requests,
      count(*) filter (where reason = 'overload_cooldown') as overload_cooldown_requests
    from retry_lab.request_events
    where request_events.run_id = p_run_id
  ),
  peak as (
    select coalesce(max(bucket_count), 0) as peak_requests_per_second
    from (
      select count(*) as bucket_count
      from retry_lab.request_events
      where request_events.run_id = p_run_id
      group by second_bucket
    ) per_second
  ),
  clients as (
    select
      count(*) filter (where completed) as completed_clients,
      max(completed_at) as finished_at
    from retry_lab.client_state
    where client_state.run_id = p_run_id
  ),
  decisions as (
    select
      count(*) filter (
        where action in ('CIRCUIT_OPENED', 'CIRCUIT_REOPENED')
      ) as circuit_open_events,
      count(*) filter (where action = 'PROBE') as probe_calls,
      count(*) filter (where action = 'DEFER') as deferred_attempts
    from retry_lab.decision_events
    where decision_events.run_id = p_run_id
  )
  select
    selected_run.run_id,
    selected_run.strategy,
    selected_run.expected_clients,
    clients.completed_clients,
    request_summary.total_requests,
    request_summary.successful_requests,
    request_summary.failed_requests,
    request_summary.scheduled_outage_requests,
    request_summary.capacity_exceeded_requests,
    request_summary.overload_cooldown_requests,
    peak.peak_requests_per_second,
    round(
      request_summary.total_requests::numeric / selected_run.expected_clients,
      2
    ) as retry_amplification,
    coalesce(
      floor(extract(epoch from (clients.finished_at - selected_run.started_at)) * 1000)::bigint,
      0
    ) as run_duration_ms,
    coalesce(
      floor(extract(epoch from (clients.finished_at - selected_run.outage_until)) * 1000)::bigint,
      0
    ) as recovery_delay_ms,
    decisions.circuit_open_events,
    decisions.probe_calls,
    decisions.deferred_attempts
  from selected_run
  cross join request_summary
  cross join peak
  cross join clients
  cross join decisions;
$$;
