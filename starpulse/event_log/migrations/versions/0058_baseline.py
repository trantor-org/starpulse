"""Every table a store holds, as the chain before the squash left them: the one revision every store starts at.

A store at the last pre-squash revision is stamped here without DDL. The derived tables are built empty and no stamp is
written, so their owners fill them on first use; the revisions after this one change durable tables only."""

from alembic import op

revision = "0058"
down_revision = None

_DDL = (
    "CREATE TABLE starpulse_events (\n\tid INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, \n\tstream VARCHAR NOT NULL, \n\tevent_id VARCHAR NOT NULL, \n\tfields JSON NOT NULL, \n\tat FLOAT NOT NULL, \n\tUNIQUE (event_id)\n)",
    "CREATE INDEX ix_starpulse_events_stream ON starpulse_events (stream, id)",
    "CREATE INDEX ix_starpulse_events_at ON starpulse_events (at)",
    "CREATE TABLE starpulse_gaps (\n\tid INTEGER NOT NULL, \n\tstream VARCHAR NOT NULL, \n\tafter_id VARCHAR NOT NULL, \n\tbefore_id VARCHAR NOT NULL, \n\tlost INTEGER NOT NULL, \n\tnoted_at FLOAT NOT NULL, \n\tPRIMARY KEY (id)\n)",
    "CREATE UNIQUE INDEX ux_starpulse_gaps ON starpulse_gaps (stream, after_id)",
    "CREATE TABLE starpulse_machine_events (\n\tid INTEGER NOT NULL, \n\tevent_id VARCHAR NOT NULL, \n\ttask VARCHAR, \n\trun VARCHAR, \n\tmachine VARCHAR NOT NULL, \n\tevent VARCHAR NOT NULL, \n\tactor VARCHAR, \n\toccurred_at FLOAT NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (event_id)\n)",
    "CREATE INDEX ix_starpulse_machine_events_task ON starpulse_machine_events (task, machine, occurred_at)",
    "CREATE TABLE starpulse_lane_changes (\n\tid INTEGER NOT NULL, \n\tevent_id VARCHAR NOT NULL, \n\ttask VARCHAR NOT NULL, \n\told_status VARCHAR, \n\tnew_status VARCHAR NOT NULL, \n\tobserved_at FLOAT NOT NULL, actor VARCHAR, \n\tPRIMARY KEY (id), \n\tUNIQUE (event_id)\n)",
    "CREATE INDEX ix_starpulse_lane_changes_task ON starpulse_lane_changes (task, observed_at)",
    "CREATE TABLE starpulse_learned_steps (\n\tid INTEGER NOT NULL, \n\tworkflow VARCHAR NOT NULL, \n\tstep VARCHAR NOT NULL, \n\tdepends TEXT NOT NULL, \n\tPRIMARY KEY (id)\n)",
    "CREATE UNIQUE INDEX ux_starpulse_learned_steps ON starpulse_learned_steps (workflow, step)",
    "CREATE TABLE starpulse_pull_requests (\n\trepo VARCHAR NOT NULL, \n\tnumber INTEGER NOT NULL, \n\tstate VARCHAR NOT NULL, \n\tis_draft BOOLEAN NOT NULL, \n\tmergeable VARCHAR NOT NULL, \n\tbase VARCHAR NOT NULL, \n\thead VARCHAR NOT NULL, \n\tbody TEXT NOT NULL, \n\tchecks VARCHAR NOT NULL, \n\trequired JSON NOT NULL, \n\tthreads INTEGER NOT NULL, \n\tupdated_at VARCHAR NOT NULL, \n\tfetched_at FLOAT NOT NULL, detail JSON, merged_at VARCHAR, merge_sha VARCHAR, head_ref VARCHAR, unresolved JSON, title VARCHAR, rollup JSON, \n\tPRIMARY KEY (repo, number)\n)",
    "CREATE INDEX ix_starpulse_pull_requests_state ON starpulse_pull_requests (state, repo)",
    'CREATE TABLE starpulse_settings (\n\t"key" VARCHAR NOT NULL, \n\tvalue JSON NOT NULL, \n\tupdated_at FLOAT NOT NULL, \n\tPRIMARY KEY ("key")\n)',
    'CREATE TABLE "starpulse_scheduler_runs" (\n\tid INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, \n\ttask VARCHAR NOT NULL, \n\ttier VARCHAR NOT NULL, \n\tpoints INTEGER NOT NULL, \n\toutcome VARCHAR NOT NULL, \n\tduration_s FLOAT NOT NULL, \n\tpeak JSON NOT NULL, \n\trecorded_at FLOAT NOT NULL\n)',
    "CREATE TABLE starpulse_retired_tasks (\n\ttask VARCHAR NOT NULL, \n\tname VARCHAR NOT NULL, \n\ttext TEXT NOT NULL, \n\tretired_at FLOAT NOT NULL, \n\tPRIMARY KEY (task)\n)",
    "CREATE INDEX ix_starpulse_retired_tasks_retired_at ON starpulse_retired_tasks (retired_at)",
    "CREATE INDEX ix_starpulse_lane_changes_observed ON starpulse_lane_changes (observed_at, id)",
    "CREATE INDEX ix_starpulse_machine_events_run ON starpulse_machine_events (run, machine, occurred_at)",
    "CREATE TABLE starpulse_checkpoints (\n\tname VARCHAR NOT NULL, \n\tposition INTEGER NOT NULL, \n\tschema_version INTEGER NOT NULL, \n\tstate JSON, \n\tsaved_at FLOAT NOT NULL, \n\tPRIMARY KEY (name)\n)",
    "CREATE TABLE starpulse_stream_events (\n\tid INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, \n\tevent_id VARCHAR NOT NULL, \n\tsubject_kind VARCHAR NOT NULL, \n\tsubject_id VARCHAR NOT NULL, \n\tversion INTEGER NOT NULL, \n\ttype VARCHAR NOT NULL, \n\tschema_version INTEGER NOT NULL, \n\tat FLOAT NOT NULL, \n\tactor VARCHAR NOT NULL, \n\twriter VARCHAR NOT NULL, \n\tdefinition_hash VARCHAR, \n\tcausation_id VARCHAR, \n\tcorrelation_id VARCHAR, \n\tpayload JSON NOT NULL, \n\tCONSTRAINT uq_starpulse_stream_events_version UNIQUE (subject_kind, subject_id, version), \n\tUNIQUE (event_id)\n)",
    "CREATE INDEX ix_starpulse_scheduler_runs_tier_points ON starpulse_scheduler_runs (tier, points)",
    "CREATE TABLE starpulse_machine_versions (\n\thash VARCHAR NOT NULL, \n\tmachine VARCHAR NOT NULL, \n\tdocument JSON NOT NULL, \n\tcreated_at FLOAT NOT NULL, \n\tPRIMARY KEY (hash)\n)",
    "CREATE TABLE starpulse_machine_active (\n\tmachine VARCHAR NOT NULL, \n\thash VARCHAR NOT NULL, \n\tactivated_at FLOAT NOT NULL, \n\tPRIMARY KEY (machine), \n\tFOREIGN KEY(hash) REFERENCES starpulse_machine_versions (hash)\n)",
    "CREATE TABLE starpulse_worker_state (\n\tname VARCHAR NOT NULL, \n\tstate JSON NOT NULL, \n\tversion INTEGER NOT NULL, \n\tupdated_at FLOAT NOT NULL, \n\tPRIMARY KEY (name)\n)",
    "CREATE TABLE starpulse_task_verdicts (\n\tid INTEGER NOT NULL, \n\tevent_id VARCHAR NOT NULL, \n\ttask VARCHAR NOT NULL, \n\tlens VARCHAR NOT NULL, \n\tround INTEGER NOT NULL, \n\toutcome VARCHAR NOT NULL, \n\treason VARCHAR NOT NULL, \n\toccurred_at FLOAT NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (event_id)\n)",
    "CREATE INDEX ix_starpulse_task_verdicts_task ON starpulse_task_verdicts (task, occurred_at)",
    'CREATE TABLE starpulse_signals (\n\t"key" VARCHAR NOT NULL, \n\tharness VARCHAR NOT NULL, \n\tsession VARCHAR NOT NULL, \n\ttime FLOAT NOT NULL, \n\tkind VARCHAR NOT NULL, \n\tfields JSON NOT NULL, \n\tPRIMARY KEY ("key")\n)',
    "CREATE INDEX ix_starpulse_signals_time ON starpulse_signals (time)",
    "CREATE INDEX ix_starpulse_signals_session ON starpulse_signals (harness, session, time)",
    "CREATE TABLE starpulse_leases (\n\tname VARCHAR NOT NULL, \n\tholder INTEGER NOT NULL, \n\ttaken_at FLOAT NOT NULL, \n\tPRIMARY KEY (name)\n)",
    "CREATE TABLE starpulse_breaking_changes (\n\tid INTEGER NOT NULL, \n\tcommit_sha VARCHAR NOT NULL, \n\tpr INTEGER, \n\ttask VARCHAR, \n\toutcome VARCHAR, \n\tfirst_seen FLOAT NOT NULL, \n\tpostmortem_task VARCHAR, \n\tPRIMARY KEY (id), \n\tUNIQUE (commit_sha)\n)",
    "CREATE TABLE starpulse_breaking_change_detections (\n\tid INTEGER NOT NULL, \n\tevent_id VARCHAR NOT NULL, \n\tcommit_sha VARCHAR NOT NULL, \n\tdetector VARCHAR NOT NULL, \n\toutcome VARCHAR, \n\tevidence VARCHAR, \n\toccurred_at FLOAT NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (commit_sha, detector), \n\tUNIQUE (event_id)\n)",
    "CREATE TABLE starpulse_policy_lanes (\n\tname VARCHAR NOT NULL, \n\trole VARCHAR, \n\tposition INTEGER NOT NULL, \n\tskill VARCHAR, label VARCHAR, \n\tPRIMARY KEY (name)\n)",
    "CREATE TABLE starpulse_policy_routes (\n\tid INTEGER NOT NULL, \n\tevent VARCHAR NOT NULL, \n\tsource VARCHAR NOT NULL, \n\ttarget VARCHAR NOT NULL, \n\tcondition JSON, \n\tPRIMARY KEY (id)\n)",
    'CREATE TABLE starpulse_policy_exits (\n\tid INTEGER NOT NULL, \n\tevent VARCHAR NOT NULL, \n\tactor VARCHAR NOT NULL, \n\t"trigger" VARCHAR NOT NULL, \n\tPRIMARY KEY (id)\n)',
    "CREATE TABLE starpulse_policy_watches (\n\tid INTEGER NOT NULL, \n\tlane VARCHAR NOT NULL, \n\tfact VARCHAR NOT NULL, \n\tevent VARCHAR NOT NULL, \n\tposition INTEGER NOT NULL, \n\tPRIMARY KEY (id)\n)",
    'CREATE TABLE starpulse_policy_rules (\n\tposition INTEGER NOT NULL, \n\t"on" JSON NOT NULL, \n\trequire JSON NOT NULL, \n\treason TEXT NOT NULL, \n\tskill VARCHAR NOT NULL, \n\tunless_actor JSON NOT NULL, \n\tPRIMARY KEY (position)\n)',
    "CREATE TABLE starpulse_policy_vocabularies (\n\tname VARCHAR NOT NULL, \n\tvalue VARCHAR NOT NULL, \n\tposition INTEGER NOT NULL, \n\tPRIMARY KEY (name, value)\n)",
    "CREATE TABLE starpulse_policy_profiles (\n\tkind VARCHAR NOT NULL, \n\tsize INTEGER NOT NULL, \n\tprofile VARCHAR NOT NULL, \n\tPRIMARY KEY (kind, size)\n)",
    "CREATE TABLE starpulse_policy_tools (\n\tlane VARCHAR NOT NULL, \n\ttool VARCHAR NOT NULL, \n\tPRIMARY KEY (lane, tool)\n)",
    "CREATE TABLE github_inbox (\n\tid INTEGER NOT NULL, \n\tdelivery_id VARCHAR NOT NULL, \n\tsource VARCHAR NOT NULL, \n\tevent VARCHAR NOT NULL, \n\taction VARCHAR NOT NULL, \n\trepository VARCHAR NOT NULL, \n\tbody BLOB NOT NULL, \n\treceived_at FLOAT NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (delivery_id)\n)",
    "CREATE INDEX github_inbox_fact ON github_inbox (repository, event, action, received_at)",
    "CREATE TABLE github_inbox_state (\n\tdelivery_id VARCHAR NOT NULL, \n\tconsumer VARCHAR NOT NULL, \n\tstatus VARCHAR NOT NULL, \n\tattempts INTEGER NOT NULL, \n\tnext_attempt_at FLOAT NOT NULL, \n\tlast_error VARCHAR, \n\tupdated_at FLOAT NOT NULL, \n\tPRIMARY KEY (delivery_id, consumer)\n)",
    "CREATE INDEX ix_github_inbox_state_due ON github_inbox_state (consumer, status, next_attempt_at)",
    "CREATE TABLE github_reconcile_state (\n\tname VARCHAR NOT NULL, \n\tcursor VARCHAR NOT NULL, \n\tetag VARCHAR, \n\tPRIMARY KEY (name)\n)",
    'CREATE TABLE starpulse_answers (\n\t"view" VARCHAR NOT NULL, \n\t"query" VARCHAR NOT NULL, \n\tbody BLOB NOT NULL, \n\tstatus INTEGER NOT NULL, \n\tfolded_at FLOAT NOT NULL, \n\tPRIMARY KEY ("view", "query")\n)',
    "CREATE INDEX ix_starpulse_answers_folded_at ON starpulse_answers (folded_at)",
    "CREATE TABLE starpulse_cases (\n\tmachine VARCHAR NOT NULL, \n\tsource VARCHAR NOT NULL, \n\tkind VARCHAR NOT NULL, \n\tcase_id VARCHAR NOT NULL, \n\tstate VARCHAR NOT NULL, \n\tsince FLOAT NOT NULL, \n\tfirst_at FLOAT NOT NULL, \n\tlast_event_id VARCHAR NOT NULL, \n\tlast_at FLOAT NOT NULL, \n\tPRIMARY KEY (machine, source, kind, case_id)\n)",
    "CREATE INDEX ix_starpulse_cases_state ON starpulse_cases (machine, state)",
    "CREATE TABLE starpulse_lane_intervals (\n\tid INTEGER NOT NULL, \n\ttask VARCHAR NOT NULL, \n\tlane VARCHAR NOT NULL, \n\tentered_at FLOAT NOT NULL, \n\tleft_at FLOAT, \n\tevent_id VARCHAR NOT NULL, \n\tsource VARCHAR, \n\tPRIMARY KEY (id), \n\tUNIQUE (event_id)\n)",
    "CREATE INDEX ix_starpulse_lane_intervals_entered ON starpulse_lane_intervals (entered_at)",
    "CREATE INDEX ix_starpulse_lane_intervals_left ON starpulse_lane_intervals (left_at)",
    "CREATE INDEX ix_starpulse_lane_intervals_stay ON starpulse_lane_intervals (lane, left_at, entered_at)",
    "CREATE INDEX ix_starpulse_lane_intervals_task_entered ON starpulse_lane_intervals (task, entered_at)",
    "CREATE TABLE starpulse_lanes (\n\tsource VARCHAR NOT NULL, \n\tlane VARCHAR NOT NULL, \n\topen_tasks INTEGER NOT NULL, \n\tfirst_at FLOAT NOT NULL, \n\tPRIMARY KEY (source, lane)\n)",
    "CREATE TABLE starpulse_machine_tasks (\n\tmachine VARCHAR NOT NULL, \n\ttask VARCHAR NOT NULL, \n\tstate VARCHAR NOT NULL, \n\tagent JSON NOT NULL, \n\tactive_at FLOAT NOT NULL, \n\tseq INTEGER NOT NULL, \n\tPRIMARY KEY (machine, task)\n)",
    "CREATE INDEX ix_starpulse_machine_tasks_active ON starpulse_machine_tasks (active_at)",
    "CREATE INDEX ix_starpulse_machine_tasks_machine_active ON starpulse_machine_tasks (machine, active_at)",
    "CREATE INDEX ix_starpulse_machine_tasks_seq ON starpulse_machine_tasks (seq)",
    'CREATE TABLE starpulse_signal_folds (\n\t"view" VARCHAR NOT NULL, \n\tharness VARCHAR NOT NULL, \n\tsession VARCHAR NOT NULL, \n\tfirst_at FLOAT NOT NULL, \n\tlast_at FLOAT NOT NULL, \n\tfolded_through INTEGER NOT NULL, \n\tbasis VARCHAR NOT NULL, \n\tresult JSON NOT NULL, \n\tPRIMARY KEY ("view", harness, session)\n)',
    "CREATE INDEX ix_starpulse_signal_folds_basis ON starpulse_signal_folds (basis)",
    "CREATE INDEX ix_starpulse_signal_folds_last_at ON starpulse_signal_folds (last_at)",
    "CREATE TABLE starpulse_snapshot_deltas (\n\tseq INTEGER NOT NULL, \n\tkind VARCHAR NOT NULL, \n\tdata JSON NOT NULL, \n\tPRIMARY KEY (seq)\n)",
    'CREATE TABLE starpulse_snapshots (\n\t"view" VARCHAR NOT NULL, \n\tseq INTEGER NOT NULL, \n\tbody BLOB NOT NULL, \n\tgzipped BLOB, \n\tstored_at FLOAT NOT NULL, \n\tPRIMARY KEY ("view")\n)',
    "CREATE TABLE starpulse_step_summaries (\n\tday DATE NOT NULL, \n\tmachine VARCHAR NOT NULL, \n\tfrom_state VARCHAR NOT NULL, \n\tto_state VARCHAR NOT NULL, \n\tsteps INTEGER NOT NULL, \n\tduration_s FLOAT NOT NULL, \n\tPRIMARY KEY (day, machine, from_state, to_state)\n)",
    "CREATE TABLE starpulse_task_criteria (\n\ttask_id VARCHAR NOT NULL, \n\tkind VARCHAR NOT NULL, \n\tn INTEGER NOT NULL, \n\ttext TEXT NOT NULL, \n\tchecked BOOLEAN NOT NULL, \n\tevidence TEXT NOT NULL, \n\tPRIMARY KEY (task_id, kind, n), \n\tFOREIGN KEY(task_id) REFERENCES starpulse_tasks (id) ON DELETE CASCADE\n)",
    'CREATE TABLE starpulse_tasks (\n\tid VARCHAR NOT NULL, \n\tseq INTEGER NOT NULL, \n\tversion INTEGER NOT NULL, \n\tcreated_at FLOAT NOT NULL, \n\tupdated_at FLOAT NOT NULL, \n\ttitle TEXT NOT NULL, \n\ttype VARCHAR NOT NULL, \n\tstate VARCHAR NOT NULL, \n\tpriority VARCHAR NOT NULL, \n\tmilestone VARCHAR NOT NULL, \n\tassignee VARCHAR NOT NULL, \n\treleased JSON, \n\tarchived BOOLEAN NOT NULL, \n\tdescription TEXT NOT NULL, \n\t"plan" TEXT NOT NULL, \n\tnotes TEXT NOT NULL, \n\tfinal_summary TEXT NOT NULL, \n\tlabels JSON NOT NULL, \n\tdependencies JSON NOT NULL, \n\t"references" JSON NOT NULL, \n\tdocumentation JSON NOT NULL, \n\tmodified_files JSON NOT NULL, \n\tcomments JSON NOT NULL, \n\tfields JSON NOT NULL, \n\tmeta JSON NOT NULL, \n\tPRIMARY KEY (id)\n)',
    "CREATE INDEX ix_starpulse_tasks_archived_updated ON starpulse_tasks (updated_at) WHERE archived = 1",
    "CREATE INDEX ix_starpulse_tasks_live_assignee ON starpulse_tasks (assignee) WHERE archived = 0",
    "CREATE INDEX ix_starpulse_tasks_live_id ON starpulse_tasks (id) WHERE archived = 0",
    "CREATE INDEX ix_starpulse_tasks_live_milestone ON starpulse_tasks (milestone) WHERE archived = 0",
    "CREATE INDEX ix_starpulse_tasks_live_set ON starpulse_tasks (archived, state, updated_at) WHERE archived = 0",
    "CREATE INDEX ix_starpulse_tasks_live_state ON starpulse_tasks (state, id) WHERE archived = 0",
    "CREATE INDEX ix_starpulse_tasks_lower_id ON starpulse_tasks (lower(id))",
    "CREATE INDEX ix_starpulse_tasks_seq ON starpulse_tasks (seq)",
)


def upgrade() -> None:
    for statement in _DDL:
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError("the baseline has nothing below it")
