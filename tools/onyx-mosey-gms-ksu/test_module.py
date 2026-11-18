#!/usr/bin/env python3
"""Exercise scoped transactions, rollback, WAL backup and provider startup guards."""
import os
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
import zlib

HERE = Path(__file__).resolve().parent
MODULE = HERE / "module-template"
SQLITE = shutil.which("sqlite3")
MKSH = os.environ.get("MOSEY_TEST_MKSH") or shutil.which("mksh")
SCHEMA = """
PRAGMA user_version=1036;
PRAGMA foreign_keys=ON;
CREATE TABLE accounts(account_id INTEGER PRIMARY KEY,name TEXT UNIQUE NOT NULL);
CREATE TABLE config_packages(config_package_id INTEGER PRIMARY KEY,name TEXT UNIQUE NOT NULL,
  committed_experiment_state_id INTEGER REFERENCES experiment_states);
CREATE TABLE experiment_states(experiment_state_id INTEGER PRIMARY KEY,
  account_id INTEGER NOT NULL REFERENCES accounts,config_package_id INTEGER NOT NULL REFERENCES config_packages);
CREATE TABLE flag_overrides(override_id INTEGER PRIMARY KEY,
  config_package_id INTEGER REFERENCES config_packages,config_package_name TEXT,
  account_id INTEGER NOT NULL REFERENCES accounts,active INTEGER DEFAULT 1,name TEXT NOT NULL,
  value NOT NULL,type INTEGER NOT NULL,source INTEGER DEFAULT 0,
  UNIQUE(config_package_id,account_id,active,name),UNIQUE(config_package_name,account_id,active,name),
  CHECK(active IS NULL OR active IS 1),CHECK((config_package_id IS NULL)!=(config_package_name IS NULL)));
CREATE TABLE experiment_states_to_overrides(experiment_state_id INTEGER NOT NULL REFERENCES experiment_states,
  override_id INTEGER NOT NULL REFERENCES flag_overrides,PRIMARY KEY(experiment_state_id,override_id));
CREATE TABLE flag_overrides_to_commit(override_id INTEGER NOT NULL REFERENCES flag_overrides,
  config_package_id INTEGER NOT NULL REFERENCES config_packages,account_id INTEGER NOT NULL REFERENCES accounts,
  PRIMARY KEY(override_id,config_package_id,account_id));
INSERT INTO accounts VALUES(0,''),(1,'other-account');
INSERT INTO config_packages VALUES(42,'com.google.android.gms.nearby',NULL),(43,'other.namespace',NULL);
INSERT INTO experiment_states VALUES(100,0,42),(101,0,42),(102,1,42),(103,0,43);
UPDATE config_packages SET committed_experiment_state_id=100 WHERE config_package_id=42;
UPDATE config_packages SET committed_experiment_state_id=103 WHERE config_package_id=43;
INSERT INTO flag_overrides VALUES(20,42,NULL,1,1,'45704091',0,2,77),
 (21,43,NULL,0,1,'45704091',0,2,77),(22,42,NULL,0,1,'unrelated.flag',23,1,77);
INSERT INTO experiment_states_to_overrides VALUES(102,20),(103,21),(100,22),(101,22);
"""


class ModuleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="mosey-module-test-")
        self.root = Path(self.temp.name)
        self.db = self.root / "phenotype.db"
        self.c = sqlite3.connect(self.db)
        self.c.executescript(SCHEMA)
        self.c.commit()

    def tearDown(self):
        self.c.close()
        self.temp.cleanup()

    def cli(self, text, check=True):
        return subprocess.run([SQLITE, "-bail", str(self.db)], input=text,
                              text=True, capture_output=True, check=check)

    def run_sql(self, name, check=True):
        return self.cli((MODULE / name).read_text(), check=check).stdout.strip()

    def unrelated(self):
        return (self.c.execute("SELECT * FROM flag_overrides WHERE override_id IN(20,21,22)").fetchall(),
                self.c.execute("SELECT * FROM experiment_states_to_overrides WHERE override_id IN(20,21,22)").fetchall(),
                self.c.execute("SELECT * FROM config_packages").fetchall(),
                self.c.execute("SELECT * FROM accounts").fetchall())

    def target(self, value, type_=2, linked=True):
        self.c.execute("INSERT INTO flag_overrides VALUES(1,42,NULL,0,1,'45704091',?,?,77)", (value, type_))
        if linked:
            self.c.execute("INSERT INTO experiment_states_to_overrides VALUES(100,1)")
        self.c.commit()

    def backup(self):
        path = self.root / "before.sqlite"
        with sqlite3.connect(path) as dest:
            self.c.backup(dest)
        return path

    def rollback(self, backup):
        self.cli("ATTACH DATABASE 'file:" + str(backup) + "?mode=ro' AS baseline;\n"
                 + (MODULE / "rollback.sql").read_text())

    def test_absent_scoped_insert_pending_link_and_idempotence(self):
        before = self.unrelated()
        self.assertEqual("absent", self.run_sql("inspect.sql"))
        self.assertEqual("changed", self.run_sql("apply.sql"))
        self.assertEqual("true", self.run_sql("inspect.sql"))
        target = self.c.execute("SELECT override_id,value,type,source FROM flag_overrides WHERE account_id=0 AND config_package_id=42 AND name='45704091'").fetchone()
        self.assertEqual((1, 2, 0), target[1:])
        self.assertEqual([(100,), (101,)], self.c.execute("SELECT experiment_state_id FROM experiment_states_to_overrides WHERE override_id=? ORDER BY 1", (target[0],)).fetchall())
        self.assertEqual("unchanged", self.run_sql("apply.sql"))
        self.assertEqual(before, self.unrelated())
        self.assertEqual([], self.c.execute("PRAGMA foreign_key_check").fetchall())

    def test_existing_false_preserves_source_and_scoped_rollback(self):
        self.target(0)
        backup = self.backup()
        before = self.unrelated()
        self.assertEqual("changed", self.run_sql("apply.sql"))
        self.assertEqual((1, 2, 77), self.c.execute("SELECT value,type,source FROM flag_overrides WHERE override_id=1").fetchone())
        self.rollback(backup)
        self.assertEqual((0, 2, 77), self.c.execute("SELECT value,type,source FROM flag_overrides WHERE override_id=1").fetchone())
        self.assertEqual(before, self.unrelated())

    def test_rollback_absent_removes_only_created_override_and_references(self):
        backup = self.backup()
        before = self.unrelated()
        self.run_sql("apply.sql")
        target_id = self.c.execute("SELECT override_id FROM flag_overrides WHERE account_id=0 AND config_package_id=42 AND name='45704091'").fetchone()[0]
        self.c.execute("INSERT INTO flag_overrides_to_commit VALUES(?,42,0)", (target_id,))
        self.c.commit()
        self.rollback(backup)
        self.assertEqual("absent", self.run_sql("inspect.sql"))
        self.assertEqual(before, self.unrelated())
        self.assertEqual([], self.c.execute("PRAGMA foreign_key_check").fetchall())

    def test_new_committed_state_and_latest_pending_state(self):
        self.target(0)
        self.c.execute("INSERT INTO experiment_states VALUES(105,0,42)")
        self.c.execute("UPDATE config_packages SET committed_experiment_state_id=101 WHERE config_package_id=42")
        self.c.commit()
        self.run_sql("apply.sql")
        self.assertEqual([(100,), (101,), (105,)], self.c.execute("SELECT experiment_state_id FROM experiment_states_to_overrides WHERE override_id=1 ORDER BY 1").fetchall())

    def test_unknown_schema_and_wrong_type_reject_without_writes(self):
        before = self.unrelated()
        self.c.execute("PRAGMA user_version=1037")
        self.assertEqual("schema-mismatch", self.run_sql("inspect.sql"))
        self.assertNotEqual(0, self.cli((MODULE / "apply.sql").read_text(), check=False).returncode)
        self.assertEqual(before, self.unrelated())
        self.c.execute("PRAGMA user_version=1036")
        self.target("true", 4)
        self.assertEqual("unsupported-value", self.run_sql("inspect.sql"))
        self.assertNotEqual(0, self.cli((MODULE / "apply.sql").read_text(), check=False).returncode)
        self.assertEqual(("true", 4), self.c.execute("SELECT value,type FROM flag_overrides WHERE override_id=1").fetchone())
        self.assertEqual(before, self.unrelated())

    def test_missing_registration_and_missing_ce_do_not_create_data(self):
        self.c.execute("UPDATE config_packages SET committed_experiment_state_id=NULL WHERE config_package_id=42")
        self.c.commit()
        self.assertEqual("not-ready", self.run_sql("inspect.sql"))
        self.assertNotEqual(0, self.cli((MODULE / "apply.sql").read_text(), check=False).returncode)
        missing = self.root / "unavailable-ce.db"
        run = subprocess.run([SQLITE, "-bail", "-readonly", str(missing)], input="SELECT 1;", text=True, capture_output=True)
        self.assertNotEqual(0, run.returncode)
        self.assertFalse(missing.exists())

    def test_shell_apply_coherent_wal_backup_and_repeat(self):
        self.c.execute("PRAGMA journal_mode=WAL")
        self.target(0)
        state = self.root / "state"
        state.mkdir()
        command = (f'. {shlex.quote(str(MODULE / "common.sh"))}\n'
                   f'MOSEY_MOD={shlex.quote(str(MODULE))}\nMOSEY_STATE={shlex.quote(str(state))}\n'
                   f'MOSEY_SQLITE={shlex.quote(SQLITE)}\n'
                   f'mosey_apply_database {shlex.quote(str(self.db))} ce\n')
        run = subprocess.run(["sh", "-c", command], text=True, capture_output=True, check=True)
        self.assertEqual("changed", run.stdout.strip())
        with sqlite3.connect(state / "ce-before.sqlite") as before:
            self.assertEqual((0,), before.execute("SELECT value FROM flag_overrides WHERE override_id=1").fetchone())
            self.assertEqual(("ok",), before.execute("PRAGMA quick_check").fetchone())
        self.assertEqual("unchanged", subprocess.run(["sh", "-c", command], text=True, capture_output=True, check=True).stdout.strip())

    def test_provider_requires_true_flag_binder_and_enabled_package(self):
        self.target(0)
        calls = self.root / "calls"
        state = self.root / "state"
        state.mkdir()
        fixture = HERE / 'tests/services-provider-delegate.dump'
        requested = self.root / 'delegate-requested'
        prefix = (f'. {shlex.quote(str(MODULE / "common.sh"))}\n'
                  f'MOSEY_MOD={shlex.quote(str(MODULE))}\nMOSEY_STATE={shlex.quote(str(state))}\n'
                  f'MOSEY_CE={shlex.quote(str(self.db))}\nMOSEY_SQLITE={shlex.quote(SQLITE)}\n'
                  'sleep() { :; }\nmosey_pid_live() { [ "$1" = 13590 ]; }\n'
                  f'''mosey_framework() {{
case "$*" in
 "timeout 2 service check com.google.android.moseyservice.IMoseyService/default") echo "Service: $MOSEY_TEST_BINDER";;
 "pm list packages -e --user 0 com.google.android.mosey") echo package:com.google.android.mosey;;
 "pm enable --user 0 com.google.android.mosey/.ExternalSharingService"|"cmd deviceidle tempwhitelist -d 30000 com.google.android.mosey") printf '%s\\n' "$*" >> {shlex.quote(str(calls))};;
 "am startservice --user 0 -n com.google.android.mosey/.ExternalSharingService") printf '%s\\n' "$*" >> {shlex.quote(str(calls))}; echo "Starting service: Intent {{ cmp=com.google.android.mosey/.ExternalSharingService }}";;
 "timeout 3 dumpsys activity services com.google.android.mosey")
   if [ -f {shlex.quote(str(requested))} ]; then cat {shlex.quote(str(fixture))};
   else sed 's/isFgsDelegate=true/isFgsDelegate=false/' {shlex.quote(str(fixture))}; fi;;
 "cmd activity set-foreground-service-delegate --user 0 com.google.android.mosey start") printf '%s\\n' "$*" >> {shlex.quote(str(calls))}; touch {shlex.quote(str(requested))};;
 *) exit 70;;
esac
}}\n''')
        found = 'MOSEY_TEST_BINDER=found\n'
        self.assertNotEqual(0, subprocess.run(["sh", "-c", prefix + found + "mosey_provider_start"], capture_output=True).returncode)
        self.assertFalse(calls.exists())
        self.run_sql("apply.sql")
        missing = 'MOSEY_TEST_BINDER="not found"\n'
        self.assertNotEqual(0, subprocess.run(["sh", "-c", prefix + missing + "mosey_provider_start"], capture_output=True).returncode)
        self.assertFalse(calls.exists())
        subprocess.run(["sh", "-c", prefix + found + "mosey_provider_start"], capture_output=True, check=True)
        self.assertEqual(["pm enable --user 0 com.google.android.mosey/.ExternalSharingService",
                          "cmd deviceidle tempwhitelist -d 30000 com.google.android.mosey",
                          "am startservice --user 0 -n com.google.android.mosey/.ExternalSharingService",
                          "cmd activity set-foreground-service-delegate --user 0 com.google.android.mosey start"], calls.read_text().splitlines())


