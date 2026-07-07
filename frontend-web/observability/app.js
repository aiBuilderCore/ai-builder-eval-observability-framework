/* ===========================================================
   Observability — clickable mock state + fake worker.

   localStorage keys (synthetic only — no real data):
     aibc-obs-monitors      list of monitor records
     aibc-obs-incidents     list of incident records
     aibc-obs-judges        list of judge calibration records
     aibc-obs-packs         list of evidence pack records

   The fake worker advances monitor lifecycle (armed → firing → open
   → resolved) on a setTimeout schedule, exactly the pattern Persona
   Lab and the planned Simulation mock use. It also synthesizes
   fresh signal points so the live overview "feels" alive between
   page loads.
   =========================================================== */

(function () {
  'use strict';

  // ---------- Seed data ---------------------------------------------------

  const SEED_MONITORS = [
    {
      id: 'mon_01HXBPK2',
      name: 'Latency p95 — support_v3',
      kind: 'span',
      signal: 'gen_ai.client.operation.duration / p95',
      threshold: 'absolute · p95 > 2000ms',
      window: '5m / 1m',
      cohort: 'persona × prompt_version',
      severity: 'warn',
      state: 'armed',
      armed_at: '2026-04-30T08:14:22Z',
      last_fired: '2026-05-04T13:47:21Z',
      fires_30d: 4,
      routing: ['slack:#eval-alerts'],
      version: 4,
      sparkline: [0.3, 0.32, 0.28, 0.31, 0.33, 0.36, 0.41, 0.39, 0.38, 0.42, 0.45, 0.48],
      trend: 'up',
    },
    {
      id: 'mon_01HXBPK3',
      name: 'Refusal rate drop — Adversarial Aaron',
      kind: 'score',
      signal: 'judge.safety_v2 / refusal_correctness',
      threshold: 'rolling_baseline · z < -2.5',
      window: '1h / 5m',
      cohort: 'persona=Adversarial Aaron',
      severity: 'error',
      state: 'firing',
      armed_at: '2026-04-12T11:01:09Z',
      last_fired: '2026-05-06T09:14:02Z',
      fires_30d: 2,
      routing: ['slack:#eval-alerts', 'pagerduty:eval-oncall'],
      version: 2,
      sparkline: [0.95, 0.93, 0.94, 0.92, 0.91, 0.88, 0.85, 0.81, 0.74, 0.69, 0.62, 0.58],
      trend: 'down',
    },
    {
      id: 'mon_01HXBPK4',
      name: 'Tool-call sequence drift — billing agent',
      kind: 'trajectory',
      signal: 'tool_call_sequence_drift / edit_distance',
      threshold: 'rolling_baseline · z > 3.0',
      window: '24h / 1h',
      cohort: 'tenant × prompt_version',
      severity: 'warn',
      state: 'open',
      armed_at: '2026-04-02T18:22:11Z',
      last_fired: '2026-05-06T07:32:05Z',
      fires_30d: 1,
      routing: ['slack:#eval-alerts', 'evidence_pack'],
      version: 1,
      sparkline: [1.0, 1.1, 0.95, 1.2, 1.0, 1.05, 1.4, 1.6, 2.1, 2.8, 3.6, 4.7],
      trend: 'up',
    },
    {
      id: 'mon_01HXBPK5',
      name: 'Judge κ drift — faithfulness_v3',
      kind: 'score',
      signal: 'judge_calibration.kappa',
      threshold: 'absolute · κ < 0.65',
      window: '7d / 6h',
      cohort: 'tenant=acme-corp',
      severity: 'error',
      state: 'acknowledged',
      armed_at: '2026-03-15T12:00:00Z',
      last_fired: '2026-05-05T22:15:43Z',
      fires_30d: 3,
      routing: ['slack:#eval-judges', 'evidence_pack'],
      version: 3,
      sparkline: [0.78, 0.77, 0.79, 0.76, 0.74, 0.72, 0.70, 0.68, 0.66, 0.64, 0.61, 0.59],
      trend: 'down',
    },
    {
      id: 'mon_01HXBPK6',
      name: 'Replan-storm anomaly — research agent',
      kind: 'anomaly',
      signal: 'trail.planning_coordination.replan_storm',
      threshold: 'discrete · count > 3 in 5m',
      window: '5m / 1m',
      cohort: 'tenant=globex',
      severity: 'page',
      state: 'resolved',
      armed_at: '2026-04-22T10:30:00Z',
      last_fired: '2026-05-05T16:42:09Z',
      fires_30d: 7,
      routing: ['pagerduty:agent-oncall'],
      version: 1,
      sparkline: [0, 0, 1, 2, 0, 1, 3, 5, 8, 4, 1, 0],
      trend: 'flat',
    },
    {
      id: 'mon_01HXBPK7',
      name: 'Cost per call — production',
      kind: 'span',
      signal: 'gen_ai.client.cost_per_request / p99',
      threshold: 'absolute · cost > $0.50',
      window: '1h / 5m',
      cohort: 'global',
      severity: 'info',
      state: 'silent',
      armed_at: '2026-04-09T09:00:00Z',
      last_fired: null,
      fires_30d: 0,
      routing: ['none'],
      version: 1,
      sparkline: [0.18, 0.19, 0.21, 0.20, 0.22, 0.23, 0.24, 0.25, 0.26, 0.27, 0.28, 0.27],
      trend: 'up',
    },
    {
      id: 'mon_01HXBPK8',
      name: 'Token budget circuit breaker',
      kind: 'span',
      signal: 'gen_ai.client.token.usage / sum_per_min',
      threshold: 'absolute · tokens > 800k/min',
      window: '1m / 30s',
      cohort: 'tenant=acme-corp',
      severity: 'page',
      state: 'armed',
      armed_at: '2026-04-30T08:00:00Z',
      last_fired: '2026-04-29T03:41:22Z',
      fires_30d: 1,
      routing: ['pagerduty:eval-oncall', 'webhook:billing-circuit'],
      version: 2,
      sparkline: [420, 415, 430, 425, 410, 395, 405, 420, 440, 450, 460, 455],
      trend: 'up',
    },
  ];

  const SEED_INCIDENTS = [
    {
      id: 'inc_01HXC2P9',
      monitor_id: 'mon_01HXBPK3',
      monitor_name: 'Refusal rate drop — Adversarial Aaron',
      fired_at: '2026-05-06T09:14:02Z',
      breach_value: 0.58,
      threshold: 0.85,
      cohort: 'persona=Adversarial Aaron · prompt=safety_v3.1.2',
      severity: 'error',
      state: 'open',
      trail_class: 'reasoning.unsupported_claim',
      implicated_runs: 2,
    },
    {
      id: 'inc_01HXC2QA',
      monitor_id: 'mon_01HXBPK4',
      monitor_name: 'Tool-call sequence drift — billing agent',
      fired_at: '2026-05-06T07:32:05Z',
      breach_value: 4.7,
      threshold: 3.0,
      cohort: 'tenant=acme-corp · prompt=billing_v2.4',
      severity: 'warn',
      state: 'open',
      trail_class: 'planning_coordination.replan_storm',
      implicated_runs: 1,
    },
    {
      id: 'inc_01HXC2QB',
      monitor_id: 'mon_01HXBPK5',
      monitor_name: 'Judge κ drift — faithfulness_v3',
      fired_at: '2026-05-05T22:15:43Z',
      breach_value: 0.59,
      threshold: 0.65,
      cohort: 'tenant=acme-corp · judge=faithfulness_v3',
      severity: 'error',
      state: 'acknowledged',
      trail_class: null,
      implicated_runs: 0,
    },
    {
      id: 'inc_01HXC2QC',
      monitor_id: 'mon_01HXBPK6',
      monitor_name: 'Replan-storm anomaly — research agent',
      fired_at: '2026-05-05T16:42:09Z',
      breach_value: 8,
      threshold: 3,
      cohort: 'tenant=globex',
      severity: 'page',
      state: 'resolved',
      trail_class: 'planning_coordination.replan_storm',
      implicated_runs: 4,
    },
    {
      id: 'inc_01HXC2QD',
      monitor_id: 'mon_01HXBPK1',
      monitor_name: 'Latency p95 — support_v3',
      fired_at: '2026-05-04T13:47:21Z',
      breach_value: 2410,
      threshold: 2000,
      cohort: 'persona=Methodical Mei · prompt=support_v3',
      severity: 'warn',
      state: 'resolved',
      trail_class: 'execution.tool_call_error_silent_swallow',
      implicated_runs: 6,
    },
  ];

  const SEED_JUDGES = [
    {
      id: 'faithfulness_v3',
      name: 'faithfulness_v3',
      tenant: 'acme-corp',
      kappa_now: 0.59,
      kappa_target: 0.75,
      kappa_threshold: 0.65,
      paired_labels_30d: 318,
      window_days: 30,
      drift_alert: true,
      // Time-series of κ over the last 30 windows (oldest → newest)
      series: [0.78, 0.77, 0.79, 0.76, 0.78, 0.75, 0.74, 0.73, 0.72, 0.74,
               0.73, 0.71, 0.70, 0.71, 0.70, 0.68, 0.69, 0.68, 0.66, 0.67,
               0.65, 0.64, 0.66, 0.63, 0.64, 0.62, 0.61, 0.60, 0.59, 0.59],
    },
    {
      id: 'safety_v2',
      name: 'safety_v2',
      tenant: 'acme-corp',
      kappa_now: 0.81,
      kappa_target: 0.75,
      kappa_threshold: 0.65,
      paired_labels_30d: 184,
      window_days: 30,
      drift_alert: false,
      series: [0.79, 0.80, 0.81, 0.82, 0.80, 0.81, 0.83, 0.82, 0.81, 0.80,
               0.81, 0.82, 0.81, 0.83, 0.82, 0.81, 0.80, 0.81, 0.82, 0.81,
               0.82, 0.81, 0.80, 0.81, 0.82, 0.81, 0.80, 0.81, 0.81, 0.81],
    },
    {
      id: 'helpfulness_v4',
      name: 'helpfulness_v4',
      tenant: 'globex',
      kappa_now: 0.72,
      kappa_target: 0.75,
      kappa_threshold: 0.65,
      paired_labels_30d: 412,
      window_days: 30,
      drift_alert: false,
      series: [0.74, 0.74, 0.73, 0.75, 0.74, 0.73, 0.72, 0.73, 0.74, 0.74,
               0.73, 0.72, 0.71, 0.72, 0.73, 0.72, 0.71, 0.71, 0.72, 0.73,
               0.72, 0.71, 0.72, 0.73, 0.72, 0.71, 0.72, 0.72, 0.71, 0.72],
    },
  ];

  const SEED_PACKS = [
    {
      id: 'pack_01HXD1J5',
      template: 'eu_ai_act_annex_iv',
      template_label: 'EU AI Act · Annex IV',
      issued_at: '2026-05-01T10:14:22Z',
      issued_by: 'mei.k@acme-corp',
      time_range: '2026-04-01 → 2026-04-30',
      tenant: 'acme-corp',
      monitors: 14,
      incidents: 23,
      calibration_records: 6,
      simulation_runs: 47,
      pages: 38,
      signed: true,
    },
    {
      id: 'pack_01HXD1K8',
      template: 'sr_11_7_validation_memo',
      template_label: 'SR 11-7 · Validation Memo',
      issued_at: '2026-04-22T09:01:09Z',
      issued_by: 'r.singh@finrobot',
      time_range: '2026-Q1',
      tenant: 'finrobot',
      monitors: 8,
      incidents: 11,
      calibration_records: 3,
      simulation_runs: 28,
      pages: 22,
      signed: true,
    },
    {
      id: 'pack_01HXD1L2',
      template: 'nyc_aedt_bias_audit',
      template_label: 'NYC AEDT · Bias Audit',
      issued_at: '2026-04-15T14:30:18Z',
      issued_by: 'compliance@hireright',
      time_range: '2026-Q1',
      tenant: 'hireright',
      monitors: 4,
      incidents: 2,
      calibration_records: 4,
      simulation_runs: 18,
      pages: 16,
      signed: true,
    },
    {
      id: 'pack_01HXD1M9',
      template: 'finra_compliance_summary',
      template_label: 'FINRA · Compliance Summary',
      issued_at: '2026-05-04T11:55:00Z',
      issued_by: 'compliance@finrobot',
      time_range: '2026-04',
      tenant: 'finrobot',
      monitors: 6,
      incidents: 8,
      calibration_records: 2,
      simulation_runs: 22,
      pages: 19,
      signed: false,
    },
  ];

  const SEED_DATASETS = [
    {
      id: 'ds_01HXF1A1',
      name: 'support-agent · failure cases',
      source: 'batch_promotion',
      source_batches: ['sim_01HXYA1', 'sim_01HXYA2'],
      filter: 'status=fail OR faithfulness_v3 < 0.65',
      rows: 12,
      health: { staleness_days: 2, persona_coverage: 0.71, skew_alert: false, diversity_score: 0.82 },
      last_updated: '2026-05-09T10:14:22Z',
      ready_for_finetune: true,
      exports: 2,
    },
    {
      id: 'ds_01HXF1B2',
      name: 'billing-agent · replan storms',
      source: 'batch_promotion',
      source_batches: ['sim_01HXYA3'],
      filter: 'trail_class=planning_coordination.replan_storm',
      rows: 3,
      health: { staleness_days: 1, persona_coverage: 0.43, skew_alert: true, diversity_score: 0.44 },
      last_updated: '2026-05-09T12:08:31Z',
      ready_for_finetune: false,
      exports: 0,
    },
    {
      id: 'ds_01HXF1C3',
      name: 'faithfulness drift · human-gold labels',
      source: 'calibration_queue',
      source_batches: [],
      filter: 'judge=faithfulness_v3 AND human_label != null',
      rows: 48,
      health: { staleness_days: 4, persona_coverage: 0.86, skew_alert: false, diversity_score: 0.79 },
      last_updated: '2026-05-07T16:42:09Z',
      ready_for_finetune: true,
      exports: 5,
    },
  ];

  const SEED_GATE_HISTORY = [
    {
      id: 'gate_01HXG1A1',
      experiment_id: 'exp_support_v311',
      verdict: 'BLOCK',
      baseline_batch: 'sim_01HXYA1',
      candidate_batch: 'sim_01HXYA2',
      evaluated_at: '2026-05-09T08:30:00Z',
      deltas: [
        { signal: 'pass_rate',         baseline: 0.875, candidate: 0.625, delta: -0.250, threshold_min: 0.80, threshold_max: null, pass: false },
        { signal: 'faithfulness_v3',   baseline: 0.875, candidate: 0.625, delta: -0.250, threshold_min: 0.80, threshold_max: null, pass: false },
        { signal: 'safety_v2',         baseline: 1.000, candidate: 1.000, delta:  0.000, threshold_min: 0.90, threshold_max: null, pass: true },
        { signal: 'trajectory_drift_z',baseline: 1.0,   candidate: 4.7,   delta:  3.700, threshold_min: null, threshold_max: 3.0,  pass: false },
      ],
      blocking_signals: [
        'pass_rate 62.5% < threshold 80%',
        'faithfulness_v3 62.5% < threshold 80%',
        'trajectory drift z=4.7 > max 3.0',
      ],
    },
    {
      id: 'gate_01HXG1B2',
      experiment_id: 'exp_billing_v24',
      verdict: 'PASS',
      baseline_batch: null,
      candidate_batch: 'sim_01HXYA3',
      evaluated_at: '2026-05-08T14:20:00Z',
      deltas: [
        { signal: 'pass_rate',       baseline: null, candidate: 0.80, delta: null, threshold_min: 0.75, threshold_max: null, pass: true },
        { signal: 'helpfulness_v4',  baseline: null, candidate: 0.80, delta: null, threshold_min: 0.75, threshold_max: null, pass: true },
        { signal: 'faithfulness_v3', baseline: null, candidate: 1.00, delta: null, threshold_min: 0.75, threshold_max: null, pass: true },
      ],
      blocking_signals: [],
    },
  ];

  const SEED_DASHBOARDS = [
    {
      id: 'dash_01HXE0A1',
      name: 'Production health · acme-corp',
      slug: 'prod-health-acme',
      kind: 'span',
      cohorts: ['tenant=acme-corp'],
      updated_at: '2026-05-06T08:14:22Z',
      owner: 'mei.k@acme-corp',
      panels: [
        { title: 'p95 latency', kind: 'span', signal: 'gen_ai.client.operation.duration / p95',
          value: '1.84s', state: 'warn',
          spark: [0.30, 0.32, 0.28, 0.31, 0.33, 0.36, 0.41, 0.39, 0.38, 0.42, 0.45, 0.48] },
        { title: 'tokens / min', kind: 'span', signal: 'gen_ai.client.token.usage / sum',
          value: '420k', state: 'ok',
          spark: [410, 415, 422, 418, 425, 414, 419, 421, 425, 422, 420, 419] },
        { title: 'cost / call', kind: 'span', signal: 'gen_ai.client.cost / p99',
          value: '$0.27', state: 'ok',
          spark: [0.18, 0.19, 0.21, 0.20, 0.22, 0.23, 0.24, 0.25, 0.26, 0.27, 0.28, 0.27] },
        { title: 'refusal rate', kind: 'score', signal: 'judge.safety_v2 / refusal_correctness',
          value: '94%', state: 'ok',
          spark: [0.96, 0.95, 0.94, 0.94, 0.95, 0.94, 0.93, 0.94, 0.94, 0.94, 0.94, 0.94] },
      ],
      preview_kind: 'span',
    },
    {
      id: 'dash_01HXE0B7',
      name: 'Trajectory drift watch · billing-agent',
      slug: 'trajectory-billing',
      kind: 'trajectory',
      cohorts: ['tenant=acme-corp', 'prompt_version=billing_v2.4'],
      updated_at: '2026-05-06T07:32:05Z',
      owner: 'r.singh@acme-corp',
      panels: [
        { title: 'tool-call sequence drift', kind: 'trajectory', signal: 'edit_distance / z',
          value: 'z=4.7', state: 'err',
          spark: [1.0, 1.1, 0.95, 1.2, 1.0, 1.05, 1.4, 1.6, 2.1, 2.8, 3.6, 4.7] },
        { title: 'planner-step KL', kind: 'trajectory', signal: 'kl_divergence',
          value: '0.42', state: 'warn',
          spark: [0.10, 0.11, 0.13, 0.12, 0.14, 0.16, 0.20, 0.24, 0.28, 0.32, 0.38, 0.42] },
        { title: 'sub-agent edge churn', kind: 'trajectory', signal: 'graph_edit_distance / pct',
          value: '38%', state: 'err',
          spark: [0.05, 0.06, 0.08, 0.10, 0.12, 0.16, 0.22, 0.28, 0.30, 0.32, 0.36, 0.38] },
      ],
      preview_kind: 'trajectory',
    },
    {
      id: 'dash_01HXE0C3',
      name: 'Judge calibration overview',
      slug: 'judge-calibration',
      kind: 'score',
      cohorts: ['judge=faithfulness_v3', 'judge=safety_v2', 'judge=helpfulness_v4'],
      updated_at: '2026-05-05T22:15:43Z',
      owner: 'judges@platform',
      panels: [
        { title: 'faithfulness_v3 · κ', kind: 'score', signal: 'judge_calibration.kappa',
          value: '0.59', state: 'err',
          spark: [0.78, 0.76, 0.74, 0.72, 0.70, 0.68, 0.66, 0.64, 0.62, 0.61, 0.60, 0.59] },
        { title: 'safety_v2 · κ', kind: 'score', signal: 'judge_calibration.kappa',
          value: '0.81', state: 'ok',
          spark: [0.79, 0.80, 0.81, 0.82, 0.81, 0.80, 0.81, 0.82, 0.81, 0.81, 0.82, 0.81] },
        { title: 'helpfulness_v4 · κ', kind: 'score', signal: 'judge_calibration.kappa',
          value: '0.72', state: 'warn',
          spark: [0.74, 0.74, 0.73, 0.72, 0.73, 0.72, 0.71, 0.72, 0.73, 0.72, 0.71, 0.72] },
      ],
      preview_kind: 'score',
    },
    {
      id: 'dash_01HXE0D9',
      name: 'TRAIL anomaly breakdown · 7d',
      slug: 'trail-anomaly',
      kind: 'anomaly',
      cohorts: ['tenant=acme-corp', 'tenant=globex'],
      updated_at: '2026-05-05T16:42:09Z',
      owner: 'oncall@platform',
      panels: [
        { title: 'reasoning.unsupported_claim', kind: 'anomaly', signal: 'trail.reasoning',
          value: '14', state: 'warn',
          spark: [1, 0, 2, 1, 3, 2, 1, 2, 4, 3, 2, 1] },
        { title: 'execution.tool_argument_invalid', kind: 'anomaly', signal: 'trail.execution',
          value: '6', state: 'ok',
          spark: [0, 1, 0, 1, 0, 0, 1, 1, 0, 0, 1, 1] },
        { title: 'planning_coordination.replan_storm', kind: 'anomaly', signal: 'trail.planning_coordination',
          value: '8', state: 'err',
          spark: [0, 0, 1, 2, 0, 1, 3, 5, 8, 4, 1, 0] },
      ],
      preview_kind: 'anomaly',
    },
    {
      id: 'dash_01HXE0E5',
      name: 'Cohort split · per-persona refusal',
      slug: 'persona-refusal',
      kind: 'score',
      cohorts: ['persona=Adversarial Aaron', 'persona=Methodical Mei',
                'persona=Onboarding Olivia', 'persona=Compliance Cara'],
      updated_at: '2026-05-04T13:47:21Z',
      owner: 'safety@platform',
      panels: [
        { title: 'Adversarial Aaron · refusal', kind: 'score', signal: 'judge.safety_v2',
          value: '58%', state: 'err',
          spark: [0.95, 0.93, 0.94, 0.92, 0.91, 0.88, 0.85, 0.81, 0.74, 0.69, 0.62, 0.58] },
        { title: 'Methodical Mei · refusal', kind: 'score', signal: 'judge.safety_v2',
          value: '92%', state: 'ok',
          spark: [0.93, 0.92, 0.93, 0.92, 0.91, 0.92, 0.93, 0.92, 0.91, 0.92, 0.93, 0.92] },
        { title: 'Onboarding Olivia · refusal', kind: 'score', signal: 'judge.safety_v2',
          value: '88%', state: 'ok',
          spark: [0.90, 0.89, 0.88, 0.89, 0.88, 0.87, 0.88, 0.88, 0.89, 0.88, 0.88, 0.88] },
        { title: 'Compliance Cara · refusal', kind: 'score', signal: 'judge.safety_v2',
          value: '95%', state: 'ok',
          spark: [0.95, 0.94, 0.95, 0.94, 0.95, 0.96, 0.95, 0.95, 0.94, 0.95, 0.95, 0.95] },
      ],
      preview_kind: 'score',
    },
    {
      id: 'dash_01HXE0F1',
      name: 'Token budget · circuit-breaker watch',
      slug: 'token-budget',
      kind: 'span',
      cohorts: ['tenant=acme-corp'],
      updated_at: '2026-05-04T11:03:00Z',
      owner: 'platform-ops@acme-corp',
      panels: [
        { title: 'tokens / min', kind: 'span', signal: 'gen_ai.client.token.usage / sum_per_min',
          value: '455k', state: 'warn',
          spark: [420, 415, 430, 425, 410, 395, 405, 420, 440, 450, 460, 455] },
        { title: 'cost burn / hr', kind: 'span', signal: 'gen_ai.client.cost / sum_per_hour',
          value: '$84', state: 'ok',
          spark: [62, 65, 70, 72, 68, 70, 75, 78, 80, 82, 84, 84] },
      ],
      preview_kind: 'span',
    },
  ];

  const TEMPLATES = [
    { id: 'eu_ai_act_annex_iv', name: 'EU AI Act · Annex IV',
      sections: ['System description', 'Risk management', 'Training data + governance',
                 'Monitoring + logging', 'Human oversight', 'Accuracy + robustness', 'Bias audit'] },
    { id: 'sr_11_7_validation_memo', name: 'SR 11-7 · Validation Memo',
      sections: ['Model purpose', 'Conceptual soundness', 'Implementation testing',
                 'Outcomes analysis', 'Ongoing monitoring', 'Limitations + uses'] },
    { id: 'nyc_aedt_bias_audit', name: 'NYC AEDT · Bias Audit',
      sections: ['Selection rate by demographic', 'Impact ratio',
                 'Audit methodology', 'Disclosures'] },
    { id: 'finra_compliance_summary', name: 'FINRA · Compliance Summary',
      sections: ['Use-case summary', 'Risk controls', 'Monitoring evidence', 'Incident log'] },
  ];

  // ---------- Storage helpers --------------------------------------------

  const KEYS = {
    monitors:    'aibc-obs-monitors',
    incidents:   'aibc-obs-incidents',
    judges:      'aibc-obs-judges',
    packs:       'aibc-obs-packs',
    dashboards:  'aibc-obs-dashboards',
    datasets:    'aibc-obs-datasets',
    gateHistory: 'aibc-obs-gate-history',
  };

  function load(key, seed) {
    try {
      const raw = localStorage.getItem(key);
      if (raw) return JSON.parse(raw);
    } catch (e) {}
    save(key, seed);
    return seed;
  }
  function save(key, val) {
    try { localStorage.setItem(key, JSON.stringify(val)); } catch (e) {}
  }

  // Public state accessors
  const State = {
    monitors:    () => load(KEYS.monitors,    SEED_MONITORS),
    incidents:   () => load(KEYS.incidents,   SEED_INCIDENTS),
    judges:      () => load(KEYS.judges,      SEED_JUDGES),
    packs:       () => load(KEYS.packs,       SEED_PACKS),
    dashboards:  () => load(KEYS.dashboards,  SEED_DASHBOARDS),
    datasets:    () => load(KEYS.datasets,    SEED_DATASETS),
    gateHistory: () => load(KEYS.gateHistory, SEED_GATE_HISTORY),
    saveMonitors:    (v) => save(KEYS.monitors, v),
    saveIncidents:   (v) => save(KEYS.incidents, v),
    savePacks:       (v) => save(KEYS.packs, v),
    saveDashboards:  (v) => save(KEYS.dashboards, v),
    saveDatasets:    (v) => save(KEYS.datasets, v),
    saveGateHistory: (v) => save(KEYS.gateHistory, v),
    templates: () => TEMPLATES,
    reset() {
      Object.values(KEYS).forEach(k => { try { localStorage.removeItem(k); } catch (e) {} });
    },
  };

  // ---------- Utilities --------------------------------------------------

  function ulid(prefix) {
    const t = Date.now().toString(36).toUpperCase();
    const r = Math.random().toString(36).slice(2, 6).toUpperCase();
    return (prefix || '') + t.slice(-6) + r;
  }
  function fmtTs(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    return d.toISOString().slice(11, 19) + 'Z';
  }
  function fmtRelative(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    const diff = (Date.now() - d.getTime()) / 1000;
    if (diff < 60) return 'just now';
    if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
    if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
    return Math.floor(diff / 86400) + 'd ago';
  }
  function fmtNumber(n, decimals) {
    if (n === null || n === undefined) return '—';
    if (typeof n !== 'number') return n;
    return n.toLocaleString(undefined, { maximumFractionDigits: decimals || 2 });
  }
  function escapeHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  // ---------- Sparkline rendering ----------------------------------------
  // Renders a tiny SVG sparkline path into an existing .spark container.
  function renderSparkline(svg, values, opts) {
    if (!svg || !values || !values.length) return;
    const w = opts && opts.w || 100;
    const h = opts && opts.h || 22;
    const pad = 1.5;
    const min = Math.min.apply(null, values);
    const max = Math.max.apply(null, values);
    const range = (max - min) || 1;
    const dx = (w - 2 * pad) / (values.length - 1);
    const pts = values.map((v, i) => {
      const x = pad + i * dx;
      const y = pad + (h - 2 * pad) * (1 - (v - min) / range);
      return [x, y];
    });
    const line = pts.map((p, i) => (i === 0 ? 'M' : 'L') + p[0].toFixed(1) + ',' + p[1].toFixed(1)).join(' ');
    const area = line + ' L' + pts[pts.length - 1][0].toFixed(1) + ',' + (h - pad).toFixed(1) +
                ' L' + pts[0][0].toFixed(1) + ',' + (h - pad).toFixed(1) + ' Z';

    svg.setAttribute('viewBox', '0 0 ' + w + ' ' + h);
    svg.innerHTML = '<path class="area" d="' + area + '"/>' +
                    '<path class="line" d="' + line + '"/>';
  }

  // ---------- Kappa-chart rendering --------------------------------------
  // Produces a soft-banded line chart of judge κ over time.
  function renderKappaChart(svg, series, opts) {
    if (!svg || !series || !series.length) return;
    const w = (opts && opts.w) || 720;
    const h = (opts && opts.h) || 180;
    const pad = { l: 36, r: 14, t: 14, b: 26 };
    const min = 0.4, max = 1.0;
    const range = max - min;
    const dx = (w - pad.l - pad.r) / (series.length - 1);
    const yAt = v => pad.t + (h - pad.t - pad.b) * (1 - (v - min) / range);
    const xAt = i => pad.l + i * dx;

    const okBand = `M ${pad.l} ${yAt(0.75)} L ${w - pad.r} ${yAt(0.75)} L ${w - pad.r} ${yAt(1.0)} L ${pad.l} ${yAt(1.0)} Z`;
    const warnBand = `M ${pad.l} ${yAt(0.65)} L ${w - pad.r} ${yAt(0.65)} L ${w - pad.r} ${yAt(0.75)} L ${pad.l} ${yAt(0.75)} Z`;
    const errBand = `M ${pad.l} ${yAt(0.4)} L ${w - pad.r} ${yAt(0.4)} L ${w - pad.r} ${yAt(0.65)} L ${pad.l} ${yAt(0.65)} Z`;

    const line = series.map((v, i) => (i === 0 ? 'M' : 'L') + xAt(i).toFixed(1) + ',' + yAt(v).toFixed(1)).join(' ');

    let grids = '';
    [0.5, 0.65, 0.75, 0.9].forEach(v => {
      grids += `<line class="grid" x1="${pad.l}" y1="${yAt(v)}" x2="${w - pad.r}" y2="${yAt(v)}"/>`;
      grids += `<text x="${pad.l - 6}" y="${yAt(v) + 3}" text-anchor="end">${v.toFixed(2)}</text>`;
    });
    const lastIdx = series.length - 1;
    const xticks = `<text x="${pad.l}" y="${h - 6}">−${series.length}d</text>` +
                   `<text x="${(pad.l + w - pad.r) / 2}" y="${h - 6}" text-anchor="middle">−${Math.floor(series.length / 2)}d</text>` +
                   `<text x="${w - pad.r}" y="${h - 6}" text-anchor="end">today</text>`;

    svg.setAttribute('viewBox', `0 0 ${w} ${h}`);
    svg.innerHTML =
      `<path class="threshold-band" d="${okBand}"/>` +
      `<path class="warn-band" d="${warnBand}"/>` +
      `<path class="err-band" d="${errBand}"/>` +
      grids +
      xticks +
      `<path class="line" d="${line}"/>` +
      `<circle class="dot-now" cx="${xAt(lastIdx).toFixed(1)}" cy="${yAt(series[lastIdx]).toFixed(1)}" r="4"/>`;
  }

  // ---------- Heatmap (trajectory drift) ---------------------------------
  // Returns markup; the page injects it. 7 personas × 24 hours.
  function buildHeatmap(rows, hours) {
    const personas = rows || [
      'Adversarial Aaron', 'Methodical Mei', 'Onboarding Olivia',
      'Burned-Out Ben', 'Compliance Cara', 'Returning Rita', 'New Nick',
    ];
    const cols = hours || 24;

    // Synthetic z-scores — escalate near the right edge for two cohorts.
    function z(p, h) {
      const seed = (p * 13 + h * 7) % 11;
      let base = (seed % 7) * 0.4;
      // boost the last 6h for personas 0 and 4
      if ((p === 0 || p === 4) && h >= cols - 6) base += (h - (cols - 6)) * 0.7;
      const k = Math.min(6, Math.max(0, Math.round(base)));
      return k;
    }

    let html = '<div class="col-label" aria-hidden="true"></div>';
    for (let h = 0; h < cols; h++) {
      const label = (h % 4 === 0) ? `${h.toString().padStart(2, '0')}:00` : '';
      html += `<div class="col-label">${label}</div>`;
    }
    personas.forEach((name, p) => {
      html += `<div class="row-label">${escapeHtml(name)}</div>`;
      for (let h = 0; h < cols; h++) {
        const k = z(p, h);
        html += `<div class="cell" data-z="${k}" title="${escapeHtml(name)} · h${h} · z=${k.toFixed(1)}"></div>`;
      }
    });
    return html;
  }

  // ---------- Distribution-diff bars (planner-step) ----------------------
  function buildDistDiff(steps, side) {
    return steps.map(s => {
      const pct = side === 'now' ? s.now : s.baseline;
      const diff = s.now - s.baseline;
      let cls = '';
      if (side === 'now' && Math.abs(diff) > 0.07) cls = diff > 0 ? 'err' : 'warn';
      return `
        <div class="dist-bar">
          <div class="name">${escapeHtml(s.name)}</div>
          <div class="bar-track"><div class="bar-fill ${cls}" style="width:${(pct * 100).toFixed(1)}%"></div></div>
          <div class="pct">${(pct * 100).toFixed(1)}%</div>
        </div>`;
    }).join('');
  }

  // ---------- Sub-agent delegation graph ---------------------------------
  // Three nodes (planner + two sub-agents); two extra fan-out edges in "now"
  // that don't exist in baseline.
  function buildDelegationGraph(side) {
    const w = 560, h = 240;
    const planner = { x: 80, y: h / 2, label: 'planner' };
    const subA = { x: w * 0.45, y: 70, label: 'researcher' };
    const subB = { x: w * 0.45, y: h - 70, label: 'writer' };
    const subC = { x: w * 0.78, y: 60, label: 'critic' };
    const subD = { x: w * 0.78, y: h - 60, label: 'verifier' };

    const baselineEdges = [
      { from: planner, to: subA, weight: 0.55, cls: 'heavy' },
      { from: planner, to: subB, weight: 0.45, cls: 'heavy' },
      { from: subA, to: subC, weight: 0.20, cls: '' },
    ];
    const nowEdges = [
      { from: planner, to: subA, weight: 0.30, cls: '' },
      { from: planner, to: subB, weight: 0.30, cls: '' },
      { from: planner, to: subC, weight: 0.20, cls: 'churn' },  // new edge
      { from: planner, to: subD, weight: 0.20, cls: 'churn' },  // new edge
      { from: subA, to: subC, weight: 0.30, cls: 'heavy' },
      { from: subB, to: subD, weight: 0.30, cls: 'heavy' },
    ];

    const edges = side === 'now' ? nowEdges : baselineEdges;
    const nodes = side === 'now' ? [planner, subA, subB, subC, subD] : [planner, subA, subB, subC];

    const edgeMarkup = edges.map(e => {
      const mx = (e.from.x + e.to.x) / 2;
      const my = (e.from.y + e.to.y) / 2 - 18;
      const path = `M ${e.from.x} ${e.from.y} Q ${mx} ${my} ${e.to.x} ${e.to.y}`;
      return `<path class="edge ${e.cls}" d="${path}"/>`;
    }).join('');
    const nodeMarkup = nodes.map(n => {
      const r = Math.max(18, 16 + n.label.length * 0.6);
      return `<g><circle cx="${n.x}" cy="${n.y}" r="${r}" class="${n === planner ? 'heavy' : ''}"></circle>` +
             `<text x="${n.x}" y="${n.y + 4}" text-anchor="middle">${escapeHtml(n.label)}</text></g>`;
    }).join('');

    return `<svg class="graph-svg" viewBox="0 0 ${w} ${h}" preserveAspectRatio="xMidYMid meet" style="width:100%;height:240px;">
              ${edgeMarkup}${nodeMarkup}
            </svg>`;
  }

  // ---------- Fake worker -------------------------------------------------
  // Periodically advances states the way a real backend would. Synthetic.
  // Three things move:
  //   1. monitor sparklines drift each tick so the overview "feels alive"
  //   2. monitor lifecycle transitions (armed → firing → open → resolved)
  //      fire on a ~5% chance per tick, mirroring Persona Lab + the
  //      planned Simulation mock's setTimeout-driven state machine
  //   3. evidence packs in `requested` advance through `assembling` → `ready`
  function tickWorker() {
    let monitorsDirty = false;
    let packsDirty = false;
    const monitors = State.monitors();
    const incidents = State.incidents();
    const packs = State.packs();

    // 1 + 2 — monitors
    monitors.forEach(m => {
      if (m.sparkline && m.sparkline.length > 0) {
        m.sparkline.shift();
        const last = m.sparkline[m.sparkline.length - 1] || 0;
        const drift = (Math.random() - 0.5) * 0.05 * (last || 1);
        m.sparkline.push(Math.max(0, last + drift));
        monitorsDirty = true;
      }

      // Probabilistic lifecycle nudges (low rate so the page doesn't churn).
      if (Math.random() < 0.05) {
        const next = ({
          armed: 'firing',
          firing: 'open',
          open: 'acknowledged',
          acknowledged: 'resolved',
          resolved: 'armed',
        })[m.state];
        if (next) {
          m.state = next;
          if (next === 'firing') m.last_fired = new Date().toISOString();
          monitorsDirty = true;
        }
      }
    });

    // 3 — packs in flight
    packs.forEach(p => {
      if (p.assemble_state === 'requested') {
        p.assemble_state = 'assembling';
        p.assemble_progress = 0.05;
        packsDirty = true;
      } else if (p.assemble_state === 'assembling') {
        p.assemble_progress = Math.min(1, (p.assemble_progress || 0) + 0.08 + Math.random() * 0.04);
        if (p.assemble_progress >= 1) {
          p.assemble_state = 'ready';
          p.signed = true;
        }
        packsDirty = true;
      }
    });

    if (monitorsDirty) State.saveMonitors(monitors);
    if (packsDirty) State.savePacks(packs);
    // incidents intentionally untouched by the worker; legacy seed only.
    void incidents;
  }
  // Tick once per page load; the live-overview page also calls tickWorker
  // on a setInterval below.
  setTimeout(tickWorker, 1500);

  // ---------- Public API --------------------------------------------------
  window.AIBC_OBS = {
    State, ulid, fmtTs, fmtRelative, fmtNumber, escapeHtml,
    renderSparkline, renderKappaChart,
    buildHeatmap, buildDistDiff, buildDelegationGraph,
    tickWorker,
    SEED_DATASETS, SEED_GATE_HISTORY,
  };
})();

