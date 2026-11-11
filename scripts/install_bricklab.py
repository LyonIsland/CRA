"""Install a local BRICKLAB ZIP/directory, preserving the original source."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

ROOT=Path(__file__).resolve().parents[1]


def snapshot_hash(root):
    digest=hashlib.sha256()
    for path in sorted(root.rglob('*')):
        relative=path.relative_to(root)
        if path.is_file() and not any(part in ('.git','__pycache__','.venv','node_modules','jobs') for part in relative.parts) and path.suffix!='.pyc':
            digest.update(relative.as_posix().encode()+b'\0'+hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def install(source):
    source=Path(source).resolve()
    target=ROOT/'tools/BRICKLAB'
    archive_hash=hashlib.sha256(source.read_bytes()).hexdigest() if source.is_file() else None
    if not target.exists():
        if source.is_dir():
            if not (source/'isaaclab-bridge/manual_renderer.py').is_file():raise ValueError('Not a BRICKLAB source directory')
            shutil.copytree(source,target,ignore=shutil.ignore_patterns('.git','__pycache__','.venv','node_modules','jobs'))
        else:
            with zipfile.ZipFile(source) as archive:
                files=[item for item in archive.infolist() if not item.is_dir()]
                if sum(item.file_size for item in files)>100*1024*1024:raise ValueError('Unexpectedly large source archive')
                prefixes={Path(item.filename).parts[0] for item in files}
                if len(prefixes)!=1:raise ValueError('Expected one source root in archive')
                for item in files:
                    relative=Path(*Path(item.filename).parts[1:])
                    resolved=(target/relative).resolve()
                    if target.resolve() not in resolved.parents or '..' in relative.parts:raise ValueError('Unsafe archive member')
                for item in files:
                    path=target.joinpath(*Path(item.filename).parts[1:])
                    path.parent.mkdir(parents=True,exist_ok=True)
                    path.write_bytes(archive.read(item))
    if not (target/'isaaclab-bridge/manual_renderer.py').is_file():raise ValueError('BRICKLAB source is incomplete')
    digest=snapshot_hash(target)
    lock=ROOT/'config/bricklab-source.json'
    if lock.is_file():
        expected=json.loads(lock.read_text(encoding='utf-8'))['tree_sha256']
        if digest!=expected:raise ValueError('Installed BRICKLAB differs from the reviewed snapshot; preserve it and review before changing the lock')
    else:
        lock.parent.mkdir(exist_ok=True)
        lock.write_text(json.dumps({'repository':'https://github.com/EXTEND-Intelligence/BRICKLAB',
            'distribution':'user-supplied local source; no Git commit available',
            'archive_sha256':archive_hash,'tree_sha256':digest},indent=2),encoding='utf-8')
    return {'source':str(source),'installed':str(target),'tree_sha256':digest}


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('source',type=Path)
    args=parser.parse_args()
    print(json.dumps(install(args.source)))