class AndroidContractTests(unittest.TestCase):
    def shell(self, body, text='', interpreter='sh'):
        prefix = '. ' + shlex.quote(str(MODULE / 'common.sh')) + '\n'
        return subprocess.run([interpreter, '-c', prefix + body], input=text, text=True,
                              capture_output=True, timeout=10)

    def test_provider_readiness_and_bounded_failures_under_mksh(self):
        # Android /system/bin/sh is mksh. Its unescaped | in a parameter
        # expansion is alternation, unlike the host's /bin/sh (dash).
        self.assertIsNotNone(MKSH, 'Install mksh or set MOSEY_TEST_MKSH to its executable.')
        version = subprocess.run([MKSH, '-c', 'printf "%s" "$KSH_VERSION"'],
                                 text=True, capture_output=True, check=True)
        self.assertIn('MIRBSD KSH', version.stdout)
        sample = (HERE / 'tests/services-provider-delegate.dump').read_text()
        process = 'app=ProcessRecord{1ee5269 13590:com.google.android.mosey/u0a638}'
        index = sample.index('SPECIAL_USE:FgsDelegate')
        cases = [
            ('matching', sample, 0, 1, 0),
            ('delegate becomes ready', sample.replace('isFgsDelegate=true', 'isFgsDelegate=false'), 0, 2, 1),
            ('provider absent', sample.replace(process, 'app=null', 1), 1, 15, 0),
            ('delegate absent', sample[:index] + sample[index:].replace(process, 'app=null'), 1, 15, 1),
            ('different live PIDs', sample[:index] + sample[index:].replace('13590:', '24680:'), 1, 15, 1),
            ('not foreground', sample.replace('isForeground=true', 'isForeground=false'), 1, 15, 1),
            ('not delegated', sample.replace('isFgsDelegate=true', 'isFgsDelegate=false'), 1, 15, 1),
        ]
        for name, dump, expected, polls, delegates in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory(prefix='mosey-mksh-') as temp:
                root = Path(temp)
                fixture = root / 'services.dump'
                fixture.write_text(dump)
                ready_fixture = root / 'ready.dump'
                ready_fixture.write_text(sample)
                delegate_action = (f'cp {shlex.quote(str(ready_fixture))} {shlex.quote(str(fixture))}'
                                   if name == 'delegate becomes ready' else ':')
                calls = root / 'calls'
                calls.touch()
                body = f'''mosey_inspect() {{ printf '%s\\n' true; }}
mosey_pid_live() {{ case "$1" in 13590|24680) return 0;; *) return 1;; esac; }}
mosey_log() {{ printf '%s\\n' "$*"; }}
sleep() {{ :; }}
mosey_framework() {{
case "$*" in
 "timeout 2 service check com.google.android.moseyservice.IMoseyService/default") printf '%s\\n' 'Service: found';;
 "pm list packages -e --user 0 com.google.android.mosey") printf '%s\\n' package:com.google.android.mosey;;
 "pm enable --user 0 com.google.android.mosey/.ExternalSharingService"|"cmd deviceidle tempwhitelist -d 30000 com.google.android.mosey"|"am startservice --user 0 -n com.google.android.mosey/.ExternalSharingService") :;;
 "timeout 3 dumpsys activity services com.google.android.mosey") printf '%s\\n' poll >> {shlex.quote(str(calls))}; cat {shlex.quote(str(fixture))};;
 "cmd activity set-foreground-service-delegate --user 0 com.google.android.mosey start") printf '%s\\n' delegate >> {shlex.quote(str(calls))}; {delegate_action};;
 *) return 70;;
esac
}}
mosey_provider_start
'''
                run = self.shell(body, interpreter=MKSH)
                self.assertEqual(expected, run.returncode, run.stdout + run.stderr)
                records = calls.read_text().splitlines()
                self.assertEqual(polls, records.count('poll'))
                self.assertEqual(delegates, records.count('delegate'))
                self.assertEqual(expected == 0, 'foreground-service delegate verified.' in run.stdout)

    def test_unlock_uses_verified_android17_api_and_exact_state(self):
        for state, expected in [('RUNNING_UNLOCKED', 0), ('RUNNING_LOCKED', 1),
                                ('RUNNING_UNLOCKING', 1), ('Unknown command: is-user-unlocked', 1)]:
            wrapper = 'mosey_framework() { [ "$*" = "timeout 3 cmd activity get-started-user-state 0" ] || return 70; printf "%s\\n" ' + shlex.quote(state) + '; }\n'
            self.assertEqual(expected, self.shell(wrapper + 'mosey_user_unlocked').returncode)

    def test_process_and_delegate_fields_are_record_local(self):
        sample = (HERE / 'tests/services-provider-delegate.dump').read_text()
        self.assertEqual('13590:13590', self.shell('mosey_parse_services', sample).stdout.strip())
        # A live delegate cannot make an app=null provider ready.
        no_provider = sample.replace('app=ProcessRecord{1ee5269 13590:com.google.android.mosey/u0a638}', 'app=null', 1)
        self.assertEqual('0:13590', self.shell('mosey_parse_services', no_provider).stdout.strip())
        # A live provider cannot make an app=null delegate ready.
        index = sample.index('SPECIAL_USE:FgsDelegate')
        no_delegate = sample[:index] + sample[index:].replace('app=ProcessRecord{1ee5269 13590:com.google.android.mosey/u0a638}', 'app=null')
        self.assertEqual('13590:0', self.shell('mosey_parse_services', no_delegate).stdout.strip())
        # The caller must require a matching provider/delegate PID.
        mismatch = sample[:index] + sample[index:].replace('13590:', '24680:')
        self.assertEqual('13590:24680', self.shell('mosey_parse_services', mismatch).stdout.strip())
        other_user = sample.replace(' u0 ', ' u10 ')
        self.assertEqual('0:0', self.shell('mosey_parse_services', other_user).stdout.strip())

    def test_actual_live_pid_and_missing_pid(self):
        for interpreter in ['sh', MKSH]:
            with self.subTest(interpreter=interpreter):
                self.assertEqual(0, self.shell('mosey_pid_live ' + str(os.getpid()), interpreter=interpreter).returncode)
                self.assertNotEqual(0, self.shell('mosey_pid_live 0', interpreter=interpreter).returncode)
                self.assertNotEqual(0, self.shell('mosey_pid_live 999999999', interpreter=interpreter).returncode)


