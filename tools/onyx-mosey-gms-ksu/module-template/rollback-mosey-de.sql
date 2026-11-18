PRAGMA foreign_keys=ON;
BEGIN IMMEDIATE;
CREATE TEMP TABLE mosey_assert(ok INTEGER NOT NULL CHECK(ok=1));
INSERT INTO mosey_assert SELECT (SELECT user_version FROM pragma_user_version)=1036
  AND (SELECT user_version FROM baseline.pragma_user_version)=1036;
INSERT INTO mosey_assert SELECT (SELECT COUNT(*) FROM pragma_table_info('flag_overrides'))=4
  AND (SELECT COUNT(*) FROM baseline.pragma_table_info('flag_overrides'))=4;
INSERT INTO mosey_assert SELECT COUNT(*) FROM config_packages WHERE name='mosey_app_android#com.google.android.mosey';
CREATE TEMP TABLE mosey_old AS SELECT o.name,o.value,o.type FROM baseline.flag_overrides o
  JOIN baseline.config_packages cp USING(config_package_id) JOIN mosey_expected e ON e.name=o.name
  WHERE cp.name='mosey_app_android#com.google.android.mosey';
INSERT INTO mosey_assert SELECT NOT EXISTS(SELECT name FROM mosey_old GROUP BY name HAVING COUNT(*)>1);
INSERT INTO mosey_assert SELECT NOT EXISTS(SELECT 1 FROM mosey_old o JOIN mosey_expected e ON e.name=o.name
  WHERE o.type!=e.type OR (e.type=2 AND (typeof(o.value)!='integer' OR o.value NOT IN(0,1))) OR
    (e.type=5 AND (typeof(o.value)!='blob' OR NOT EXISTS(
      SELECT 1 FROM mosey_maps m WHERE o.value=m.previous OR o.value=m.desired))));
DELETE FROM flag_overrides WHERE config_package_id IN(
  SELECT config_package_id FROM config_packages WHERE name='mosey_app_android#com.google.android.mosey')
  AND name IN(SELECT name FROM mosey_expected)
  AND NOT EXISTS(SELECT 1 FROM mosey_old old WHERE old.name=flag_overrides.name);
INSERT INTO flag_overrides(config_package_id,name,value,type)
SELECT cp.config_package_id,old.name,old.value,old.type FROM config_packages cp CROSS JOIN mosey_old old
WHERE cp.name='mosey_app_android#com.google.android.mosey'
ON CONFLICT(config_package_id,name) DO UPDATE SET value=excluded.value,type=excluded.type;
COMMIT;
