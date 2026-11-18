SELECT CASE
  WHEN (SELECT user_version FROM pragma_user_version)!=1036
    OR (SELECT COUNT(*) FROM pragma_table_info('flag_overrides'))!=9 THEN 'schema-mismatch'
  WHEN (SELECT COUNT(*) FROM config_packages cp
    JOIN experiment_states es ON es.experiment_state_id=cp.committed_experiment_state_id
    JOIN accounts a ON a.account_id=es.account_id
    WHERE cp.name='mosey_app_android#com.google.android.mosey'
      AND es.config_package_id=cp.config_package_id AND a.account_id=0 AND a.name='')!=1 THEN 'not-ready'
  WHEN EXISTS(SELECT 1 FROM flag_overrides o JOIN config_packages cp USING(config_package_id)
    JOIN mosey_expected e ON e.name=o.name
    WHERE cp.name='mosey_app_android#com.google.android.mosey' AND o.account_id=0 AND o.active=1
      AND (o.type!=e.type OR
        (e.type=2 AND (typeof(o.value)!='integer' OR o.value NOT IN(0,1))) OR
        (e.type=5 AND (typeof(o.value)!='blob' OR NOT EXISTS(
          SELECT 1 FROM mosey_maps m WHERE o.value=m.previous OR o.value=m.desired))))) THEN 'unsupported-value'
  WHEN EXISTS(SELECT 1 FROM mosey_expected e WHERE NOT EXISTS(
    SELECT 1 FROM flag_overrides o JOIN config_packages cp USING(config_package_id)
    WHERE cp.name='mosey_app_android#com.google.android.mosey' AND o.account_id=0 AND o.active=1
      AND o.name=e.name)) THEN 'absent'
  WHEN EXISTS(SELECT 1 FROM flag_overrides o JOIN config_packages cp USING(config_package_id)
    JOIN mosey_expected e ON e.name=o.name
    WHERE cp.name='mosey_app_android#com.google.android.mosey' AND o.account_id=0 AND o.active=1
      AND ((e.type=2 AND o.value!=1) OR (e.type=5 AND NOT EXISTS(
        SELECT 1 FROM mosey_maps m WHERE o.value=m.desired)))) THEN 'false'
  WHEN EXISTS(SELECT 1 FROM config_packages cp
    JOIN experiment_states es ON es.config_package_id=cp.config_package_id AND es.account_id=0
    JOIN flag_overrides o ON o.config_package_id=cp.config_package_id AND o.account_id=0 AND o.active=1
    JOIN mosey_expected e ON e.name=o.name
    WHERE cp.name='mosey_app_android#com.google.android.mosey'
      AND (es.experiment_state_id=cp.committed_experiment_state_id OR es.experiment_state_id=(
        SELECT MAX(s.experiment_state_id) FROM experiment_states s
        WHERE s.config_package_id=cp.config_package_id AND s.account_id=0))
      AND NOT EXISTS(SELECT 1 FROM experiment_states_to_overrides l
        WHERE l.experiment_state_id=es.experiment_state_id AND l.override_id=o.override_id)) THEN 'unlinked'
  ELSE 'true'
END;