class SharedCacheStartupTests(unittest.TestCase):
    def run_service(self, cache_result, cache_valid=True, app_sql_changed=False,
                    country_sql_changed=False, cache_country_result='unchanged'):
        with tempfile.TemporaryDirectory(prefix='mosey-cache-startup-') as temp:
            state = Path(temp)
            calls = state / 'calls'
            calls.touch()
            applied = state / 'cache-applied'
            fixtures = f'''
MOSEY_STATE={shlex.quote(str(state))}
mosey_init() {{ return 0; }}
mosey_user_unlocked() {{ return 0; }}
mosey_compatible() {{ return 0; }}
mosey_app_compatible() {{ return 0; }}
mosey_policy_apply() {{ return 0; }}
mosey_inspect() {{ printf '%s\\n' true; }}
mosey_release_country() {{
    if [ "$2" = ce-mosey ] && [ {int(country_sql_changed)} = 1 ]; then printf '%s\\n' changed;
    else printf '%s\\n' unchanged; fi
}}
mosey_apply_database() {{
    if [ "$2" = ce-mosey ] && [ {int(app_sql_changed)} = 1 ]; then
        printf '%s\\n' changed
    else
        printf '%s\\n' unchanged
    fi
}}
mosey_framework() {{
    case "$*" in
        'getprop sys.boot_completed') printf '%s\\n' 1;;
        'am force-stop --user 0 com.google.android.mosey'|'am force-stop --user 0 com.google.android.gms')
            printf '%s\\n' "$*" >> {shlex.quote(str(calls))};;
        *) return 70;;
    esac
}}
mosey_cache() {{
    case "$1" in
        --release-country)
            # Migration can write even when the managed Boolean is already true.
            grep -q 'am force-stop --user 0 com.google.android.mosey' {shlex.quote(str(calls))} || return 71
            grep -q 'am force-stop --user 0 com.google.android.gms' {shlex.quote(str(calls))} || return 72
            {'return 1' if cache_country_result == 'failure' else 'printf "%s\\n" ' + shlex.quote(cache_country_result)};;
        --apply) {'return 1' if cache_result == 'failure' else 'touch ' + shlex.quote(str(applied)) + '; printf "%s\\n" ' + shlex.quote(cache_result)};;
        --inspect)
            if [ {shlex.quote(cache_result)} = unchanged ] || [ -f {shlex.quote(str(applied))} ]; then
                printf '%s\\n' {'true' if cache_valid else 'false'}
            else
                printf '%s\\n' false
            fi;;
        *) return 70;;
    esac
}}
mosey_log() {{ printf '%s\\n' "$*"; }}
mosey_provider_start() {{ printf '%s\\n' provider >> {shlex.quote(str(calls))}; }}
'''
            source_line = '. "${0%/*}/common.sh"'
            service = (MODULE / 'service.sh').read_text()
            self.assertEqual(1, service.count(source_line))
            script = service.replace(source_line, '. ' + shlex.quote(str(MODULE / 'common.sh')) + fixtures)
            result = subprocess.run([MKSH, '-c', script], text=True, capture_output=True, timeout=10)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            return result.stdout, calls.read_text().splitlines()

    def test_correct_sql_and_changed_cache_reload_the_app_before_provider(self):
        _, calls = self.run_service('changed')
        self.assertEqual(['am force-stop --user 0 com.google.android.mosey',
                          'am force-stop --user 0 com.google.android.gms', 'provider'], calls)

    def test_country_release_stops_consumers_before_helper_and_provider(self):
        _, calls = self.run_service('unchanged')
        self.assertEqual(['am force-stop --user 0 com.google.android.mosey',
                          'am force-stop --user 0 com.google.android.gms', 'provider'], calls)

    def test_country_only_sql_and_cache_changes_reload_each_package_once(self):
        for sql_changed, cache_country in [(True, 'unchanged'), (False, 'changed')]:
            with self.subTest(sql=sql_changed, cache=cache_country):
                _, calls = self.run_service('unchanged', country_sql_changed=sql_changed,
                                            cache_country_result=cache_country)
                self.assertEqual(['am force-stop --user 0 com.google.android.mosey',
                                  'am force-stop --user 0 com.google.android.gms', 'provider'], calls)

    def test_unknown_country_cache_state_prevents_provider_startup(self):
        for country_result in ('failure', 'invalid-result'):
            output, calls = self.run_service('unchanged', cache_country_result=country_result)
            self.assertNotIn('provider', calls)
            self.assertIn('startup skipped', output)

    def test_invalid_cache_prevents_provider_startup(self):
        for result, valid in [('failure', True), ('changed', False), ('invalid-result', True)]:
            with self.subTest(result=result, valid=valid):
                output, calls = self.run_service(result, valid)
                self.assertNotIn('provider', calls)
                self.assertIn('startup skipped', output)

    def test_sql_and_cache_changes_restart_each_package_once(self):
        _, calls = self.run_service('changed', app_sql_changed=True)
        self.assertEqual(['am force-stop --user 0 com.google.android.mosey',
                          'am force-stop --user 0 com.google.android.gms', 'provider'], calls)


class VersionParsingTests(unittest.TestCase):
    def parse(self, dump):
        script = '. ' + shlex.quote(str(MODULE / 'common.sh')) + '\nmosey_active_gms_version\n'
        return subprocess.run(['sh', '-c', script], input=dump, text=True, capture_output=True)

    def test_updated_gms_uses_active_package_not_hidden_prebuilt(self):
        dump = '''Packages:
  Package [unrelated.package] (abc):
    versionCode=99 minSdk=28
  Package [com.google.android.gms] (123):
    versionCode=264630035 minSdk=28 targetSdk=37
Hidden system packages:
  Package [com.google.android.gms] (456):
    versionCode=261136035 minSdk=28 targetSdk=36
'''
        run = self.parse(dump)
        self.assertEqual(0, run.returncode)
        self.assertEqual('264630035', run.stdout.strip())

    def test_hidden_only_and_duplicate_active_versions_reject(self):
        for dump in [
            'Hidden system packages:\n  Package [com.google.android.gms] (123):\n    versionCode=264630035\n',
            'Packages:\n  Package [com.google.android.gms] (123):\n    versionCode=264630035\n    versionCode=261136035\n',
        ]:
            run = self.parse(dump)
            self.assertNotEqual(0, run.returncode)
            self.assertEqual('', run.stdout.strip())

    def test_supported_hidden_prebuilt_does_not_mask_unsupported_active_update(self):
        run = self.parse('Packages:\n  Package [com.google.android.gms] (123):\n    versionCode=265000000\nHidden system packages:\n  Package [com.google.android.gms] (456):\n    versionCode=264630035\n')
        self.assertEqual(0, run.returncode)
        self.assertEqual('265000000', run.stdout.strip())

    def test_mosey_apk_contract_checks_active_version_and_rejects_unknown_update(self):
        for version, expected in [(60715, 0), (60714, 1), (60716, 1)]:
            dump = f'Packages:\n  Package [com.google.android.mosey] (123):\n    versionCode={version}\nHidden system packages:\n  Package [com.google.android.mosey] (456):\n    versionCode=60715\n'
            script = ('. ' + shlex.quote(str(MODULE / 'common.sh')) + '\n'
                      'mosey_framework() { [ "$*" = "timeout 5 dumpsys package com.google.android.mosey" ] || return 70; cat; }\n'
                      'mosey_app_compatible\n')
            run = subprocess.run([MKSH, '-c', script], input=dump, text=True, capture_output=True)
            self.assertEqual(expected, run.returncode, run.stdout + run.stderr)


class DELayoutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="mosey-de-test-")
        self.root = Path(self.temp.name)
        self.db = self.root / "de.db"
        self.c = sqlite3.connect(self.db)
        self.c.executescript("""
          PRAGMA user_version=1036;
          CREATE TABLE config_packages(config_package_id INTEGER PRIMARY KEY,name TEXT UNIQUE NOT NULL);
          CREATE TABLE flag_overrides(config_package_id INTEGER NOT NULL REFERENCES config_packages,
            name TEXT NOT NULL,value NOT NULL,type INTEGER NOT NULL,PRIMARY KEY(config_package_id,name)) WITHOUT ROWID;
          INSERT INTO config_packages VALUES(4,'com.google.android.gms.nearby'),(5,'other.namespace');
          INSERT INTO flag_overrides VALUES(5,'45704091',0,2),(4,'other.flag',23,1);
        """)

    def tearDown(self):
        self.c.close()
        self.temp.cleanup()

    def sql(self, name, check=True):
        return subprocess.run([SQLITE, "-bail", str(self.db)], input=(MODULE / name).read_text(),
                              text=True, capture_output=True, check=check)

    def test_de_insert_idempotence_and_scoped_rollback(self):
        before = self.c.execute("SELECT * FROM flag_overrides ORDER BY 1,2").fetchall()
        backup = self.root / "baseline.sqlite"
        with sqlite3.connect(backup) as out:
            self.c.backup(out)
        self.assertEqual("absent", self.sql("inspect-de.sql").stdout.strip())
        self.assertEqual("changed", self.sql("apply-de.sql").stdout.strip())
        self.assertEqual("true", self.sql("inspect-de.sql").stdout.strip())
        self.assertEqual("unchanged", self.sql("apply-de.sql").stdout.strip())
        subprocess.run([SQLITE, "-bail", str(self.db)], input="ATTACH DATABASE 'file:" + str(backup)
                       + "?mode=ro' AS baseline;\n" + (MODULE / "rollback-de.sql").read_text(),
                       text=True, capture_output=True, check=True)
        self.assertEqual(before, self.c.execute("SELECT * FROM flag_overrides ORDER BY 1,2").fetchall())

    def test_de_missing_namespace_and_cross_layout_reject(self):
        self.c.execute("DELETE FROM config_packages WHERE config_package_id=4")
        self.c.commit()
        self.assertEqual("not-ready", self.sql("inspect-de.sql").stdout.strip())
        self.assertNotEqual(0, self.sql("apply-de.sql", check=False).returncode)
        self.assertEqual([(5, "45704091", 0, 2), (4, "other.flag", 23, 1)],
                         self.c.execute("SELECT * FROM flag_overrides ORDER BY name").fetchall())
        self.c.execute("ALTER TABLE flag_overrides ADD COLUMN account_id INTEGER")
        self.c.commit()
        self.assertEqual("schema-mismatch", self.sql("inspect-de.sql").stdout.strip())
        self.assertNotEqual(0, self.sql("apply-de.sql", check=False).returncode)


def country_map(blob):
    """Read the independent map<string,int32> wire contract used by APK60715."""
    def varint(at):
        value = 0
        for shift in range(0, 70, 7):
            if at >= len(blob):
                raise ValueError('truncated protobuf')
            byte = blob[at]; at += 1; value |= (byte & 127) << shift
            if byte < 128:
                return value, at
        raise ValueError('oversized protobuf varint')
    result = {}; at = 0
    while at < len(blob):
        tag, at = varint(at)
        if tag != 10:
            raise ValueError('not a map entry')
        size, at = varint(at); end = at + size
        tag, at = varint(at)
        if tag != 10:
            raise ValueError('missing country key')
        size, at = varint(at); key = blob[at:at + size].decode('ascii'); at += size
        tag, at = varint(at)
        if tag != 16:
            raise ValueError('missing channel value')
        value, at = varint(at)
        if at != end or key in result:
            raise ValueError('invalid or duplicate map entry')
        result[key] = value
    return result


