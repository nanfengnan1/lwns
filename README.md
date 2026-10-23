# route-ovs

通过 Docker 图形组网工作台搭建和验证路由实验，也保留原有 OVS/FRR 命令行工具。

用户文档：

- [环境准备](docs/user/deployment.rst)与[快速开始](docs/user/quickstart.rst)
- [Web 工作台使用指南](docs/user/workbench.rst)：启动、设备库、镜像管理、组网与终端
- [Wireshark 抓包指南](docs/user/workbench-capture.rst)：安装、密码登录、会话状态与本机文件位置
- [实验保存、备份与恢复](docs/user/workbench-data.rst)：拓扑、FRR 配置、迁移和当前限制
- [故障排查](docs/user/troubleshooting.rst)

## Docker 图形组网工作台

Web 工作台使用 **Vue 3 + TypeScript + Vite + Pinia + xterm.js**，Python 后端使用 **FastAPI + Uvicorn**。支持：

- 拖放 FRR 路由器、Linux bridge 交换机和 VPCS 容器；
- 左右侧边栏收起/展开、拖动调宽及浏览器布局记忆；
- 新建项目时命名，支持已部署项目重命名并保留设备和终端；
- 设备库搜索、分类、分批显示；Web 拉取仓库镜像、下载或上传镜像归档、通过 Dockerfile 构建；
- 点击设备端口，使用 veth pair 创建点对点网线；
- 配置镜像、端口地址、默认网关和 FRR 启动配置；
- FRR 配置目录读写共享、Web 保存运行配置、清理后重新部署恢复；
- 保存、导入和导出 JSON 拓扑；
- 部署、查看状态、浏览器交互终端、清理及失败回滚。
- 双击设备进入 `vtysh` / `sh`，支持多标签、实时输出、Ctrl+C、终端拖动和放大。
- 点击已部署连线，选择端点/BPF，通过本机 Wireshark 的 sshdump 实时抓包；支持 Windows/Linux 本地启动器。

首次使用先构建前端（Node.js 22.12+ 的 22.x，或 24+；建议使用 Node.js 24 LTS）：

```bash
npm --prefix web ci --include=optional
npm --prefix web run build
```

构建产物位于 `web/dist/`。可以在 Windows 或构建机上生成后，将整个 `web/dist/`
复制到 Linux 项目的相同位置；运行后端时无需安装 Node.js。源码仓库不提交 `dist/` 和 `node_modules/`。

**Windows 与 Linux 不要共用同一份 `node_modules/`。** 如果通过 Samba 共享项目，
切换运行平台后应在当前系统执行 `npm --prefix web ci --include=optional`，
按锁文件重装该平台的依赖。建议两端使用独立检出目录；`dist/` 可以跨平台复制。

在 **Linux Docker 宿主机**上，从项目根目录安装后端依赖并启动（Python 3.10+）：

```bash
docker load -i devices/route/frr.tar.xz
docker load -i devices/vpcs/vpcs.tar.xz
python3 -m venv .venv
.venv/bin/python -m pip install -r script/python/requirements.txt
sudo .venv/bin/python script/python/lab_server.py --host 0.0.0.0 --port 8090
```

路由器默认使用 `alpine/frr:latest`，交换机和主机默认使用 `alpine/vpcs:latest`。
在浏览器访问 `http://宿主机IP:8090`，输入终端显示的访问令牌。镜像标签应以
`docker image ls` 为准，可在设备属性中修改。默认仅监听 `127.0.0.1`；此工具面向可信实验网络。

也可启动后从左侧“镜像管理”导入镜像，支持仓库地址、HTTP(S) 归档 URL、本地
`docker.tar.xz` 等镜像归档，以及 Dockerfile 文件和可选构建上下文。选择兼容的设备模板后，
镜像会出现在设备库。初始默认清单在 `config/images.defaults.json`，实际管理清单自动保存到
`.route-ovs-labs/images/registry.json`；导入和删除成功后同步，已被保存实验或容器引用的镜像拒绝删除。

