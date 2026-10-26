#!/usr/bin/env python3
"""Reject malformed modified/new XML before resource compilation.

AAPT2 can compile a values file while silently ignoring strings after its
closing resources tag. A patch applying successfully is not sufficient:
parse the entire XML document, including any trailing content.
"""
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def changed_xml(project):
    paths = set()
    for args in (
        ['diff', '--name-only', '-z', 'HEAD', '--', '*.xml'],
        ['ls-files', '--others', '--exclude-standard', '-z', '--', '*.xml'],
    ):
        result = subprocess.run(
            ['git', '-C', str(project), *args], check=True, stdout=subprocess.PIPE
        )
        paths.update(Path(name.decode()) for name in result.stdout.split(b'\0') if name)
    return sorted(paths)


def main(projects):
    checked = 0
    errors = 0
    for project in map(Path, projects):
        try:
            paths = changed_xml(project)
        except subprocess.CalledProcessError:
            print(f'XML check: cannot enumerate changes in {project}', file=sys.stderr)
            errors += 1
            continue
        for relative in paths:
            path = project / relative
            if not path.exists():  # A deliberately deleted XML file.
                continue
            checked += 1
            try:
                root = ET.parse(path).getroot()
                parts = relative.parts
                values_file = any(
                    parts[i] == 'res' and
                    (parts[i + 1] == 'values' or parts[i + 1].startswith('values-'))
                    for i in range(len(parts) - 1)
                )
                if values_file and root.tag != 'resources':
                    raise ValueError('values XML must have a <resources> root')
            except (ET.ParseError, OSError, ValueError) as exc:
                print(f'XML check: {path}: {exc}', file=sys.stderr)
                errors += 1
    print(f'XML check: {checked} modified/new files checked, {errors} errors')
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
