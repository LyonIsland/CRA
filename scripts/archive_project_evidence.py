"""Lossless split archives of project evidence (requires zstandard).

Original files are read only. Each archive and source file gets SHA-256 evidence.
Large live logs are captured at their initial length, never truncated in place.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
import os
from pathlib import Path
import re
import tarfile
import time
import zstandard

ROOT=Path(__file__).resolve().parents[1]
EXCLUDE_DIRS={'.git','node_modules','__pycache__','.venv','venv','.pytest_cache'}
SECRET_PATTERNS=[re.compile(rb'(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})'),
                 re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----')]


def files(root,prefix,exclude=()):
    for directory,dirs,names in os.walk(root):
        dirs[:]=sorted(d for d in dirs if d not in EXCLUDE_DIRS and d not in exclude)
        for name in sorted(names):
            path=Path(directory)/name
            if name=='STOP' or path.suffix in ('.pyc','.pid','.pem','.key') or name=='.env' or name.startswith('.env.'):
                continue
            if path.is_symlink():raise ValueError('Refusing archive symlink: '+str(path))
            yield path,(Path(prefix)/path.relative_to(root)).as_posix()


class SplitWriter:
    def __init__(self,folder,name,limit):
        self.folder=folder;self.name=name;self.limit=limit;self.handle=None;self.parts=[];self.size=0
    def writable(self):return True
    def write(self,data):
        total=len(data);data=memoryview(data)
        while data:
            if self.handle is None:
                self.path=self.folder/f'{self.name}.tar.zst.part{len(self.parts)+1:03d}'
                self.handle=self.path.with_suffix(self.path.suffix+'.partial').open('xb')
                self.digest=hashlib.sha256();self.size=0
            count=min(len(data),self.limit-self.size);piece=data[:count]
            self.handle.write(piece);self.digest.update(piece);self.size+=count;data=data[count:]
            if self.size==self.limit:self.finish_part()
        return total
    def flush(self):
        if self.handle:self.handle.flush()
    def finish_part(self):
        if self.handle:
            temporary=Path(self.handle.name);self.handle.close();temporary.replace(self.path)
            self.parts.append({'name':self.path.name,'bytes':self.size,'sha256':self.digest.hexdigest()})
            self.handle=None
    def close(self):self.finish_part()


class AuditedReader:
    def __init__(self,handle,path):self.handle=handle;self.path=path;self.digest=hashlib.sha256();self.tail=b''
    def read(self,size=-1):
        data=self.handle.read(size);self.digest.update(data)
        sample=self.tail+data
        if any(pattern.search(sample) for pattern in SECRET_PATTERNS):
            raise ValueError('Credential-shaped content requires review: '+str(self.path))
        self.tail=sample[-256:]
        return data


def pack(out,name,entries,limit):
    entries=list(entries);writer=SplitWriter(out,name,limit);records=[];started=time.monotonic()
    raw=sum(p.stat().st_size for p,_ in entries)
    print(json.dumps({'group':name,'files':len(entries),'raw_bytes':raw}),flush=True)
    with zstandard.ZstdCompressor(level=6,threads=2).stream_writer(writer,closefd=False) as compressed:
        with tarfile.open(fileobj=compressed,mode='w|',bufsize=1024*1024,copybufsize=1024*1024) as archive:
            for index,(path,relative) in enumerate(entries):
                info=archive.gettarinfo(str(path),arcname=relative)
                with path.open('rb') as handle:
                    reader=AuditedReader(handle,path);archive.addfile(info,reader)
                records.append({'path':relative,'bytes':info.size,'sha256':reader.digest.hexdigest(),
                                'source_grew_during_snapshot':path.stat().st_size!=info.size})
                if index%20==0 or info.size>512*1024*1024:
                    print(json.dumps({'group':name,'completed_files':index+1,'total_files':len(entries),
                                      'elapsed_seconds':round(time.monotonic()-started)}),flush=True)
    writer.close()
    manifest={'group':name,'format':'concatenated tar.zst parts','raw_bytes':sum(x['bytes'] for x in records),
              'parts':writer.parts,'files':records}
    (out/(name+'.manifest.json')).write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(json.dumps({'group':name,'complete':True,'compressed_bytes':sum(p['bytes'] for p in writer.parts)}),flush=True)
    return manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--training-root',type=Path,default=Path('D:/PiperCameraTraining'))
    parser.add_argument('--part-mib',type=int,default=512)
    args=parser.parse_args();args.out.mkdir(parents=True,exist_ok=False)
    if not 1<=args.part_mib<=1024:parser.error('Part size must be 1..1024 MiB')
    groups={
        'project-outputs':list(files(ROOT/'outputs','project/outputs',exclude={'xr_sessions'})),
        'xr-history':list(files(ROOT/'outputs/xr_sessions','project/outputs/xr_sessions')),
        'camera-training':list(files(args.training_root,'camera-training')),
        'simulation-assets':list(files(ROOT/'assets/piper','project/assets/piper'))+
                            list(files(ROOT/'generated','project/generated'))+
                            list(files(ROOT/'tools/BRICKLAB','project/tools/BRICKLAB')),
    }
    groups['project-outputs'] += [(p,'project/'+p.name) for p in ROOT.iterdir()
                                  if p.is_file() and (p.suffix=='.log' or p.name in ('preflight.json','deployment-status.json'))]
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures=[pool.submit(pack,args.out,name,entries,args.part_mib*1048576) for name,entries in groups.items()]
        manifests=[future.result() for future in futures]
    summary={'schema':'cra-evidence-archive-v1','created_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
             'source_roots':{'project':str(ROOT),'camera-training':str(args.training_root)},
             'excluded':['installed Python/Node environments','download caches and installers','Git internal metadata',
                         'credentials and key files','runtime PID/STOP control files'],
             'groups':[{k:v for k,v in m.items() if k!='files'} for m in manifests]}
    (args.out/'artifact-manifest.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps({'complete':True,'manifest':str(args.out/'artifact-manifest.json')}),flush=True)


if __name__=='__main__':main()
