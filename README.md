# Piper LEGO — Isaac Sim 主线

物理后端为 NVIDIA Isaac Sim / PhysX。此项目独立于 `D:\piper-lego` 的 MuJoCo 基准，也不依赖 Unity 安装。

仓库包含源码、配置和生成的乐高说明书，不包含 Python 环境、第三方机器人网格、生成的 USD、训练权重或本机运行记录。克隆后需按本文安装依赖，运行 `scripts/fetch_piper.py` 下载固定版本资源，再运行 `scripts/prepare_urdf.py`；浏览器依赖使用 `npm --prefix web ci` 安装。历史报告路径描述的是本机试验记录，不表示这些报告随仓库分发。当前启动脚本中的本机路径和 Python 安装位置需按新机器调整。

## 新目标：按说明书从散落积木中拼搭

第一套说明书位于 `assets/manuals/step_wall6/`：`manual.pdf` 是 8 页人读图解，`recipe.json` 是同源机器版本。目标是 6 块 2×4 砖组成三层交错小墙：底层红／蓝／绿，中层黄／橙，顶层紫；需要夹紧并配准的底板。说明书定义零件需求、目标凸点坐标、方向、依赖和连接数量，不包含散落源位置。

实时概念搭建入口：`http://127.0.0.1:8877/assembly`，运行 `open-assembly.ps1` 启动。页面同时显示说明书、实时机器人、进度与视觉库存，可开始、暂停、继续和重新随机散落。原 `8875` 单块抓放工作台保留，其 `/assembly` 仍为离线扫描／规划检查页。

`live_assembly.py` 将结构化说明书接入真实 Isaac 控制循环：按当前步骤搜索需要的颜色，重新观察、物理夹持、抬起、搬运、结构上方视觉配准、低速下降、松爪和验收。控制源位置来自当前腕部 RGB；环境真值只用于场景初始化、接触连接模型和独立物理评估。运动采用逆运动学与反馈控制，本次没有训练端到端拼搭策略。

当前是明确标注的**概念搭建模式**：积木为实心底面，凸点只作外观，碰撞代理在长边两端各留 1.5 mm 间隙，以容纳当前视觉配准误差；显示外观、夹持宽度和支撑高度保留标称尺寸。`concept_connectors.py` 在实际接触、低速、直立和凸点格位对齐后，以当前相对位姿创建 PhysX 固定约束来近似连接。不瞬移零件，不把积木焊在夹爪上。连接断裂事件会停止执行，最终还检查整体位置与稳定性。该模式不能证明真实塑料卡接；严格物理模式仍拒绝这种近似证据。完成状态分别记录 `concept_build_completed` 和始终为假的 `physical_assembly_completed`。

复现完整概念执行：启动后点击“开始按说明书搭建”；或运行 `ASSEMBLY_PORT=8877` 对应的 `web/drive_live_assembly.cjs`。实际运行报告位于 `outputs/live_assembly/run_<seed>.json`，包含每步视觉验收、接触连接、实际抬高和双指接触统计；以报告状态为准，失败或部分进度不是完整搭建成功。`check_live_assembly.py` 审核实际运行报告，`check_concept_contract.py` 只审核语义与权限边界，`web/check_live_assembly.cjs` 单独测试嵌入控制台按钮。

2026-11-06 的最终配置实测：随机平移布局 seed 3200、3201 均完成 6/6，分别保留九条近似连接，无断裂，全部零件实际抬起并保持双指接触；最终最大位置误差分别为 2.29 mm、2.89 mm。后者仍处于概念模式的毫米级配准范围，不是 LEGO 过盈装配精度。汇总：`outputs/live_assembly/acceptance.json`；完成后的浏览器截图：`final-console.png`、`final-closeup.png`；浏览器按钮和完成场景检查：`browser-check.json`、`completed-browser.json`。两组完成记录不代表任意散落布局、遮挡或实机的通用成功率。

`assembly_agent.py` 是确定性说明书 Agent 原型，当前读取结构化说明书，尚不是任意 PDF 图像理解模型。它根据观察的砖型、颜色、置信分选择未占用的视觉轨迹，目标来自说明书。缺料时继续观察；未配准底板、缺少抓取／转向／限力压入／连接验收能力时阻止执行。必须有独立的连接证据才能推进步骤；视觉位置接近不能代替卡接验收。生产模式拒绝规划测试用的伪观察与伪连接证据。

