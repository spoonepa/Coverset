export type JsonObject = Record<string, unknown>;

export type ActorRole =
  | "first_ad"
  | "second_ad"
  | "script_supervisor"
  | "director"
  | "producer"
  | "upm"
  | "line_producer";

export type Actor = {
  name: string;
  role: ActorRole;
};

export type Production = {
  id: string;
  title: string;
  created_at?: string;
  cast_count: number;
  location_count: number;
  shoot_day_count: number;
};

export type CastMember = {
  id: string;
  production_id: string;
  cast_id: string;
  performer: string;
  character: string;
  is_minor: boolean;
  availability_windows: string[];
};

export type LocationRow = {
  id: string;
  production_id: string;
  location_id: string;
  name: string;
  zone: string;
  address: string;
  latitude: number;
  longitude: number;
  timezone: string;
  aliases: string[];
};

export type Candidate = {
  id: string;
  scene_id: string;
  scene_number: string;
  slugline: string;
  int_ext: string;
  day_night: string;
  location_ref: string;
  page_eighths: number;
  cast_ids: string[];
  flags: Record<string, boolean>;
  source_page_range: string;
  confidence: number | null;
  proposal_scene: JsonObject | null;
  status: string;
  accepted: boolean;
  rejected: boolean;
  schedulable: boolean;
  resolution_errors: string[];
  number_synthesized: boolean;
};

export type BreakdownRun = {
  id: string;
  production_id: string;
  screenplay_asset_id: string;
  status: string;
  agent_mode: string;
  error: string;
  unresolved_locations: string[];
  unresolved_cast: string[];
  candidates: Candidate[];
};

export type CandidateBatchAcceptResponse = {
  accepted: string[];
  skipped: Record<string, string[]>;
  candidates: Candidate[];
};

export type ScheduleConflictConstraint = {
  constraint_id: string;
  family: string;
  policy: string;
  subject: string;
  expression: string;
  relaxable: boolean;
  active: boolean;
  source: JsonObject;
};

export type ScheduleConflict = {
  status?: string;
  constraint_ids?: string[];
  structural_causes?: string[];
  irreducible?: boolean;
  detail?: string;
  binding_constraint_count?: number;
  constraint_snapshot_hash?: string;
  relaxable_constraints?: ScheduleConflictConstraint[];
  relaxation_check?: JsonObject;
};

export type ScheduleRun = {
  id: string;
  production_id: string;
  status: string;
  error: string;
  input_hash: string;
  board_id: string | null;
  diagnostics: string[];
  conflict: ScheduleConflict;
};

export type Job = {
  id: string;
  production_id: string | null;
  job_type: string;
  target_id: string;
  status: string;
  attempts: number;
  error: string;
  result: JsonObject;
};

export type GroundingEvidence = {
  id: string;
  production_id: string;
  location_id: string;
  fact_kind: string;
  target_date: string;
  status: string;
  error: string;
  evidence: JsonObject;
};

export type GroundedValue = {
  id: string;
  production_id: string;
  evidence_id: string;
  fact_kind: string;
  location_id: string;
  target_date: string;
  normalized_value: JsonObject;
  units: string;
  source_url: string;
  source_quote: string;
  source_span: string;
  query: string;
  provider_response_id: string;
  content_hash: string;
  derived_from: string;
  validator_result: JsonObject;
  covering_date: boolean;
  context_source_urls: string[];
};

export type ConstraintProposal = {
  id: string;
  production_id: string;
  source_text: string;
  status: string;
  confidence: number;
  payload: JsonObject;
  validation_errors: string[];
  created_by_name: string;
  accepted_by_name: string | null;
  accepted_by_role: string | null;
  accepted_constraint_id: string | null;
};

export type ConstraintRow = {
  id: string;
  production_id: string;
  constraint_id: string;
  family: string;
  policy: string;
  active: boolean;
  constraint: JsonObject;
  provenance: JsonObject;
};

export type ExplanationTrace = {
  work_id: string;
  reason: string;
  constraint_id?: string;
  source?: string;
  weight?: number;
};

export type BoardStrip = {
  work_id: string;
  scene_id: string;
  scene_number: string;
  shoot_day: string;
  sequence: number;
  location_id: string;
  zone: string;
  day_night: string;
  cast_ids: string[];
  page_eighths: number;
  minutes: number;
  planned_call_time?: string;
  planned_wrap_time?: string;
  kind?: string;
  [key: string]: unknown;
};

export type BoardDay = {
  date: string;
  day_index?: number;
  kind?: string;
  planned_call_time?: string;
  planned_wrap_time?: string;
  [key: string]: unknown;
};

