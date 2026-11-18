-- The caller attaches its read-only pre-change backup as baseline.
PRAGMA foreign_keys=ON;
BEGIN IMMEDIATE;
CREATE TEMP TABLE mosey_assert(ok INTEGER NOT NULL CHECK(ok=1));
INSERT INTO mosey_assert SELECT (SELECT user_version FROM pragma_user_version)=1036
  AND (SELECT user_version FROM baseline.pragma_user_version)=1036;
INSERT INTO mosey_assert SELECT (SELECT COUNT(*) FROM pragma_table_info('flag_overrides'))=9
  AND (SELECT COUNT(*) FROM baseline.pragma_table_info('flag_overrides'))=9;
INSERT INTO mosey_assert SELECT COUNT(*) FROM config_packages cp
  JOIN experiment_states es ON es.experiment_state_id=cp.committed_experiment_state_id
  JOIN accounts a ON a.account_id=es.account_id
  WHERE cp.name='com.google.android.gms.nearby' AND es.config_package_id=cp.config_package_id
    AND a.account_id=0 AND a.name='';
CREATE TEMP TABLE mosey_old AS SELECT o.value,o.type,o.source FROM baseline.flag_overrides o
  JOIN baseline.config_packages cp USING(config_package_id)
  WHERE cp.name='com.google.android.gms.nearby' AND o.account_id=0 AND o.active=1 AND o.name='45704091';
INSERT INTO mosey_assert SELECT COUNT(*)<=1 FROM mosey_old;
INSERT INTO mosey_assert SELECT NOT EXISTS(SELECT 1 FROM mosey_old
  WHERE type!=2 OR typeof(value)!='integer' OR value NOT IN(0,1));
-- A newly inserted override has no original row. Remove only references to it.
DELETE FROM experiment_states_to_overrides WHERE override_id IN(
  SELECT o.override_id FROM flag_overrides o JOIN config_packages cp USING(config_package_id)
  WHERE cp.name='com.google.android.gms.nearby' AND o.account_id=0 AND o.active=1
    AND o.name='45704091' AND NOT EXISTS(SELECT 1 FROM mosey_old));
DELETE FROM flag_overrides_to_commit WHERE override_id IN(
  SELECT o.override_id FROM flag_overrides o JOIN config_packages cp USING(config_package_id)
  WHERE cp.name='com.google.android.gms.nearby' AND o.account_id=0 AND o.active=1
    AND o.name='45704091' AND NOT EXISTS(SELECT 1 FROM mosey_old));
DELETE FROM flag_overrides WHERE config_package_id IN(
  SELECT config_package_id FROM config_packages WHERE name='com.google.android.gms.nearby')
  AND account_id=0 AND active=1 AND name='45704091' AND NOT EXISTS(SELECT 1 FROM mosey_old);
INSERT INTO flag_overrides(config_package_id,config_package_name,account_id,active,name,value,type,source)
SELECT cp.config_package_id,NULL,0,1,'45704091',old.value,old.type,old.source
FROM config_packages cp CROSS JOIN mosey_old old WHERE cp.name='com.google.android.gms.nearby'
ON CONFLICT(config_package_id,account_id,active,name) DO UPDATE SET
  value=excluded.value,type=excluded.type,source=excluded.source;
INSERT OR IGNORE INTO experiment_states_to_overrides(experiment_state_id,override_id)
SELECT cp.committed_experiment_state_id,o.override_id FROM config_packages cp
JOIN flag_overrides o USING(config_package_id)
WHERE cp.name='com.google.android.gms.nearby' AND o.account_id=0 AND o.active=1
  AND o.name='45704091' AND EXISTS(SELECT 1 FROM mosey_old);
COMMIT;
