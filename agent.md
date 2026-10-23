# route-ovs Web 工作台设计与开发说明

记录日期：2026-10-23。本文描述当前已实现的 Web 工作台，供后续开发与维护使用。修改架构、交互、启动方式或数据协议时，应同步更新本文及对应用户文档。

## 1. 产品定位与范围

提供类似 GNS3 的浏览器组网工作台：在画布添加路由器、交换机和主机，连接端口，保存拓扑，再部署为实际设备并通过网页终端操作。

- 当前只支持同一 Linux Docker 宿主机上的容器设备。
- 每根网线是一对 veth，两端直接位于对应容器的网络命名空间。
- 路由器使用 FRR，默认镜像为 `alpine/frr:latest`；交换机使用容器内的 Linux bridge `br0`，接入已连接端口并启用 STP；主机使用 VPCS 模板对应的 Linux 容器。
- 当前交换机模板没有厂商交换机 CLI，也不创建宿主机 OVS 网桥。
- 支持设计模式：编辑、保存、导入和导出拓扑；真实部署和设备终端需要可用的 Linux 后端。
- 面向单用户实验环境，暂不提供多用户权限体系、虚拟机设备、跨宿主机连线或部署后的在线拓扑变更。
- 既有 FRR/VPCS 脚本继续独立使用；工作台只管理自己创建并记录归属的容器。

## 2. 总体架构

```text
浏览器
  Vue 3 + TypeScript + Pinia
  ├─ 声明式 SVG 拓扑画布
  ├─ 设备库、属性、部署日志
  └─ xterm.js 交互终端
           │
           ├─ HTTP /api/*：拓扑、状态、部署、终端凭证
           └─ WebSocket /api/terminal：终端输入、输出、尺寸
           │
Linux Docker 宿主机
  FastAPI + Uvicorn，默认端口 8090
  ├─ lab_server.py：静态资源、认证、API、WebSocket 入口
  ├─ lab_core.py：拓扑持久化、Docker 生命周期、veth、状态核对
  └─ lab_terminal.py：连接凭证、PTY、交互会话和资源回收
           │
           ├─ .route-ovs-labs/*.json
           ├─ Docker CLI → 本机 Docker Unix socket
           └─ ip / nsenter → 容器网络命名空间
```

- 前端使用 Vue 单文件组件和 TypeScript；共享状态由 Pinia 管理。
- 画布由 Vue 渲染 SVG，设备节点具有稳定 key。当前没有引入 Vue Flow 或 Vue Router。
- 后端为 Python 3.10+、FastAPI、Uvicorn，依赖见 [requirements.txt](script/python/requirements.txt)。当前已经替换早期的标准库 HTTP 服务。
- 文件和 Docker 等阻塞操作在线程中执行，避免阻塞 WebSocket 事件循环。
- 后端保持单进程运行。数据目录锁、部署任务、终端凭证和会话保存在同一实例中，不能直接改成多个 Uvicorn worker。
- 生产模式由后端同时提供 `web/dist`、HTTP API 和 WebSocket，浏览器只访问一个端口，不需要启动 Vite。
- 开发模式由 Vite 在 `5173` 提供前端，将 `/api` 的 HTTP 和 WebSocket 请求代理到 Python 后端。

## 3. 界面与视觉设计

采用面向桌面浏览器的三栏工作台，顶部为全局导航；主体左侧是设备库，中间是拓扑画布与底部面板，右侧是属性检查器。

| 区域 | 内容与作用 |
| --- | --- |
| 顶部导航 | 北极熊头像、route-ovs 品牌、Docker/veth 标识、宿主机环境状态 |
| 左侧设备库 | 实验选择、新建实验、设备模板、示例、JSON 导入导出 |
| 中间工具栏 | 实验名称、保存、部署、清理 |
| 中间画布 | 设备、端口、veth 连线、缩放和平移、运行状态 |
| 右侧属性 | 镜像、名称、端口/IP、默认网关、启动命令、FRR 启动配置、终端入口 |
| 底部面板 | 部署日志、设备终端、多设备标签、刷新状态、收起和放大 |

视觉约定：

