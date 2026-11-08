"""Download NVIDIA wheels in verified resumable ranges from its official index."""
import argparse
import concurrent.futures
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import threading
import urllib.parse
import urllib.request

ROOT=Path(__file__).resolve().parents[1]

class Links(HTMLParser):
    def __init__(self):
        super().__init__(); self.links=[]
    def handle_starttag(self,tag,attrs):
        if tag=='a': self.links.extend(v for k,v in attrs if k=='href')

def cache(package, workers):
    index=f'https://pypi.nvidia.cn/{package}/'
    parser=Links()
    parser.feed(urllib.request.urlopen(index,timeout=30).read().decode())
    url=next(urllib.parse.urljoin(index,s) for s in parser.links
             if '-5.1.0.0-' in s and 'cp311' in s and 'win_amd64.whl' in s)
    expected=urllib.parse.parse_qs(urllib.parse.urlparse(url).fragment)['sha256'][0]
    url=url.split('#')[0]
    folder=ROOT/'wheelhouse'; folder.mkdir(exist_ok=True)
    target=folder/Path(urllib.parse.urlparse(url).path).name
    if target.exists() and hashlib.file_digest(target.open('rb'),'sha256').hexdigest()==expected:
        print(f'Already verified {target.name}',flush=True); return
    head=urllib.request.urlopen(urllib.request.Request(url,method='HEAD'),timeout=30)
    length=int(head.headers['Content-Length'])
    part=target.with_suffix('.part')
    state=target.with_suffix('.parts.json')
    size=32*1024*1024
    chunks=(length+size-1)//size
    completed=set(json.loads(state.read_text())) if state.exists() and part.exists() and part.stat().st_size==length else set()
    if not part.exists() or part.stat().st_size!=length:
        with part.open('wb') as f: f.truncate(length)
    lock=threading.Lock()
    def download(i):
        if i in completed: return
        first,last=i*size,min((i+1)*size,length)-1
        for attempt in range(4):
            try:
                request=urllib.request.Request(url,headers={'Range':f'bytes={first}-{last}'})
                with urllib.request.urlopen(request,timeout=45) as response:
                    if response.status!=206 or not response.headers.get('Content-Range','').startswith(f'bytes {first}-{last}/'):
                        raise RuntimeError('Server did not honor exact range')
                    with part.open('r+b') as f:
                        f.seek(first); remaining=last-first+1
                        while remaining:
                            block=response.read(min(1024*1024,remaining))
                            if not block: raise RuntimeError('Incomplete range')
                            f.write(block); remaining-=len(block)
                with lock:
                    completed.add(i)
                    state.write_text(json.dumps(sorted(completed)))
                    if len(completed)%8==0 or len(completed)==chunks:
                        print(json.dumps({'package':package,'parts':len(completed),'total_parts':chunks}),flush=True)
                return
            except Exception:
                if attempt==3: raise
    print(json.dumps({'package':package,'bytes':length,'workers':workers}),flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(download,range(chunks)))
    with part.open('rb') as f: actual=hashlib.file_digest(f,'sha256').hexdigest()
    if actual!=expected: raise RuntimeError(f'SHA256 mismatch: {package}')
    os.replace(part,target)
    print(f'Verified {target.name}',flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('packages',nargs='*',default=['isaacsim-extscache-kit','isaacsim-extscache-kit-sdk','isaacsim-extscache-physics'])
    p.add_argument('--workers',type=int,default=6)
    p.add_argument('--components',action='store_true')
    args=p.parse_args()
    if args.components:
        info=json.load(urllib.request.urlopen('https://pypi.org/pypi/isaacsim/5.1.0.0/json',timeout=30))['info']
        args.packages=['isaacsim']+sorted({r.split('==')[0] for r in info['requires_dist']
            if 'extra == "all"' in r or ';' not in r})
    if args.components:
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(lambda name:cache(name,min(args.workers,3)),args.packages))
    else:
        for name in args.packages: cache(name,args.workers)
