"""Prepare the basic six-axis Piper + standard gripper, without camera USDs."""
import json
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]

def main():
    source=ROOT/'assets/piper/piper_description/urdf/piper_description.urdf'
    tree=ET.parse(source)
    for mesh in tree.findall('.//mesh'):
        name=mesh.get('filename')
        prefix='package://piper_description/'
        if not name.startswith(prefix):
            raise RuntimeError(f'Unexpected mesh reference {name}')
        path=ROOT/'assets/piper/piper_description'/name.removeprefix(prefix)
        if not path.is_file():
            raise FileNotFoundError(path)
        mesh.set('filename',path.as_posix())
    folder=ROOT/'generated'
    folder.mkdir(exist_ok=True)
    target=folder/'piper_basic.urdf'
    tree.write(target,encoding='utf-8',xml_declaration=True)
    joints=[{'name':j.get('name'),'type':j.get('type'),
             'limit':j.find('limit').attrib if j.find('limit') is not None else {}}
             for j in tree.findall('joint')]
    (folder/'model_inventory.json').write_text(json.dumps({'source':str(source),
            'working_urdf':str(target),'joints':joints,
            'note':'basic Piper, six revolute axes and two standard gripper slides; no camera'},indent=2))
    print(target)

if __name__=='__main__':
    main()