- 采用深蓝导航、浅色工作区和蓝色交互强调；终端使用深色背景与等宽字体。
- 项目图标为北极熊头像，唯一资源为 [polar-bear.svg](web/src/assets/polar-bear.svg)，用于导航栏、登录对话框和 favicon。
- 公共布局和样式集中在 [workbench.css](web/src/styles/workbench.css)。当前页面最小宽度为 1000px，尚未设计移动端布局。
- 用户可见的按钮、状态和提示以中文为主。设备名称、命令、接口和镜像名保留原始内容。

底部面板约定：

- 拖动面板顶部的水平分隔条调整高度，双击恢复默认；聚焦分隔条后可使用方向键、Home、End。
- 默认内容区高度为 174px，最小为 96px；普通模式为画布保留至少 280px 高度，最大面板高度随窗口计算。
- 首选高度保存在浏览器 `localStorage` 的 `route-ovs-panel-height`，切换标签、收起和刷新后保留。
- 放大模式覆盖顶部导航以下区域，恢复后回到普通布局；布局变化必须同步终端行列数。
- 拖动使用 Pointer Events 和 pointer capture，结束或组件卸载时释放捕获、光标及事件资源。

## 4. 拓扑编辑与状态管理

- 点击设备卡片或拖入画布添加设备；拖动节点调整位置，滚轮缩放，拖动空白区域平移。
- 选择工具下选中设备显示四边和四角的八个缩放手柄，左右改宽度、上下改高度、四角同时改宽高；对侧边缘固定，图标、端口和网线随尺寸变化。手柄支持方向键微调（6 单位，Shift 为 24），属性栏显示尺寸并可恢复默认。
- 设备缩放遵循拓扑编辑锁，连线或有待接端口时隐藏手柄。拖动使用 Pointer Events 和捕获，换算视口缩放，手柄保持屏幕尺寸；结束、失焦、切换实验或卸载时释放捕获。适应画布使用实际设备宽高。
- 点击两个空闲端口创建双向 veth 网线。端口最多连接一根网线，当前不允许设备连接自身。
- 单击设备查看属性；双击已部署设备打开交互终端。
- 设备属性先进入草稿，应用、切换选择、保存和导出时提交。应用属性时保留画布中最新的节点坐标和尺寸，包括已恢复默认的尺寸。
- “我的实验”旁及实验属性中均提供删除入口，共用 `DeleteLabButton.vue`。确认删除未保存实验只清空本地拓扑和属性草稿，不请求后端删除（即使导入草稿与已有文件同 ID）；已保存实验成功删除后移除列表项。删除后回到无未保存修改的“空白画布”，空白占位不显示为待删除的未保存实验；部署中、已部署或操作中禁止删除。
- 已部署、正在保存或正在部署/清理时，按状态锁定相应编辑操作。修改拓扑、端口或地址前需要清理设备。
- 图上端口表示接线插槽，仅已连接端口会创建 veth；未接线端口不能配置待部署 IP。
- 保留 `V` 选择、`C` 连线、Delete 删除、Esc 取消连线等快捷键。输入框、对话框和终端的键盘事件不能触发画布快捷键。
- 运行状态轮询间隔为 4 秒；读取真实运行状态，不根据拓扑文件直接判定设备和网线可用。

Pinia 状态分工：

| Store | 职责 |
| --- | --- |
| `stores/lab.ts` | 拓扑、设备目录、环境、实验列表、部署状态与 API 操作 |
| `stores/editor.ts` | 当前选择、端口连线、视口、属性草稿和未保存状态 |
| `stores/ui.ts` | 登录/环境对话框、提示消息、日志/终端面板和收起状态 |
| `stores/terminals.ts` | 终端标签、活动标签、连接状态、切换实验与部署变化后的清理 |

拓扑配置、运行状态、编辑草稿、终端连接分别管理。`documentVersion` 与运行状态版本用于拒绝旧请求结果，防止切换实验后被延迟响应覆盖，也防止旧的空闲状态解除新部署的编辑锁。

## 5. 数据与部署模型

拓扑 JSON 保持 `version: 1`，结构不依赖 Vue、Pinia 或终端组件：

