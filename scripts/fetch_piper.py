"""Fetch a pinned official Piper asset tree, retaining relative USD paths."""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
REPO='agilexrobotics/piper_isaac_sim'
COMMIT='8e1f88fdb7afca49c40e9a0c1c01cc588e86f0d2'

def fetch(url):
    return urllib.request.urlopen(url,timeout=90).read()

def main():
    tree=json.loads(fetch(f'https://api.github.com/repos/{REPO}/git/trees/{COMMIT}?recursive=1'))
    names=[x['path'] for x in tree['tree'] if x['type']=='blob' and
           (x['path'].startswith('piper_description/') or x['path'] in
            ['README.md','USD/piper_v1.usd','USD/piper_v2.usd'])]
    def download(name):
        target=ROOT/'assets/piper'/name
        if target.exists():
            data=target.read_bytes()
        else:
            data=fetch(f'https://raw.githubusercontent.com/{REPO}/{COMMIT}/{name}')
            if data.startswith(b'version https://git-lfs'):
                raise RuntimeError(f'Git LFS payload required for {name}')
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(data)
        return name,hashlib.sha256(data).hexdigest()
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        hashes=dict(pool.map(download,names))
    (ROOT/'assets/source.json').write_text(json.dumps({'repository':f'https://github.com/{REPO}',
        'commit':COMMIT,'sha256':hashes},indent=2))
    print(json.dumps({'files':len(hashes),'commit':COMMIT}),flush=True)

if __name__=='__main__':
    main()
