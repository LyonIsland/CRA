"""Install Android platform-tools from Google's published archive/checksum."""
import hashlib
import json
from pathlib import Path
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

ROOT=Path(__file__).resolve().parents[1]

def main():
    base='https://dl.google.com/android/repository/'
    xml=ET.fromstring(urllib.request.urlopen(base+'repository2-1.xml',timeout=30).read())
    # Namespace versions vary; match by local tag name instead of pinning them.
    def local(element): return element.tag.rsplit('}',1)[-1]
    package=next(e for e in xml.iter() if local(e)=='remotePackage' and e.get('path')=='platform-tools')
    archive=next(e for e in package.iter() if local(e)=='archive' and
                 any(local(x)=='host-os' and x.text=='windows' for x in e))
    complete=next(e for e in archive if local(e)=='complete')
    values={local(e):e for e in complete}
    url=base+values['url'].text
    checksum=values['checksum'].text
    algorithm=values['checksum'].get('type','sha1')
    folder=ROOT/'tools';folder.mkdir(exist_ok=True)
    path=folder/'platform-tools.zip'
    with urllib.request.urlopen(url,timeout=90) as response,path.open('wb') as target:
        while block:=response.read(1024*1024):target.write(block)
    digest=hashlib.new(algorithm,path.read_bytes()).hexdigest()
    if digest.lower()!=checksum.lower():raise RuntimeError('Google archive checksum mismatch')
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            destination=(folder/name).resolve()
            if not destination.is_relative_to(folder.resolve()):raise RuntimeError('Unsafe archive path')
        archive.extractall(folder)
    (folder/'platform-tools-source.json').write_text(json.dumps({'url':url,'algorithm':algorithm,'checksum':digest},indent=2))
    print(folder/'platform-tools/adb.exe')

if __name__=='__main__':main()
