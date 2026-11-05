#!/usr/bin/env python3
"""Export the built GKI UAPI plus pinned Onyx module UAPI for ROM userspace. No kernel build."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import tarfile
import tempfile


def sha(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def export(artifact, source_root, revision, baseline_root, output):
    report=json.loads((artifact/'report.json').read_text())
    archive=artifact/'gki/out-dir-kernel-headers.tar.gz'
    if sha(archive)!=report['sha256']['gki/out-dir-kernel-headers.tar.gz']:
        raise ValueError('GKI header archive hash mismatch')
    sources=json.loads(subprocess.check_output(['git','show',revision+':port/sources.json'],cwd=source_root))
    pin=next(p for p in sources['baseline'] if p['rom_path']=='kernel/xiaomi/sm8735')
    if subprocess.check_output(['git','rev-parse','HEAD'],cwd=baseline_root,text=True).strip()!=pin['revision']:
        raise ValueError('Wrong pinned ABI baseline')
    with tempfile.TemporaryDirectory(prefix='konoha-uapi-') as temp:
        work=Path(temp);tree=work/'export';tree.mkdir();material=work/'source';material.mkdir()
        hashes={};providers={}
        with tarfile.open(archive) as tar:
            for member in tar:
                path=PurePosixPath(member.name)
                if '..' in path.parts or path.is_absolute():raise ValueError('Unsafe GKI archive path')
                if member.isfile() and member.name.startswith('usr/include/'):
                    dest=tree/member.name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(tar.extractfile(member).read())
        process=subprocess.Popen(['git','archive',revision,'modules','common/scripts/headers_install.sh','common/scripts/unifdef.c'],cwd=source_root,stdout=subprocess.PIPE)
        selected=[]
        with tarfile.open(fileobj=process.stdout,mode='r|') as tar:
            for member in tar:
                path=PurePosixPath(member.name)
                if path.is_absolute() or '..' in path.parts:raise ValueError('Unsafe source archive path')
                if member.isfile() and (member.name in ['common/scripts/headers_install.sh','common/scripts/unifdef.c'] or (member.name.startswith('modules/') and '/include/uapi/' in member.name and member.name.endswith('.h'))):
                    dest=material/member.name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(tar.extractfile(member).read())
                    if member.name.startswith('modules/'):selected.append(dest)
        if process.wait():raise ValueError('Unable to read pinned source')
        (work/'scripts').mkdir()
        subprocess.run(['cc','-O2',str(material/'common/scripts/unifdef.c'),'-o',str(work/'scripts/unifdef')],check=True,capture_output=True)
        env={**os.environ,'objtree':str(work)}
        root_qsee='modules/include/uapi/linux/qseecom.h'
        for path in sorted(selected):
            original=path.relative_to(material).as_posix();relative=original.split('/include/uapi/',1)[1]
            keys=[relative]
            if relative.split('/')[0] in {'audio','camera','display','eva','synx','vidc','touch','sync_fence'}:
                keys.append(relative.split('/',1)[1])
            sanitized=work/'sanitized.h'
            result=subprocess.run(['sh',str(material/'common/scripts/headers_install.sh'),str(path),str(sanitized)],env=env,capture_output=True,text=True)
            if result.returncode:raise ValueError(original+': '+result.stderr)
            data=sanitized.read_bytes()
            for key in keys:
                if key in providers and (tree/'usr/include'/key).read_bytes()!=data:
                    # The port's full public qseecom ABI supersedes the deprecated subset.
                    if key=='linux/qseecom.h' and providers[key]==root_qsee:continue
                    raise ValueError('Conflicting module UAPI: '+key)
                dest=tree/'usr/include'/key;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(data);providers[key]=original
            hashes[original]=sha(path)
        # The device's existing userspace still uses the legacy ION ABI constants.
        # Carry their exact pinned syscall headers; no baseline kernel source is needed by the ROM.
        for name in ['ion.h','msm_ion.h','msm_ion_ids.h']:
            relative='include/uapi/linux/'+name
            data=subprocess.check_output(['git','show',pin['revision']+':'+relative],cwd=baseline_root)
            src=work/name;src.write_bytes(data)
            dest=tree/'usr/include/linux'/name
            subprocess.run(['sh',str(material/'common/scripts/headers_install.sh'),str(src),str(dest)],env=env,check=True,capture_output=True)
            hashes['baseline/'+relative]=sha(src)
        output.parent.mkdir(parents=True,exist_ok=True)
        with output.open('wb') as raw,gzip.GzipFile(filename='',mode='wb',fileobj=raw,mtime=0) as gz,tarfile.open(fileobj=gz,mode='w') as tar:
            for path in sorted(tree.rglob('*')):
                if not path.is_file():continue
                info=tar.gettarinfo(str(path),arcname=path.relative_to(tree).as_posix());info.uid=info.gid=0;info.uname=info.gname='';info.mtime=0;info.mode=0o644
                with path.open('rb') as f:tar.addfile(info,f)
        receipt={'source_revision':revision,'gki_archive_sha256':sha(archive),'module_source_headers':hashes,'module_export_providers':providers,'compatibility_header_baseline':pin,'headers':sum(p.is_file() for p in tree.rglob('*')),'archive_sha256':sha(output),'sanitizer':'Pinned Linux scripts/headers_install.sh with unifdef; __KERNEL__ sections removed'}
        output.with_suffix(output.suffix+'.json').write_text(json.dumps(receipt,indent=2)+'\n')
        print('Exported',receipt['headers'],'sanitized userspace headers to',output)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['artifact','source-root','baseline-root','output']:p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--source-revision',required=True);a=p.parse_args()
    export(a.artifact,a.source_root,a.source_revision,a.baseline_root,a.output)
