# lwns — Linux Web Network Simulator

**lwns（Linux Web Network Simulator）** 是基于 Linux、Docker 和浏览器的网络实验平台。
在 Web 画布中添加设备、连接端口，即可在当前连接的 Linux 宿主机上部署网络，
通过网页终端配置设备，并用本机 Wireshark 远程抓包。Windows 和 Linux 客户端都可通过浏览器使用。

- **图形化组网**：设备分类库、拖放画布、自动对齐、注释和缩放；容器之间以 veth 对连接。
- **真实设备运行环境**：支持 FRR、Linux bridge、VPCS/Linux 容器，以及通过 `.lwns` 描述的 Docker 设备。
- **设备包与配置恢复**：Web 或 CLI 将 `device.json` 与镜像来源打包为 `.lwns`，按描述启动服务、挂载独立配置目录，并执行设备自己的保存命令。
- **远程项目管理**：在当前服务器上新建、打开、保存和关闭项目；部署后可编辑拓扑，再显式应用变更。
- **调试与部署**：Web 交互终端、部署日志、SSH/Wireshark 抓包；支持源码运行、Linux 目录安装包及可选的 HTTP/2、HTTP/3 入口。

当前面向单用户、单台 Linux Docker 宿主机；完整项目包导入导出、虚拟机设备和跨宿主机连线尚未实现。
配置恢复范围由设备描述及保存动作决定，手工 Shell 命令产生的运行状态不会自动全部持久化。
原有 OVS/FRR 命令行工具仍可独立使用。

