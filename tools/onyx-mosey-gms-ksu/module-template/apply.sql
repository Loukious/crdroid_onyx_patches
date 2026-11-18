PRAGMA foreign_keys=ON;
BEGIN IMMEDIATE;
CREATE TEMP TABLE mosey_assert(ok INTEGER NOT NULL CHECK(ok=1));
INSERT INTO mosey_assert SELECT (SELECT user_version FROM pragma_user_version)=1036;
INSERT INTO mosey_assert SELECT COUNT(*)=9 FROM pragma_table_info('flag_overrides');
INSERT INTO mosey_assert SELECT COUNT(*) FROM config_packages cp
  JOIN experiment_states es ON es.experiment_state_id=cp.committed_experiment_state_id
  JOIN accounts a ON a.account_id=es.account_id
  WHERE cp.name='com.google.android.gms.nearby' AND es.config_package_id=cp.config_package_id
    AND a.account_id=0 AND a.name='';
INSERT INTO mosey_assert SELECT NOT EXISTS(SELECT 1 FROM flag_overrides o
  JOIN config_packages cp USING(config_package_id)
  WHERE cp.name='com.google.android.gms.nearby' AND o.account_id=0 AND o.active=1
    AND o.name='45704091' AND (o.type!=2 OR typeof(o.value)!='integer' OR o.value NOT IN(0,1)));
CREATE TEMP TABLE mosey_changes(initial INTEGER);
INSERT INTO mosey_changes SELECT total_changes();
INSERT INTO flag_overrides(config_package_id,config_package_name,account_id,active,name,value,type,source)
SELECT cp.config_package_id,NULL,0,1,'45704091',1,2,0 FROM config_packages cp
WHERE cp.name='com.google.android.gms.nearby'
ON CONFLICT(config_package_id,account_id,active,name) DO UPDATE SET value=excluded.value,type=excluded.type
WHERE flag_overrides.value!=1 OR flag_overrides.type!=2;
INSERT OR IGNORE INTO experiment_states_to_overrides(experiment_state_id,override_id)
SELECT es.experiment_state_id,o.override_id FROM config_packages cp
JOIN experiment_states es ON es.config_package_id=cp.config_package_id AND es.account_id=0
JOIN flag_overrides o ON o.config_package_id=cp.config_package_id AND o.account_id=0
  AND o.active=1 AND o.name='45704091'
WHERE cp.name='com.google.android.gms.nearby'
  AND (es.experiment_state_id=cp.committed_experiment_state_id
    OR es.experiment_state_id=(SELECT MAX(s.experiment_state_id) FROM experiment_states s
       WHERE s.config_package_id=cp.config_package_id AND s.account_id=0));
-- The bookkeeping INSERT above itself counts once; exclude it from the result.
SELECT CASE WHEN total_changes()>(SELECT initial+1 FROM mosey_changes)
  THEN 'changed' ELSE 'unchanged' END;
COMMIT;