```text
Topology
  version, id, name
  nodes[]
    id, name, kind, image, x, y
    width?, height?  # 可选画布尺寸
    ports[]: { name, address }
    gateway, command[], config
  links[]
    id
    a: { node, port }
    b: { node, port }
```

- `kind` 为 `router`、`switch`、`host`；`command` 为启动参数数组，`config` 为 FRR 启动配置文本。
- `width` / `height` 随拓扑保存、导入和导出，旧文件缺省宽 128、高至少 100；前后端校验宽 96～640、高 72～640。实际高度不小于 `max(72, ceil(端口数 / 2) * 13 + 20)`，为多端口设备保留空间；尺寸仅影响画布，不参与容器部署。
- CIDR、默认网关、镜像、端口和连线约束同时在前后端校验，后端是部署约束的最终校验方。
- 当前限制：最多 64 台设备、256 条链路、每台 1～32 个端口；拓扑导入和后端 JSON 请求上限为 1 MiB。
- 实验记录包含 `topology`、`runtime`、更新时间；保存在 `.route-ovs-labs/<实验ID>.json`，采用原子写入。
- 运行阶段包括 `idle`、`deploying`、`running`、`destroying`、`error`、`degraded`。
- 部署和清理使用后台任务，接口返回 `202`，前端随后轮询状态。全局同时只执行一个部署或清理任务。
- 后端固定使用本机 Docker Unix socket，默认 `/var/run/docker.sock`；不跟随 Docker 的远程 context。
- 创建的设备使用 `--network none`，部署时根据记录的 PID 创建 veth、设置地址、网关和桥接关系。
- 容器名称为 `rov-实验ID-设备ID`，使用实验、部署和节点标签标记归属。操作前验证归属、PID 和容器运行状态。
- 部署前检查本机镜像，不自动拉取。失败时回滚本次部署；清理只操作归属明确的资源。
- 停止后端保留已部署容器；重新启动同一数据目录后可以检查与清理。容器重启或链路异常会显示需要检查。
- 在交互终端临时修改的配置不会自动写回拓扑；需要重复部署的 FRR 配置应写入设备启动配置。

示例见 [basic-lab.json](examples/basic-lab.json)，完整操作说明见 [用户指南](docs/user/workbench.rst)。

## 6. Web 交互式终端

终端由 `xterm.js`、`@xterm/addon-fit`、WebSocket 和 Linux PTY 实现。命令在设备容器内执行，容器不需要 SSH 服务、管理 IP 或额外发布端口。

入口与会话行为：

- FRR 路由器默认进入 `vtysh`，可另开 Linux Shell；其他设备默认进入 `sh -i`。
- 标签按实验、部署、设备和模式区分。重复打开相同设备和模式会激活已有标签，FRR CLI 与 Shell 是独立会话。
- 切换终端标签、切换日志、收起面板保留连接；关闭标签结束对应终端会话，设备容器继续运行。
- 切换实验、清理设备或部署标识变化时清理旧标签和连接。
- 支持持续输出、Ctrl+C、复制粘贴、清屏、重连与尺寸同步；补全和历史命令由容器内程序提供。
- 当前每个页面最多 12 个标签，后端最多 32 个会话。
- 刷新网页后需要重新打开终端，不恢复原 Shell 的目录、历史和前台命令。

连接协议：

1. 前端携带 Bearer 令牌请求 `POST /api/labs/{id}/terminals`，提交 `node` 和 `mode`（`default` / `shell`）。后端确认设备归属，返回 30 秒有效的一次性凭证。
2. 前端连接 `/api/terminal`，首条消息发送 `{ type: "connect", ticket, cols, rows }`。凭证和长期访问令牌不放入 WebSocket URL。
3. 后端校验 Origin、凭证、部署版本和运行状态，分配 PTY，执行对应容器的交互式 `docker exec -it`。
4. 前端发送 `input`、`resize`、`ack` JSON 消息；后端输出为二进制帧，控制消息为 `ready`、`exit`、`error` JSON。输出字节直接交给 xterm.js，避免逐帧字符串解码破坏跨帧 UTF-8 序列。
5. 浏览器在 xterm.js 写入回调完成后发送 `ack`，后端继续读取下一块输出。单块最多 16 KiB，确认等待上限 30 秒，WebSocket 消息上限 64 KiB。
6. 输入写入 PTY 使用独立任务及有界队列，避免 PTY 写入阻塞接收输出确认和尺寸消息。
7. 每三秒复查设备。断开或服务退出时回收 Docker 客户端、PTY，以及容器中带有该随机会话标识的进程；不能仅结束宿主机 Docker 客户端就认为容器内命令已停止。

