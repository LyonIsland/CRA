# 纯相机算法

## 基础抓取基线（2026-11-11，首轮独立测试）

目标先限定为单个可见矩形积木的对准、接近、夹取和稳定抬升。新入口为
`workbench.py --task camera-only --camera-mode grasp`，不把视觉预训练权重
误当成现成抓取策略。`--grasp-flat` 是明确的单块直立散件入门课程；不代表
任意堆叠、任意朝向已经通过。多块任务也从同一个 BRICKLAB inventory 加载。

固定版本在新种子 `52001–52005` 上完成 5 个场景，**3/5 成功（60%）**。
成功场景抬升 68.3–88.2 mm，连续双指接触 3.34–4.00 秒；两个失败均为
初始图像未检出可见完整矩形积木，在接近/夹取前停止。样本仅 5 个，不能据此
宣称稳定处理任意遮挡、堆叠或真实硬件。记录位于
`outputs/camera_grasp/frozen-eval-v1/summary.json`，策略 SHA-256 为
`53219fb32cce1d64c59b823d19e4f7b3b80d1b9f577df8ac282b1d1ef1bee0fb`。
开发场景 `dev-20`（51001）另有抬升 70.1 mm、连续接触 3.66 秒的成功记录，
不计入上述成功率。

补充对照：同一场景 52001 的在线张爪测试在闭爪前跟踪丢失，不能用于解释
闭爪的作用；该失败记录保留在 `outputs/camera_grasp/negative-52001`。
随后使用成功动作记录做成对机械回放：原始指令再次抬升 71.0 mm 并夹持
3.42 秒，只在夹取/抬升/保持阶段强制张爪时抬升与连续夹持均为零。
记录为 `outputs/camera_grasp/paired-control-52001/comparison.json`。
回放不执行在线视觉策略，不计入 3/5 成功率；这同时说明重复场景的视觉
跟踪仍不稳定，机械对照不能掩盖这一限制。

方法选择依据：

