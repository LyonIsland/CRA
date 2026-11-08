"""Generate a human illustrated booklet and a shared machine-readable recipe."""
import html,json,math
from pathlib import Path
from assembly_agent import validate_recipe,target_pose,ROOT

OUT=ROOT/'assets/manuals/step_wall6'
PALETTE={'red':'#db3d36','blue':'#347cda','green':'#2aa76c','yellow':'#edca31','orange':'#ee852b','purple':'#9557c8'}
ZH={'red':'红色','blue':'蓝色','green':'绿色','yellow':'黄色','orange':'橙色','purple':'紫色'}

def recipe():
    specs=[('red',[0,0,0],[('fixture',8)]),('blue',[4,0,0],[('fixture',8)]),
           ('green',[8,0,0],[('fixture',8)]),('yellow',[2,0,1],[('S1',4),('S2',4)]),
           ('orange',[6,0,1],[('S2',4),('S3',4)]),('purple',[4,0,2],[('S4',4),('S5',4)])]
    steps=[]
    for i,(color,anchor,connections) in enumerate(specs,1):
        steps.append({'id':f'S{i}','part':{'catalog_id':'3001','studs_xy':[4,2],'color':color},
            'anchor_stud':anchor,'yaw_deg':0,'connections':[{'support_step':s,'stud_count':n} for s,n in connections],
            'human_instruction':f'找到一块{ZH[color]} 2×4 基础砖，长边沿图示方向，对齐后压紧。',
            'acceptance':{'position_tolerance_m':.001,'yaw_tolerance_deg':2,'connection_required':True}})
    return {'schema_version':'1.0','id':'step_wall6_v1','title':'六块积木 · 三层交错小墙',
        'geometry':{'stud_pitch_m':.008,'brick_height_m':.0096,'body_size_m':[.0318,.0158,.0096]},
        'frame':{'name':'assembly_fixture','origin':'底板第一个目标凸点中心的水平坐标；Z=底板连接基准面，不含凸点高度',
                 'registration_required':True,'source_layout_in_recipe':False},
        'fixture':{'type':'clamped_studded_baseplate','minimum_studs_xy':[12,2],
                   'recommended_studs_xy':[16,16],'must_be_registered_and_clamped':True},
        'bom':[{'catalog_id':'3001','studs_xy':[4,2],'color':c,'quantity':1} for c,_,_ in specs],
        'steps':steps,'execution':{'do_not_advance_without_connection_evidence':True,
                                  'assembly_frame_registration_is_not_supplied_by_recipe':True},
        'limits':['此说明书不是原厂 LEGO 说明书','纸面尺寸不代表经实物校准的插入力／公差','现有实心底部模型不能验证真实卡接']}

def drawing(steps,new_id=None):
    def point(x,y,z):return (80+29*x+15*y,220+10*x-17*y-26*z)
    def polygon(points,color,opacity=1,stroke='#26374b'):
        coords=' '.join(f'{a:.1f},{b:.1f}' for a,b in points)
        return f'<polygon points="{coords}" fill="{color}" fill-opacity="{opacity}" stroke="{stroke}" stroke-width="1.2"/>'
    body=['<svg viewBox="0 0 520 400" role="img" aria-label="逐步装配轴测图">']
    body.append(polygon([point(x,y,-.18) for x,y in [(-1,-1),(13,-1),(13,3),(-1,3)]],'#c4d6df'))
    for step in sorted(steps,key=lambda s:(s['anchor_stud'][2],s['anchor_stud'][0])):
        x,y,z=step['anchor_stud'];color=PALETTE[step['part']['color']];o=1 if new_id is None or step['id']==new_id else .45
        x-=.5;y-=.5
        body.append(polygon([point(x,y,z),point(x+4,y,z),point(x+4,y,z+1),point(x,y,z+1)],color,o))
        body.append(polygon([point(x+4,y,z),point(x+4,y+2,z),point(x+4,y+2,z+1),point(x+4,y,z+1)],color,o))
        body.append(polygon([point(x,y,z+1),point(x+4,y,z+1),point(x+4,y+2,z+1),point(x,y+2,z+1)],color,o))
        for i in range(4):
            for j in range(2):
                a,b=point(x+i+.5,y+j+.5,z+1.06)
                body.append(f'<ellipse cx="{a}" cy="{b}" rx="6" ry="3.6" fill="{color}" fill-opacity="{o}" stroke="#33495c"/>')
        if step['id']==new_id:
            a,b=point(x+2,y+1,z+1)
            body.append(f'<path d="M {a} {b-70} v 42 m -8 -9 l 8 9 l 8 -9" stroke="#162b47" stroke-width="4" fill="none"/>')
    body.append('</svg>');return ''.join(body)