export type BoardResult = {
  days?: BoardDay[];
  strips?: BoardStrip[];
  objective?: JsonObject;
  explanation_traces?: ExplanationTrace[];
  approval_state?: string;
  diagnostics?: string[];
  [key: string]: unknown;
};

export type Board = {
  id: string;
  production_id: string;
  schedule_run_id: string;
  solver_status: string;
  approval_state: string;
  stripboard: string;
  result: BoardResult;
};

export type CallSheetPayload = {
  production_id: string;
  board_id: string;
  schedule_run_id: string;
  shoot_date: string;
  day?: JsonObject;
  scenes?: JsonObject[];
  locations?: JsonObject[];
  cast_calls?: JsonObject[];
  crew_call?: string;
  wrap?: string;
  daylight?: JsonObject;
  turnaround_notes?: JsonObject[];
  permit_notes?: JsonObject[];
  recipients?: JsonObject[];
  generated_by?: string;
  generated_by_role?: string;
  [key: string]: unknown;
};

export type CallSheet = {
  id: string;
  production_id: string;
  board_id: string;
  schedule_run_id: string;
  shoot_date: string;
  generated_by_name: string;
  generated_by_role: string;
  payload: CallSheetPayload;
  rendered_text: string;
};

export type LockedDay = {
  id: string;
  production_id: string;
  board_id: string;
  schedule_run_id: string;
  shoot_date: string;
  locked_assignments: JsonObject[];
  locations: string[];
  cast: string[];
  call_sheet_version: string;
  recorded_by_name: string;
  recorded_by_role: string;
};

export type MonitoredSource = {
  id: string;
  production_id: string;
  board_id: string;
  source_url: string;
  fact_kind: string;
  location_id: string;
  query: string;
  provider: string;
  external_monitor_id: string;
  status: string;
  last_fingerprint: string;
};

export type MonitorChangeEvent = {
  id: string;
  production_id: string;
  monitored_source_id: string | null;
  board_id: string;
  status: string;
  material: boolean;
  old_fingerprint: string;
  new_fingerprint: string;
  payload: JsonObject;
  finding_id: string | null;
  replan_request_id: string | null;
};

export type MonitorFinding = {
  id: string;
  production_id: string;
  board_id: string;
  evidence_id: string | null;
  source_url: string;
  fact_kind: string;
  status: string;
  material: boolean;
  message: string;
  old_fingerprint: string;
  new_fingerprint: string;
  old_value: JsonObject;
  new_value: JsonObject;
  affected_work_ids: string[];
  requester_component: string;
  reviewed_by_name: string | null;
  reviewed_by_role: string | null;
};

export type ReplanRequest = {
  id: string;
  production_id: string;
  finding_id: string | null;
  current_board_id: string;
  requester_component: string;
  source_kind: string;
  source_id: string;
  reason: string;
  status: string;
  affected_work_ids: string[];
  locked_days: string[];
};

export type ScheduleDiff = {
  id: string;
  production_id: string;
  base_board_id: string;
  revised_board_id: string;
  replan_request_id: string | null;
  diff: JsonObject;
  required_approvals: string[];
  cost_delta: number;
  rendered_text: string;
};

export type BoardSelection = {
  id: string;
  production_id: string;
  prior_board_id: string | null;
  selected_board_id: string;
  prior_schedule_run_id: string | null;
  new_schedule_run_id: string;
  actor_name: string;
  actor_role: string;
};

export type CostApproval = {
  id: string;
  production_id: string;
  board_id: string;
  approver_name: string;
  approver_role: string;
  cost_delta: number;
  added_shoot_days: string[];
  decision: string;
};

export type CoverageItem = {
  id: string;
  production_id: string;
  scene_id: string;
  coverage_key: string;
  coverage_type: string;
  planned: JsonObject;
  shot: JsonObject;
  status: string;
};

export type CoverageFinding = {
  id: string;
  production_id: string;
  coverage_item_id: string;
  board_id: string | null;
  status: string;
  severity: string;
  message: string;
  raised_by_name: string;
  raised_by_role: string;
  human_raised: boolean;
};

export type PickupTask = {
  id: string;
  production_id: string;
  finding_id: string;
  coverage_item_id: string;
  board_id: string | null;
  status: string;
  scene_id: string;
  pickup_spec: JsonObject;
  decision: JsonObject;
  requested_by_name: string;
  requested_by_role: string;
  confirmed_by_name: string | null;
  confirmed_by_role: string | null;
};

export type AuditEvent = {
  id: string;
  production_id: string | null;
  event_type: string;
  actor: string;
  payload: JsonObject;
  created_at: string;
};
