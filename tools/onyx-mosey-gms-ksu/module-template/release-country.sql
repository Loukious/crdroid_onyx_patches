-- Release the old country pin using its immutable independent CE baseline.
-- All validation and writes share one SQLite writer transaction.
PRAGMA foreign_keys=ON;
BEGIN IMMEDIATE;
CREATE TEMP TABLE country_assert(ok INTEGER NOT NULL CHECK(ok=1));
INSERT INTO country_assert SELECT (SELECT user_version FROM pragma_user_version)=1036
  AND (SELECT user_version FROM baseline.pragma_user_version)=1036;
INSERT INTO country_assert SELECT (SELECT COUNT(*) FROM pragma_table_info('flag_overrides'))=9
  AND (SELECT COUNT(*) FROM baseline.pragma_table_info('flag_overrides'))=9;
CREATE TEMP TABLE country_package AS SELECT cp.config_package_id FROM config_packages cp
  JOIN experiment_states es ON es.experiment_state_id=cp.committed_experiment_state_id
  JOIN accounts a ON a.account_id=es.account_id
  WHERE cp.name='mosey_app_android#com.google.android.mosey'
    AND es.config_package_id=cp.config_package_id AND a.account_id=0 AND a.name='';
CREATE TEMP TABLE country_baseline_package AS SELECT cp.config_package_id FROM baseline.config_packages cp
  JOIN baseline.experiment_states es ON es.experiment_state_id=cp.committed_experiment_state_id
  JOIN baseline.accounts a ON a.account_id=es.account_id
  WHERE cp.name='mosey_app_android#com.google.android.mosey'
    AND es.config_package_id=cp.config_package_id AND a.account_id=0 AND a.name='';
INSERT INTO country_assert SELECT (SELECT COUNT(*) FROM country_package)=1
  AND (SELECT COUNT(*) FROM country_baseline_package)=1
  AND (SELECT config_package_id FROM country_package)=(SELECT config_package_id FROM country_baseline_package);
CREATE TEMP TABLE country_old AS SELECT o.* FROM baseline.flag_overrides o
  JOIN country_baseline_package cp USING(config_package_id)
  WHERE o.account_id=0 AND o.active=1 AND o.name='45718707';
CREATE TEMP TABLE country_current AS SELECT o.* FROM flag_overrides o
  JOIN country_package cp USING(config_package_id)
  WHERE o.account_id=0 AND o.active=1 AND o.name='45718707';
INSERT INTO country_assert SELECT (SELECT COUNT(*) FROM country_old)<=1
  AND (SELECT COUNT(*) FROM country_current)<=1;
-- A pre-existing entry must retain its identity, type and source. Its value
-- may be the baseline value or the exact legacy transform of that value.
INSERT INTO country_assert SELECT NOT EXISTS(SELECT 1 FROM country_old old WHERE NOT EXISTS(
  SELECT 1 FROM country_current cur WHERE cur.override_id=old.override_id
    AND cur.config_package_id=old.config_package_id AND cur.config_package_name IS old.config_package_name
    AND cur.account_id=old.account_id AND cur.active=old.active AND cur.name=old.name
    AND cur.type=old.type AND cur.source IS old.source
    AND (cur.value IS old.value OR (old.type=5 AND typeof(old.value)='blob'
      AND typeof(cur.value)='blob' AND EXISTS(SELECT 1 FROM mosey_maps m
        WHERE old.value=m.previous AND cur.value=m.desired)))));