- [Chaumette & Hutchinson, 2006：Visual Servo Control, Part I](https://ieeexplore.ieee.org/abstract/document/4015997)：以图像特征误差闭环控制。
- [Yoshimi & Allen, ICRA 1994：Active Uncalibrated Visual Servoing](https://www.cs.columbia.edu/robotics/projects/visual_control/bill-peginhole.html)：利用腕部旋转产生的图像轨迹进行轴线对准；用实际试探估计图像雅可比。本项目参考这一思路，自行实现单 RGB、关节指令空间的版本，未复现原论文全部实验。
- [ViSP](https://github.com/lagadic/visp)：视觉伺服开源平台，作为接口和算法参考；当前实现使用已有 OpenCV/NumPy，未引入或复制其库代码。
- [GG-CNN, RSS 2018](https://github.com/dougsm/ggcnn)：经典闭环抓取基线，其标准模型输入为深度图，因此本任务未直接采用该权重或增加深度传感器。

控制器 `camera_grasp_policy.py` 只接收 RGB 数组，使用灰度边缘、矩形轮廓、
Lucas–Kanade 亚像素跟踪、关节小幅试探、阻尼最小二乘和 Broyden 更新。
多尺度局部灰度对比用于分开积木与夹爪阴影；光流保留同一组表面特征点，
避免每帧重新选点而逐渐转去跟踪夹爪。流程为夹爪图像定位、获取目标、
转动对准、三维图像特征闭环、闭爪、反向执行自身接近指令并保持。
控制器自有的阶段和已发指令记录不是模拟器提供的阶段标签。无 FK/IK、
关节实测值、相机外参、桌面高度、物体身份或位姿输入。固定起始姿态与指令
协同属于执行器设置，独立于散件位置。夹指图像参考目前包含本机工具外观假设，
并非任意相机安装和任意物体的通用方法。

执行器限幅导致试探不成立时停止；视觉目标丢失或迭代不收敛时停止。
独立评估器位于 `camera_grasp_runtime.py`，读取真实物理位置和接触力进行
验收，不向控制器反馈、触发重试或选择动作。成功门槛为同一物体抬升至少
30 mm，且双侧夹指接触连续保持至少 2 秒。没有抓取焊接、运行中物体位姿改写
或物体吸附。结果仅适用于当前仿真及近似夹指碰撞几何。

离线检查：`scripts/check_camera_grasp.py`。物理运行输出 `result.json`、
`visual-servo.json`、腕部图像和仅用于评估的 `evaluation-only.json`。

运行基本抓取（单块 2×4 直立散件，随机位置、偏航与材质；默认种子 51001
为开发演示场景，不算独立测试）：

```powershell
.\start-camera-grasp.ps1 -Headless
# 每个新批次必须使用不存在的输出目录；代码变化会中止批次。
.\.venv\Scripts\python.exe scripts/evaluate_camera_grasp.py --out outputs/camera_grasp/new-batch --seeds 53001 53002 53003 53004 53005
# 同场景张爪负对照；不改变视觉对准阶段。
.\start-camera-grasp.ps1 -Headless -Seed 51001 -NegativeOpen
```

`evaluate_camera_grasp.py` 固定策略、执行器与环境代码哈希，按完整场景逐次
验收。所有已尝试场景都进入分母，进程失败与超时也计为失败；中途停止不会
把未运行场景算成成功。批次目录中的 `STOP` 文件会请求当前场景退出。
控制器源码快照和 SHA-256 随每次实验保存，开发调参种子与新种子测试分开。

BRICKLAB 工作区右上方的“基础抓取验收”链接打开
<http://127.0.0.1:18110/grasp-report/>。页面每两秒读取当前批次的进度与实际
腕部相机，展示成功录像、独立物理曲线及结果快照。页面是面向操作者的只读
看板，不是策略输入；HTTP 仅公开指定报告文件，不公开物体位姿轨迹与场景文件。
生成或刷新结果快照：

```powershell
.\.venv\Scripts\python.exe scripts/report_camera_grasp.py --development outputs/camera_grasp/dev-20 --evaluation outputs/camera_grasp/frozen-eval-v1 --negative outputs/camera_grasp/negative-52001 --replay-control outputs/camera_grasp/paired-control-52001 --out outputs/camera_grasp/reports/latest
```

当前基础抓取不读取说明书来选择具体积木，也不执行放置、插接或多步搭建。
工作区原有的“按说明书自动搭建”按钮仍需合格的说明书条件策略权重。

## 夜间视觉预训练（2026-11-11）

当前没有经过审核的完整搭建示范。新增流程先用真实 Isaac 物理交互采集
单个腕部摄像头图像和实际发出的七维动作，训练视觉编码器、图像运动预测与
逆动力学。随机探索不属于成功示范，也不训练“模仿随机动作”的搭建策略。
说明书页面只参加图像重建预训练，尚未学习说明书与搭建动作的对应关系。

独立 CUDA 环境位于 `D:\PiperCameraTraining\venv`，避免改动 Isaac 环境。
使用 PyTorch `2.7.1+cu128`、NumPy `2.2.6`、Pillow `11.2.1`。
现有 Isaac `.venv` 的 PyTorch 是 CPU 版；它仍负责仿真与 RTX 相机渲染。
重新安装时先创建独立 venv、升级其中的 pip，再安装 `camera-training-requirements.txt`。

```powershell
# 已准备好的课程：4 块塔、6 块墙、12 块金字塔；留出小屋与独立布局。
# 如需重新生成，请使用一个新的输出目录：
.\.tools\bricklab-venv\Scripts\python.exe scripts\prepare_camera_curriculum.py --out D:\PiperCameraTraining\curriculum-new

# 默认最多 7 小时、96 轮；每轮新增两组各 512 次动作的物理交互。
.\start-camera-overnight.ps1 -Hours 7

# 查询当前任务与日志位置：
$run = (Get-Content outputs\camera_only\overnight.json -Raw | ConvertFrom-Json).run
Get-Content "$run\status.json"
Get-Content "$run\latest.json"
# 优雅停止，仅停止本次训练拥有的进程：
New-Item -ItemType File -Path "$run\STOP"
```

流程按完整场景布局隔离训练/验证/最终测试；最终测试不参与学习率选择。
初始比较 `3e-4`、`1e-4` 两组学习率，随后增量采集并继续训练，使用梯度裁剪、
验证集早停、学习率衰减、原子权重保存与可恢复的优化器状态。
训练数据记录严格限于 `contract/rgb/actions/split_group`；分组标签不输入网络。
初始场景种子与动作随机数独立，执行时只累计历史命令，不读取编码器或 FK/IK。

检查项包括：下一帧误差是否优于复制当前帧、逆动力学是否优于零动作/均值动作，
以及打乱动作后预测是否变差。**指标下降不等于抓取或搭建成功**。
如果学习没有超过基线，报告会保留原始对照值，不会把它标记为有效搭建策略。
自动运行受总时间、子进程超时、D 盘 8 GiB / 项目盘 3 GiB 余量和 STOP 文件约束。
训练期间代码变化会让监督进程停止，避免单次实验混入不同版本。

产物在 `D:\PiperCameraTraining\runs\<时间>\`：

- `status.json`、`logs/`：运行状态和日志。
- `data/`：真实相机探索数据，与生产示范隔离。
- `models/<轮次>/best.pt`：预训练模型及优化器；执行接口拒绝此协议。
- `models/<轮次>/encoder.pt`：可以用于后续示范学习的视觉初始化。
- `latest.json`：当前选中的权重位置。
- `final-test.json`：结束时独立测试的误差与基线；不评估搭建成功率。

拿到合格搭建示范后再运行：

```powershell
D:\PiperCameraTraining\venv\Scripts\python.exe scripts\train_camera_policy.py --data <审核后的示范目录> --encoder-init <encoder.pt> --out outputs\camera_only\manual-policy.pt --epochs 50
```

离线验证：`scripts/check_camera_pretrain.py`、`scripts/check_camera_overnight.py` 和 `scripts/check_camera_only.py`。
前者的随机图像只用于程序测试，不进入真实训练数据。

BRICKLAB 说明书模块已接入。运行 `start-bricklab.ps1` 打开编辑器并生成训练任务；通过 `start-camera-only.ps1 -Task <task.json>` 将整本说明书图像作为任务条件。详细流程、来源与文件边界见 [BRICKLAB.md](BRICKLAB.md)。原 `-Goal` 照片入口继续可用；两种输入采用不同的训练合同。

新入口为 `start-camera-only.ps1`，旧的 `open-clutter.ps1` 仍是历史控制器，**不满足此协议**。本次没有将旧的成功率移植为新算法的结果，也没有用随机权重执行机械臂。

执行策略的动态观测只有同一个腕部摄像头的最近四帧。任务由操作者提供的目标照片指定；目标照片是任务说明，不是第二路实时摄像头。策略不接收关节位置/速度、相机外参、深度、接触、物体身份、世界坐标、桌面高度、步骤时钟、奖励或成功标志。CNN 编码观测与目标，GRU 根据图像历史输出六个关节增量与夹爪增量，每次重新观察后再决策。当前没有任意说明书 PDF 理解能力。

部署侧只对历史指令积分并执行关节限位，不读取实际关节反馈给策略，也不调用 FK/IK。每步最大关节增量为 0.01 rad，夹爪增量为 1 mm，仿真控制周期 20 ms。机械臂自身的底层位置驱动仍属于执行器。机器人初始姿态固定且不依赖物体位置。

场景初始化时由物理环境随机释放多块积木，所有积木采用相同材质亮度，每次布局重新随机亮度；控制器看不到初始化参数。取消颜色与零件身份对应关系；图像预处理取三个颜色通道的均值，对通道交换严格不变。亮度增强并不能保证不存在其他视觉偏差，需要跨材质、布局、光照的真实留出测试。

不启动旧 Agent、模拟人、接触连接器、状态教师或旧抓取技能。零件位姿写入仅用于开始前的场景生成。不会自动判定完整装配完成；新增独立物理评估只覆盖上文的基础抓取。当前仍沿用项目的刚体 LEGO 与夹指近似，无法据此宣称真实塑料插接或实机安全。

## 重新采集与训练

需要操作者准备目标照片，并在可见终端中逐步遥操作，观察视口默认使用同一腕部相机。q/a、w/s、e/d、r/f、t/g、y/h 分别控制六关节正负增量，u/j 开合夹爪，空格保持，Esc 保存退出。不要切换到外部相机采集示范。当前遥操作是逐步决策，不是实时连续手柄控制。

```powershell
.\start-camera-only.ps1 -Mode collect -Goal .\my-goal.png -Episode .\outputs\camera_only\demos\episode01.npz -Group layout01 -Seed 6001
```

同一布局、重复演示、同源任务变体使用同一个 Group，至少采集两个独立 Group。演示文件包含前置 RGB、目标照片、实际发送的归一化动作与分组标记，不包含场景状态。仅保留合格示范，失败重试另存并人工审核；当前没有自动识别成功的能力。训练器按完整 Group 留出验证，图像历史不跨 episode，拒绝多出的字段和旧状态示范。

```powershell
.\.venv\Scripts\python.exe scripts\train_camera_policy.py --data outputs\camera_only\demos --out outputs\camera_only\policy.pt --epochs 50
.\start-camera-only.ps1 -Goal .\my-goal.png -Policy .\outputs\camera_only\policy.pt -Seed 7001
.\.venv\Scripts\python.exe scripts\check_camera_only.py
```

当前没有通过验收的说明书自动搭建策略。夜间视觉预训练权重与上文的基础抓取基线是不同产物，均不代表已学会完整搭建。离线测试用随机图像只验证输入隔离、分组、训练和推理代码，不是物理任务成功证据。早期 Isaac 无动作检查报告 `outputs/camera_only/run_6000.json` 仅验证场景与相机；抓取结果以本文开头的独立物理验收为准。

可以独立运行无动作相机检查：

```powershell
.\.venv\Scripts\python.exe scripts\workbench.py --task camera-only --camera-mode inspect --headless --frames 2 --seed 6000
```

要达到任务验收，还需在独立布局、同色同形多件、材质变化、遮挡与姿态变化下进行闭环抓放和整套搭建测试，测试中独立评估器可读取真值，但不得把结果反馈给策略。单目不可见信息必须通过主动观察或明确求助获得，不能填入预设场景答案。