完成前端构建后，没有 Docker 或仅预览界面时：

```bash
.venv/bin/python script/python/lab_server.py --preview
```

打开启动时显示的地址即可编辑和保存拓扑；设计模式不会创建设备。
实验配置默认保存在 `.route-ovs-labs/`，不会接管旧脚本创建的容器。
第一版仅支持同一 Linux 主机上的 Docker 设备；交换机使用容器内 Linux bridge。
Windows 设计模式使用 `py -m venv .venv` 创建环境，通过 `.venv\Scripts\python.exe`
安装相同依赖并启动。Python 虚拟环境与 `node_modules` 一样不能跨操作系统共用。

设备部署完成后双击设备，底部打开交互终端。FRR 默认进入 `vtysh`，也可选择
“Linux Shell”；其他设备进入 `sh`。切换标签或收起面板保留会话，关闭标签结束
对应终端，设备继续运行。刷新网页后需要重新打开终端。

FRR 终端配置完成后，点击工具栏或设备属性中的“保存设备配置”；拓扑“保存”不会保存设备运行配置。后端执行
`vtysh -w`，保存到 `.route-ovs-labs/devices/<实验ID>/<设备ID>/frr/`，同时同步拓扑
中的启动配置。该目录读写挂载到容器 `/etc/frr`，包含 `frr.conf`、`daemons` 和
`vtysh.conf`。清理容器保留配置，重新部署自动恢复；删除实验才会删除配置和备份。
旧版本已部署设备也可先点击保存，再清理重建以启用目录共享。
前端更新需重新构建，后端更新需重启；日常部署实验不需要重新编译。
当前导出 JSON 不包含全部配置文件和镜像，完整项目包尚未实现。备份步骤见
[保存与恢复指南](docs/user/workbench-data.rst)。

连线抓包需要在 Docker 宿主机安装 `tcpdump` 并以 root 运行后端；本机安装 Wireshark 的
SSH remote capture 组件，以及抓包窗口提供下载的本地启动器。点击“准备抓包”后，再点击
“打开本机 Wireshark”。首次在本地填写 SSH 主机和用户名；Profile 和私钥可选。
密码认证无需私钥：先不启用自动开始，在 Wireshark 的 SSH 接口设置中输入密码并开始。
密码/密钥口令由本机 Wireshark 处理，不上传工作台。

新版默认将报文保存到浏览器电脑的 `~/route-ovs/captures` 独立子目录，Windows 对应
`%USERPROFILE%\route-ovs\captures`；Web 会话显示完整路径。更新抓包功能后需重新下载安装
本地启动器，仅刷新页面不会更新客户端。详细步骤见 [抓包指南](docs/user/workbench-capture.rst)
和 [启动器说明](clients/capture/README.md)。

## Web 开发

在两个终端分别启动后端和 Vite（均从项目根目录执行）：

```bash
# 终端 1：设计模式后端
.venv/bin/python script/python/lab_server.py --preview --port 8090

# 终端 2：带热更新的 Vue 开发服务器
npm --prefix web ci
npm --prefix web run dev
```

访问 `http://127.0.0.1:5173` 并输入 Python 后端打印的令牌。Vite 将 `/api` 代理到
`http://127.0.0.1:8090`；可在 `web/.env.local` 中设置 `ROUTE_OVS_API_TARGET`
指向 Linux 后端。Vite 只负责开发与构建，实际 Docker/veth 操作仍在 Linux 后端执行。

```bash
npm --prefix web run format:check
npm --prefix web run typecheck
npm --prefix web test
.venv/bin/python -m pip install -r tests/requirements.txt
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
```

使用说明见 [图形组网指南](docs/user/workbench.rst)，代码结构与开发流程见
[Web 开发指南](docs/developer/workbench.rst)。