class MoseyFlagTests(unittest.TestCase):
    setUpDatabase = ModuleTests.setUp
    tearDown = ModuleTests.tearDown
    cli = ModuleTests.cli
    backup = ModuleTests.backup

    def setUp(self):
        self.setUpDatabase()
        self.c.executescript("""
          INSERT INTO config_packages VALUES(44,'mosey_app_android#com.google.android.mosey',NULL);
          INSERT INTO experiment_states VALUES(110,0,44),(111,0,44),(112,1,44);
          UPDATE config_packages SET committed_experiment_state_id=110 WHERE config_package_id=44;
          INSERT INTO flag_overrides VALUES(24,44,NULL,1,1,'45768305',0,2,77),
            (25,43,NULL,0,1,'45718707',X'CAFE',5,99),(26,44,NULL,0,1,'other.app.flag',23,1,99);
          INSERT INTO experiment_states_to_overrides VALUES(112,24),(103,25),(110,26),(111,26);
        """)
        self.contract = (MODULE / 'mosey-flags.sql').read_text()
        with sqlite3.connect(':memory:') as definitions:
            definitions.executescript(self.contract)
            self.maps = definitions.execute('SELECT previous,desired FROM mosey_maps').fetchall()
            self.desired = definitions.execute("SELECT value FROM mosey_legacy_country WHERE name='45718707'").fetchone()[0]
            self.flagsets = [row[0] for row in definitions.execute('SELECT content FROM mosey_snapshot')]
            self.flagset = next(blob for blob in self.flagsets if hashlib.sha256(blob).hexdigest() ==
                                'ae73a7028c5225ff93d457d69b23c2f9cfdd828b02217780a404d4e8d3162b03')
        captured_map = next(pair[0] for pair in self.maps if country_map(pair[0])['PS'] == 44)
        default_map = next(pair[0] for pair in self.maps if country_map(pair[0])['PS'] == 149)
        def block(value):
            size = len(value)
            return bytes([(size & 127) | 128, size >> 7]) + value
        decoded = zlib.decompress(self.flagset, -15)
        self.assertEqual(1, decoded.count(block(captured_map)))
        compressor = zlib.compressobj(wbits=-15)
        different = decoded.replace(block(captured_map), block(default_map))
        self.default_flagset = compressor.compress(different) + compressor.flush()
        self.c.executescript('''
          CREATE TABLE param_partitions(param_partition_id INTEGER PRIMARY KEY,flags_content BLOB NOT NULL);
          CREATE TABLE experiment_states_to_partitions(experiment_state_id INTEGER NOT NULL,
            ordinal INTEGER NOT NULL,param_partition_id INTEGER NOT NULL,PRIMARY KEY(experiment_state_id,ordinal));
          INSERT INTO experiment_states_to_partitions VALUES(110,0,7),(111,0,7);
        ''')
        self.c.execute('INSERT INTO param_partitions VALUES(7,?)', (self.flagset,)); self.c.commit()

    def sql(self, name, check=True, prefix=''):
        return self.cli(prefix + self.contract + (MODULE / name).read_text(), check=check)

    def snapshot(self):
        return {table: self.c.execute('SELECT * FROM ' + table + ' ORDER BY 1,2').fetchall()
                for table in ('flag_overrides', 'experiment_states_to_overrides',
                              'flag_overrides_to_commit', 'config_packages', 'experiment_states', 'accounts')}

    def target(self, name, value, type_, id_, source=77):
        self.c.execute('INSERT INTO flag_overrides VALUES(?,44,NULL,0,1,?,?,?,?)',
                       (id_, name, value, type_, source))
        self.c.execute('INSERT INTO experiment_states_to_overrides VALUES(110,?)', (id_,))
        self.c.commit()

    def rollback(self, path):
        self.sql('rollback-mosey.sql', prefix="ATTACH DATABASE 'file:" + str(path) + "?mode=ro' AS baseline;\n")


    def release(self, baseline, de=False, check=True):
        return self.sql('release-country-de.sql' if de else 'release-country.sql', check=check,
                        prefix="ATTACH DATABASE 'file:" + str(baseline) + "?mode=ro' AS baseline;\n")

    def legacy_ce(self, original=True, previous=None):
        previous = previous or self.maps[0][0]
        desired = next(after for before, after in self.maps if before == previous)
        self.target('45768305', 0, 2, 1, 77)
        if original:
            self.target('45718707', previous, 5, 2, 99)
        baseline = self.backup()
        if original:
            self.c.execute('UPDATE flag_overrides SET value=? WHERE override_id=2', (desired,))
        else:
            self.c.execute("INSERT INTO flag_overrides VALUES(2,44,NULL,0,1,'45718707',?,5,0)", (self.desired,))
            self.c.execute('INSERT INTO experiment_states_to_overrides VALUES(110,2)')
        self.c.execute('INSERT INTO experiment_states_to_overrides VALUES(111,2)')
        self.c.execute('UPDATE flag_overrides SET value=1 WHERE override_id=1')
        self.c.commit()
        return baseline

    def unrelated_country_and_bool(self):
        return {table: [row for row in rows if not (table == 'flag_overrides' and row[0] == 2)
                       and not (table in ('experiment_states_to_overrides', 'flag_overrides_to_commit') and row[1 if table == 'experiment_states_to_overrides' else 0] == 2)]
                for table, rows in self.snapshot().items()}

    def test_only_boolean_is_managed_and_legacy_country_bytes_are_preserved(self):
        proof = json.loads((HERE / 'flags-contract.json').read_text())
        self.assertEqual({'45768305'}, set(proof['flags']))
        self.assertFalse(proof['legacy_country_migration']['managed'])
        for previous, desired in self.maps:
            before, after = country_map(previous), country_map(desired)
            self.assertEqual({'TN'}, {key for key in before if before[key] != after[key]})
            self.assertEqual((149, 6), (before['TN'], after['TN']))
        self.assertEqual(44, country_map(self.desired)['PS'])
        for name, digest in proof['sql_file_sha256'].items():
            self.assertEqual(digest, hashlib.sha256((MODULE / name).read_bytes()).hexdigest())

    def test_fresh_install_creates_only_boolean_without_country_snapshot_requirement(self):
        self.c.execute('UPDATE param_partitions SET flags_content=?', (b'new server snapshot',)); self.c.commit()
        before = self.snapshot()
        self.assertEqual('absent', self.sql('inspect-mosey.sql').stdout.strip())
        self.assertEqual('changed', self.sql('apply-mosey.sql').stdout.strip())
        self.assertEqual('true', self.sql('inspect-mosey.sql').stdout.strip())
        self.assertEqual('unchanged', self.sql('apply-mosey.sql').stdout.strip())
        self.assertEqual([('45768305', 1, 2, 'integer')], self.c.execute(
            "SELECT name,value,type,typeof(value) FROM flag_overrides WHERE config_package_id=44 AND account_id=0 AND name IN('45768305','45718707')").fetchall())
        for table, rows in before.items():
            self.assertTrue(all(row in self.snapshot()[table] for row in rows))

    def test_fresh_boolean_apply_preserves_unknown_country_override_sources_and_links(self):
        self.target('45718707', b'unknown server country map', 5, 2, 99)
        self.target('45768305', 0, 2, 1, 77)
        before = self.snapshot()
        self.assertEqual('false', self.sql('inspect-mosey.sql').stdout.strip())
        self.sql('apply-mosey.sql')
        after = self.snapshot()
        self.assertEqual([row for row in before['flag_overrides'] if row[0] != 1],
                         [row for row in after['flag_overrides'] if row[0] != 1])
        self.assertEqual((1, 2, 77), self.c.execute('SELECT value,type,source FROM flag_overrides WHERE override_id=1').fetchone())
        self.assertIn((110, 2), after['experiment_states_to_overrides'])
        self.assertNotIn((111, 2), after['experiment_states_to_overrides'])

    def test_ce_upgrade_restores_original_country_and_links_preserving_boolean(self):
        for previous, desired in self.maps:
            with self.subTest(map_sha256=hashlib.sha256(previous).hexdigest()):
                baseline = self.legacy_ce(previous=previous)
                baseline_bytes = baseline.read_bytes()
                unrelated = self.unrelated_country_and_bool()
                self.assertEqual('changed', self.release(baseline).stdout.strip())
                self.assertEqual((previous, 5, 99), self.c.execute('SELECT value,type,source FROM flag_overrides WHERE override_id=2').fetchone())
                self.assertEqual([(110, 2)], self.c.execute('SELECT * FROM experiment_states_to_overrides WHERE override_id=2').fetchall())
                self.assertEqual((1, 2, 77), self.c.execute('SELECT value,type,source FROM flag_overrides WHERE override_id=1').fetchone())
                self.assertEqual(unrelated, self.unrelated_country_and_bool())
                self.assertEqual(baseline_bytes, baseline.read_bytes())
                self.assertEqual('unchanged', self.release(baseline).stdout.strip())
                self.c.execute('DELETE FROM experiment_states_to_overrides WHERE override_id IN(1,2)')
                self.c.execute('DELETE FROM flag_overrides WHERE override_id IN(1,2)'); self.c.commit()

    def test_ce_upgrade_removes_only_module_created_country_entry(self):
        baseline = self.legacy_ce(original=False)
        before = self.unrelated_country_and_bool()
        self.assertEqual('changed', self.release(baseline).stdout.strip())
        self.assertIsNone(self.c.execute('SELECT 1 FROM flag_overrides WHERE override_id=2').fetchone())
        self.assertEqual([], self.c.execute('SELECT * FROM experiment_states_to_overrides WHERE override_id=2').fetchall())
        self.assertEqual(before, self.unrelated_country_and_bool())
        self.assertEqual('unchanged', self.release(baseline).stdout.strip())
        self.assertEqual([], self.c.execute('PRAGMA foreign_key_check').fetchall())

    def test_ce_unknown_writer_rejection_is_atomic_for_values_sources_ids_and_links(self):
        baseline = self.legacy_ce()
        clean = sqlite3.connect(':memory:'); self.c.backup(clean)
        changes = [
            "UPDATE flag_overrides SET value=X'BEEF' WHERE override_id=2",
            'UPDATE flag_overrides SET source=88 WHERE override_id=2',
            'UPDATE flag_overrides SET type=4 WHERE override_id=2',
            'INSERT INTO experiment_states_to_overrides VALUES(112,2)',
            'DELETE FROM experiment_states_to_overrides WHERE override_id=2 AND experiment_state_id=110',
            'INSERT INTO flag_overrides_to_commit VALUES(2,44,0)',
        ]
        for change in changes:
            with self.subTest(change=change):
                self.c.execute(change); self.c.commit(); before = self.snapshot()
                self.assertNotEqual(0, self.release(baseline, check=False).returncode)
                self.assertEqual(before, self.snapshot())
                clean.backup(self.c)
        clean.close()

    def test_absent_baseline_rejects_unowned_country_or_changed_effective_snapshot(self):
        baseline = self.legacy_ce(original=False)
        for sql in ["UPDATE flag_overrides SET source=7 WHERE override_id=2",
                    "UPDATE flag_overrides SET value=X'BEEF' WHERE override_id=2"]:
            clean = sqlite3.connect(':memory:'); self.c.backup(clean)
            self.c.execute(sql); self.c.commit(); before = self.snapshot()
            self.assertNotEqual(0, self.release(baseline, check=False).returncode)
            self.assertEqual(before, self.snapshot()); clean.backup(self.c); clean.close()
        with sqlite3.connect(baseline) as c:
            c.execute('UPDATE param_partitions SET flags_content=?', (b'unknown original server snapshot',))
        before = self.snapshot()
        self.assertNotEqual(0, self.release(baseline, check=False).returncode)
        self.assertEqual(before, self.snapshot())

    def test_release_rejects_concurrent_database_writer_without_partial_changes(self):
        baseline = self.legacy_ce()
        before = self.snapshot()
        self.c.execute('BEGIN IMMEDIATE')
        self.assertNotEqual(0, self.release(baseline, check=False).returncode)
        self.c.rollback()
        self.assertEqual(before, self.snapshot())

    def test_boolean_rollback_never_touches_country_after_server_update(self):
        self.target('45768305', 0, 2, 1, 77)
        self.target('45718707', self.maps[0][0], 5, 2, 99)
        baseline = self.backup()
        self.sql('apply-mosey.sql')
        self.c.execute('UPDATE flag_overrides SET value=? WHERE override_id=2', (b'new server country map',)); self.c.commit()
        country = self.c.execute('SELECT * FROM flag_overrides WHERE override_id=2').fetchone()
        country_links = self.c.execute('SELECT * FROM experiment_states_to_overrides WHERE override_id=2').fetchall()
        self.rollback(baseline)
        self.assertEqual((0, 2, 77), self.c.execute('SELECT value,type,source FROM flag_overrides WHERE override_id=1').fetchone())
        self.assertEqual(country, self.c.execute('SELECT * FROM flag_overrides WHERE override_id=2').fetchone())
        self.assertEqual(country_links, self.c.execute('SELECT * FROM experiment_states_to_overrides WHERE override_id=2').fetchall())

    def test_missing_registration_and_wrong_boolean_type_reject_atomically(self):
        self.target('45768305', 'true', 4, 1)
        before = self.snapshot()
        self.assertEqual('unsupported-value', self.sql('inspect-mosey.sql').stdout.strip())
        self.assertNotEqual(0, self.sql('apply-mosey.sql', check=False).returncode)
        self.assertEqual(before, self.snapshot())
        self.c.execute('UPDATE config_packages SET committed_experiment_state_id=NULL WHERE config_package_id=44'); self.c.commit()
        before = self.snapshot()
        self.assertEqual('not-ready', self.sql('inspect-mosey.sql').stdout.strip())
        self.assertNotEqual(0, self.sql('apply-mosey.sql', check=False).returncode)
        self.assertEqual(before, self.snapshot())

    def shell_command(self, state, operation='mosey_apply_database', label='ce-mosey'):
        return (f'. {shlex.quote(str(MODULE / "common.sh"))}\numask 077\n'
                f'MOSEY_MOD={shlex.quote(str(MODULE))}\nMOSEY_STATE={shlex.quote(str(state))}\n'
                f'MOSEY_SQLITE={shlex.quote(SQLITE)}\n'
                f'{operation} {shlex.quote(str(self.db))} {label}\n')

    def test_shell_release_marker_baseline_and_boolean_backup_are_independent(self):
        self.c.execute('PRAGMA journal_mode=WAL')
        baseline = self.legacy_ce()
        self.c.execute('UPDATE flag_overrides SET value=0 WHERE override_id=1'); self.c.commit()
        state = self.root / 'state'; state.mkdir(mode=0o700)
        legacy = state / 'ce-mosey-before.sqlite'; shutil.copyfile(baseline, legacy)
        (state / 'ce-mosey-version').write_text('264630035\n')
        (state / 'ce-mosey-app-version').write_text('60715\n')
        nearby = state / 'ce-before.sqlite'; nearby.write_bytes(b'Nearby baseline must be preserved')
        bytes_before = legacy.read_bytes(); nearby_before = nearby.read_bytes()
        command = self.shell_command(state)
        result = subprocess.run([MKSH, '-c', command], text=True, capture_output=True, check=True)
        self.assertEqual('changed', result.stdout.strip())
        self.assertEqual(bytes_before, legacy.read_bytes()); self.assertEqual(nearby_before, nearby.read_bytes())
        backup = state / 'ce-mosey-bool-v10-before.sqlite'
        with sqlite3.connect(backup) as old:
            self.assertEqual((0,), old.execute('SELECT value FROM flag_overrides WHERE override_id=1').fetchone())
            self.assertEqual((self.maps[0][0],), old.execute('SELECT value FROM flag_overrides WHERE override_id=2').fetchone())
        self.assertEqual(0o600, backup.stat().st_mode & 0o777)
        self.assertEqual(hashlib.sha256(bytes_before).hexdigest(), (state / 'ce-mosey-country-released').read_text().strip())
        self.c.execute('UPDATE flag_overrides SET value=? WHERE override_id=2', (b'new server value after release',)); self.c.commit()
        self.assertEqual('unchanged', subprocess.run([MKSH, '-c', command], text=True, capture_output=True, check=True).stdout.strip())
        self.assertEqual((b'new server value after release',), self.c.execute('SELECT value FROM flag_overrides WHERE override_id=2').fetchone())
        (state / 'ce-mosey-country-released').write_text('wrong baseline hash\n')
        before = self.snapshot()
        self.assertNotEqual(0, subprocess.run([MKSH, '-c', command], capture_output=True).returncode)
        self.assertEqual(before, self.snapshot())

    def test_shell_fresh_install_and_partial_legacy_state(self):
        state = self.root / 'state'; state.mkdir(mode=0o700)
        release = self.shell_command(state, 'mosey_release_country')
        self.assertEqual('unchanged', subprocess.run([MKSH, '-c', release], text=True, capture_output=True, check=True).stdout.strip())
        command = self.shell_command(state)
        self.assertEqual('changed', subprocess.run([MKSH, '-c', command], text=True, capture_output=True, check=True).stdout.strip())
        self.assertTrue((state / 'ce-mosey-bool-v10-before.sqlite').exists())
        self.assertFalse((state / 'ce-mosey-before.sqlite').exists())
        self.assertEqual('unchanged', subprocess.run([MKSH, '-c', release], text=True, capture_output=True, check=True).stdout.strip())
        (state / 'ce-mosey-version').write_text('264630035\n')
        before = self.snapshot()
        self.assertNotEqual(0, subprocess.run([MKSH, '-c', release], capture_output=True).returncode)
        self.assertEqual(before, self.snapshot())

    def test_backup_metadata_write_failure_prevents_boolean_transaction(self):
        self.target('45768305', 0, 2, 1)
        for suffix in ('version', 'app-version'):
            with self.subTest(metadata=suffix):
                state = self.root / ('state-' + suffix); state.mkdir(mode=0o700)
                # A directory in place of the metadata file makes redirection fail
                # even when the test runs as root; it models unwritable metadata.
                (state / ('ce-mosey-bool-v10-' + suffix)).mkdir()
                before = self.snapshot()
                result = subprocess.run([MKSH, '-c', self.shell_command(state)],
                                        text=True, capture_output=True)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual(before, self.snapshot())
                self.assertEqual((0,), self.c.execute('SELECT value FROM flag_overrides WHERE override_id=1').fetchone())

    def de_database(self, country=None):
        self.c.close(); self.db=self.root / 'de.db'; self.db.unlink(missing_ok=True); self.c=sqlite3.connect(self.db)
        self.c.executescript("PRAGMA user_version=1036; PRAGMA foreign_keys=ON; "
            "CREATE TABLE config_packages(config_package_id INTEGER PRIMARY KEY,name TEXT UNIQUE NOT NULL,flags_content BLOB);"
            "CREATE TABLE flag_overrides(config_package_id INTEGER NOT NULL REFERENCES config_packages,"
            "name TEXT NOT NULL,value NOT NULL,type INTEGER NOT NULL,PRIMARY KEY(config_package_id,name)) WITHOUT ROWID;"
            "INSERT INTO config_packages VALUES(4,'com.google.android.gms.nearby',NULL);"
            "INSERT INTO flag_overrides VALUES(4,'45704091',1,2);")
        self.c.execute("INSERT INTO config_packages VALUES(5,'mosey_app_android#com.google.android.mosey',?)", (self.flagset,))
        if country is not None:
            self.c.execute("INSERT INTO flag_overrides VALUES(5,'45718707',?,5)", (country,))
        self.c.commit()

    def test_de_fresh_boolean_apply_and_rollback_preserve_country_and_nearby(self):
        self.de_database(b'new server map')
        baseline = self.backup()
        self.assertEqual('absent', self.sql('inspect-mosey-de.sql').stdout.strip())
        self.assertEqual('changed', self.sql('apply-mosey-de.sql').stdout.strip())
        self.assertEqual('unchanged', self.sql('apply-mosey-de.sql').stdout.strip())
        self.assertEqual((b'new server map', 5), self.c.execute("SELECT value,type FROM flag_overrides WHERE name='45718707'").fetchone())
        self.c.execute("UPDATE flag_overrides SET value=? WHERE name='45718707'", (b'later server map',)); self.c.commit()
        self.sql('rollback-mosey-de.sql', prefix="ATTACH DATABASE 'file:" + str(baseline) + "?mode=ro' AS baseline;\n")
        self.assertEqual([(4, '45704091', 1, 2), (5, '45718707', b'later server map', 5)], self.c.execute('SELECT * FROM flag_overrides ORDER BY 1,2').fetchall())

    def test_de_upgrade_restores_original_or_removes_owned_country_only(self):
        for original in (True, False):
            with self.subTest(original=original):
                self.de_database(self.maps[0][0] if original else None)
                baseline = self.backup()
                self.c.execute("INSERT INTO flag_overrides VALUES(5,'45768305',1,2)")
                self.c.execute("INSERT INTO flag_overrides VALUES(5,'45718707',?,5) ON CONFLICT(config_package_id,name) DO UPDATE SET value=excluded.value", (self.maps[0][1] if original else self.desired,))
                self.c.commit(); before = baseline.read_bytes()
                self.assertEqual('changed', self.release(baseline, de=True).stdout.strip())
                value=self.c.execute("SELECT value FROM flag_overrides WHERE name='45718707'").fetchone()
                self.assertEqual((self.maps[0][0],) if original else None, value)
                self.assertEqual((1, 2), self.c.execute("SELECT value,type FROM flag_overrides WHERE name='45768305'").fetchone())
                self.assertEqual((1, 2), self.c.execute("SELECT value,type FROM flag_overrides WHERE name='45704091'").fetchone())
                self.assertEqual(before, baseline.read_bytes())
                self.assertEqual('unchanged', self.release(baseline, de=True).stdout.strip())

    def test_de_unknown_writer_and_missing_registration_reject_without_changes(self):
        self.de_database(self.maps[0][0]); baseline = self.backup()
        self.c.execute("UPDATE flag_overrides SET value=? WHERE name='45718707'", (b'unowned new map',)); self.c.commit()
        before = self.c.execute('SELECT * FROM flag_overrides').fetchall()
        self.assertNotEqual(0, self.release(baseline, de=True, check=False).returncode)
        self.assertEqual(before, self.c.execute('SELECT * FROM flag_overrides').fetchall())
        self.c.execute("UPDATE config_packages SET name='unregistered' WHERE config_package_id=5"); self.c.commit()
        self.assertEqual('not-ready', self.sql('inspect-mosey-de.sql').stdout.strip())
        self.assertNotEqual(0, self.sql('apply-mosey-de.sql', check=False).returncode)
        self.assertEqual(before, self.c.execute('SELECT * FROM flag_overrides').fetchall())


if __name__ == "__main__":
    if not SQLITE:
        raise SystemExit("A host sqlite3 CLI is required for the transaction tests.")
    if not MKSH:
        raise SystemExit("A real mksh CLI is required; install mksh or set MOSEY_TEST_MKSH.")
    unittest.main(verbosity=2)