从[设备包教程](docs/user/workbench-devices.rst)制作或加载 FRR `frr.lwns`，
再按[第一次实验](docs/user/quickstart.rst)完成组网。保存范围见[保存与恢复](docs/user/workbench-data.rst)。
旧版本升级说明见[更名与已有数据](docs/user/workbench-start.rst#lwns-upgrade)。

## 获取代码或安装包

源码仓库：[nanfengnan1/lwns](https://github.com/nanfengnan1/lwns)。在 Linux 宿主机准备存放源码的目录中执行：

```bash
git clone --branch main https://github.com/nanfengnan1/lwns.git
cd lwns
```

后续源码命令都在这个项目根目录执行。也可在仓库网页选择 **Code → Download ZIP**，解压后进入 `lwns-main`。已有源码直接进入原目录即可。

可直接安装的 **[v1.0 Linux 程序包](https://github.com/nanfengnan1/lwns/releases/tag/v1.0)**：下载 `lwns-1.0-linux-x86_64.tar.xz`、同名 `.sha256` 和验证记录。包内包含可执行后端、Python 运行库、已构建前端、安装脚本与离线手册，无需 Node.js/npm 或后端虚拟环境。目标为 Linux x86_64、glibc 2.35 基线；Docker/ip/nsenter 仍由宿主机提供。GitHub 的 Source code 归档不是可执行安装包，设备镜像另行导入。安装步骤见[目录包教程](docs/user/workbench-install.rst)，维护者流程见[构建与发布](docs/developer/release.rst)。

该程序包来自原 `v1.0` 提交，设备包使用 `.rov`；当前 main 后续增加的设备包格式和 SDN 示例需要新版程序。完整测试范围及限制见 Release 的 validation.json 附件。

## 用户文档

从[用户指南](docs/user/index.rst)按任务选择入口；构建后的 HTML 首页为 `docs/html/index.html`。

| 你要做什么 | 阅读入口 |
| --- | --- |
| 首次安装 | [获取代码与环境准备](docs/user/deployment.rst) → [部署与启动](docs/user/workbench-start.rst) |
| 已有地址，开始实验 | [第一次实验：让两台 PC 互通](docs/user/quickstart.rst) |
| 导入设备并绘图 | [.lwns 设备包制作与导入](docs/user/workbench-devices.rst) · [镜像管理（兼容）](docs/user/workbench-images.rst) · [项目与画布](docs/user/workbench-editor.rst) |
| 配置设备、保存和抓包 | [设备终端](docs/user/workbench-terminal.rst) · [配置保存与恢复](docs/user/workbench-data.rst) · [Wireshark 抓包](docs/user/workbench-capture.rst) |
| 安装目录包或启用 HTTPS | [目录包安装](docs/user/workbench-install.rst) · [HTTPS / HTTP/2 / HTTP/3](docs/user/workbench-https.rst) |
| 排查错误 | [故障排查](docs/user/troubleshooting.rst) |
| 使用旧版脚本 | [旧版 FRR 命令行入口](docs/user/legacy-cli.rst) |

## 开发部署与发布部署

**原来的 `npm run dev` + Python 后端方式仍然有效。** 先选择开发或发布，再选择普通 HTTP 或可选 HTTPS；完整步骤集中在[部署与启动](docs/user/workbench-start.rst)。

| 部署方式 | 首次准备 | 每次运行 | 默认浏览器入口 |
| --- | --- | --- | --- |
| 开发部署 | 安装 npm 和 Python 依赖，无需 build | Vite + Python 后端，两个终端 | `http://宿主机IP:5173` |
| 发布部署：源码构建 | 安装依赖并执行 build | 只运行 Python 后端 | `http://宿主机IP:8090` |
| 发布部署：Linux 目录包 | 解压并安装到系统目录 | systemd 启动打包后的后端 | `http://宿主机IP:8090` |

开发部署：依赖已安装时，在 Linux 项目根目录分别打开两个终端。

```bash
# 终端一：后端，默认监听 127.0.0.1:8090
sudo .venv/bin/python script/python/lab_server.py --port 8090
```

```bash
# 终端二：Vite，浏览器访问 http://宿主机IP:5173
npm --prefix web run dev -- --host 0.0.0.0
```

同机 Vite 会代理 `/api` 和 WebSocket 到 8090，登录时输入后端的 Token。直接访问 8090 不会看到 Vite 的热更新。
发布部署不运行 Vite；源码构建步骤见下文，下载目录包的用户按[目录包安装教程](docs/user/workbench-install.rst)操作。

两种部署方式的普通 HTTP 均为 HTTP/1.1。发布部署需要 HTTPS 时，再按 [Caddy 教程](docs/user/workbench-https.rst)增加入口，访问 `https://宿主机IP`。
HTTPS 默认配置为 `protocols h1 h2 h3`，浏览器协商协议；
HTTP/3 额外需要 UDP 443 可达及满足浏览器的证书信任要求，实际使用情况在 Network 的 Protocol 列确认。
HTTPS 教程包含 Ubuntu 安装、后端启动、Caddy 服务、TCP/UDP 端口、Windows/Linux 证书信任及 Chrome 验证命令。
切换方式时先停止旧后端，再使用同一实验数据目录启动；不要同时运行两个后端占用该目录。

## 网络架构

Caddy 是可选的 HTTPS 入口；直接启动后端时也可以通过 HTTP 8090 访问。
启用 Caddy 后，推荐后端只监听回环地址；以下两条访问路径是可选部署方式。

```text
Windows / Linux 客户端
┌──────────────────────────────────────────────┐
│ 浏览器                                       │
│ Vue 画布 + 设备库 + 管理面板 + xterm 终端      │
└───────────────┬──────────────────┬───────────┘
                │                  │
        可选 HTTPS 入口       直接访问 HTTP
                │                  │
       TCP 443：HTTP/1.1、HTTP/2    │ TCP 8090
       UDP 443：HTTP/3             │
                │                  │
================│==================│====================
Linux Docker 宿主机（例如 10.8.126.103）
                │                  │
       ┌────────▼────────┐         │
       │ Caddy（可选）   │         │
       │ TLS 证书        │         │
       │ HTTP/2、HTTP/3  │         │
       │ WebSocket 代理 │         │
       └────────┬────────┘         │
                │                  │
        HTTP / WebSocket           │
        127.0.0.1:8090              │
                │                  │
       ┌────────▼──────────────────▼────────────┐
       │ FastAPI / Uvicorn                      │
       │                                        │
       │ web/dist       前端资源、gzip、缓存    │
       │ /api/*         实验、镜像、配置管理    │
       │ /api/terminal  WebSocket 交互式终端    │
       └───────┬────────────┬────────────┬───────┘
               │            │            │
          Docker CLI    ip / nsenter   文件读写
               │            │            │
       /var/run/            │     .lwns-labs/
       docker.sock          │       ├─ 拓扑 JSON
               │            │       ├─ 镜像管理清单
       ┌───────▼──────┐     │       └─ 设备配置目录
       │ Docker daemon│     │               │
       │ 创建/清理容器│     │          RW 目录挂载
       └───────┬──────┘     │               │
               │      创建 veth、移入 netns  │
               └────────────┬───────────────┘
                            │
                     实验设备与链路
```

设备间报文直接通过 veth 传输，不经过 Caddy 或 Web 后端。交换机是容器内的 Linux bridge，
并非宿主机的 Docker 默认网桥。示例数据通道如下：

```text
PC1 容器 eth0
      │ veth
      ▼
FRR 容器 eth0 ── 路由转发 ── eth1
                              │ veth
                              ▼
交换机容器 eth0 ── br0 ── eth1
                           │ veth
                           ▼
                       PC2 容器 eth0
```

Wireshark 抓包使用独立的 SSH 通道，PCAP 数据沿原通道返回客户端：

```text
本机 Wireshark / sshdump
        │ SSH / TCP 22
        ▼
宿主机 sshd → remote_relay
        │ HTTP：127.0.0.1:8090/api/capture/stream
        ▼
后端抓包服务 → 目标容器网络命名空间中的 tcpdump
```

HTTP/3 只作用于浏览器到 Caddy 的通信；终端继续使用 WebSocket/WSS，PCAP 数据继续走 SSH。
Caddy 的公开入口拒绝 `/api/capture/stream`。配置文件见 [config/Caddyfile](config/Caddyfile)，
安装、内网证书信任及浏览器实际协商 `h3` 的操作见 [HTTP/3 启用指南](docs/user/workbench-https.rst)。

## Docker 图形组网工作台

Web 工作台使用 **Vue 3 + TypeScript + Vite + Pinia + xterm.js**，Python 后端使用 **FastAPI + Uvicorn**。支持：

- 拖放 FRR 路由器、Linux bridge 交换机和 VPCS 容器；
- 紧凑圆形设备、顶部自动对齐、就近连线优化；支持多行网段注释与样式保存；
- 左右侧边栏收起/展开、拖动调宽及浏览器布局记忆；
- 新建项目时命名，支持已部署项目重命名并保留设备和终端；
- 路由器、交换机、PC、防火墙四类设备库，横向分类、按类浏览与分批显示；Web 导入/构建镜像，删除与分类条目同步；
- 点击设备端口，使用 veth pair 创建点对点网线；
- 配置镜像、端口地址、默认网关和 FRR 启动配置；
- 部署后可增删设备和连线、修改属性，通过“应用拓扑”增量更新运行网络；位置和注释通过“保存项目”保存；
- FRR 配置目录读写共享、Web 保存运行配置、清理后重新部署恢复；
- 保存、导入和导出 JSON 拓扑；
- 部署、查看状态、浏览器交互终端、清理及失败回滚。
- 双击设备进入 `vtysh` / `sh`，支持多标签、实时输出、Ctrl+C、终端拖动和放大。
- 点击已部署连线，选择端点/BPF，通过本机 Wireshark 的 sshdump 实时抓包；支持 Windows/Linux 本地启动器。

以下是**源码发布部署**的步骤；开发部署按上面的两个终端运行，无需预先 build。
源码发布首次构建前端（Node.js 22.12+ 的 22.x，或 24+；建议使用 Node.js 24 LTS）：

```bash
npm --prefix web ci --include=optional
npm --prefix web run build
```

构建产物位于 `web/dist/`。可以在 Windows 或构建机上生成后，将整个 `web/dist/`
复制到 Linux 项目的相同位置；运行后端时无需安装 Node.js。源码仓库不提交 `dist/` 和 `node_modules/`。

**Windows 与 Linux 不要共用同一份 `node_modules/`。** 如果通过 Samba 共享项目，
切换运行平台后应在当前系统执行 `npm --prefix web ci --include=optional`，
按锁文件重装该平台的依赖。建议两端使用独立检出目录；`dist/` 可以跨平台复制。

以下为 **HTTP/1.1 直接启动**。在 **Linux Docker 宿主机**上，从项目根目录安装后端依赖并启动（Python 3.10+）：

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

选择 HTTPS / HTTP/2 / HTTP/3 时，共用相同构建产物和 Python 依赖，将上述后端启动命令换为：

```bash
sudo .venv/bin/python script/python/lab_server.py \
  --host 127.0.0.1 --port 8090 --trusted-proxy 127.0.0.1
```

然后按 [HTTPS 启动教程](docs/user/workbench-https.rst) 安装并启动 Caddy、设置实际站点地址和信任证书。
**只执行这条 Python 命令不会启用 HTTPS 或 HTTP/3**；经 Caddy 访问时使用 `https://宿主机IP`，不是 `:8090`。

也可启动后从左侧“镜像管理”导入镜像，支持仓库地址、HTTP(S) 归档 URL、本地
未压缩 `.tar` 镜像归档，以及 Dockerfile 文件和可选构建上下文；Web 镜像导入不解压 `.gz` / `.xz`。选择兼容的设备模板后，
镜像会出现在设备库。初始默认清单在 `config/images.defaults.json`，实际管理清单自动保存到
`.lwns-labs/images/registry.json`；导入和删除成功后同步，已被保存项目或容器引用的镜像拒绝删除。
管理界面只显示项目管理的镜像，刷新不会纳入宿主机其他镜像；可通过“已有镜像”显式引用。
“移出清单”保留本地镜像，“删除镜像”仅适用于能确认由本项目新建且归属未变化的标签。

完成前端构建后，没有 Docker 或仅预览界面时：

```bash
.venv/bin/python script/python/lab_server.py --preview
```

打开启动时显示的地址即可编辑和保存拓扑；设计模式不会创建设备。
实验配置默认保存在 `.lwns-labs/`，不会接管旧脚本创建的容器。
第一版仅支持同一 Linux 主机上的 Docker 设备；交换机使用容器内 Linux bridge。
Windows 设计模式使用 `py -m venv .venv` 创建环境，通过 `.venv\Scripts\python.exe`
安装相同依赖并启动。Python 虚拟环境与 `node_modules` 一样不能跨操作系统共用。

设备部署完成后双击设备，底部打开交互终端。FRR 默认进入 `vtysh`，也可选择
“Linux Shell”；其他设备进入 `sh`。切换标签或收起面板保留会话，关闭标签结束
对应终端，设备继续运行。刷新网页后需要重新打开终端。

FRR 终端配置完成后，点击工具栏或设备属性中的“保存设备配置”；拓扑“保存”不会保存设备运行配置。后端执行
`vtysh -w`，保存到 `.lwns-labs/devices/<实验ID>/<设备ID>/frr/`，同时同步拓扑
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

新版默认将报文保存到浏览器电脑的 `~/lwns/captures` 独立子目录，Windows 对应
`%USERPROFILE%\lwns\captures`；Web 会话显示完整路径。更新抓包功能后需重新下载安装
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
`http://127.0.0.1:8090`；可在 `web/.env.local` 中设置 `LWNS_API_TARGET`
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
