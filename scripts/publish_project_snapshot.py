"""Upload evidence to an existing GitHub repo without changing its visibility.

Authentication uses Git Credential Manager in memory; credentials are never
printed, written to the project, or placed on the command line. Upload first to
a draft release; publish only after the requested source commit exists remotely.
Requires requests. Supports resuming already verified assets.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
from urllib.parse import urlsplit,quote
from urllib.request import getproxies
import requests


def sha(path):
    digest=hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda:handle.read(4*1024*1024),b''):digest.update(block)
    return digest.hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',required=True);parser.add_argument('--tag',required=True)
    parser.add_argument('--assets',type=Path,required=True)
    parser.add_argument('--phase',choices=['upload','publish'],default='upload')
    parser.add_argument('--commit');parser.add_argument('--body-file',type=Path)
    args=parser.parse_args()
    if not re.fullmatch(r'[\w.-]+/[\w.-]+',args.repo):parser.error('Expected owner/repository')
    credential=subprocess.run(['git','credential','fill'],input=f'protocol=https\nhost=github.com\npath={args.repo}.git\n\n',
                              text=True,capture_output=True,timeout=30,
                              env={**os.environ,'GIT_TERMINAL_PROMPT':'0','GCM_INTERACTIVE':'Never'})
    fields=dict(line.split('=',1) for line in credential.stdout.splitlines() if '=' in line)
    if credential.returncode or not fields.get('password'):raise RuntimeError('GitHub credential unavailable')
    headers={'Authorization':'Bearer '+fields['password'],'User-Agent':'CRA-evidence-publication',
             'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28'}
    proxies={k:v for k,v in getproxies().items() if k in ('http','https')}
    base='https://api.github.com/repos/'+args.repo
    def api(method,url,**kwargs):
        if urlsplit(url).hostname not in ('api.github.com','uploads.github.com') or urlsplit(url).scheme!='https':
            raise ValueError('Refusing to send GitHub authentication to another host')
        response=requests.request(method,url,headers={**headers,**kwargs.pop('headers',{})},proxies=proxies,
                                  timeout=(30,1800),**kwargs)
        if not response.ok:raise RuntimeError(f'GitHub {method} failed: HTTP {response.status_code} {response.text[:250]}')
        return response.json() if response.content else None
    repo=api('GET',base)
    if not repo.get('permissions',{}).get('push'):raise RuntimeError('Repository write access required')
    releases=api('GET',base+'/releases?per_page=100')
    release=next((r for r in releases if r['tag_name']==args.tag),None)
    if release is None:
        if args.phase=='publish':raise RuntimeError('Upload the draft first')
        release=api('POST',base+'/releases',json={'tag_name':args.tag,'target_commitish':repo['default_branch'],
            'name':'Project and experiment snapshot — 2026-11-11','draft':True,'prerelease':False,
            'body':'Uploading complete experiment evidence; source and analysis will be linked before publication.'})
    state={'repository':args.repo,'private':repo['private'],'release_id':release['id'],
           'release_url':f'https://github.com/{args.repo}/releases/tag/{args.tag}','tag':args.tag}
    def assets():
        result=[];page=1
        while True:
            rows=api('GET',base+f'/releases/{release["id"]}/assets?per_page=100&page={page}')
            result.extend(rows)
            if len(rows)<100:return {row['name']:row for row in result}
            page+=1
    def verified(remote,item):
        return (remote is not None and remote['state']=='uploaded' and remote['size']==item['bytes'] and
                remote.get('digest')=='sha256:'+item['sha256'])
    def entries():
        result={}
        for manifest_path in args.assets.glob('*.manifest.json'):
            manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
            for item in manifest['parts']:result[item['name']]=item
            result[manifest_path.name]={'name':manifest_path.name,'bytes':manifest_path.stat().st_size,'sha256':sha(manifest_path)}
        final=args.assets/'artifact-manifest.json'
        if final.is_file():result[final.name]={'name':final.name,'bytes':final.stat().st_size,'sha256':sha(final)}
        return result
    if args.phase=='publish':
        if not args.commit or not re.fullmatch(r'[0-9a-f]{40}',args.commit):parser.error('Publish requires a full commit SHA')
        if not (args.assets/'artifact-manifest.json').is_file():raise RuntimeError('Archive creation is incomplete')
        remote=assets();expected=entries()
        if any(not verified(remote.get(name),item) for name,item in expected.items()):raise RuntimeError('Release assets are incomplete or checksums differ')
        commit=api('GET',base+'/commits/'+args.commit)
        if commit['sha']!=args.commit:raise RuntimeError('Source commit missing on GitHub')
        body=args.body_file.read_text(encoding='utf-8') if args.body_file else release['body']
        release=api('PATCH',base+f'/releases/{release["id"]}',json={'draft':False,'target_commitish':args.commit,'body':body})
        state.update(published=True,commit=args.commit,asset_count=len(expected),asset_bytes=sum(x['bytes'] for x in expected.values()))
    else:
        if not release['draft']:raise RuntimeError('Refusing to modify an already published snapshot')
        remote=assets();done={name for name,item in entries().items() if verified(remote.get(name),item)}
        upload_url=release['upload_url'].split('{',1)[0]
        def upload(item):
            name=item['name'];path=args.assets/name
            if Path(name).name!=name or path.stat().st_size!=item['bytes'] or sha(path)!=item['sha256']:
                raise ValueError('Archive checksum/path mismatch: '+name)
            print(json.dumps({'uploading':name,'bytes':item['bytes']}),flush=True)
            for attempt in range(4):
                previous=assets().get(name)
                if verified(previous,item):return name
                if previous:
                    if previous['state']=='uploaded':raise RuntimeError('Existing completed asset differs: '+name)
                    api('DELETE',base+f'/releases/assets/{previous["id"]}')
                try:
                    with path.open('rb') as handle:
                        response=api('POST',upload_url+'?name='+quote(name,safe=''),data=handle,
                                     headers={'Content-Type':'application/octet-stream','Content-Length':str(item['bytes'])})
                    if not verified(response,item):raise RuntimeError('Remote SHA-256 mismatch: '+name)
                    print(json.dumps({'uploaded':name,'sha256_verified':True}),flush=True)
                    return name
                except (requests.RequestException,RuntimeError):
                    if attempt==3:raise
                    time.sleep(3*(attempt+1))
        deadline=time.monotonic()+7200
        with ThreadPoolExecutor(max_workers=3) as pool:
            running={}
            while True:
                expected=entries()
                for name,item in expected.items():
                    if name not in done and name not in running:running[name]=pool.submit(upload,item)
                for name,future in list(running.items()):
                    if future.done():done.add(future.result());del running[name]
                if (args.assets/'artifact-manifest.json').is_file() and not running and set(expected)<=done:break
                if time.monotonic()>deadline:raise TimeoutError('Publication time limit; rerun to resume verified assets')
                time.sleep(2)
        state.update(published=False,uploaded_asset_count=len(done),asset_bytes=sum(x['bytes'] for x in expected.values()))
    (args.assets/'release-state.json').write_text(json.dumps(state,indent=2),encoding='utf-8')
    print(json.dumps(state),flush=True)


if __name__=='__main__':main()