终端会话不会持续持有部署全局锁。组件卸载时释放 WebSocket、xterm.js、ResizeObserver、定时器和动画帧；服务端负责清理相应任务与进程。

## 7. HTTP API 与访问认证

| 方法和路径 | 作用 |
| --- | --- |
| `GET /api/bootstrap` | 设备目录、环境、实验列表、示例 |
| `GET /api/environment` | Docker 与宿主机环境检查、本机镜像 |
| `GET /api/labs` | 实验列表 |
| `GET /api/labs/{id}` | 拓扑与实际运行状态 |
| `PUT /api/labs/{id}` | 保存拓扑 |
| `DELETE /api/labs/{id}` | 删除已清理的实验记录 |
| `POST /api/labs/{id}/deploy` | 开始部署 |
| `POST /api/labs/{id}/destroy` | 开始清理并关闭关联终端 |
| `POST /api/labs/{id}/terminals` | 申请终端连接凭证 |
| `WS /api/terminal` | 交互式终端 |
| `POST /api/labs/{id}/exec` | 保留的单次命令 API，等待上限 15 秒 |

- 启动时随机生成访问令牌，也可通过 `ROUTE_OVS_TOKEN` 设置。前端从输入框、URL fragment 或 `sessionStorage` 读取；从 fragment 读取后移除 URL 中的令牌。
- HTTP API 使用 Bearer 认证并校验 Origin；WebSocket 需要同源 Origin 和一次性凭证。
- Vite 同时代理 HTTP 和 WebSocket，仅改写来自当前开发页面的同源 Origin。
- 静态服务只开放构建首页和 `assets` 资源，不开放源代码、实验文件或整个项目目录。
- 用户输入经容器终端执行；宿主机命令使用参数数组，不拼接成宿主机 Shell 命令。

## 8. 关键代码位置

| 文件 | 职责 |
| --- | --- |
| [App.vue](web/src/App.vue) | 页面组合、认证初始化、状态轮询、全局快捷键 |
| [DeviceLibrary.vue](web/src/components/DeviceLibrary.vue) | 设备模板、实验选择、导入导出 |
| [LabToolbar.vue](web/src/components/LabToolbar.vue) | 保存、部署、清理 |
| [TopologyCanvas.vue](web/src/components/TopologyCanvas.vue) | SVG 画布、拖动、缩放和平移 |
| [TopologyNode.vue](web/src/components/TopologyNode.vue) | 设备节点、端口、双击打开终端 |
| [DeviceInspector.vue](web/src/components/DeviceInspector.vue) | 设备和链路属性、终端入口 |
| [WorkbenchPanels.vue](web/src/components/WorkbenchPanels.vue) | 日志/终端面板、收起与放大 |
| [usePanelResize.ts](web/src/composables/usePanelResize.ts) | 面板拖动、边界计算、高度持久化 |
| [TerminalWorkspace.vue](web/src/components/TerminalWorkspace.vue) | 终端工具栏、多标签和组件生命周期 |
| [DeviceTerminal.vue](web/src/components/DeviceTerminal.vue) | xterm.js、连接、按键转发、输出确认和行列同步 |
| [WorkbenchDialogs.vue](web/src/components/WorkbenchDialogs.vue) | 登录、环境信息与提示 |
| [topology.ts](web/src/domain/topology.ts) | 导入校验、连线约束、SVG 几何 |
| [client.ts](web/src/api/client.ts) | 带认证的 HTTP 请求与错误处理 |
| [lab_server.py](script/python/lab_server.py) | FastAPI 应用、认证、路由与启动入口 |
| [lab_core.py](script/python/lab_core.py) | 实验存储、Docker/veth 生命周期和归属检查 |
| [lab_terminal.py](script/python/lab_terminal.py) | 凭证、PTY、数据转发与会话回收 |

