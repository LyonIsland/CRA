# BRICKLAB 与纯相机训练平台

运行 `start-bricklab.ps1`，打开 <http://127.0.0.1:18110/>。当前工作台中的“BRICKLAB 说明书与训练任务”链接也指向该入口。它复用 BRICKLAB 编辑器和说明书模块，使用本机生成服务，既不连接其原有 Linux 双臂服务器，也不启动旧的颜色取件控制器。

## 使用

1. 在编辑器中搭建或导入网页 JSON，也可选择 Studio `.io`、自包含 `.mpd` / `.ldr`。
2. 选择逐步搭建、结构视图或 LEGO 风格，点击“生成说明书与训练任务”。结构视图仅提供结构观察，不宣称包含逐件装配顺序。
3. 点击“完成作品，进入机械臂搭建”，确认说明书设置并提交。生成完成后自动打开 `/workspace/<任务编号>`，加载该作品对应的机械臂场景。浏览器拦截新窗口时，可点击结果中的“进入机械臂搭建”。设计页保留，返回修改不会覆盖已经提交的模型快照。
4. 同一工作区左侧显示本作品的 PDF，右侧显示持续运行的机械臂、对应数量和形状的散件、底板及实际腕部相机。可以旋转场景视角，或切换到腕部相机。
5. “手动操作与示范采集”提供六关节和夹爪的小幅增量操作。开始记录后仅显示说明书与腕部相机，隐藏额外场景视图；保存的图像/动作示范留在本次运行的 `live/<运行编号>/demonstrations/`，需要审查后再加入正式训练集。物理检查用的单步示范不应当作成功装配数据。
6. 训练并导出 `outputs/camera_only/manual-policy.pt` 后，“按说明书自动搭建”可启动说明书条件策略。没有该策略时按钮禁用，后端同样拒绝启动；旧的颜色/坐标控制器不会作为回退。当前没有正式训练好的说明书策略，自动搭建能力尚未验收。

工作区可以暂停策略或关闭本平台启动的场景。切换到另一作品时，会先请求当前由本服务管理的场景正常退出，再启动新场景；不会结束其他机械臂服务。每次重新启动使用新的随机布局，相同作品不绑定固定散件位置。原 `/training/<任务编号>` 的有限帧检查页继续保留。

平台附带 `assets/manuals/bricklab_camera_wall/model.json`：6 块相同颜色、相同规格的砖组成三层交错小墙，避免依赖颜色辨认物体身份。可通过网页“导入作品”载入。

也可直接准备任务：

```powershell
.\.tools\bricklab-venv\Scripts\python.exe scripts\bricklab_prepare.py assets\manuals\bricklab_camera_wall\model.json --output outputs\bricklab\my-wall --mode steps
.\start-camera-only.ps1 -Task outputs\bricklab\my-wall\task.json -Mode collect -Episode outputs\camera_only\demos\wall01.npz -Group wall-layout01 -Seed 6101
.\.venv\Scripts\python.exe scripts\train_camera_policy.py --data outputs\camera_only\demos --out outputs\camera_only\manual-policy.pt
.\start-camera-only.ps1 -Task outputs\bricklab\my-wall\task.json -Policy outputs\camera_only\manual-policy.pt -Seed 7101
```

输出目录必须不存在，避免覆盖已有任务。同一布局的重复示范使用相同 Group；至少准备两个独立分组。照片任务和说明书任务采用不同 checkpoint / 数据合同，不允许混在同一次训练中。

## 文件与信息边界

```text
outputs/bricklab/jobs/<任务编号>/
  inputs/                   提交时的模型快照
  task/
    task.json               任务关联清单，供平台加载器使用
    policy/manual.pdf       对外发布的说明书
    policy/pages/*.png      策略接收的全部说明书页面
    policy-inputs.zip       仅包含 PDF 和页面图像
    environment/inventory.json
                            环境专用：标称几何及数量，无颜色、实例身份或目标/散件位姿
    evaluation/             结构参考答案、原始适配结果及页面对应关系
  runtime/<运行编号>/        独立的检查日志、报告及腕部相机图像
  live/<运行编号>/           持续搭建场景、命令记录及待审查的示范
```

`bricklab_prepare.py` 在 CPU 工具环境中复用 BRICKLAB 的输入适配、Studio 提取、几何校验及说明书渲染。使用 PDFium 输出全部 PNG 页面，不依赖 macOS 字体路径或 Poppler。系统已有中文字体仅用于嵌入 PDF，不复制到仓库。

