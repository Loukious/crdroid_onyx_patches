PRAGMA foreign_keys=ON;
BEGIN IMMEDIATE;
CREATE TEMP TABLE mosey_assert(ok INTEGER NOT NULL CHECK(ok=1));
INSERT INTO mosey_assert SELECT (SELECT user_version FROM pragma_user_version)=1036
  AND (SELECT user_version FROM baseline.pragma_user_version)=1036;
INSERT INTO mosey_assert SELECT (SELECT COUNT(*) FROM pragma_table_info('flag_overrides'))=4
  AND (SELECT COUNT(*) FROM baseline.pragma_table_info('flag_overrides'))=4;
INSERT INTO mosey_assert SELECT COUNT(*) FROM config_packages WHERE name='com.google.android.gms.nearby';
CREATE TEMP TABLE mosey_old AS SELECT o.value,o.type FROM baseline.flag_overrides o
  JOIN baseline.config_packages cp USING(config_package_id)
  WHERE cp.name='com.google.android.gms.nearby' AND o.name='45704091';
INSERT INTO mosey_assert SELECT COUNT(*)<=1 FROM mosey_old;
INSERT INTO mosey_assert SELECT NOT EXISTS(SELECT 1 FROM mosey_old
  WHERE type!=2 OR typeof(value)!='integer' OR value NOT IN(0,1));
DELETE FROM flag_overrides WHERE config_package_id IN(
  SELECT config_package_id FROM config_packages WHERE name='com.google.android.gms.nearby')
  AND name='45704091' AND NOT EXISTS(SELECT 1 FROM mosey_old);
INSERT INTO flag_overrides(config_package_id,name,value,type)
SELECT cp.config_package_id,'45704091',old.value,old.type FROM config_packages cp CROSS JOIN mosey_old old
WHERE cp.name='com.google.android.gms.nearby'
ON CONFLICT(config_package_id,name) DO UPDATE SET value=excluded.value,type=excluded.type;
COMMIT;