## 9. 构建、启动与开发

以下 Linux 命令均在项目根目录执行。完整前端开发环境建议使用 Node.js 24；具体版本约束以 `web/package.json` 和锁文件为准。

```bash
# 安装并构建前端
npm --prefix web ci --include=optional
npm --prefix web run build

# 安装后端依赖
python3 -m venv .venv
.venv/bin/python -m pip install -r script/python/requirements.txt

# Linux Docker 宿主机真实部署
sudo .venv/bin/python script/python/lab_server.py --host 0.0.0.0 --port 8090
```

浏览器访问 `http://宿主机IP:8090`，输入启动时显示的令牌。真实部署需要 Linux root、Docker CLI、本机 Docker daemon、`ip` 和 `nsenter`。镜像按用户指南准备，标签以本机 `docker image ls` 为准。

```bash
# 仅设计/预览；不能打开真实设备终端
.venv/bin/python script/python/lab_server.py --preview --port 8090

# 另一个终端启动 Vite 开发服务器
npm --prefix web run dev
```

- 开发默认地址为 `http://127.0.0.1:5173`。通过 `web/.env.local` 的 `ROUTE_OVS_API_TARGET` 指定后端，默认 `http://127.0.0.1:8090`。
- 前端构建输出为 `web/dist`，可以跨平台复制；仅运行生产后端不需要 Node.js。
- Windows 设计模式使用独立虚拟环境及 `.venv\Scripts\python.exe` 安装依赖并启动。
- Windows 与 Linux 不能共用 `node_modules` 或 `.venv`。通过 Samba 共享代码时，应在实际运行环境安装依赖；不要在 Windows 安装依赖覆盖正在供 Linux 使用的目录。
- 遇到 Rolldown 原生模块缺失，在实际运行 Vite 的系统执行 `npm --prefix web ci --include=optional`，保留锁文件。`web/scripts/check-native.mjs` 会在开发和构建前检查原生绑定。
- `.route-ovs-labs`、`.venv`、`web/node_modules`、`web/dist` 和本地环境文件已被 Git 忽略。
- 更新后端代码后需要重启服务；更新生产前端代码后需要重新构建。

## 10. 验证与后续修改约定

根据改动运行相应检查：

```bash
npm --prefix web run format:check
npm --prefix web run typecheck
npm --prefix web test
npm --prefix web run build

.venv/bin/python -m pip install -r tests/requirements.txt
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v

# 显式启用真实 Docker 终端测试：创建独立测试容器，结束时清理
ROUTE_OVS_DOCKER_TESTS=1 .venv/bin/python -m unittest discover -s tests -p 'test_terminal.py' -v
```

- [check_workbench.cjs](tests/check_workbench.cjs)：Chromium 中验证拓扑编辑、拖动、设备八方向缩放及尺寸持久化、连线、保存、导入导出和面板调整，使用独立设计模式数据目录。
- [check_terminal.cjs](tests/check_terminal.cjs)：验证真实浏览器输入、FRR 配置、路由器 Shell、多标签、ping/Ctrl+C、尺寸同步、放大、重连和关闭。
- [serve_terminal_fixture.py](tests/serve_terminal_fixture.py)：为浏览器测试创建独立 Docker 设备，退出时清理；测试用的环境替换不能复制到生产入口。
- Docker 终端测试不验证 veth 数据平面，真实拓扑仍需按照用户指南检查跨设备连通性和清理结果。
- 保持 `version: 1` 拓扑兼容、组件职责、状态隔离及资源生命周期；新增设备类型时同步前端类型、模板、展示和后端部署逻辑。
- 修改终端时同时检查输入/输出、尺寸、连接认证、断开、重连和清理；保留终端键盘与画布快捷键之间的隔离。
- 修改布局或品牌时保持北极熊头像、三栏工作台及可调整底部面板的设计，除非用户明确要求变更。
- 避免覆盖工作区已有修改；验证使用独立实验数据和测试设备，按记录归属清理资源。

更多细节见 [用户指南](docs/user/workbench.rst) 和 [开发指南](docs/developer/workbench.rst)。
