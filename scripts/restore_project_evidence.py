"""Verify or restore release archives, with per-part and per-file SHA-256.

Requires zstandard. Verification streams decompressed data without storing it.
Restoration requires a new destination and refuses links or escaping paths.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path,PurePosixPath
import tarfile
import zstandard


class PartsReader(io.RawIOBase):
    def __init__(self,paths):self.paths=iter(paths);self.handle=None
    def readable(self):return True
    def readinto(self,buffer):
        while True:
            if self.handle is None:
                path=next(self.paths,None)
                if path is None:return 0
                self.handle=path.open('rb')
            count=self.handle.readinto(buffer)
            if count:return count
            self.handle.close();self.handle=None
    def close(self):
        if self.handle:self.handle.close()
        super().close()


def verify_part(path,item):
    if Path(item['name']).name!=item['name'] or path.stat().st_size!=item['bytes']:
        raise ValueError('Archive name/size mismatch: '+str(path))
    digest=hashlib.sha256()
    with path.open('rb') as handle:
        for data in iter(lambda:handle.read(4*1024*1024),b''):digest.update(data)
    if digest.hexdigest()!=item['sha256']:raise ValueError('Archive SHA-256 mismatch: '+str(path))


def process_group(directory,manifest,out=None):
    expected={item['path']:item for item in manifest['files']};seen=set();total=0
    for part in manifest['parts']:verify_part(directory/part['name'],part)
    with PartsReader([directory/p['name'] for p in manifest['parts']]) as combined:
        with zstandard.ZstdDecompressor().stream_reader(combined) as decoded:
            with tarfile.open(fileobj=decoded,mode='r|',bufsize=1024*1024) as archive:
                for member in archive:
                    name=member.name;relative=PurePosixPath(name)
                    if (name not in expected or name in seen or not member.isfile() or relative.is_absolute()
                        or '..' in relative.parts or '\\' in name or ':' in name):
                        raise ValueError('Unsafe or unexpected archive entry: '+name)
                    entry=expected[name]
                    if member.size!=entry['bytes']:raise ValueError('Source size mismatch: '+name)
                    target=None
                    if out:
                        path=(out/name).resolve()
                        if out not in path.parents:raise ValueError('Archive path escape')
                        path.parent.mkdir(parents=True,exist_ok=True);target=path.open('xb')
                    digest=hashlib.sha256()
                    try:
                        with archive.extractfile(member) as source:
                            for data in iter(lambda:source.read(1024*1024),b''):
                                digest.update(data)
                                if target:target.write(data)
                    finally:
                        if target:target.close()
                    if digest.hexdigest()!=entry['sha256']:raise ValueError('Source SHA-256 mismatch: '+name)
                    seen.add(name);total+=member.size
    if seen!=set(expected):raise ValueError('Archive is missing source files')
    return {'group':manifest['group'],'verified_files':len(seen),'verified_raw_bytes':total}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archives',type=Path,required=True)
    parser.add_argument('--out',type=Path)
    parser.add_argument('--verify-only',action='store_true')
    parser.add_argument('--groups',nargs='+')
    args=parser.parse_args()
    if not args.verify_only and not args.out:parser.error('Specify a NEW --out directory or --verify-only')
    out=None if args.verify_only else args.out.resolve()
    if out:out.mkdir(parents=True,exist_ok=False)
    summary=json.loads((args.archives/'artifact-manifest.json').read_text(encoding='utf-8'))
    groups=[g for g in summary['groups'] if not args.groups or g['group'] in args.groups]
    if args.groups and len(groups)!=len(set(args.groups)):raise ValueError('Unknown archive group')
    reports=[]
    for group in groups:
        manifest=json.loads((args.archives/(group['group']+'.manifest.json')).read_text(encoding='utf-8'))
        if manifest['parts']!=group['parts']:raise ValueError('Group manifest differs from archive index')
        report=process_group(args.archives,manifest,out);reports.append(report);print(json.dumps(report),flush=True)
    if out:(out/'restore-verification.json').write_text(json.dumps(reports,indent=2),encoding='utf-8')
    print(json.dumps({'complete':True,'verified_files':sum(r['verified_files'] for r in reports),
                      'verified_raw_bytes':sum(r['verified_raw_bytes'] for r in reports)}),flush=True)


if __name__=='__main__':main()