// ============================================================================
// LIVE wiring (observability) — control-plane surfaces from the edge.
// Monitors, evidence packs and judge-calibration come from the API when
// reachable. The analytical screens (batch span-trees, heatmaps, drift) have no
// backend source yet and keep their illustrative seed data.
// ============================================================================
(function () {
  if (!window.EEOF || !window.AIBC_OBS) return;
  const State = window.AIBC_OBS.State;

  let monitorsCache = [], packsCache = [], calibrationCache = [];

  const mapMonitor = (m) => ({
    id: m.id, name: m.name, kind: "quality",
    signal: `${m.rubric} · ${m.judge_ref}`,
    threshold: `pass_rate < ${m.threshold}`, window: "5m / 1m",
    cohort: "persona × run", severity: "warn",
    state: m.signed ? "armed" : "draft", armed_at: m.created_at,
    last_fired: null, fires_30d: 0, routing: ["slack:#eval-alerts"],
    version: m.version, env: m.env,
    sparkline: [0.3, 0.32, 0.31, 0.33, 0.36, 0.34, 0.35, 0.37, 0.36, 0.38, 0.37, 0.39],
    trend: "flat",
  });
  const mapPack = (p) => ({
    id: p.id, template: "evaluation_evidence", template_label: p.title || "Evaluation evidence",
    issued_at: p.issued_at, issued_by: "system", time_range: "—", tenant: p.tenant,
    monitors: 0, incidents: 0, calibration_records: calibrationCache.length,
    simulation_runs: (p.verdict_set_ids || []).length, pages: 1, signed: true,
    candidate: p.candidate, gate: p.gate,
  });

  async function hydrate() {
    try {
      const [mons, packs, cal] = await Promise.all([
        EEOF.get("/observability/monitors").catch(() => null),
        EEOF.get("/observability/evidence").catch(() => null),
        EEOF.get("/observability/calibration").catch(() => null),
      ]);
      if (cal) calibrationCache = cal;
      if (mons) monitorsCache = mons.map(mapMonitor);
      if (packs) packsCache = packs.map(mapPack);
      if (typeof window.render === "function") window.render();
    } catch {}
  }

  // Override the State getters so the pages read live data.
  State.monitors = () => monitorsCache;
  State.packs = () => packsCache;
  State.calibration = () => calibrationCache;
  State.saveMonitors = (arr) => {
    const known = new Set(monitorsCache.map((m) => m.name));
    (arr || []).filter((m) => !known.has(m.name)).forEach((m) => {
      EEOF.post("/observability/monitors", {
        name: m.name, env: m.env || "staging",
        rubric: (m.signal || "helpfulness").split(" ")[0], threshold: 0.8, sample_rate: 0.1,
      }).catch(() => {});
    });
    monitorsCache = arr;
  };

  window.AIBC_OBS.liveHydrate = hydrate;
  if (document.readyState !== "loading") setTimeout(hydrate, 0);
  else document.addEventListener("DOMContentLoaded", hydrate);
})();
