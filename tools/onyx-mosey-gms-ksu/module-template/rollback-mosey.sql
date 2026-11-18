-- Restore only the managed hopping Boolean; country metadata is never restored here.
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
  WHERE cp.name='mosey_app_android#com.google.android.mosey' AND es.config_package_id=cp.config_package_id
    AND a.account_id=0 AND a.name='';
CREATE TEMP TABLE mosey_old AS SELECT o.name,o.value,o.type,o.source FROM baseline.flag_overrides o
  JOIN baseline.config_packages cp USING(config_package_id) JOIN mosey_expected e ON e.name=o.name
  WHERE cp.name='mosey_app_android#com.google.android.mosey' AND o.account_id=0 AND o.active=1;
INSERT INTO mosey_assert SELECT NOT EXISTS(SELECT name FROM mosey_old GROUP BY name HAVING COUNT(*)>1);
INSERT INTO mosey_assert SELECT NOT EXISTS(SELECT 1 FROM mosey_old o JOIN mosey_expected e ON e.name=o.name
  WHERE o.type!=e.type OR (e.type=2 AND (typeof(o.value)!='integer' OR o.value NOT IN(0,1))) OR
    (e.type=5 AND (typeof(o.value)!='blob' OR NOT EXISTS(
      SELECT 1 FROM mosey_maps m WHERE o.value=m.previous OR o.value=m.desired))));
DELETE FROM experiment_states_to_overrides WHERE override_id IN(
  SELECT o.override_id FROM flag_overrides o JOIN config_packages cp USING(config_package_id)
  JOIN mosey_expected e ON e.name=o.name
  WHERE cp.name='mosey_app_android#com.google.android.mosey' AND o.account_id=0 AND o.active=1
    AND NOT EXISTS(SELECT 1 FROM mosey_old old WHERE old.name=o.name));
DELETE FROM flag_overrides_to_commit WHERE override_id IN(
  SELECT o.override_id FROM flag_overrides o JOIN config_packages cp USING(config_package_id)
  JOIN mosey_expected e ON e.name=o.name
  WHERE cp.name='mosey_app_android#com.google.android.mosey' AND o.account_id=0 AND o.active=1
    AND NOT EXISTS(SELECT 1 FROM mosey_old old WHERE old.name=o.name));
DELETE FROM flag_overrides WHERE config_package_id IN(
  SELECT config_package_id FROM config_packages WHERE name='mosey_app_android#com.google.android.mosey')
  AND account_id=0 AND active=1 AND name IN(SELECT name FROM mosey_expected)
  AND NOT EXISTS(SELECT 1 FROM mosey_old old WHERE old.name=flag_overrides.name);
INSERT INTO flag_overrides(config_package_id,config_package_name,account_id,active,name,value,type,source)
SELECT cp.config_package_id,NULL,0,1,old.name,old.value,old.type,old.source
FROM config_packages cp CROSS JOIN mosey_old old WHERE cp.name='mosey_app_android#com.google.android.mosey'
ON CONFLICT(config_package_id,account_id,active,name) DO UPDATE SET
  value=excluded.value,type=excluded.type,source=excluded.source;
INSERT OR IGNORE INTO experiment_states_to_overrides(experiment_state_id,override_id)
SELECT cp.committed_experiment_state_id,o.override_id FROM config_packages cp
JOIN flag_overrides o USING(config_package_id) JOIN mosey_old old ON old.name=o.name
WHERE cp.name='mosey_app_android#com.google.android.mosey' AND o.account_id=0 AND o.active=1;
COMMIT;