-- An entry absent from the baseline is owned only when it matches the old
-- inserted row and its exact effective-snapshot prerequisite.
INSERT INTO country_assert SELECT EXISTS(SELECT 1 FROM country_old)
  OR NOT EXISTS(SELECT 1 FROM country_current)
  OR (EXISTS(SELECT 1 FROM country_current cur JOIN mosey_legacy_country expected ON cur.name=expected.name
      WHERE cur.type=expected.type AND typeof(cur.value)='blob' AND cur.value=expected.value
        AND cur.source=0 AND NOT EXISTS(SELECT 1 FROM baseline.flag_overrides b WHERE b.override_id=cur.override_id))
    AND EXISTS(SELECT 1 FROM baseline.config_packages cp
      JOIN baseline.experiment_states_to_partitions l ON l.experiment_state_id=cp.committed_experiment_state_id
      JOIN baseline.param_partitions p USING(param_partition_id) JOIN mosey_snapshot s ON s.content=p.flags_content
      WHERE cp.name='mosey_app_android#com.google.android.mosey' AND l.ordinal=0
        AND (SELECT COUNT(*) FROM baseline.experiment_states_to_partitions all_parts
          WHERE all_parts.experiment_state_id=cp.committed_experiment_state_id)=1));
-- Old apply never removed links or added to-commit rows. Missing baseline
-- links, foreign scope, or a new to-commit reference indicates another writer.
INSERT INTO country_assert SELECT NOT EXISTS(SELECT 1 FROM baseline.experiment_states_to_overrides old
  JOIN country_old o USING(override_id) WHERE NOT EXISTS(
    SELECT 1 FROM experiment_states_to_overrides cur
      WHERE cur.experiment_state_id=old.experiment_state_id AND cur.override_id=old.override_id));
INSERT INTO country_assert SELECT NOT EXISTS(SELECT 1 FROM experiment_states_to_overrides cur
  JOIN country_current o USING(override_id)
  WHERE NOT EXISTS(SELECT 1 FROM baseline.experiment_states_to_overrides old
    WHERE old.experiment_state_id=cur.experiment_state_id AND old.override_id=cur.override_id)
  AND NOT EXISTS(SELECT 1 FROM experiment_states es JOIN config_packages cp USING(config_package_id)
    WHERE cp.name='mosey_app_android#com.google.android.mosey' AND es.account_id=0
      AND es.experiment_state_id=cur.experiment_state_id
      AND (es.experiment_state_id=cp.committed_experiment_state_id OR es.experiment_state_id=(
        SELECT MAX(s.experiment_state_id) FROM experiment_states s
          WHERE s.config_package_id=cp.config_package_id AND s.account_id=0))));
INSERT INTO country_assert SELECT NOT EXISTS(SELECT 1 FROM flag_overrides_to_commit cur
  JOIN country_current o USING(override_id) WHERE NOT EXISTS(
    SELECT 1 FROM baseline.flag_overrides_to_commit old WHERE old.override_id=cur.override_id
      AND old.config_package_id=cur.config_package_id AND old.account_id=cur.account_id));
INSERT INTO country_assert SELECT NOT EXISTS(SELECT 1 FROM baseline.flag_overrides_to_commit old
  JOIN country_old o USING(override_id) WHERE NOT EXISTS(
    SELECT 1 FROM flag_overrides_to_commit cur WHERE old.override_id=cur.override_id
      AND old.config_package_id=cur.config_package_id AND old.account_id=cur.account_id));
CREATE TEMP TABLE country_changes(initial INTEGER);
INSERT INTO country_changes SELECT total_changes();
-- Remove only links old apply added; all baseline links survive unchanged.
DELETE FROM experiment_states_to_overrides WHERE override_id IN(SELECT override_id FROM country_current)
  AND NOT EXISTS(SELECT 1 FROM baseline.experiment_states_to_overrides old
    WHERE old.override_id=experiment_states_to_overrides.override_id
      AND old.experiment_state_id=experiment_states_to_overrides.experiment_state_id);
UPDATE flag_overrides SET value=(SELECT old.value FROM country_old old WHERE old.override_id=flag_overrides.override_id)
  WHERE override_id IN(SELECT override_id FROM country_old)
    AND value IS NOT (SELECT old.value FROM country_old old WHERE old.override_id=flag_overrides.override_id);
DELETE FROM flag_overrides WHERE override_id IN(SELECT override_id FROM country_current)
  AND NOT EXISTS(SELECT 1 FROM country_old);
SELECT CASE WHEN total_changes()>(SELECT initial+1 FROM country_changes) THEN 'changed' ELSE 'unchanged' END;
COMMIT;