`bricklab_task.load_manual()` 验证 PDF/PNG 哈希和路径后，只返回图像数组。评估文件不经过该加载路径，也不在 HTTP 下载允许列表中。`load_scene()` 单独供环境初始化使用，根据清单在本机创建真实 PhysX 刚体并随机散落；不采用 BRICKLAB 原来的按类型/颜色固定料区。零件统一材质；网页输入增加对应的 20×20 固定底板。初始化以后机器人不改写零件位姿。

多页策略以视觉特征对说明书各页面计算注意力，不从页面映射选择“正确步骤”。训练批次对不同页数使用掩码，避免填充页参与注意力。说明书页面顺序与图示是任务说明，不是机器人当前执行阶段。当前页面缩放到 128×96，与相机编码器共享 CNN；这只是可训练输入通路，不表示已经学会阅读小字、理解任意 PDF 或完成装配。

实时场景的网格/物体变换只作为人类查看器的输出。`camera_live.py` 调用策略时只传入腕部 RGB，任务条件为说明书图像；它不读取评估目标，不把查看器变换传给策略，也不在示范中保存这些变换。关节动作仍由历史指令积分产生，不把编码器反馈作为观测。手动示范的“保存”只说明数据已保存，不自动标记装配成功。

上述隔离是当前代码与 HTTP 接口的输入边界，不是针对任意恶意 Python 代码的操作系统沙箱。现有策略没有文件/网络工具或场景对象引用。

## 安装与来源

本机使用下载目录中的 `BRICKLAB-main (1).zip`，未修改源码，安装到被 Git 忽略的 `tools/BRICKLAB/`。来源和源码树 SHA-256 固定在 `config/bricklab-source.json`；ZIP 没有 Git 元数据，因此不声称对应某个 commit。

实际安装的 BRICKLAB 源码快照现随 [2026-11-11 完整 Release](experiments/2026-11-11/ARTIFACTS.md) 的 `simulation-assets` 归档保存。换机器时也可从恢复后的源码目录安装，无需依赖原下载目录中的 ZIP：`setup-bricklab.ps1 -Source <恢复目录>/project/tools/BRICKLAB`。

重建时运行：

```powershell
.\setup-bricklab.ps1 -Source 'C:\Users\Administrator\Downloads\BRICKLAB-main (1).zip'
.\start-bricklab.ps1
```

也接受 BRICKLAB 源码目录。安装器不覆盖已有源码；源码树与锁文件不一致时要求先审查差异。依赖固定在 `bricklab-requirements.txt` 并安装于独立 `.tools/bricklab-venv`，不升级 Isaac 环境。上游文档及第三方许可保留在 `tools/BRICKLAB/`。

## 验证与限制

```powershell
.\.tools\bricklab-venv\Scripts\python.exe scripts\check_bricklab.py
.\.venv\Scripts\python.exe scripts\check_camera_only.py
node web\check_bricklab.cjs
node web\check_bricklab_workspace.cjs
```

已实际生成同色小墙（6 件、逐步模式 8 页）和小屋示例（38 件、LEGO 模式 12 页）。CPU 检查覆盖三种模式、Studio MPD、图像完整性、路径越界、下载包内容、中文网页请求及私有文件访问拒绝；策略检查覆盖多页训练、填充掩码和 checkpoint 合同。浏览器结果在 `outputs/bricklab/browser-check/`。

Isaac 检查只验证散件生成与单路相机采集。当前没有正式训练的说明书条件策略或闭环抓取/装配成功率。各零件沿用 BRICKLAB 的标称中空复合刚体几何，包括经核验的圆柱/空心凸点；没有真实塑料公差与卡接力标定。限制为每任务最多 64 件和 64 页，超出时明确拒绝，不静默丢页或替换零件。

持续工作区的浏览器实测已覆盖：提交同色小墙后自动打开对应场景、加载 6 件积木和 8 页说明书、拒绝未训练策略、执行一个真实 PhysX 关节增量并验证变换改变、切换为仅腕部相机记录、保存纯图像/动作示范以及正常关闭。证据在 `outputs/bricklab/workspace-check/`。这项检查未抓取或装配积木。

训练场景统一颜色，因此只评估几何结构，不评估指定颜色的最终搭建。相机初始只看到局部散件，遮挡或视野外的物体需要策略通过实际观察动作寻找；不会补入隐藏物体的真值。