def main():
    OUT.mkdir(parents=True,exist_ok=True);r=recipe();validate_recipe(r)
    (OUT/'recipe.json').write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8')
    pages=[f'<section class="page"><span class="kicker">PIPER · ASSEMBLY MANUAL 01</span><h1>{r["title"]}</h1>'
        '<p>固定目标结构，积木可散落在不同位置。每一步都先找料，再对齐和连接。</p>'+drawing(r['steps'])+
        '<h2>准备材料</h2><div class="parts">'+''.join(f'<span style="border-left:12px solid {PALETTE[b["color"]]}">{ZH[b["color"]]} 2×4 ×1</span>' for b in r['bom'])+'</div>'
        '<p>另需一块夹紧且已标定的底板，至少覆盖 12×2 凸点，建议使用 16×16 或更大底板。长边沿 X 方向，所有积木凸点朝上。</p>'
        '<p class="notice">这是项目生成的说明书。当前软件的规划、视觉与物理插接必须分别验收；摆到目标附近不等于已经卡接。</p></section>']
    for i,step in enumerate(r['steps']):
        x,y,layer=step['anchor_stud'];parents='底板' if layer==0 else '、'.join(c['support_step'] for c in step['connections'])
        pages.append(f'<section class="page"><span class="kicker">STEP {i+1} / 6</span><h1>{i+1}. {ZH[step["part"]["color"]]} 2×4 ×1</h1>'
            f'<p>{step["human_instruction"]}</p>'+drawing(r['steps'][:i+1],step['id'])+
            f'<div class="detail"><p>位置：从底板基准凸点起，沿 X 数 {x} 个间距，沿 Y 数 {y} 个间距；第 {layer+1} 层。</p>'
            f'<p>连接对象：{parents}。'+('全部 8 个凸点连接到底板。' if layer==0 else '分别覆盖两块下层积木各 4 个凸点，连接两侧。')+'</p>'
            '<p>检查：颜色和砖型正确、方向正确、与支撑块平行贴合、连接已确认；检查通过后再进行下一步。</p></div></section>')
    pages.append('<section class="page"><span class="kicker">AGENT EXECUTION CONTRACT</span><h1>给机器人 Agent 的执行规则</h1>'
        '<ol><li>说明书提供目标结构、砖型、颜色、方向及依赖；不提供散落积木位置。</li><li>使用当前视觉观察搜索和选择积木，避免重复占用同一块。</li>'
        '<li>底板未标定、缺料、遮挡或置信度不足时，停止并重新观察。</li><li>抓取、转向、限力压入和连接验收由独立技能执行。</li>'
        '<li>只有实际连接证据满足本步骤的连接关系，才能推进步骤。仅看到位置接近不能确认完成。</li></ol>'
        '<p>机器可读版本：recipe.json。当前 Agent 读取这份结构化版本，不声称能直接理解任意外部 PDF。</p>'
        '<p class="notice">现有 Windows 实心积木模型尚无经过验证的 LEGO 插接；执行器必须报告能力未就绪，不能自动把积木焊在一起后宣称完成。</p></section>')
    document='<!doctype html><html lang="zh-CN"><meta charset="UTF-8"><title>'+r['title']+'</title><style>'
    document+='body{margin:0;background:#eaf0f4;color:#1a3047;font:16px "Microsoft YaHei",sans-serif}.page{box-sizing:border-box;max-width:860px;min-height:1040px;margin:24px auto;padding:44px 52px;background:white;break-after:page}.kicker{font-size:12px;letter-spacing:2px;color:#657b91}h1{font-size:30px;margin:18px 0}h2{font-size:21px}p,li{line-height:1.8}svg{width:100%;max-height:520px}.parts{display:flex;gap:12px;flex-wrap:wrap}.parts span{padding:8px;background:#f3f7fb}.notice{padding:14px;background:#fff4d8;border-left:4px solid #d99e27}.detail{padding:14px 24px;background:#f1f6fa}@page{size:A4;margin:10mm}@media print{body{background:white}.page{margin:0;max-width:none;min-height:0;height:273mm;padding:12mm;overflow:hidden}}'
    document+='</style>'+''.join(pages)+'</html>'
    (OUT/'manual.html').write_text(document,encoding='utf-8')
    (OUT/'targets.json').write_text(json.dumps({s['id']:target_pose(r,s) for s in r['steps']},indent=2))
    print(json.dumps({'manual':str(OUT/'manual.html'),'steps':len(r['steps']),'bricks':len(r['bom'])}))

if __name__=='__main__':main()
