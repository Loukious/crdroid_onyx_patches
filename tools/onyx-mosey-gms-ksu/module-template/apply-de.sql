PRAGMA foreign_keys=ON;
BEGIN IMMEDIATE;
CREATE TEMP TABLE mosey_assert(ok INTEGER NOT NULL CHECK(ok=1));
INSERT INTO mosey_assert SELECT (SELECT user_version FROM pragma_user_version)=1036;
INSERT INTO mosey_assert SELECT COUNT(*)=4 FROM pragma_table_info('flag_overrides');
INSERT INTO mosey_assert SELECT COUNT(*)=4 FROM pragma_table_info('flag_overrides')
  WHERE name IN('config_package_id','name','value','type');
INSERT INTO mosey_assert SELECT COUNT(*) FROM config_packages WHERE name='com.google.android.gms.nearby';
INSERT INTO mosey_assert SELECT NOT EXISTS(SELECT 1 FROM flag_overrides o JOIN config_packages cp USING(config_package_id)
  WHERE cp.name='com.google.android.gms.nearby' AND o.name='45704091'
    AND (o.type!=2 OR typeof(o.value)!='integer' OR o.value NOT IN(0,1)));
CREATE TEMP TABLE mosey_changes(initial INTEGER);
INSERT INTO mosey_changes SELECT total_changes();
INSERT INTO flag_overrides(config_package_id,name,value,type)
SELECT config_package_id,'45704091',1,2 FROM config_packages WHERE name='com.google.android.gms.nearby'
ON CONFLICT(config_package_id,name) DO UPDATE SET value=excluded.value,type=excluded.type
WHERE flag_overrides.value!=1 OR flag_overrides.type!=2;
SELECT CASE WHEN total_changes()>(SELECT initial+1 FROM mosey_changes) THEN 'changed' ELSE 'unchanged' END;
COMMIT;
