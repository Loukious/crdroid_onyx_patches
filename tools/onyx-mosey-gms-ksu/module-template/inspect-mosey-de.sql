SELECT CASE
  WHEN (SELECT user_version FROM pragma_user_version)!=1036
    OR (SELECT COUNT(*) FROM pragma_table_info('flag_overrides'))!=4
    OR (SELECT COUNT(*) FROM pragma_table_info('flag_overrides')
      WHERE name IN('config_package_id','name','value','type'))!=4 THEN 'schema-mismatch'
  WHEN (SELECT COUNT(*) FROM config_packages WHERE name='mosey_app_android#com.google.android.mosey')!=1 THEN 'not-ready'
  WHEN EXISTS(SELECT 1 FROM flag_overrides o JOIN config_packages cp USING(config_package_id)
    JOIN mosey_expected e ON e.name=o.name
    WHERE cp.name='mosey_app_android#com.google.android.mosey'
      AND (o.type!=e.type OR (e.type=2 AND (typeof(o.value)!='integer' OR o.value NOT IN(0,1))) OR
        (e.type=5 AND (typeof(o.value)!='blob' OR NOT EXISTS(
          SELECT 1 FROM mosey_maps m WHERE o.value=m.previous OR o.value=m.desired))))) THEN 'unsupported-value'
  WHEN EXISTS(SELECT 1 FROM mosey_expected e WHERE NOT EXISTS(
    SELECT 1 FROM flag_overrides o JOIN config_packages cp USING(config_package_id)
    WHERE cp.name='mosey_app_android#com.google.android.mosey' AND o.name=e.name)) THEN 'absent'
  WHEN EXISTS(SELECT 1 FROM flag_overrides o JOIN config_packages cp USING(config_package_id)
    JOIN mosey_expected e ON e.name=o.name
    WHERE cp.name='mosey_app_android#com.google.android.mosey'
      AND ((e.type=2 AND o.value!=1) OR (e.type=5 AND NOT EXISTS(
        SELECT 1 FROM mosey_maps m WHERE o.value=m.desired)))) THEN 'false'
  ELSE 'true'
END;
