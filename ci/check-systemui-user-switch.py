#!/usr/bin/env python3
"""Exercise production QS arithmetic, blur sync and bouncer message flows on a JVM.

The complete blur class, AuthenticationFlags and message strings are unchanged.
QS's method and the bouncer's initial message flow are extracted verbatim. Android
views/services are host models; this does not replace device/instrumentation tests.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess


def method(source, signature):
    start = source.index(signature)
    brace = source.index('{', start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path, help='frameworks/base checkout')
    parser.add_argument('--ref', help='read a Git revision instead of the worktree')
    parser.add_argument('--kotlin-home', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=True)
    sources = output / 'src'
    hashes = {}

    def read(path):
        text = (subprocess.check_output(
            ['git', '-C', str(args.source), 'show', f'{args.ref}:{path}'], text=True)
            if args.ref else (args.source / path).read_text())
        hashes[path] = hashlib.sha256(text.encode()).hexdigest()
        return text

    def write(path, text):
        target = sources / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)

    prefix = 'packages/SystemUI/src/com/android/systemui/'
    qs = read(prefix + 'shade/QuickSettingsControllerImpl.java')
    write('Qs.java', '''public class Qs {
        boolean mAnimatingHiddenFromCollapsed;
        float mExpansionHeight;
        int mMinExpansionHeight, mMaxExpansionHeight;
        static class MathUtils {
            static float saturate(float v) { return Math.max(0f, Math.min(1f, v)); }
        }
        ''' + method(qs, 'float computeExpansionFraction()') + '\n}\n')
    for name in ['common/ui/view/BackgroundBlurAlphaSync.kt',
                 'keyguard/shared/model/AuthenticationFlags.kt',
                 'bouncer/shared/model/BouncerMessageStrings.kt',
                 'bouncer/shared/model/BouncerMessageModel.kt']:
        write(name, read(prefix + name))
    flags = read('core/java/com/android/internal/widget/LockPatternUtils.java')
    constants = re.findall(r'public static final int (\w*AUTH\w*) = (0x[0-9a-fA-F]+|0);', flags)
    write('LockPatternUtils.kt', 'package com.android.internal.widget\n'
          'class LockPatternUtils { object StrongAuthTracker {\n' + '\n'.join(
              f'const val {k} = {v}' for k, v in constants) + '\n} }\n')
    strings = (sources / 'bouncer/shared/model/BouncerMessageStrings.kt').read_text()
    resource_names = sorted(set(re.findall(r'(?<!internal\.)R\.string\.(\w+)', strings)))
    write('R.kt', 'package com.android.systemui.res\nobject R { object string {\n' +
          '\n'.join(f'const val {name} = {i+1}' for i, name in enumerate(resource_names)) + '\n} }')
    write('InternalR.kt', 'package com.android.internal\nobject R { object string { '
          'const val config_lockscreenLockoutShortlink = 1 } }')
    write('Resources.kt', 'package android.content.res\nclass ColorStateList\n'
          'class Resources { fun getString(id: Int) = id.toString() }')
    write('Flags.kt', 'package android.security\nobject Flags { '
          'fun secureLockDevice() = false; fun lockscreenTimeoutShortlink() = false; '
          'fun lockscreenLargerTimeoutTimeUnits() = false }')
    write('AuthModel.kt', 'package com.android.systemui.authentication.shared.model\n'
          'enum class AuthenticationMethodModel { None, Pin, Password, Pattern, Biometric, Sim }')
    write('View.kt', '''package android.view
        open class View {
            var alpha = 1f; var transitionAlpha = 1f; var parent: View? = null
            val viewTreeObserver = ViewTreeObserver()
        }
        class ViewTreeObserver {
            fun interface OnPreDrawListener { fun onPreDraw(): Boolean }
            val isAlive = true
            fun addOnPreDrawListener(v: OnPreDrawListener) {}
            fun removeOnPreDrawListener(v: OnPreDrawListener) {}
        }
    ''')
    write('Drawable.kt', 'package com.android.internal.graphics.drawable\n'
          'class BackgroundBlurDrawable { var alpha = 255 }')
    interactor = read(prefix + 'bouncer/domain/interactor/BouncerMessageInteractor.kt')
    flow = interactor[interactor.index('    private val initialBouncerMessage:'):
                      interactor.index('    fun onPrimaryAuthLockedOut(')]
    helpers = interactor[interactor.index('private fun Pair<Int, Int>.toMessage()'):]
    fixture = Path(__file__).with_name('tests') / 'SystemUiUserSwitchHarness.kt'
    write('SystemUiUserSwitchHarness.kt', fixture.read_text().replace(
        '// PRODUCTION_MESSAGE_FLOW', flow).replace('// PRODUCTION_MESSAGE_HELPERS', helpers))
    classes = output / 'classes'
    classes.mkdir(exist_ok=True)
    subprocess.run(['javac', '-d', str(classes), str(sources / 'Qs.java')], check=True)
    coroutines = args.kotlin_home.resolve() / 'lib/kotlinx-coroutines-core-jvm.jar'
    jar = output / 'tests.jar'
    compile_result = subprocess.run([
        str(args.kotlin_home.resolve() / 'bin/kotlinc'), '-J-Xmx512m', '-jvm-target', '17',
        '-cp', f'{classes}:{coroutines}', '-include-runtime', '-d', str(jar),
        *[str(p) for p in sources.rglob('*.kt')]], capture_output=True, text=True, timeout=90)
    (output / 'compile.log').write_text(compile_result.stdout + compile_result.stderr)
    if compile_result.returncode:
        raise RuntimeError(compile_result.stdout + compile_result.stderr)
    result = subprocess.run(['java', '-ea', '-cp', f'{jar}:{classes}:{coroutines}',
                             'SystemUiUserSwitchHarnessKt'],
                            capture_output=True, text=True, timeout=30)
    (output / 'run.log').write_text(result.stdout + result.stderr)
    counts = re.search(r'passed=(\d+) failed=(\d+)', result.stdout)
    report = {'source_sha256': hashes, 'exit': result.returncode,
              'passed': int(counts[1]) if counts else None,
              'failed': int(counts[2]) if counts else None}
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(result.stdout + result.stderr, end='')
    return int(result.returncode != 0 or counts is None)


if __name__ == '__main__':
    raise SystemExit(main())
