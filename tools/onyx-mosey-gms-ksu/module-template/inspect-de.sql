SELECT CASE
  WHEN (SELECT user_version FROM pragma_user_version)!=1036
    OR (SELECT COUNT(*) FROM pragma_table_info('flag_overrides'))!=4
    OR (SELECT COUNT(*) FROM pragma_table_info('flag_overrides')
        WHERE name IN('config_package_id','name','value','type'))!=4 THEN 'schema-mismatch'
  WHEN (SELECT COUNT(*) FROM config_packages WHERE name='com.google.android.gms.nearby')!=1 THEN 'not-ready'
  WHEN EXISTS(SELECT 1 FROM flag_overrides o JOIN config_packages cp USING(config_package_id)
    WHERE cp.name='com.google.android.gms.nearby' AND o.name='45704091'
      AND (o.type!=2 OR typeof(o.value)!='integer' OR o.value NOT IN(0,1))) THEN 'unsupported-value'
  WHEN NOT EXISTS(SELECT 1 FROM flag_overrides o JOIN config_packages cp USING(config_package_id)
    WHERE cp.name='com.google.android.gms.nearby' AND o.name='45704091') THEN 'absent'
  WHEN EXISTS(SELECT 1 FROM flag_overrides o JOIN config_packages cp USING(config_package_id)
    WHERE cp.name='com.google.android.gms.nearby' AND o.name='45704091' AND o.value=0) THEN 'false'
  ELSE 'true'
END;
