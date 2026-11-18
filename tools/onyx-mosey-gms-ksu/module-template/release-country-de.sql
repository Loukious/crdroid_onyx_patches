-- Release only the legacy country entry in the independently backed-up DE DB.
PRAGMA foreign_keys=ON;
BEGIN IMMEDIATE;
CREATE TEMP TABLE country_assert(ok INTEGER NOT NULL CHECK(ok=1));
INSERT INTO country_assert SELECT (SELECT user_version FROM pragma_user_version)=1036
  AND (SELECT user_version FROM baseline.pragma_user_version)=1036;
INSERT INTO country_assert SELECT (SELECT COUNT(*) FROM pragma_table_info('flag_overrides'))=4
  AND (SELECT COUNT(*) FROM baseline.pragma_table_info('flag_overrides'))=4;
CREATE TEMP TABLE country_package AS SELECT config_package_id FROM config_packages
  WHERE name='mosey_app_android#com.google.android.mosey';
CREATE TEMP TABLE country_baseline_package AS SELECT config_package_id FROM baseline.config_packages
  WHERE name='mosey_app_android#com.google.android.mosey';
INSERT INTO country_assert SELECT (SELECT COUNT(*) FROM country_package)=1
  AND (SELECT COUNT(*) FROM country_baseline_package)=1
  AND (SELECT config_package_id FROM country_package)=(SELECT config_package_id FROM country_baseline_package);
CREATE TEMP TABLE country_old AS SELECT o.* FROM baseline.flag_overrides o
  JOIN country_baseline_package cp USING(config_package_id) WHERE o.name='45718707';
CREATE TEMP TABLE country_current AS SELECT o.* FROM flag_overrides o
  JOIN country_package cp USING(config_package_id) WHERE o.name='45718707';
INSERT INTO country_assert SELECT (SELECT COUNT(*) FROM country_old)<=1
  AND (SELECT COUNT(*) FROM country_current)<=1;
INSERT INTO country_assert SELECT NOT EXISTS(SELECT 1 FROM country_old old WHERE NOT EXISTS(
  SELECT 1 FROM country_current cur WHERE cur.config_package_id=old.config_package_id AND cur.name=old.name
    AND cur.type=old.type AND (cur.value IS old.value OR (old.type=5 AND typeof(old.value)='blob'
      AND typeof(cur.value)='blob' AND EXISTS(SELECT 1 FROM mosey_maps m
        WHERE old.value=m.previous AND cur.value=m.desired)))));
INSERT INTO country_assert SELECT EXISTS(SELECT 1 FROM country_old)
  OR NOT EXISTS(SELECT 1 FROM country_current)
  OR (EXISTS(SELECT 1 FROM country_current cur JOIN mosey_legacy_country expected ON cur.name=expected.name
      WHERE cur.type=expected.type AND typeof(cur.value)='blob' AND cur.value=expected.value)
    AND EXISTS(SELECT 1 FROM baseline.config_packages cp JOIN mosey_snapshot s ON s.content=cp.flags_content
      WHERE cp.name='mosey_app_android#com.google.android.mosey'));
CREATE TEMP TABLE country_changes(initial INTEGER);
INSERT INTO country_changes SELECT total_changes();
UPDATE flag_overrides SET value=(SELECT old.value FROM country_old old WHERE old.name=flag_overrides.name)
  WHERE config_package_id IN(SELECT config_package_id FROM country_package)
    AND name IN(SELECT name FROM country_old)
    AND value IS NOT (SELECT old.value FROM country_old old WHERE old.name=flag_overrides.name);
DELETE FROM flag_overrides WHERE config_package_id IN(SELECT config_package_id FROM country_package)
  AND name='45718707' AND NOT EXISTS(SELECT 1 FROM country_old);
SELECT CASE WHEN total_changes()>(SELECT initial+1 FROM country_changes) THEN 'changed' ELSE 'unchanged' END;
COMMIT;