`assembly_perception.py` 用 RGB 色彩分量和已知 2×4 几何估计多块积木的位置，颜色原型按 Isaac 的 LDR 输出校准；这是启发式多物体感知基线，不是新训练好的通用 LEGO 检测器。场景含 6 块所需积木、1 块青色 2×2 干扰块及 1 块黑色干扰块。检测器和 Agent 不调用物体场景真值；扫描程序只在独立误差统计中读取真值。

```powershell
# 重建图解说明书和 PDF
E:\PiperIsaac\.venv\Scripts\python.exe E:\PiperIsaac\scripts\build_manual.py
node E:\PiperIsaac\web\export_manual.cjs
# 规划单元测试；不是物理成功率
E:\PiperIsaac\.venv\Scripts\python.exe E:\PiperIsaac\scripts\check_instruction_agent.py
# 随机散落布局，实际腕部 RGB 扫描；可附加 S1 抓取／抬起技能前缀测试
powershell -ExecutionPolicy Bypass -File E:\PiperIsaac\scan-assembly.ps1 -PickPrefix
```

`outputs/assembly/planner-check.json` 是 100 组随机合成观察的规划检查；`rgb-scan-check.json` 是实际 Isaac 多视角相机观察；`prefix_pick_*.json` 只验证按 S1 选红砖、抓取和抬高。这些历史组件验证不能合并声称为完整拼搭成功率。

当前默认同时随机位置和桌面内的角度（−90° 至 90° 连续采样，矩形砖旋转 180° 等价），不再统一朝向。机器人从源位置 RGB 识别朝向，在积木上方旋转夹爪、抓起后转到搭建方向，再搬运就位；不向控制器提供初始角度真值。`open-assembly.ps1 -FixedYaw` 保留旧的统一朝向复现方式。默认散落仍为平放、互相分离的六块同规格彩色砖和两块干扰物，尚未加入翻倒、倒扣或相互堆压。

随机角度新增实测 seed 4200：六块初始方向约为 45.5°、−31.5°、−78.8°、64.2°、−12.6°、8.0°，完成 6/6，九条近似连接未断裂，最终最大位置误差 1.50 mm。此记录只证明一组连续随机角度布局跑通，不能解释为任意散落场景的成功率；上面的 3200／3201 是固定方向历史记录。最新汇总在 `outputs/live_assembly/acceptance.json`，完整证据在 `run_4200.json`，初始散落截图在 `scattered-layout.png`。页面默认保留初始散落状态，点击开始后才抓取和转正。

