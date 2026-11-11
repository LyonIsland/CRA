# 完整快照、下载与恢复

[GitHub Release：snapshot-2026-11-11](https://github.com/LyonIsland/CRA/releases/tag/snapshot-2026-11-11)

源码与可阅读实验记录在 Git 中；完整大文件通过同一个私有仓库的 Release 附件保存。未改变仓库可见性。
原始资料共 **99,616,653,856 字节（约 92.8 GiB）**，无损压缩为 **10,871,450,390 字节（约 10.1 GiB）**，共 24 个数据分卷。
每卷最多 512 MiB，另外附有五个 JSON 清单；不存在“只上传成功样例、丢弃失败日志”的筛选。

## 保存范围

| 归档组 | 原始字节 | 压缩字节 | 数据分卷 | 内容 |
|---|---:|---:|---:|---|
| `project-outputs` | 680,068,477 | 587,008,182 | 2 | 全部项目实验输出、逐帧 PNG、录像、动作/评价轨迹、失败日志、BRICKLAB 任务与旧版报告 |
| `xr-history` | 91,989,853,339 | 3,809,114,234 | 8 | 全部 75 个历史 XR 逐帧 JSONL 文件，属于历史协议，不混入当前纯相机成功率 |
| `camera-training` | 6,804,741,200 | 6,443,214,532 | 13 | 夜间全部轮次的原始数据、模型、优化器状态、配置、日志、课程与先导试验 |
| `simulation-assets` | 141,990,840 | 32,113,442 | 1 | 实际 Piper 资源、生成的 URDF/USD 与已安装 BRICKLAB 源码快照 |

总索引为 [artifact-manifest.json](artifacts/artifact-manifest.json)。各组的完整文件名、大小与 SHA-256：

- [project-outputs](artifacts/project-outputs.manifest.json)
- [xr-history](artifacts/xr-history.manifest.json)
- [camera-training](artifacts/camera-training.manifest.json)
- [simulation-assets](artifacts/simulation-assets.manifest.json)

发布前已完成全量流式回读校验：**5,902 个原始文件、99,616,653,856 字节全部通过 SHA-256 比对**，见 [verification.json](artifacts/verification.json)。Git 中的实验文件禁用换行自动转换，避免克隆后破坏字节级校验值。

原始结果没有为了报告好看而删除、改写或覆盖。导出的 HTML 只移除了仅供本机使用的实时轮询；其他可阅读证据的来源与校验值见 [evidence-manifest.json](evidence-manifest.json)。

排除的是可重新安装的 Python/Node 环境、缓存和安装器、Git 内部数据、凭据/私钥以及 PID/STOP 运行控制文件。
STOP 的存在已记入抓取实验索引，主动中断不伪装为完整失败或成功试验。归档时仍增长的服务日志按读取开始时的长度保存，清单会标注 `source_grew_during_snapshot`；不会修改正在使用的原文件。
这不是包含操作系统、驱动和已安装虚拟环境的整机磁盘镜像。

## 下载

登录具有该私有仓库权限的 GitHub 账号，可从 Release 页面下载。安装 GitHub CLI 后也可批量下载：

```powershell
gh release download snapshot-2026-11-11 --repo LyonIsland/CRA --dir D:\CRA-archives
python -m pip install zstandard
```

每个 `*.tar.zst.partNNN` 都是同一个压缩流的连续分卷，不能单独解压。请保留所有分卷和 JSON 清单的原始文件名。

## 校验与恢复

下面的校验逐一检查分卷 SHA-256，并流式解压、校验归档内每个原始文件，不把约 93 GiB 的原始资料写入磁盘：

```powershell
python scripts/restore_project_evidence.py --archives D:\CRA-archives --verify-only
```

恢复到一个**不存在的新目录**，需要另留足够空间容纳所选组的原始数据：

```powershell
python scripts/restore_project_evidence.py --archives D:\CRA-archives --out D:\CRA-restored --groups project-outputs simulation-assets camera-training
# 若需要全部历史逐帧日志，可另选新目录恢复 xr-history：
python scripts/restore_project_evidence.py --archives D:\CRA-archives --out D:\CRA-xr-history --groups xr-history
```

恢复后的 `project/` 对应原 `E:\PiperIsaac` 的资源与输出；`camera-training/` 对应原 `D:\PiperCameraTraining` 的数据与模型。
源码从 Git 克隆取得。生成 USD 与部分实验配置保留原机器路径用于溯源；换机器时需要调整路径或重新运行资源准备脚本。
第三方来源和固定版本见 `assets/source.json` 与 `config/bricklab-source.json`。BRICKLAB 来自用户提供的无 Git 元数据源码快照，未虚构其 commit。

## 复现关键结果

安装依赖及 BRICKLAB 后，可执行：

```powershell
.\start-camera-grasp.ps1 -Headless -Seed 51001
.\.venv\Scripts\python.exe scripts/evaluate_camera_grasp.py --out outputs/camera_grasp/new-independent-batch --seeds 53001 53002 53003 53004 53005
.\.venv\Scripts\python.exe scripts/replay_camera_grasp_control.py --source outputs/camera_grasp/frozen-eval-v1/52001 --out outputs/camera_grasp/new-mechanical-control
```

51001 是开发演示种子，不是新的留出评估。原始冻结测试用的 52001–52005 不应再次调参后冒充新测试。
同一随机种子下视觉跟踪仍可能失败；成对机械回放可以复核指令的物理效果，但不代表在线策略稳定性。
基础抓取不会读取恢复的评价位姿来选择动作。归档包含评价真值是为了独立审计，不是为了给控制器提供额外输入。
