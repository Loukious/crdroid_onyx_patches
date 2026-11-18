PRAGMA foreign_keys=ON;
BEGIN IMMEDIATE;
CREATE TEMP TABLE mosey_assert(ok INTEGER NOT NULL CHECK(ok=1));
INSERT INTO mosey_assert SELECT (SELECT user_version FROM pragma_user_version)=1036;
INSERT INTO mosey_assert SELECT COUNT(*)=9 FROM pragma_table_info('flag_overrides');
INSERT INTO mosey_assert SELECT COUNT(*) FROM config_packages cp
  JOIN experiment_states es ON es.experiment_state_id=cp.committed_experiment_state_id
  JOIN accounts a ON a.account_id=es.account_id
  WHERE cp.name='mosey_app_android#com.google.android.mosey' AND es.config_package_id=cp.config_package_id
    AND a.account_id=0 AND a.name='';
INSERT INTO mosey_assert SELECT NOT EXISTS(SELECT 1 FROM flag_overrides o
  JOIN config_packages cp USING(config_package_id) JOIN mosey_expected e ON e.name=o.name
  WHERE cp.name='mosey_app_android#com.google.android.mosey' AND o.account_id=0 AND o.active=1
    AND (o.type!=e.type OR (e.type=2 AND (typeof(o.value)!='integer' OR o.value NOT IN(0,1))) OR
      (e.type=5 AND (typeof(o.value)!='blob' OR NOT EXISTS(
        SELECT 1 FROM mosey_maps m WHERE o.value=m.previous OR o.value=m.desired)))));
CREATE TEMP TABLE mosey_changes(initial INTEGER);
INSERT INTO mosey_changes SELECT total_changes();
INSERT INTO flag_overrides(config_package_id,config_package_name,account_id,active,name,value,type,source)
SELECT cp.config_package_id,NULL,0,1,e.name,e.value,e.type,0 FROM config_packages cp CROSS JOIN mosey_expected e
WHERE cp.name='mosey_app_android#com.google.android.mosey'
ON CONFLICT(config_package_id,account_id,active,name) DO UPDATE SET
  value=CASE WHEN excluded.type=5 THEN COALESCE(
    (SELECT desired FROM mosey_maps WHERE previous=flag_overrides.value),excluded.value) ELSE excluded.value END,
  type=excluded.type
WHERE (excluded.type=2 AND flag_overrides.value!=1) OR (excluded.type=5 AND NOT EXISTS(
  SELECT 1 FROM mosey_maps m WHERE flag_overrides.value=m.desired));
INSERT OR IGNORE INTO experiment_states_to_overrides(experiment_state_id,override_id)
SELECT es.experiment_state_id,o.override_id FROM config_packages cp
JOIN experiment_states es ON es.config_package_id=cp.config_package_id AND es.account_id=0
JOIN flag_overrides o ON o.config_package_id=cp.config_package_id AND o.account_id=0 AND o.active=1
JOIN mosey_expected e ON e.name=o.name
WHERE cp.name='mosey_app_android#com.google.android.mosey'
  AND (es.experiment_state_id=cp.committed_experiment_state_id OR es.experiment_state_id=(
    SELECT MAX(s.experiment_state_id) FROM experiment_states s
    WHERE s.config_package_id=cp.config_package_id AND s.account_id=0));
SELECT CASE WHEN total_changes()>(SELECT initial+1 FROM mosey_changes) THEN 'changed' ELSE 'unchanged' END;
COMMIT;
