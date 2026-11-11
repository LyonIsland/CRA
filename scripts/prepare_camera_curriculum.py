"""Create authored BRICKLAB tasks for visual pretraining scene diversity.

Their layouts are environment inputs; the learner receives no authored poses.
"""
import argparse
import json
from pathlib import Path
from bricklab_prepare import prepare


def build(out):
    out=Path(out);out.mkdir(parents=True,exist_ok=False)
    tasks=[]
    layouts={
        'tower4':[(8,9,3*i) for i in range(4)],
        'pyramid12':[(4*i+2*layer,9,3*layer) for layer in range(3) for i in range(5-layer)],
    }
    for name,positions in layouts.items():
        source=out/(name+'.json')
        source.write_text(json.dumps({'version':1,'boardSize':20,'title':name,
            'bricks':[{'id':f'b{i}','type':'brick-2x4','color':'cream','x':x,'z':z,'y':y,'rotation':90}
                      for i,(x,z,y) in enumerate(positions)]}),encoding='utf-8')
        result=prepare(source,out/name,mode='steps')
        tasks.append(result['task'])
    root=Path(__file__).resolve().parents[1]
    wall=str(root/'outputs/bricklab/camera-wall/task.json')
    house=str(root/'outputs/bricklab/house-integration-2/task.json')
    config={'train':[wall,*tasks],'validation':[wall,house]}
    (out/'tasks.json').write_text(json.dumps(config,indent=2),encoding='utf-8')
    print(json.dumps(config),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True)
    build(parser.parse_args().out)
