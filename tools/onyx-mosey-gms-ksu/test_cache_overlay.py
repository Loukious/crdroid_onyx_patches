#!/usr/bin/env python3
"""Independent host fixtures for APK60715 shared-cache override semantics.

Run with --helper pointing at a MOSEY_CACHE_HOST_TEST binary. Fixtures use
public synthetic tokens and the exact reviewed compressed flagsets/maps from
mosey-flags.sql; no device paths, tokens or live Android tools are involved.
"""
import argparse
import hashlib
import os
from pathlib import Path
import sqlite3
import stat
import struct
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parent
BOOL, COUNTRY = "45768305", "45718707"
HELPER = None


def vi(value):
    result = bytearray()
    while value > 127:
        result.append((value & 127) | 128)
        value >>= 7
    result.append(value)
    return bytes(result)


def scalar(number, value):
    return vi(number << 3) + vi(value)


def ld(number, value):
    if isinstance(value, str):
        value = value.encode()
    return vi((number << 3) | 2) + vi(len(value)) + value


def read_vi(data, offset):
    value, shift = 0, 0
    while True:
        byte = data[offset]
        offset += 1
        value |= (byte & 127) << shift
        if byte < 128:
            return value, offset
        shift += 7


def fields(data):
    result, offset = [], 0
    while offset < len(data):
        start = offset
        tag, offset = read_vi(data, offset)
        number, wire = tag >> 3, tag & 7
        if wire == 0:
            value, offset = read_vi(data, offset)
        elif wire == 2:
            length, offset = read_vi(data, offset)
            value = data[offset:offset + length]
            offset += length
        elif wire in (1, 5):
            length = 8 if wire == 1 else 4
            value = data[offset:offset + length]
            offset += length
        else:
            raise ValueError("unsupported fixture wire")
        result.append((number, wire, value, data[start:offset]))
    return result


def bin_entry(key, value, name=None, bin_extra=b"", outer_extra=b""):
    name = key if name is None else name
    record = value + (ld(10, name) if name != "" else b"") + bin_extra
    return ld(5, ld(1, key) + ld(2, record) + outer_extra)


def metadata(entries=(), token="public-token-A", server="public-server-A", extra=b""):
    return ld(1, token) + ld(2, b"public-experiment") + ld(3, server) + scalar(4, 77) + b"".join(entries) + extra


def frame(meta, compressed):
    return struct.pack("<II", 1, 0) + vi(len(meta)) + meta + vi(len(compressed)) + compressed


def decode(data):
    length, offset = read_vi(data, 8)
    meta = data[offset:offset + length]
    offset += length
    suffix = data[offset:]
    records = {}
    for number, _, outer, raw in fields(meta):
        if number == 5:
            outer_fields = fields(outer)
            key = next(v.decode() for n, _, v, _ in outer_fields if n == 1)
            value = next(v for n, _, v, _ in outer_fields if n == 2)
            records[key] = (fields(value), outer_fields, raw)
    return meta, suffix, records


def apk_values(data):
    # APK60715 bld.c() iterates map values, then bix.b() keys by bin field10.
    records = decode(data)[2]
    result = {}
    for values, _, _ in records.values():
        name = next(v.decode() for n, _, v, _ in values if n == 10)
        typed = [(n, w, v) for n, w, v, _ in values if n in range(1, 6)]
        result[name] = typed
    return result


def map_values(data):
    return {next(v.decode() for n, _, v, _ in fields(record) if n == 1):
            next(v for n, _, v, _ in fields(record) if n == 2)
            for _, _, record, _ in fields(data)}


class CacheOverlayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        connection = sqlite3.connect(":memory:")
        connection.executescript((ROOT / "module-template/mosey-flags.sql").read_text())
        cls.maps = connection.execute("SELECT previous,desired FROM mosey_maps").fetchall()
        cls.snapshots = [row[0] for row in connection.execute("SELECT content FROM mosey_snapshot")]
        cls.captured = next(pair for pair in cls.maps if map_values(pair[0])["PS"] == 44)
        cls.default = next(pair for pair in cls.maps if map_values(pair[0])["PS"] == 149)
        connection.close()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="onyx-cache-test-")
        self.root = Path(self.tmp.name)
        self.primary = self.root / "primary.pb"
        self.state = self.root / "state"
        self.state.mkdir(mode=0o700)
        self.original = frame(metadata(extra=ld(20, "public-unknown-meta")), self.snapshots[0])
        self.save(self.original)

    def tearDown(self):
        self.tmp.cleanup()

    def save(self, data):
        self.primary.write_bytes(data)
        self.primary.chmod(0o640)

    def command(self, action="apply", primary=None):
        return [str(HELPER), "--" + action, "--primary", str(primary or self.primary), "--state-dir", str(self.state)]

    def run_helper(self, action="apply", expect="changed", primary=None):
        result = subprocess.run(self.command(action, primary), capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), expect)
        return result

    def reject(self, action="apply", message=None):
        before = self.primary.read_bytes() if self.primary.is_file() else None
        result = subprocess.run(self.command(action), capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        if message:
            self.assertIn(message, result.stderr)
        if before is not None:
            self.assertEqual(self.primary.read_bytes(), before)
        return result

    def baseline(self, suffix):
        digest = hashlib.sha256(str(self.primary).encode()).hexdigest()
        return self.state / ("cache-overlay-bool-v10-" + digest + "-" + suffix)

    def legacy_baseline(self, suffix):
        digest = hashlib.sha256(str(self.primary).encode()).hexdigest()
        return self.state / ("cache-overlay-" + digest + "-" + suffix)

    def legacy_v9(self, original=None, family=None):
        original = self.original if original is None else original
        family = self.captured if family is None else family
        self.save(original)
        meta, suffix, _ = decode(original)
        records = []
        seen = set()
        changes = {BOOL: scalar(2, 1), COUNTRY: ld(5, family[1])}
        for number, _, value, raw in fields(meta):
            if number != 5:
                records.append(raw)
                continue
            outer = fields(value)
            key = next(v.decode() for n, _, v, _ in outer if n == 1)
            if key not in changes:
                records.append(raw)
                continue
            seen.add(key)
            rebuilt = []
            for n, _, inner, chunk in outer:
                if n == 2:
                    rebuilt.append(ld(2, b"".join(changes[key] if 1 <= fn <= 5 else fr
                                                  for fn, _, _, fr in fields(inner))))
                else:
                    rebuilt.append(chunk)
            records.append(ld(5, b"".join(rebuilt)))
        records.extend(bin_entry(key, changes[key]) for key in sorted(set(changes) - seen))
        new_meta = b"".join(records)
        self.save(original[:8] + vi(len(new_meta)) + new_meta + suffix)
        backups = {"before.pb": original,
                   "before.sha256": hashlib.sha256(original).hexdigest().encode(),
                   "source": str(self.primary).encode(), "country.pb": family[1]}
        for name, data in backups.items():
            path = self.legacy_baseline(name)
            path.write_bytes(data)
            path.chmod(0o600)
        return {name: self.legacy_baseline(name).read_bytes() for name in backups}

    def existing(self, family=None):
        family = family or self.captured
        return frame(metadata([
            bin_entry(BOOL, scalar(2, 0), bin_extra=ld(20, "old-bin"), outer_extra=ld(19, "outer")),
            bin_entry(COUNTRY, ld(5, family[0]), bin_extra=scalar(21, 11)),
            bin_entry("unrelated", ld(4, "untouched"), bin_extra=ld(29, "unknown")),
        ], extra=ld(20, "public-unknown-meta")), self.snapshots[0])

    def mutate_bin(self, key, transform):
        meta, _, _ = decode(self.primary.read_bytes())
        result = []
        for n, _, value, raw in fields(meta):
            if n != 5:
                result.append(raw)
                continue
            outer = fields(value)
            name = next(v.decode() for fn, _, v, _ in outer if fn == 1)
            if name != key:
                result.append(raw)
                continue
            rebuilt = b"".join(ld(2, transform(v)) if fn == 2 else fr for fn, _, v, fr in outer)
            result.append(ld(5, rebuilt))
        self.save(frame(b"".join(result), self.snapshots[0]))

    def paused(self, action="apply"):
        sync = self.root / "sync"
        sync.mkdir(mode=0o700)
        process = subprocess.Popen(self.command(action), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                   env={**os.environ, "MOSEY_CACHE_TEST_SYNC_DIR": str(sync)})
        deadline = time.monotonic() + 5
        while not (sync / "ready").exists():
            self.assertIsNone(process.poll(), "helper failed before source-check barrier")
            self.assertLess(time.monotonic(), deadline, "helper missing test barrier")
            time.sleep(0.01)
        return process, sync

    def release_rejected(self, process, sync):
        latest = self.primary.read_bytes()
        (sync / "continue").touch(mode=0o600)
        out, err = process.communicate(timeout=5)
        self.assertEqual(process.returncode, 1, out + err)
        self.assertIn("source changed before replacement", err)
        self.assertEqual(self.primary.read_bytes(), latest)
        self.assertFalse(list(self.root.glob(".onyx-mosey-cache-*")))

    def test_apk_getter_names_and_exact_types(self):
        self.run_helper()
        values = apk_values(self.primary.read_bytes())
        self.assertEqual(values[BOOL], [(2, 0, 1)])
        self.assertNotIn(COUNTRY, values)

    def test_tokens_unknown_metadata_and_compression_are_exact(self):
        before_meta, suffix, _ = decode(self.original)
        self.run_helper()
        after_meta, after_suffix, _ = decode(self.primary.read_bytes())
        self.assertEqual(after_suffix, suffix)
        self.assertEqual([f[3] for f in fields(after_meta) if f[0] != 5], [f[3] for f in fields(before_meta)])

    def test_private_independent_baseline_and_source_mode(self):
        original_stat = self.primary.stat()
        self.run_helper()
        self.assertEqual(self.baseline("before.pb").read_bytes(), self.original)
        self.assertEqual(self.baseline("source").read_text(), str(self.primary))
        self.assertEqual(self.baseline("before.sha256").read_text(), hashlib.sha256(self.original).hexdigest())
        self.assertFalse(self.baseline("country.pb").exists())
        for path in self.state.iterdir():
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(path.stat().st_uid, os.getuid())
        current = self.primary.stat()
        self.assertEqual((current.st_uid, current.st_gid, stat.S_IMODE(current.st_mode)),
                         (original_stat.st_uid, original_stat.st_gid, 0o640))

    def test_apply_idempotent_and_inspect(self):
        self.run_helper("inspect", "false")
        self.run_helper()
        first = self.primary.read_bytes()
        first_inode = self.primary.stat().st_ino
        self.run_helper("apply", "unchanged")
        self.run_helper("inspect", "true")
        self.assertEqual(self.primary.read_bytes(), first)
        self.assertEqual(self.primary.stat().st_ino, first_inode)

    def test_absent_entries_rollback_and_repeat(self):
        self.run_helper()
        self.run_helper("rollback")
        self.assertEqual(self.primary.read_bytes(), self.original)
        self.run_helper("rollback", "unchanged")

    def test_existing_overrides_rollback_and_repeat(self):
        for family in self.maps:
            with self.subTest(ps=map_values(family[0])["PS"]):
                # Each baseline is independent; do not reuse across country families.
                for p in self.state.iterdir():
                    p.unlink()
                original = self.existing(family)
                self.save(original)
                self.run_helper()
                self.assertEqual(apk_values(self.primary.read_bytes())[COUNTRY], [(5, 2, family[0])])
                self.run_helper("rollback")
                self.assertEqual(self.primary.read_bytes(), original)
                self.run_helper("rollback", "unchanged")

    def test_unknown_fields_survive_apply(self):
        self.save(self.existing())
        prior = decode(self.primary.read_bytes())[2]
        self.run_helper()
        now = decode(self.primary.read_bytes())[2]
        self.assertEqual(prior["unrelated"], now["unrelated"])
        for key in (BOOL, COUNTRY):
            self.assertEqual([f[3] for f in prior[key][0] if f[0] not in range(1, 6)],
                             [f[3] for f in now[key][0] if f[0] not in range(1, 6)])
            self.assertEqual([f[3] for f in prior[key][1] if f[0] != 2],
                             [f[3] for f in now[key][1] if f[0] != 2])

    def test_new_unknown_field_survives_existing_entry_rollback(self):
        self.save(self.existing())
        self.run_helper()
        self.mutate_bin(BOOL, lambda b: b.replace(ld(20, "old-bin"), ld(20, "new-bin")) + scalar(30, 99))
        self.run_helper("rollback")
        values = decode(self.primary.read_bytes())[2][BOOL][0]
        self.assertIn((20, 2, b"new-bin", ld(20, "new-bin")), values)
        self.assertIn((30, 0, 99, scalar(30, 99)), values)
        self.assertEqual(apk_values(self.primary.read_bytes())[BOOL], [(2, 0, 0)])
        self.run_helper("rollback", "unchanged")

    def test_new_unknown_field_in_created_entry_rejects_rollback(self):
        self.run_helper()
        self.mutate_bin(BOOL, lambda b: b + ld(20, "new-owner-field"))
        self.reject("rollback", "unrelated changes")

    def test_keyed_rollback_preserves_new_tokens_and_flagset(self):
        self.run_helper()
        entries = [r[2] for r in decode(self.primary.read_bytes())[2].values()]
        unrelated = bin_entry("new-unrelated", scalar(2, 0), outer_extra=scalar(18, 7))
        updated_meta = metadata(entries + [unrelated], token="public-token-B", server="public-server-B", extra=scalar(31, 111))
        self.save(frame(updated_meta, self.snapshots[1]))
        self.run_helper("rollback")
        expected = frame(metadata([unrelated], token="public-token-B", server="public-server-B", extra=scalar(31, 111)), self.snapshots[1])
        self.assertEqual(self.primary.read_bytes(), expected)

    def test_changed_managed_value_rejects_rollback(self):
        self.run_helper()
        self.mutate_bin(BOOL, lambda b: b.replace(scalar(2, 1), scalar(2, 0), 1))
        self.reject("rollback", "another writer")

    def test_missing_managed_entries_are_skipped_on_rollback(self):
        self.run_helper()
        self.save(self.original)
        self.run_helper("rollback", "unchanged")

    def test_two_primary_paths_have_independent_baselines(self):
        self.run_helper()
        other = self.root / "other.pb"
        other.write_bytes(frame(metadata(token="public-token-C"), self.snapshots[1]))
        other.chmod(0o600)
        other_original = other.read_bytes()
        self.run_helper(primary=other)
        self.run_helper("rollback", primary=other)
        self.assertEqual(other.read_bytes(), other_original)
        self.assertEqual(len(list(self.state.glob("*-before.pb"))), 2)
        self.run_helper("inspect", "true")

    def test_upgrade_releases_only_created_country_and_preserves_v9_bool(self):
        backups = self.legacy_v9()
        prior = self.primary.read_bytes()
        prior_meta, prior_suffix, prior_records = decode(prior)
        self.run_helper("release-country")
        after = self.primary.read_bytes()
        _, after_suffix, after_records = decode(after)
        self.assertNotIn(COUNTRY, after_records)
        self.assertEqual(after_records[BOOL], prior_records[BOOL])
        self.assertEqual(after_suffix, prior_suffix)
        self.assertEqual([f[3] for f in fields(decode(after)[0]) if f[0] != 5],
                         [f[3] for f in fields(prior_meta) if f[0] != 5])
        for name, data in backups.items():
            self.assertEqual(self.legacy_baseline(name).read_bytes(), data)
        self.assertEqual(self.legacy_baseline("country-released").read_bytes(),
                         backups["before.sha256"])
        self.run_helper("inspect", "true")
        self.run_helper("apply", "unchanged")
        self.run_helper("rollback", "unchanged")
        self.run_helper("release-country", "unchanged")
        self.assertEqual(self.primary.read_bytes(), after)
        self.assertFalse(self.baseline("before.pb").exists())

    def test_release_restores_original_country_family_and_unrelated_fields(self):
        for family in self.maps:
            with self.subTest(ps=map_values(family[0])["PS"]):
                for path in self.state.iterdir():
                    path.unlink()
                original = self.existing(family)
                backups = self.legacy_v9(original, family)
                self.mutate_bin(COUNTRY, lambda b: b + ld(30, "new-country-metadata"))
                prior = decode(self.primary.read_bytes())[2]
                self.run_helper("release-country")
                after = decode(self.primary.read_bytes())[2]
                self.assertEqual(apk_values(self.primary.read_bytes())[COUNTRY], [(5, 2, family[0])])
                values = map_values(apk_values(self.primary.read_bytes())[COUNTRY][0][2])
                self.assertEqual((values["TN"], values["PS"]), (149, map_values(family[0])["PS"]))
                self.assertEqual(after[BOOL], prior[BOOL])
                self.assertEqual(after["unrelated"], prior["unrelated"])
                self.assertIn((30, 2, b"new-country-metadata", ld(30, "new-country-metadata")), after[COUNTRY][0])
                for name, data in backups.items():
                    self.assertEqual(self.legacy_baseline(name).read_bytes(), data)
                self.run_helper("release-country", "unchanged")

    def test_fresh_install_release_noop_and_no_country_override_created(self):
        self.run_helper("release-country", "unchanged")
        self.run_helper()
        self.run_helper("release-country", "unchanged")
        self.run_helper("inspect", "true")
        self.assertNotIn(COUNTRY, apk_values(self.primary.read_bytes()))
        self.run_helper("rollback")
        self.assertEqual(self.primary.read_bytes(), self.original)
        self.assertFalse(self.legacy_baseline("before.pb").exists())

    def test_bool_rollback_preserves_later_country_and_unrelated_updates(self):
        original = self.existing()
        self.save(original)
        self.run_helper()
        self.mutate_bin(COUNTRY, lambda b: b.replace(ld(5, self.captured[0]), ld(5, b"new-server-map")))
        prior_country = decode(self.primary.read_bytes())[2][COUNTRY]
        self.run_helper("rollback")
        self.assertEqual(decode(self.primary.read_bytes())[2][COUNTRY], prior_country)
        self.assertEqual(apk_values(self.primary.read_bytes())[BOOL], [(2, 0, 0)])

    def test_release_marker_preserves_later_country_updates(self):
        self.legacy_v9(self.existing())
        self.run_helper("release-country")
        self.mutate_bin(COUNTRY, lambda b: b.replace(ld(5, self.captured[0]), ld(5, b"new-server-map")))
        prior = self.primary.read_bytes()
        self.run_helper("release-country", "unchanged")
        self.run_helper("inspect", "true")
        self.run_helper("apply", "unchanged")
        self.assertEqual(self.primary.read_bytes(), prior)

    def test_release_rejects_another_country_writer_before_migration(self):
        self.legacy_v9()
        self.mutate_bin(COUNTRY, lambda b: b.replace(ld(5, self.captured[1]), ld(5, b"new-owner-map")))
        self.reject("release-country", "another writer")
        self.assertFalse(self.legacy_baseline("country-released").exists())

    def test_release_rejects_unrelated_changes_in_created_country_entry(self):
        self.legacy_v9()
        self.mutate_bin(COUNTRY, lambda b: b + ld(20, "new-owner-field"))
        self.reject("release-country", "unrelated changes")

    def test_release_existing_country_removed_by_another_writer_rejected(self):
        self.legacy_v9(self.existing())
        meta, suffix, _ = decode(self.primary.read_bytes())
        chunks = [raw for n, _, value, raw in fields(meta)
                  if n != 5 or next(v.decode() for fn, _, v, _ in fields(value) if fn == 1) != COUNTRY]
        new_meta = b"".join(chunks)
        self.save(self.original[:8] + vi(len(new_meta)) + new_meta + suffix)
        self.reject("release-country", "another writer")

    def test_release_already_removed_created_country_is_idempotent(self):
        self.legacy_v9()
        self.save(frame(metadata([bin_entry(BOOL, scalar(2, 1))], extra=ld(20, "public-unknown-meta")), self.snapshots[0]))
        self.run_helper("release-country", "unchanged")
        self.run_helper("release-country", "unchanged")

    def test_release_partial_legacy_baseline_rejected(self):
        self.legacy_baseline("source").write_text(str(self.primary))
        self.legacy_baseline("source").chmod(0o600)
        self.reject("release-country", "partial legacy baseline")

    def test_release_corrupt_baseline_and_marker_rejected(self):
        self.legacy_v9()
        old = self.legacy_baseline("before.sha256").read_bytes()
        self.legacy_baseline("before.sha256").write_bytes(b"wrong")
        self.reject("release-country", "baseline identity")
        self.legacy_baseline("before.sha256").write_bytes(old)
        self.run_helper("release-country")
        self.legacy_baseline("country-released").write_bytes(b"wrong")
        self.reject("release-country", "marker identity")

    def test_release_source_race_rejected_and_no_marker_published(self):
        self.legacy_v9()
        process, sync = self.paused("release-country")
        try:
            latest = self.primary.read_bytes().replace(b"public-token-A", b"public-token-B")
            self.primary.write_bytes(latest)
            self.release_rejected(process, sync)
            self.assertFalse(self.legacy_baseline("country-released").exists())
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()

    def test_unknown_compressed_flagset_rejected(self):
        self.save(frame(metadata(), b"unknown-compressed-payload"))
        self.reject(message="unrecognized compressed")
        self.assertFalse(list(self.state.glob("*-before.pb")))

    def test_unknown_country_map_preserved(self):
        self.save(frame(metadata([bin_entry(COUNTRY, ld(5, b"unknown-map"))]), self.snapshots[0]))
        prior = decode(self.primary.read_bytes())[2][COUNTRY]
        self.run_helper()
        self.assertEqual(decode(self.primary.read_bytes())[2][COUNTRY], prior)
        self.run_helper("rollback")
        self.assertEqual(decode(self.primary.read_bytes())[2][COUNTRY], prior)

    def test_wrong_bool_type_rejected(self):
        self.save(frame(metadata([bin_entry(BOOL, scalar(1, 1))]), self.snapshots[0]))
        self.reject(message="type mismatch")

    def test_unmanaged_country_type_preserved(self):
        self.save(frame(metadata([bin_entry(COUNTRY, ld(4, self.captured[0]))]), self.snapshots[0]))
        prior = decode(self.primary.read_bytes())[2][COUNTRY]
        self.run_helper()
        self.assertEqual(decode(self.primary.read_bytes())[2][COUNTRY], prior)

    def test_invalid_boolean_rejected(self):
        self.save(frame(metadata([bin_entry(BOOL, scalar(2, 2))]), self.snapshots[0]))
        self.reject(message="invalid Boolean")

    def test_duplicate_typed_fields_rejected(self):
        self.save(frame(metadata([bin_entry(BOOL, scalar(2, 0) + scalar(2, 1))]), self.snapshots[0]))
        self.reject(message="type mismatch")

    def test_duplicate_override_key_rejected(self):
        record = bin_entry(BOOL, scalar(2, 0))
        self.save(frame(metadata([record, record]), self.snapshots[0]))
        self.reject(message="duplicate override")

    def test_missing_or_mismatched_bin_name_rejected(self):
        for name in ("", "other"):
            with self.subTest(name=name):
                self.save(frame(metadata([bin_entry(BOOL, scalar(2, 0), name=name)]), self.snapshots[0]))
                self.reject(message="bin name mismatch")

    def test_alias_bin_name_rejected(self):
        self.save(frame(metadata([bin_entry("other", scalar(2, 0), name=BOOL)]), self.snapshots[0]))
        self.reject(message="bin name alias")

    def test_corrupt_and_unsupported_framing_rejected(self):
        cases = [b"", self.original[:8], struct.pack("<II", 2, 0) + self.original[8:],
                 self.original + b"trailing", self.original[:-1],
                 frame(metadata(extra=ld(1, "duplicate-token")), self.snapshots[0])]
        for data in cases:
            with self.subTest(size=len(data)):
                self.save(data)
                self.reject()

    def test_primary_symlink_rejected(self):
        real = self.root / "real.pb"
        self.primary.rename(real)
        self.primary.symlink_to(real)
        self.reject(message="cannot open regular")
        self.assertEqual(real.read_bytes(), self.original)

    def test_state_symlink_and_nonprivate_mode_rejected(self):
        self.state.chmod(0o755)
        self.reject(message="state directory")
        self.state.chmod(0o700)
        real = self.root / "real-state"
        self.state.rename(real)
        self.state.symlink_to(real, target_is_directory=True)
        self.reject(message="state directory")

    def test_lock_nonprivate_and_symlink_rejected(self):
        lock = self.state / "cache-overlay-lock"
        lock.write_bytes(b"")
        lock.chmod(0o644)
        self.reject(message="private overlay state")
        lock.unlink()
        real = self.root / "real-lock"
        real.touch(mode=0o600)
        lock.symlink_to(real)
        self.reject(message="private overlay state")

    def test_baseline_nonprivate_or_symlink_rejected(self):
        self.run_helper()
        source = self.baseline("source")
        source.chmod(0o644)
        self.reject("rollback", "baseline is not private")
        source.chmod(0o600)
        real = self.root / "baseline-source"
        source.rename(real)
        source.symlink_to(real)
        self.reject("rollback", "cannot open regular")

    def test_corrupt_baseline_checksum_rejected(self):
        self.run_helper()
        self.baseline("before.pb").write_bytes(self.original + b"corrupted")
        self.reject("rollback", "baseline identity")

    def test_partial_baseline_rejected_for_apply_and_rollback(self):
        self.baseline("source").write_text(str(self.primary))
        self.baseline("source").chmod(0o600)
        self.reject("apply", "partial baseline")
        self.reject("rollback", "partial baseline")

    def test_missing_baseline_rollback_is_unchanged(self):
        self.run_helper("rollback", "unchanged")

    def test_same_inode_edit_detected_before_publication(self):
        process, sync = self.paused()
        try:
            original_inode = self.primary.stat().st_ino
            newer = self.original.replace(b"public-token-A", b"public-token-B")
            self.primary.write_bytes(newer)
            self.assertEqual(self.primary.stat().st_ino, original_inode)
            self.release_rejected(process, sync)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()

    def test_replaced_source_detected_before_publication(self):
        process, sync = self.paused()
        try:
            replacement = self.root / "replacement.pb"
            replacement.write_bytes(self.original)
            replacement.chmod(0o640)
            os.replace(replacement, self.primary)
            self.release_rejected(process, sync)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()

    def test_mode_change_detected_before_publication(self):
        process, sync = self.paused()
        try:
            self.primary.chmod(0o600)
            self.release_rejected(process, sync)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()

    def test_two_helpers_serialize_and_second_is_idempotent(self):
        process, sync = self.paused()
        second = subprocess.Popen(self.command(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            (sync / "continue").touch(mode=0o600)
            out1, err1 = process.communicate(timeout=5)
            out2, err2 = second.communicate(timeout=5)
            self.assertEqual((process.returncode, out1.strip()), (0, "changed"), err1)
            self.assertEqual((second.returncode, out2.strip()), (0, "unchanged"), err2)
            self.run_helper("inspect", "true")
            self.assertEqual(len(list(self.state.glob("*-before.pb"))), 1)
        finally:
            for child in (process, second):
                if child.poll() is None:
                    child.kill()
                    child.communicate()

    def resolve_info(self, includes=(), excludes=(), backing=ld(7, vi(6)),
                     secret=bytes(range(16)), enabled=1, sdk=37, root="/data/user/0/com.google.android.gms"):
        info = (ld(1, secret) + scalar(2, enabled) + ld(3, "app_phenotype_shared") +
                b"".join(ld(5, name) for name in includes) + b"".join(ld(6, name) for name in excludes) +
                backing + ld(8, ld(1, root) + scalar(2, sdk)))
        path = self.root / "storage-info.pb"
        path.write_bytes(info)
        return subprocess.run([str(HELPER), "--resolve", "--storage-info", str(path)],
                              capture_output=True, text=True, timeout=5)

    def test_resolver_file_backing_and_namespace_eligibility(self):
        for backing in (ld(7, vi(3) + vi(6)), scalar(7, 6)):
            for includes in ((), ("other", "mosey_app_android")):
                with self.subTest(backing=backing, includes=includes):
                    result = self.resolve_info(includes=includes, excludes=("other",), backing=backing)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    # Filename independently confirmed against the APK60715 live reader.
                    self.assertEqual(result.stdout, "/data/user/0/com.google.android.gms/app_phenotype_shared/AAECAwQFBgcICQoLDA0ODw==/QheAx_hRQRlcc32GD8w5vA==.pb\n")

    def test_resolver_rejects_missing_file_and_ineligible_namespace(self):
        for kwargs in ({"backing": b""}, {"backing": ld(7, vi(3))},
                       {"includes": ("other",)}, {"excludes": ("mosey_app_android",)},
                       {"includes": ("mosey_app_android",), "excludes": ("mosey_app_android",)}):
            with self.subTest(kwargs=kwargs):
                result = self.resolve_info(**kwargs)
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertEqual(result.stdout, "")

    def test_resolver_rejects_unsupported_shared_storage_contract(self):
        for kwargs in ({"secret": b"short"}, {"enabled": 0}, {"sdk": 36}, {"root": "/untrusted/gms"},
                       {"backing": ld(7, b"\x80")}, {"backing": ld(7, b"\xff" * 11)}):
            with self.subTest(kwargs=kwargs):
                result = self.resolve_info(**kwargs)
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--helper", type=Path, required=True)
    args, remaining = parser.parse_known_args()
    HELPER = args.helper.resolve()
    unittest.main(argv=[__file__, *remaining])