实际插接仍缺：实物底板配准、经过验证的空腔与过盈物理、限力压入技能及真实连接验收。概念模式使用已知仿真底板标定；尚未验证堆叠遮挡、同色多件、任意三维朝向或任意 PDF 理解。官方 [BrickSim](https://github.com/intelligent-control-lab/BrickSim) 提供专门的 interlocking-brick 仿真，但当前公开前提是 x86-64 Linux；尚未在本 Windows 工程安装或验收。

当前默认任务为腕部 RGB 搜索、抓取、抬起并放到指定位置。可在标示的可操作区域随机／点击摆放，并点击设置放置目标；开始任务保留当前积木位置。12 个分散位置的完整首轮测试为 11 次成功，失败位置经修正后复测通过，另通过主动中断夹持后的恢复测试。按各位置最新普通测试结果统计，平均放置误差 1.31 mm、最大 2.68 mm；这不是“12 次首次尝试全部成功”的声明。完整证据与限制见 `outputs/tabletop/acceptance.json`。

## 当前主线：人机协作整理（无机械翻面夹具）

`open-clutter.ps1` 启动 8878 工作台。正常零件堆场景不再创建或调用机械翻面夹具。机器人从腕部 RGB 选择零件；遇到非正面朝上、前两种朝向拟合误差差值小于 0.15 参考像素、两次重试后仍抓取失败，或多视角观察仍无可靠候选时，撤离后进入 `waiting_human`，给出零件颜色、原因和摆放指示。差值是启发式门槛，不是校准概率或学得的求助策略。

人在指定位置（X=0.20、Y=-0.04 m）将零件凸点朝上、与邻件分开，并撤手后确认。机器人重新采集多视角 RGB；只有目标颜色、正面朝上假设、目标位置及可见邻件间距通过检查，才继续。当前依赖人的撤手确认，没有人体追踪或实体安全互锁；RGB 检查仍受遮挡和几何歧义限制。Quest Pro 的真实手部操作尚未接入验收。

控制台有两个明确分开的按钮：“我已完成并撤手”只触发重观察；“模拟人完成”通过显式仿真人类代操作改变目标零件姿态，用于无头显的软件流程验证。后者单独记录 `simulated_human_pose_writes` 和 `human_assistance`，绝不计为机器人自主翻面能力。机器人自身不写零件位姿。新报告在 `outputs/clutter_human/`，不覆盖旧夹具试验。旧夹具成功记录只代表历史方案，不代表新协作流程已完成整堆验收。

seed 5300 的新协作组件实测已验证：场景无翻面夹具；机器人实际撤离并等待；未移动零件而直接确认会被重新观察拒绝；显式模拟人摆正后通过 RGB 复查。记录在 `outputs/clutter_human/browser-check.json` 和 `accepted-collaboration-5300.json`，截图为 `human-request.png`。本试验仅验证协作交接，未完成新模式的六步整堆装配，也未验证 Quest Pro 手部操作。

## 历史方案：机械夹具翻面与整理工作台

以下夹具流程和 seed 5200 成功记录仅描述历史方案；当前 `open-clutter.ps1` 启动上文的人机协作模式，不再创建翻面夹具。原 8877 平放散落搭建和 8875 单块抓放保留。新模式将八个零件依次从空中释放，由 PhysX 自然落定，包含倒扣、侧躺、倾斜和重叠；积木使用带底部空腔、侧壁和支撑管的复合刚体近似，不是弹性塑料模型。

流程为腕部 RGB 多视角观察、估计可取件姿态、接触抓取、移除干扰块或放入机械翻面夹具、视觉检查正反面、重新抓取并在整理区放稳，最后才接入已有说明书 Agent。抓取失败会先抬高松爪并重新观察，不重置零件。初始堆和运动后的物体真值仅用于独立评估，不作为取件位置输入。

浏览器提供“零件堆近景”和“翻面夹具近景”。抓取会比较两种夹持方向及中心／偏移抓取点与其他 RGB 拟合零件的间隙；下降遇到邻件／桌面接触或停滞时抬高退出。此间隙估计不能替代完整机械臂碰撞规划。`web/check_clutter_view.cjs` 通过只读 HTTP 快照检查视角，不争用正在执行任务的控制连接。

间隙比较同时将指尖碰撞盒投影到实际多视角 RGB 零件掩码上。近距离单帧仅允许小范围位置复查，不覆盖多视角朝向估计。搬运／放置读取两根夹指的实际关节坐标补偿闭合中点，避免把机械臂 TCP 当作积木中心；垂直接触搜索不再依赖横向补偿完全静止。整理位仍有释放后的 RGB 检查，偏位可在已知桌面重新定位并实际重抓，最多两次，不修改积木位姿。`check_clutter_placement_regression.py` 使用一张实际偏位图像验证定位与空图拒绝，不能当成整套物理成功率。

自动测试占用控制连接时，可打开 `http://127.0.0.1:8878/assembly?observe=1`。该入口通过 HTTP 持续读取实际状态，禁用运动按钮，不申请控制连接；相机视角仍可切换。`web/check_clutter_observer.cjs` 已检查状态持续更新、零 WebSocket 连接和按钮禁用。

新训练的是 `clutter_face_model.py` 的整理位正反面检查 CNN。训练数据由 Isaac 原始 640×480 腕部 RGB 生成，含夹具闭合遮挡、不同夹具朝向、颜色、平面角度、倾斜与位置偏移；这不是端到端抓取／装配策略训练。`outputs/clutter_face/dataset.json` 和 `training.json` 分别记录样本来源与留出验证结果。训练用的积木及夹具采用可控渲染姿态生成标签，明确不算物理抓取示范。实时翻面则由动态夹具的电机、接触与摩擦实现，积木不加抓取固定约束。

修正了训练中夹具随积木横向移动的理想化遮挡：夹爪现在保持夹具中心，积木独立偏移。seed 5204 共 3,200 张图像，2,560 训练、640 留出验证；选定检查点在 0.98 阈值下误接受 0、漏接受 14，通过受控仿真试用门槛。该阈值的输出不是校准概率，留出验证与已知物理图像回归均不等于整堆任务成功率。每次旋转后可换三个实测腕部视角复查，仍需连续两次通过。

零件堆模式使用 640×480 RGB；说明书阶段的组件面积和轮廓误差阈值已按分辨率换算，误差统一以宽 320 像素为参考，避免沿用低分辨率像素上限过滤掉被夹住的积木。`check_assembly_resolution_regression.py` 用实际 S1 配准失败图像验证 320／640 两种分辨率及空图拒绝；这是图像回归，不是物理搭建验收。

该翻面夹具是新增的仿真机械机构原型，实机需要对应机构，或另行验证机械臂自行翻面的技能。零件整理完成后，装配阶段仍使用旧的平底碰撞／接触约束连接近似；不据此宣称真实 LEGO 过盈卡接通过。

零件堆模式已将 Piper 两根夹指改为一个主动驱动和 PhysX 机械从动关系 `q8 = -q7`。这约束的是机器人夹指，不是积木；旧的两个独立限力驱动会产生不符合平行同步开合的中点漂移。`--clutter-gripper-test` 专项实测完成了一次孤立红砖的 RGB 抓起、搬运和释放，落点误差 1.55 mm，未使用积木抓取固定约束；结果位于 `outputs/clutter/gripper-commission.json`。该专项不能代替整堆装配验收，旧独立驱动运行记录也不作为新夹爪模型的通过证据。

验证记录在 `outputs/clutter/`：`scene_<seed>.json` 是独立堆形审计，`views_<seed>_<round>.json` 与 PNG 是实际相机观察，`fixture-test.json` 仅验证夹具自身翻面，`run_<seed>.json` 记录实际流程。只有 `heap_to_assembly_completed=true` 才表示整堆到六步概念搭建完成；取出一块、正反面分类通过或单独夹具测试都不是完整装配成功。`check_clutter_run.py` 分开审核整理前缀和整套结果，`check_clutter_contract.py` 审核无物体真值控制和无积木抓取固定约束的边界。

可重建视觉模型：

```powershell
E:\PiperIsaac\.venv\Scripts\python.exe E:\PiperIsaac\scripts\workbench.py --headless --task xr --clutter-collect-face --samples 3200 --seed 5204
C:\Users\Administrator\miniconda3\python.exe E:\PiperIsaac\scripts\train_clutter_face.py
```

请串行运行数据采集与物理试验，避免同时启动过多 Isaac 进程耗尽显存。当前仍限定为已知规格、颜色唯一的受控零件堆；尚未验证任意数量、同色多实例、未知砖型或真实相机／实体机械臂。

完整实测 seed 5200 已连续完成八件物理零件堆到六步概念搭建：初始包含三块倒扣、两块侧躺／倾斜、两块被垫高，并有重叠；移除两块干扰件，取出并转正六块所需零件，完成说明书 6/6。九条接触触发的近似连接无断裂，最终最大位置误差 1.16 mm。过程中实际处理了一次搬运掉件和三次下降受阻／停滞，重新观察后继续；未向夹爪固定积木，重置后未写入积木位姿。此结果仅证明这一组受控八件场景跑通，不代表任意密集零件堆或真实塑料卡接已通过。

完整记录保存在 `outputs/clutter/accepted-5200.json`、`outputs/live_assembly/clutter-accepted-5200.json`，审核汇总为 `outputs/clutter/acceptance.json`；完成截图为 `completed-console.png`、`completed-closeup.png`。浏览器完成显示、重置恢复空腔碰撞、开始／暂停／继续检查见 `completed-controls-check.json`。早期蓝砖前缀及红砖漏判记录仍作为开发历史保留；`check_clutter_face_regressions.py` 仅审核已知开发图像，不作为独立泛化成功率。

## 版本选择

采用 Isaac Sim 5.1.0、Python 3.11 的隔离环境，以便与 BrickSim 当前固定的 Isaac Sim 5.1.0 / Isaac Lab 2.3.2.post1 衔接。5.1 已停止 NVIDIA 官方维护；这是第三方集成复现基线，不代表它是当前最新版或可与 6.x 混装。当前安装仅覆盖 Isaac Sim，尚未安装 Isaac Lab、BrickSim 或 CloudXR。

项目位置：`E:\PiperIsaac`。解释器：`.venv\Scripts\python.exe`。成功安装日志：`install-local.log`。官方资源的固定提交、文件校验和见 `assets/source.json`。

历史局部基线：使用 32 条 Isaac 示范训练，20 个小范围随机场景成功，平均落点误差 0.81 mm、最大 3.05 mm；3 个全程张爪负例失败。这些报告早于夹爪碰撞实例修正，不代表当前视觉搜索任务的验收结果。相机使用 CUDA RGB 注释器读取像素。当前与历史结果分列于 `outputs/capabilities.json`、`deployment-status.json`。

当前 Windows 11 25H2 / 驱动 610.88 / Isaac Sim 5.1 组合的 Vulkan 路径在 RTX SceneDB 初始化崩溃。默认使用进程内 D3D12。CPU 直接 RGB 读回不工作，已改用 `get_annotator('rgb',device='cuda')` 后 `.numpy()` 取得真实像素，且机器人运动前后的图像变化检查通过。**实际 Quest Pro 设备、Vulkan 和真实 LEGO 卡接尚未验收。** 本次未更换系统驱动、禁用设备或修改引导。

## 一键协作工作台

```powershell
powershell -ExecutionPolicy Bypass -File E:\PiperIsaac\open-workshop.ps1
```

等待后端启动后打开 `http://127.0.0.1:8875/`。点击“随机摆放积木”或“点击台面摆放”，可再点击“点击指定放置位置”，然后点击“开始视觉搜索”。机械臂会搜索、抓取、抬起并放到绿色目标处。开始不会重置积木；“重置”是单独的场景重置操作。完成后可用“桌面抓取”“抬高 6 cm”“旋转 90°”“放下”进行人工操作。键盘 I/K、J/L、U/O 移动虚拟手，空格启动／继续，G 抓放，R 重置。保留一个控制标签页；新增按钮未显示时按 Ctrl+F5 刷新。

前端使用本地 Three.js / WebXR 渲染三维场景；所有运动和碰撞由同一 Isaac Sim / PhysX 实例决定。浏览器没有第二套刚体物理。它不是 CloudXR 视频串流，也不需要 Unity 或 Quest Link。端口只绑定 PC 本机回环地址，没有开放公网或防火墙端口。

停止工作台：

```powershell
powershell -ExecutionPolicy Bypass -File E:\PiperIsaac\stop-workshop.ps1
```

服务日志见 `outputs/xr-*.log`，状态／手柄事件记录见 `outputs/xr_sessions/*.jsonl`。

## Quest Pro 软件接入已准备

Google 官方 platform-tools 已下载并核对官方仓库校验和，来源见 `tools/platform-tools-source.json`。头显不在手边，因此没有连接设备、修改设备设置或宣称通过真实追踪测试。

设备到手后：在头显开启开发者模式，用 USB 数据线连接电脑，在头显内允许 USB 调试；先启动工作台，再运行：

```powershell
powershell -ExecutionPolicy Bypass -File E:\PiperIsaac\connect-quest-usb.ps1
```

脚本会检查设备身份和授权状态，并通过 `adb reverse` 把头显的 `http://localhost:8875/` 转到 PC。回环地址属于 WebXR 可用的安全上下文，不需要把 HTTP 场景暴露到局域网。头显浏览器打开后点击“进入 VR”并批准浏览器权限。浏览器／系统版本兼容性、空间标定、手柄追踪与实际帧率仍需现场验收。多个设备时用 `-Serial <设备序号>` 指定 Quest。

右手柄握持：抓取／释放；右 A：启动／继续；右 B：暂停；左 X：重置。用户与机器人不能同时拥有同一块积木；当前流程使用桌面交接区，尚未实现直接手递手。

## Isaac 原生抓放与学习

```powershell
powershell -ExecutionPolicy Bypass -File E:\PiperIsaac\start-pick-place.ps1
```

默认执行新训练的 Isaac 策略；`-Expert` 执行示范控制器，`-Headless` 无窗口运行，`-Record` 录制 RGB 视频。最近一次回放写入 `outputs/last_task.*`，不会覆盖保留的独立评估。

已录制的学习策略视频：`outputs/learned_demo.mp4`，来源、帧数和种子见 `outputs/learned_demo_video.json`。这段视频使用原生 CUDA RGB 注释器生成。

训练为状态观测下的八阶段行为克隆，45→256→256→256→4；使用本机既有 CUDA PyTorch / RTX 5080。源位置与目标位置的 x/y 分别随机 ±12 mm，朝向、质量和摩擦固定；机械臂从源位置上方开始。32 条示范按整条划分为 26 条训练、6 条验证；测试种子 1000–1019 不参与训练或验证。它尚不是视觉策略或自适应人机协作策略。

成功条件：抬起超过 55 mm；双侧夹爪接触且抬起超过 40 mm 至少持续 5 个控制步；落点误差小于 12 mm；松开夹爪后正放、低速稳定至少 0.3 秒；末端退出超过 50 mm。接触力来自 PhysX 接触视图。物体在 reset 后没有直接修改位姿，机器人抓取没有添加物体固定连接。

重新采集、GPU 训练和独立评估：

```powershell
powershell -ExecutionPolicy Bypass -File E:\PiperIsaac\train-isaac.ps1
```

训练脚本默认复用 `C:\Users\Administrator\miniconda3\python.exe` 的 CUDA PyTorch，没有修改该共享环境。可用 `-TrainingPython` 指定另一个训练解释器。训练会更新策略及示范；训练完成后重启工作台，以加载新权重。

第三方前端依赖使用 `web/package-lock.json` 固定。缺失时执行 `npm ci --prefix E:\PiperIsaac\web --no-audit --no-fund`。桌面端到端检查为 `node E:\PiperIsaac\web\check_browser.cjs`，要求后端已启动且没有其他控制客户端。此检查用桌面 Edge 的软件渲染，不能替代 Quest Pro 设备测试。

## 场景与启动

基础 Piper 原厂六轴和夹爪来自 AgileX 官方仓库的 `piper_description.urdf`。工作副本只将 package 网格路径解析到本机，原始文件保持不变。由 Isaac Sim URDF Importer 生成 USD，并搭建工作面、目标区、带凸点的 2×4 积木、光照和视角。

```powershell
powershell -ExecutionPolicy Bypass -File E:\PiperIsaac\start.ps1
```

无窗口验收：

```powershell
powershell -ExecutionPolicy Bypass -File E:\PiperIsaac\start.ps1 -Check
```

只有实际生成 `outputs/smoke.json` 且 `status` 为 `physics_and_viewport_render_passed` 才说明物理与 RTX 视口渲染通过。`sensor_rgb_passed` 单独表示相机 RGB 数据读取是否通过，不能由视口截图替代。安装成功或 Python 能 import 均不等于场景可用。当前验收任务为积木自然落桌、八个关节可读取／驱动、小幅关节运动及 RTX 截图；这还不是抓放成功判定。历史验收输出会在下一次检查时移入 `outputs/history`。

首次启动会导入机器人并编译渲染着色器，可能耗时较长。生成的场景为 `outputs/workbench.usda`，截图为 `outputs/workbench.png`。

交互运行保持初始姿态，供检查模型、视角和属性；检查模式会小幅驱动底座关节。按 Isaac Sim 界面常规视口方式调整观察角度，关闭窗口结束。重新导入 URDF 可直接运行 `scripts/workbench.py --reimport`。

## 物理边界

- 单位米，Z 轴朝上；PhysX 物理步长 1/240 秒，渲染步长 1/60 秒。
- 抓放与 XR 场景使用 1 ms 物理步长，50 Hz 控制；浏览器状态约 25 Hz 更新，头显本地显示独立刷新。
- 基础版 Piper：六个旋转关节、两个夹爪滑动关节；无额外相机模型。
- 保留 URDF 的网格与惯性，模型硬件修订和真实夹爪参数仍需实物核对。
- 调试初期关闭机器人自碰撞；碰撞参数、驱动力和夹爪接触需后续校准。
- 抓放场景保留原厂夹爪外观，碰撞采用简化矩形指尖接触面，并限制夹爪力。人工抓持用受限弹簧力／转矩驱动，不是真实手指接触模型，也没有全身／手部碰撞避让或触觉反馈。
- 积木为实心底面的近似模型，不包含真实空腔、过盈和材料弹性；不应把当前落桌场景当作真实 LEGO 卡接验证。
- 没有连接实体机械臂，也没有把 MuJoCo 模型的成功率或策略直接视为 Isaac Sim 验收结果。

## 台面搜索、抓取与指定放置（当前工作流）

腕部窗口有两种显示模式：默认“流畅 3D 腕部视角”使用与主画面一致的浏览器插值渲染，显示的是仿真视角预览；“Isaac 原始 RGB”显示真实传感器图像，通过 MJPEG 推送最新帧，不再每 350 ms 重新请求快照。定位／训练始终使用 Isaac 原始 RGB，浏览器预览不进入策略。

Edge 无头软件渲染测试中，3D 腕部视角约 25 fps，原始 RGB 运动时约 4.6 fps、暂停时约 6.1 fps。原始图像仍受同步 RTX 渲染和 CUDA 读回限制，未达到目标 15 fps。预览取图不推进物理时间，隐藏页面／切回 3D 模式会停止 RGB 预览订阅。更高帧率的真实 RGB 需要独立的成像与视频编码管线，不能只靠加快 HTTP 刷新。测试记录：`outputs/camera-stream-check.json`。

`tabletop.py` 使用腕部 RGB 主动扫描、训练好的中心热图 CNN、已知积木几何的轮廓拟合，以及按到位和接触反馈推进的控制器。它替代局部 BC 在这项任务中的动作控制；没有宣称重新训练了一个全台面端到端抓取网络。接近、夹持、抬起、搬运、接触桌面、松开、撤离均有反馈条件和超时退出，不再用旧任务的固定阶段时钟。

新视觉训练集包含 525 张有效腕部图像（420 训练、105 验证），验证平均中心误差 0.66 像素。覆盖多个扫描姿态与近距离视角。搬运后通过 RGB 和积木已知尺寸估计夹持偏移，补偿放置目标；被夹爪遮挡时，在双指接触保持的前提下保留视觉抓取点建立的编码器夹持变换。模拟双指接触和积木／桌面接触属于当前控制反馈，迁移实机时还需接入夹爪／力矩反馈或替代检测。

夹爪闭合采用渐进目标，驱动上限 1.5 N、刚度 500、阻尼 12。已展开原网格碰撞实例并禁用其碰撞，仅指尖方盒参与接触；启动时断言原碰撞体确实关闭。此前局部基线的报告生成于这项修正之前，含原碰撞网格与简化指尖的混合接触，保留为历史证据，不能视为当前碰撞配置的验收结果。

单边接触持续、夹紧失败或搬运中接触丢失会触发最多两次“松爪—抬高—重新视觉搜索”，不使用物体真值恢复。`recovery.json` 分开记录普通位置复测和显式中断一次夹持的故障恢复测试；故障注入只存在于测试模式，且不纳入普通抓放精度统计。

浏览器提供“随机摆放积木”“点击台面摆放”“点击指定放置位置”。“开始视觉搜索”保留当前摆放位置，不重置积木。淡蓝格子标示当前准入区域；摆放和目标都检查关节限制及抓取／抬起姿态的逆解。

整张支撑桌面为 1.0×0.8 m，部分位置超出固定向下抓取的可操作范围；当前准入区域在机器人前方 X=0.12–0.39 m、Y=−0.28–0.28 m 内，另排除近基座区及逆解不合格的位置。这是本任务的保守操作区域，不是机器人所有姿态的完整理论工作空间。未实现全机械臂碰撞路径规划，不能将其当成实机安全工作区。

验证记录位于 `outputs/tabletop/`：`evaluation.json` 为分散位置的实际 PhysX 抓放，`negative.json` 为无可见目标／可见但不可达目标的负例，`browser-check.json` 为浏览器摆放、改目标和搬运验证，`acceptance.json` 为汇总。通过验收后，启动脚本默认使用 `wrist_RGB_search_feedback`。复现训练与物理检查：

```powershell
powershell -ExecutionPolicy Bypass -File E:\PiperIsaac\train-tabletop.ps1
```

当前仍使用单块红色、固定方向的 2×4 积木和已知平桌面。真实相机内参、手眼标定、真实机械臂及 LEGO 插接尚未验证。

## 原始局部腕部 RGB 视觉基线

`config/wrist_camera.json` 配置安装在 `link6` 上的相机，默认分辨率 320×240。安装位置、镜头内参和桌面高度目前是仿真假设，尚未匹配真实相机；实机迁移前必须做内参和手眼标定。

已用 256 张 Isaac 腕部 RGB 图像训练积木中心热图 CNN（205 张训练、51 张验证），图像验证平均误差 0.54 像素。模型从 RGB 预测中心，经内参、关节正运动学和手眼变换与已知积木顶面高度求交，得到工作台坐标。接入已有 BC 动作策略后，8 个独立场景全部成功，首次定位平均误差 0.36 mm，最终放置平均误差 4.71 mm，最大 8.04 mm。此前 20/20、0.81 mm 的结果属于直接读取状态的旧基线，不能用于宣称视觉精度。

视觉运行时不向策略提供积木真值位置；真值只用于生成标签和验收。扫描姿态固定，不随积木随机位置改变。运行输入为腕部 RGB、关节编码器、标定、指定目标坐标与阶段时钟。靠近和下降阶段更新视觉，夹住后的物体位置暂由末端运动估计；尚无视觉滑移检测。动作网络沿用此前 BC 模型，新增训练的是视觉定位网络，尚不是端到端像素动作学习。

浏览器右下角显示腕部 RGB 图像。`open-workshop.ps1` 和 `start-xr.ps1` 在定位模型存在时启用视觉控制，状态显示 `wrist_rgb_plus_BC`。视觉置信度不足时停止，不回退到读取积木真值。重训命令：

```powershell
powershell -ExecutionPolicy Bypass -File E:\PiperIsaac\train-vision.ps1
```

结果位于 `outputs/vision/`：`dataset.json`、`training.json`、`evaluation.json`、`detection.png`。当前仍限制为固定红色、固定方向的 2×4 积木、小范围位置随机化和已知平桌面；没有实机相机、真实机械臂或 LEGO 插接验证。

## 递料抖动修正

URDF 导入器生成的六个旋转关节使用加速度驱动，实际刚度为 625、阻尼为 0；只设置导入器的默认阻尼没有覆盖最终资产。本项目在抓放场景配置时显式设置刚度 625、阻尼 50（临界阻尼），避免持续振荡。调整驱动后需重新采集示范并训练，旧策略不能直接视为通过新动力学的验证。

浏览器在权威物理状态之间进行位置、旋转和尺度插值，显示延迟约 80 ms；物理计算、接触判断和抓取输入仍由 Isaac Sim 处理。页面失去焦点仍会暂停，暂停后可点击“继续递料”或“重置并开始”。

## Quest Pro 与 Linux 路线

目标仍是 Quest Pro 中的人机协作拼搭。Windows 已有上述浏览器客户端；Quest Pro 实际验收由设备到手后完成。

官方 CloudXR / Isaac Capture 工作流当前要求 Linux，公开支持设备主要列出 Quest 3、Pico 4 Ultra、Vision Pro；本项目的浏览器本地渲染路径不依赖该流程。BrickSim 当前要求 x86-64 Linux。真实卡接、底部管柱／空腔、过盈力和结构断裂尚未实现或验证，需在后续 BrickSim／原生 Linux 集成和实物校准中处理。

原生 Ubuntu 24.04 为后续完整平台的优先候选。已有停止的 WSL Ubuntu-24.04 不等于经过验证的原生图形仿真环境。本次没有改分区、安装双系统或修改引导。Linux 安装需先核对磁盘布局、备份与可用空间，再决定独立磁盘或双系统。

## 复现资源准备

```powershell
python E:\PiperIsaac\scripts\fetch_piper.py
python E:\PiperIsaac\scripts\prepare_urdf.py
```

`.tools` 是独立的资产检查工具环境，包含 usd-core；它与 Isaac Sim 的 pxr 运行环境分离，避免版本冲突。`scripts/cache_wheels.py` 从 NVIDIA 官方区域索引分段下载缓存包，并核对索引提供的 SHA-256。

## 核对来源

- Piper 官方资源：https://github.com/agilexrobotics/piper_isaac_sim
- BrickSim 依赖：https://github.com/intelligent-control-lab/BrickSim/blob/main/python/pyproject.toml
- Isaac Sim 5.1 安装：https://docs.isaacsim.omniverse.nvidia.com/5.1.0/installation/install_python.html
- 硬件要求：https://docs.isaacsim.omniverse.nvidia.com/5.1.0/installation/requirements.html
- XR 路线：https://isaac-sim.github.io/IsaacLab/main/source/how-to/cloudxr_teleoperation.html
