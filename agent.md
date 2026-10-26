# lwns Web 工作台设计与开发说明

项目名称统一为 **lwns（Linux Web Network Simulator）**，仓库为 `nanfengnan1/lwns`。网页、CLI、发布包、systemd 服务与文档使用新名称；新安装使用 `lwns` 命令、`lwns-web.service`、`LWNS_*` 配置及 `/opt/lwns`、`/etc/lwns`、`/var/lib/lwns`。源码新数据默认 `.lwns-labs`。不自动搬迁已有数据：未显式配置且新目录不存在时沿用 `.route-ovs-labs`（冻结程序为 `/var/lib/route-ovs`）；显式 `--data-dir` 优先，其次 `LWNS_DATA_DIR`、旧 `ROUTE_OVS_DATA_DIR`。启动 Token、安装包装器和 Vite 保留旧环境变量回退，浏览器保留旧布局与会话读取。

兼容标识不是品牌展示：Docker 归属标签 `io.route-ovs.*`、veth alias 的 `route-ovs:` 前缀、容器控制路径 `/run/route-ovs*` 和设备包 v1 清单格式 `route-ovs-device` 保持不变，保证既有容器和设备包可管理。2026-10-26 起，新设备包统一使用 `.lwns` 后缀；JSON schema 版本保持 1，导入兼容旧 `.rov`，已安装的 `device.rov` 和旧制作任务产物继续可读，不批量移动旧文件。抓包新链接为 `lwns://`，需重新安装客户端以注册新协议；新客户端兼容解析旧链接、读取旧本地连接配置。目录包旧服务停用、配置继承和 Caddy 变量更新见用户文档 `workbench-start.rst` 的 `lwns-upgrade`。

记录日期：2026-10-25。本文第 1～10 节描述当前已实现的 Web 工作台，第 11 节记录未实现的端口接入讨论方案，第 12 节记录 SSH/Wireshark 抓包设计与实施状态，第 13 节区分已实现的远程项目保存与未实现的可移植项目包机制，第 14 节维护任务列表及完成状态，第 15 节记录已实现的第一版通用配置保存、设备描述与 `.lwns` 设备包，以及后续适配边界。修改架构、交互、启动方式或数据协议时，应同步更新本文及对应用户文档。

## 1. 产品定位与范围

提供类似 GNS3 的浏览器组网工作台：在画布添加路由器、交换机和主机，连接端口，保存拓扑，再部署为实际设备并通过网页终端操作。

- 当前只支持同一 Linux Docker 宿主机上的容器设备。
- 每根网线是一对 veth，两端直接位于对应容器的网络命名空间。
- 内置路由器使用 FRR，默认镜像为 `alpine/frr:latest`；内置交换机使用容器内的 Linux bridge `br0`，接入已连接端口并启用 STP；主机使用 VPCS 模板对应的 Linux 容器。新增 `.lwns` 设备使用各自描述的行为，分类本身不指定数据面。
- 当前交换机模板没有厂商交换机 CLI，也不创建宿主机 OVS 网桥。
- 支持设计模式：编辑、保存、导入和导出拓扑；真实部署和设备终端需要可用的 Linux 后端。
- 面向单用户实验环境，暂不提供多用户权限体系、虚拟机设备或跨宿主机连线。支持部署后编辑草稿并显式应用增量拓扑变更。
- 既有 FRR/VPCS 脚本继续独立使用；工作台只管理自己创建并记录归属的容器。

## 2. 总体架构

```text
浏览器
  Vue 3 + TypeScript + Pinia
  ├─ 声明式 SVG 拓扑画布
  ├─ 设备库、属性、部署日志
  ├─ 镜像管理：导入、构建、绑定模板、任务日志
  ├─ 连线抓包：会话与本地 Wireshark 启动入口
  └─ xterm.js 交互终端
           │
           ├─ HTTP /api/*：拓扑、状态、部署、终端凭证
           └─ WebSocket /api/terminal：终端输入、输出、尺寸
           │
Linux Docker 宿主机
  FastAPI + Uvicorn，默认端口 8090
  ├─ lab_server.py：静态资源、认证、API、WebSocket 入口
  ├─ lab_core.py：拓扑持久化、Docker 生命周期、veth、状态核对
  ├─ lab_updates.py：运行中拓扑差异、增量应用、失败恢复与配置快照
  ├─ lab_devices.py：设备模板、生命周期适配器、FRR 共享配置与备份
  ├─ lab_device_schema.py / lab_device_packages.py：设备描述校验、.lwns 打包与版本库
  ├─ lab_device_runtime.py：声明式启动、就绪、持久化目录与保存动作
  ├─ lab_device_service.py / lab_device_cli.py：设备包 Web 任务与 CLI 入口
  ├─ lab_images.py：镜像清单、上传、后台导入/构建/删除
  ├─ lab_capture.py：抓包凭证、命名空间校验、tcpdump 流与回收
  └─ lab_terminal.py：连接凭证、PTY、交互会话和资源回收
           │
           ├─ .lwns-labs/*.json
           ├─ .lwns-labs/devices/<实验ID>/<设备ID>/frr/ → 容器 /etc/frr（RW）
           ├─ .lwns-labs/images/registry.json、jobs/、uploads/
           ├─ Docker CLI → 本机 Docker Unix socket
           └─ ip / nsenter → 容器网络命名空间
```

- 前端使用 Vue 单文件组件和 TypeScript；共享状态由 Pinia 管理。
- 画布由 Vue 渲染 SVG，设备节点具有稳定 key。当前没有引入 Vue Flow 或 Vue Router。
- 后端为 Python 3.10+、FastAPI、Uvicorn，依赖见 [requirements.txt](script/python/requirements.txt)。当前已经替换早期的标准库 HTTP 服务。
- 文件和 Docker 等阻塞操作在线程中执行，避免阻塞 WebSocket 事件循环。
- 后端保持单进程运行。数据目录锁、部署任务、终端凭证和会话保存在同一实例中，不能直接改成多个 Uvicorn worker。
- Linux 发布使用 PyInstaller onedir 的 `.tar.gz` 目录包，不采用 deb/rpm。`packaging/linux/build.py` 构建前端并按固定清单收集后端资源；内置 Python 运行环境，宿主机仍需 Docker/ip/nsenter，SSH 抓包转发另需 python3。安装到 `/opt/lwns/releases/<BUILD_ID>`，`current` 选择版本，`/usr/local/bin/lwns` 读取 `/etc/lwns/lwns.env`，默认数据为 `/var/lib/lwns`。源码部署默认目录不变。
- 目录包安装器校验包内文件、拒绝覆盖非本安装器管理的目录/同名服务，要求升级前停止服务；保留配置、Token、数据和旧版本。systemd 模式启用开机启动但由用户显式 start；支持 `--no-systemd` 和隔离验收用 `--root`。卸载保留配置、数据、Docker 镜像和设备。Caddy 单独配置，目录包不携带当前主机证书私钥/令牌或实验数据。操作见 [目录包用户教程](docs/user/workbench-install.rst)。
- `lab_paths.py` 处理冻结程序资源目录及可写数据目录，`host_environment()` 恢复宿主机动态库搜索路径，供 Docker、PTY 终端和 tcpdump 子进程使用。目录包按 Linux CPU 架构分别构建，记录 glibc/Python/依赖版本；发行格式通用不代表任意发行版二进制兼容。
- 生产模式由后端同时提供 `web/dist`、HTTP API 和 WebSocket，浏览器只访问一个端口，不需要启动 Vite。
- 开发模式由 Vite 在 `5173` 提供前端，将 `/api` 的 HTTP 和 WebSocket 请求代理到 Python 后端。
- 可选 `config/Caddyfile` 在同机提供 HTTPS / HTTP/2 / HTTP/3（保留 HTTP/1.1 回退），全部请求代理到回环后端；静态压缩和缓存继续由 Python 统一处理。后端用 `--trusted-proxy 127.0.0.1` 显式信任代理协议和客户端地址，保留 Host/Origin 校验。Caddy 拒绝公开 `/api/capture/stream`，PCAP 仍经 SSH 连接后端回环端口。
- [README 网络架构](README.md#网络架构) 维护 Windows/Linux 客户端、可选 Caddy、后端、Docker/veth、配置目录和 SSH 抓包通道的字符图。[HTTP/3 启用指南](docs/user/workbench-https.rst) 提供 Ubuntu 安装、同机代理、客户端根证书信任，以及从 Caddy 当前证书提取 SPKI 后使用独立 Chrome 配置验证 h3 的操作。
- 部署文档统一入口为 [开发部署与发布部署](docs/user/workbench-start.rst)，先选用途再选协议：开发部署为 Vite + Python 两终端、访问 5173、无需预先 build；发布部署分源码构建与 Linux 目录包，后端提供成品页面、默认访问 8090。HTTPS/HTTP2/HTTP3 是发布部署的可选 Caddy 入口，不能把协议与部署方式混为一层选项。
- 文档导航按“环境准备 → 部署与启动 → 快速组网 → 工作台操作”组织；目录包和 HTTPS 各自作为专项教程。保留 `workbench.html#workbench-start`、`#workbench-start-http` 旧锚点并指向新流程，README、快速开始和开发指南同步端口与命令。启动教程明确首次准备/每次启动/停止更新、Token 来源、同机代理与数据目录；区分 Vite 开发模式和后端 `--preview` 设计模式。
- 用户指南首页按任务提供入口，侧栏分为首次使用与部署、工作台操作、维护与参考、旧版命令行工具与实验。首次实验只讲 Web 操作，并明确每一步的预期结果；旧版 FRR 入门移到 `legacy-cli.rst`，OVS/VPCS/DHCP/协议章节标明旧版范围。
- 部署教程必须从获取代码开始：仓库为 `https://github.com/nanfengnan1/lwns`，推荐 HTTPS clone，说明 Code → Download ZIP、项目根目录和首次进入目录。目录安装包下载来源指向 Releases 并注明核对时的实际状态；截至 2026-10-24 无公开 Release。源码归档、程序目录包、Docker 镜像必须区分，本地 `release/` 不自动上传。维护者发布安装包后同步更新 README 与获取教程的状态和实际附件信息。
- `workbench.rst` 保留界面总览和旧的显式锚点；镜像、画布、终端分别维护在 `workbench-images.rst`、`workbench-editor.rst`、`workbench-terminal.rst`，FRR 保存恢复统一放入 `workbench-data.rst`。宿主机/客户端/设备终端位置、源码与目录包数据路径须保持明确。安装文档先讲使用者安装，构建发布说明放最后。文档主题折叠非当前分支，长表格换行，命令代码块保留原格式。
- 文档排版参考 containerlab、GNS3 与 Caddy 官方教程，沿用 Sphinx/RTD，不增加构建依赖。首页使用原生 RST 容器组成任务入口，教程按目标/前提/步骤/成功标志/下一步组织，规范见 `docs/developer/build-docs.rst`。`docs/_templates/page.html` 提供宽屏右侧页内目录，左栏仅展示章节；窄屏保留正文 `contents`。`reading.css` 统一字号、间距、表格、提示框和打印样式，`reading.js` 提供纯代码复制及滚动定位；剪贴板失败后选中代码供手动复制。静态资源本地交付，支持 file:// 与原有版本归档，保留旧显式锚点。管理命令按需选择时用对照表，不能合成一段让用户全部执行。
- 首页不静态导入 xterm 和两个管理面板：`DeviceTerminal.vue` 在首次创建标签时异步加载，`ImageManager.vue` / `CaptureManager.vue` 在首次打开时加载，之后保持挂载，保留会话、草稿和任务轮询。管理对话框挂载时同步打开状态，避免第一次点击无响应。旧分包失效时提示检查网络/导出草稿后刷新，不自动刷新页面。
- 设备/注释拖动由对应图形捕获指针，空白平移由画布捕获，并在结束/切换时释放实际捕获者；避免部署后可拖动时把设备双击重定向到 SVG，确保双击终端入口可用。

## 3. 界面与视觉设计

采用面向桌面浏览器的三栏工作台，顶部为全局导航；主体左侧是设备库，中间是拓扑画布与底部面板，右侧是属性检查器。

| 区域 | 内容与作用 |
| --- | --- |
| 顶部导航 | 草原狼头像、lwns 品牌、实验/视图/工具菜单、宿主机环境状态 |
| 左侧设备库 | 横向四类入口、双列圆形设备与独立滚动 |
| 中间工具栏 | 项目名称与重命名入口；同一操作行左侧排版/注释，右侧保存/配置/部署/清理 |
| 中间画布 | 设备、端口、veth 连线、缩放和平移、运行状态 |
| 右侧属性 | 镜像、名称、端口/IP、默认网关、启动命令、FRR 启动配置、保存单设备配置、磁盘预览、终端入口 |
| 底部面板 | 部署日志、设备终端、多设备标签、刷新状态、收起和放大 |

视觉约定：

- 采用深蓝导航、浅色工作区和蓝色交互强调；终端使用深色背景与等宽字体。
- 项目图标为草原狼头像，唯一资源为 [steppe-wolf.svg](web/src/assets/steppe-wolf.svg)，用于导航栏、登录对话框和 favicon。
- 现代化界面沿用 Vue 3，无新增 UI 组件框架依赖；渐变深蓝顶栏、浅灰设备库、内嵌圆角画布和白色属性栏形成层次；设备采用无方形卡片背景的双列圆形图标，项目名称与保存状态并排紧凑显示，工具栏使用统一线条图标。项目名称、自动对齐、连线优化、添加注释、保存与部署按钮全部在同一操作行，窄画布在行内横向滚动而不换成上下两排，空白引导按画布实际高度收紧，避免遮挡缩放工具与底部状态。`--topbar-height` 共用 62px；底部面板观察工具栏高度变化，计算上限时包含画布外边距，保持画布与面板在窗口内。
- 公共布局和样式集中在 [workbench.css](web/src/styles/workbench.css)。当前页面最小宽度为 1000px，尚未设计移动端布局。
- 用户可见的按钮、状态和提示以中文为主。设备名称、命令、接口和镜像名保留原始内容。
- 设备库默认宽 240px，只放设备：顶部横向排列路由器、交换机、PC、防火墙四个类别和数量。初始只显示分类入口；点击后进入对应子目录，其他分类的设备不渲染。子目录不显示搜索框，进入后直接用双列圆形图标展示设备，每批 60 项；子目录标题前不设返回箭头，设备图标直径 40px，紧凑间距保留双列名称和镜像标签。切换分类时重置分页与滚动，直接点击顶部类别切换；方向键及 Home/End 支持导航。刷新回到分类首页，侧栏收起/展开保留当前子目录；镜像更新保留当前类别并同步数量/卡片，不修改画布草稿。移除侧栏底部提示与镜像管理按钮，镜像管理唯一入口为顶部“工具 → 镜像管理”。
- 设备库的分类入口与设备图标共用 `domain/topology.ts` 的 `colors`：路由器蓝、交换机绿、PC 紫、防火墙橙；组件通过 `--device-color` 传给圆形背景，不在 CSS 维护另一套类型配色。设备条目外层透明、无方形卡片边框，名称/镜像位于圆形下方；悬停、选中和键盘聚焦以圆环反馈，保留未加载提示及任务操作锁。
- 镜像管理为独立对话框：左侧“我的镜像”、数量概览、搜索及已加载/待加载筛选，右侧仓库/URL、归档、Dockerfile、已有镜像四种来源或设备库设置。条目标明来源、设备类型和“仅引用 · 保留本地”；底部日志可收起，任务开始自动展开，阅读历史输出时暂停自动跟随。关闭窗口后已提交任务继续执行；窗口内键盘不触发画布快捷键。

侧边栏约定（已实现）：

- 左右两侧使用 `SidebarPanel.vue`，均可收起/展开及拖动与画布之间的竖向分隔条调整宽度；收起时保留 36px 展开入口，内容通过 `v-show` 保留，设备属性草稿和设备库子目录状态不丢失。
- 左侧宽度 200～420px，默认 240px；右侧 240～480px，默认 280px。窗口变小时按可用空间限制实际宽度，中间区域至少 460px；重新变宽时恢复首选宽度。
- 双击分隔条恢复该侧默认宽度；键盘左右键按边界移动方向微调 10px，Shift 为 40px，Home/End 调至当前最小/最大值。
- `stores/layout.ts` 将宽度和收起状态保存在 `localStorage` 的 `lwns-sidebars`；读取无效数据或存储被禁用时仍可操作。布局偏好不写入拓扑、不标记未保存、不受部署编辑锁限制。
- 拖动使用 Pointer Events 和捕获，结束、失焦或卸载时清理捕获及光标；工作区尺寸通过 ResizeObserver 更新，原有画布与终端尺寸观察继续生效。

底部面板约定：

- 拖动面板顶部的水平分隔条调整高度，双击恢复默认；聚焦分隔条后可使用方向键、Home、End。
- 默认内容区高度为 174px，最小为 96px；普通模式为画布保留至少 280px 高度，最大面板高度随窗口计算。
- 首选高度保存在浏览器 `localStorage` 的 `lwns-panel-height`，切换标签、收起和刷新后保留。
- 放大模式覆盖顶部导航以下区域，恢复后回到普通布局；布局变化必须同步终端行列数。
- 拖动使用 Pointer Events 和 pointer capture，结束或组件卸载时释放捕获、光标及事件资源。

## 4. 拓扑编辑与状态管理

- 工作台初次启动与刷新均显示干净“空白画布”，随机实验 ID、dirty=false，不自动加载默认实验或首个已保存实验。`bootstrap` 只更新目录/环境/列表，重新认证时保留当前画布与草稿。删除实验也回到干净空白；保留 `examples/basic-lab.json` 供用户显式导入，不删除任何已有用户实验来清空首页。
- `WorkbenchMenu.vue` 在顶栏提供“实验 / 视图 / 工具”菜单；`LabOpenDialog.vue` 支持刷新、按名称/ID 搜索、选择或双击打开宿主机已保存实验，失败/取消保留当前画布。`ui.labOpen` 与 `ui.menuOpen` 隔离快捷键，菜单支持方向键、Esc、Tab、焦点返回与外部点击关闭。菜单只显示操作名称、勾选和分隔线，删除按钮下方与底部的解释文字；保存范围继续在用户文档中说明。
- `useProjectFiles.ts` 统一工具栏与菜单“保存项目”、关闭项目及 JSON 导入导出。保存先提交属性草稿，再调用服务器 `/save` 保存拓扑/画布，并逐台保存运行中受支持的 FRR 配置；显示成功、失败和不支持项，不能伪报全部已保存。部署后网络变更仍须显式应用拓扑。异步操作核对 documentVersion 与当前操作，失败保留草稿。导出仍只是拓扑 JSON，完整可移植包未实现。
- “打开项目”只列出当前后端数据目录中的记录，通过 `/open` 核对并加载；“关闭项目”调用 `/close` 回收该项目的终端、凭证和抓包，成功后回到空白画布，保留服务器项目、配置和运行设备。关闭不等于清理或删除；未保存改动须确认放弃。重开可继续访问运行设备，忙碌或关闭失败保留当前画布。
- 项目创建、打开、保存、关闭和部署统一使用当前页面的相对 `/api/*`，界面显示当前连接服务器；浏览器不使用本机文件选择器代替打开远程项目，也不把后端地址硬编码成客户端 localhost。文件导入/导出仍是明确的独立操作，界面偏好继续保存在浏览器。
- “实验 → 新建项目”菜单或空画布按钮打开 `ProjectNameDialog.vue`，填写名称后调用 `POST /api/labs`，由当前 Web 后端分配独立 ID 并立即写入服务器数据目录；成功后切换画布。取消、无效输入、认证或网络失败保留当前项目。支持中文、去除首尾空白，名称非空且最长 80 字符，同名项目使用不同 ID。
- 顶部项目名称是明确的重命名入口。未保存项目只修改草稿；已保存项目调用 `POST /api/labs/{id}/rename` 立即持久化名称并更新列表，允许已部署设备继续运行。操作中禁止改名；失败保留原名称。
- 重命名只接受 `{ "name": "..." }`，不改 ID、设备配置目录、容器归属、运行状态和连接。前端不调用 `adopt`、不更换 `documentVersion`，保留终端、选中设备及属性草稿；其他未保存拓扑改动仍需单独保存。普通拓扑保存受操作锁及运行字段一致性校验，网络差异需应用拓扑。
- 点击设备卡片或拖入画布添加设备；拖动节点调整位置，拖动空白区域平移。画布提供原生横纵滚动条；普通滚轮上下平移，Shift＋滚轮左右平移，Ctrl＋滚轮向上放大、向下缩小，缩放以鼠标位置为中心，范围 25%～250%。视口变化不修改设备坐标，不标记未保存。
- `TopologyCanvas.vue` 使用滚动容器、按内容边界扩展的占位区域及 sticky SVG 视口；`scrollBounds` 包含负坐标、设备、注释与额外平移空间。滚动偏移和 `editor.view` 双向同步，拖动、缩放、适应画布及窗口变化共用同一套坐标换算。视口位置和缩放是本次查看状态，重新加载后适应拓扑；设备/注释坐标才随项目保存。
- 设备显示为紧凑圆形图标，名称放在圆形下方，悬浮显示完整名称与类型。默认直径 64；端口密集时按 `max(32, ceil(端口数 * 9 / (2π)))` 自动调整半径，32 端口最大直径 92。已移除手动拉伸手柄与尺寸属性入口。
- 项目顶部只保留一个“自动对齐”按钮，无布局方式下拉框。分别按原始 x/y 分组，每组最大坐标差不超过 24 个画布单位，向组内最左/最上坐标对齐，只微调接近的行列，不根据连接关系重排。组跨度受限，避免连续近邻合并成大组；设备圆形和名称区域可能重叠的移动会取消并重新检查。保留设备配置、端点、注释、当前缩放和视口；重复点击不漂移，无位置变化不标记未保存，设计和部署状态均适用。
- “连线优化”默认开启；`domain/canvas.ts` 按对端方向将实际端口映射到不同圆周图形插槽，直线优先，受阻时选择可行候选中较短的一折/两折路线。拖动和对齐后自动重算，不更改接口名称、端点或 veth；关闭后使用固定圆周端口与曲线。属于有界启发式，不保证复杂拓扑全局最短或无交叉；无可行候选时保留直连显示。
- “添加注释”或 T 进入放置模式，点击画布新增说明；右侧编辑多行文字、字号、文字颜色和背景，支持拖动、Delete 删除。SVG 文本插值渲染，不解释 HTML。注释与连线优化开关随拓扑保存/导入/导出；不属于设备或服务配置。
- 部署后可增删设备、网线和注释，修改端口、地址、设备属性及注释内容/样式。编辑保留为当前页面草稿，运行环境继续使用上一版已应用拓扑；网络差异显示“拓扑待应用”，点击“应用拓扑”才同步实际资源。`layoutLocked` / `locked` 只在本地操作、忙碌或 deploying/updating/destroying 阶段锁定；滚动和缩放仍可使用。拖动使用 Pointer Events 和捕获，结束、失焦、切换实验或卸载时释放。
- 已部署项目“保存项目”通过 `/save` 保存运行字段不变的视觉、注释和项目名变化，并保存受支持的运行配置，保留部署、容器和终端。旧 PUT 拓扑保存与 `POST /api/labs/{id}/layout` 保留兼容；后者仍只接受完整设备/注释 ID 集合的 id/x/y 与 optimizeLinks。网络变化使用 `POST /api/labs/{id}/update {topology,base}`，base 为已应用的完整规范化拓扑，拒绝过期覆盖。任务开始进入 updating，成功才持久化新拓扑；失败保留客户端草稿和旧拓扑，记录错误并尝试恢复，要求清理后重新部署。
- 点击两个空闲端口创建双向 veth 网线。端口最多连接一根网线，当前不允许设备连接自身。
- 单击设备查看属性；双击已部署设备打开交互终端。
- 设备和注释属性先进入草稿，应用、切换选择、保存和导出时提交。应用属性时保留拖动产生的最新坐标；无效草稿不会被静默丢弃。旧尺寸字段继续透传用于文件兼容，不影响圆形显示。
- “实验 → 删除当前实验”菜单及实验属性中均提供删除入口，共用 `DeleteLabButton.vue`。确认删除未保存实验只清空本地拓扑和属性草稿，不请求后端删除（即使导入草稿与已有文件同 ID）；已保存实验成功删除后移除列表项。删除后回到无未保存修改的“空白画布”，空白占位不显示为待删除的未保存实验；部署中、已部署或操作中禁止删除。
- 应用拓扑只增删受影响容器及 veth；name/image/kind/template/command/config 变化重建对应设备，端口/地址/网关在线同步，不变容器不重启或重载 FRR。空闲端口不会创建接口，未连端口地址和无活动接口可用的网关暂不执行。应用前提示先保存运行配置；配置目录保留并快照，不自动执行保存命令。任务会关闭本实验终端与抓包，完成后重开。新草稿设备、未应用连线不能当作运行对象操作。
- 图上端口表示接线插槽，仅已连接端口会创建 veth；未接线端口不能配置待部署 IP。
- 保留 `V` 选择、`C` 连线、`T` 注释、Delete 删除、Esc 取消当前工具等快捷键。输入框、对话框和终端的键盘事件不能触发画布快捷键。
- 运行状态轮询间隔为 4 秒；读取真实运行状态，不根据拓扑文件直接判定设备和网线可用。

Pinia 状态分工：

| Store | 职责 |
| --- | --- |
| `stores/lab.ts` | 拓扑、设备目录、环境、实验列表、部署状态与 API 操作 |
| `stores/editor.ts` | 当前选择、端口连线、视口、属性草稿和未保存状态 |
| `stores/ui.ts` | 登录/环境对话框、提示消息、日志/终端面板和收起状态 |
| `stores/layout.ts` | 左右侧边栏首选宽度、收起状态、空间约束及浏览器持久化 |
| `stores/terminals.ts` | 终端标签、活动标签、连接状态、切换实验与部署变化后的清理 |
| `stores/images.ts` | 镜像清单、流式上传进度、后台任务轮询、设置和删除、过期响应隔离 |
| `stores/captures.ts` | 抓包端点与会话、启动 URI、环境与客户端包下载、过期响应隔离 |

拓扑配置、运行状态、编辑草稿、终端连接分别管理。`documentVersion` 与运行状态版本用于拒绝旧请求结果，防止切换实验后被延迟响应覆盖，也防止旧的空闲状态解除新部署的编辑锁。

## 5. 数据与部署模型

拓扑 JSON 保持 `version: 1`，结构不依赖 Vue、Pinia 或终端组件：

```text
Topology
  version, id, name
  nodes[]
    id, name, kind, image, x, y
    template?       # 稳定的设备模板 ID；旧节点按 kind 选择默认模板
    width?, height?  # 旧矩形尺寸，仅兼容保留，圆形显示不使用
    ports[]: { name, address }
    gateway, command[], config
  links[]
    id
    a: { node, port }
    b: { node, port }
  annotations[]?   # { id, text, x, y, fontSize, color, background }
  optimizeLinks?   # 缺省 true；仅影响视觉连线
```

- `kind` 为 `router`、`switch`、`host`、`firewall`；PC 继续使用 `host`，保持旧拓扑兼容。`command` 为启动参数数组，`config` 为 FRR 启动配置文本。
- 旧 `width` / `height` 继续校验并保留，宽 96～640、高 72～640；圆形几何由端口数决定，不再读取矩形尺寸。节点名称截短显示，完整值保留。
- 可选 `annotations` 最多 100 条，独立且唯一的合法 ID；内容 1～1000 字符，坐标有限且绝对值不超过 100000，字号 12～28 的整数；颜色为六位十六进制，背景额外支持 `none`。前后端均校验，非法导入/保存不覆盖原记录；旧文件缺字段时仍可使用。
- CIDR、默认网关、镜像、端口和连线约束同时在前后端校验，后端是部署约束的最终校验方。
- 当前限制：最多 64 台设备、256 条链路、每台 1～32 个端口；单个拓扑导入上限为 1 MiB，普通 JSON 请求上限 1 MiB；`/update` 同时包含 topology/base 两份拓扑，请求体上限 2 MiB。
- 实验记录包含 `topology`、`runtime`、更新时间；保存在 `.lwns-labs/<实验ID>.json`，采用原子写入。
- 运行阶段包括 `idle`、`deploying`、`running`、`updating`、`destroying`、`error`、`degraded`。
- 部署、拓扑应用和清理使用后台任务，接口返回 202，前端轮询状态；任务受全局互斥保护。应用支持删除全部节点，保留 deployment 和空 nodes，后续可再增加设备；清理后回到 idle。
- 后端固定使用本机 Docker Unix socket，默认 `/var/run/docker.sock`；不跟随 Docker 的远程 context。
- 创建的设备使用 `--network none`，部署时根据记录的 PID 创建 veth、设置地址、网关和桥接关系。
- 容器名称为 `rov-实验ID-设备ID`，使用实验、部署和节点标签标记归属。操作前验证归属、PID 和容器运行状态。
- 部署前检查本机镜像，不自动拉取。失败时回滚本次部署；清理只操作归属明确的资源。
- 停止后端保留已部署容器；重新启动同一数据目录后可以检查与清理。容器重启或链路异常会显示需要检查。
- 在交互终端修改 FRR 后，点击“保存设备配置”写入共享目录并同步拓扑中的 `config`；清理只删除容器和网线，重新部署恢复配置。未写入磁盘的运行配置仍会丢失。

### 5.1 设备模板与适配器

- 内置模板位于 `lab_devices.py` 的 `CATALOG`，包含 `id`、`version`、`adapter`、`kind`、镜像、端口默认值、控制台显示名与命令数组，以及 `save_config` / `startup_config` 能力。
- 模板为 `frr`、`linux-bridge`、`linux-host`、`linux-firewall`；拓扑可选 `template`，旧版本 1 JSON 仍然兼容。防火墙使用通用 Linux 适配器，默认 4 个端口、FW 命名前缀和 sh 终端；镜像需自带所需工具，不自动配置防火墙规则或启用规则持久化。镜像与模板分开配置，不能通过拓扑指定宿主机路径或任意执行器。
- `ADAPTERS` 注册适配器；接口为 `prepare`、`command`、`started`、`linked`、`config_status`、`save_config`。核心管理器保留公共容器、veth 和归属处理。
- 前端按模板 ID 添加设备，根据模板能力显示保存入口，终端程序由后端模板决定。新增同类设备优先扩展模板和适配器；新增画布种类再扩展 `kind` 和图标。
- 本阶段保留 JSON 项目文件，尚未迁移 YAML 或生成 Compose。
- 新增 `device.json` 声明式设备描述、通用生命周期执行器和 `.lwns` 设备包，详见第 15 节。已安装定义由每个 `LabManager` 独立解析，内置模板继续兼容；分类不再隐式决定新设备的 FRR/bridge 行为。

### 5.2 FRR 配置持久化

```text
.lwns-labs/
  <实验ID>.json
  devices/<实验ID>/<设备ID>/
    config-meta.json
    frr/                    # RW bind mount → /etc/frr
      daemons
      frr.conf
      vtysh.conf
    backups/<时间-随机标识>/
```

- 首次部署从本机镜像读取默认文件和 FRR 用户 UID/GID，启用 bgpd/ospfd/ospf6d，初始化 integrated-vtysh-config 与可写权限；共享整个目录，后续不覆盖现有协议设置。
- `config-meta.json` 记录模板版本、UID/GID、启动文本哈希与 Web 保存时间。拓扑启动文本只有显式改变才会备份并替换磁盘配置；终端 `write memory` 不会被旧拓扑覆盖。
- 部署创建网线并配置基础地址后，校验 FRR 配置并执行 `vtysh -b`。地址和默认路由使用 `replace`，容许 FRR 启动时已恢复同一地址。
- Web 保存先校验容器归属、可写挂载与已启用的协议进程，备份后执行 `vtysh -w`，同步 `node.config` 和实验文件。多设备逐台返回成功/失败，成功结果保留；有进程缺失时拒绝覆盖。
- 旧部署无共享目录时支持导出 FRR 配置，清理重建后启用挂载；已有错误或只读挂载拒绝保存。
- 保存操作与部署/拓扑应用/清理互斥。前端只更新配置及运行状态，不调用 `adopt` 或改变 `documentVersion`，保留选择和终端；同步属性草稿，防止后续编辑覆盖保存结果。
- 配置预览受认证保护并校验路径；保存文本沿用 32768 字符上限。备份暂不自动轮转。
- 清理保留文件；删除已保存实验同时删除配置与备份，确认文案必须明确。配置以实验 ID 和设备 ID 定位，复用 ID 视为原设备。
- JSON 导出携带 Web 保存的 `frr.conf` 文本，不包含 daemons/vtysh.conf 或备份；完整迁移应复制整个数据目录。主机与交换机临时 Shell 配置尚不支持保存。

示例见 [basic-lab.json](examples/basic-lab.json)，完整操作说明见 [用户指南](docs/user/workbench.rst)。

### 5.3 镜像清单与导入（已实现）

- 源码默认清单为 `config/images.defaults.json`，首次初始化运行清单时读取，默认 FRR/VPCS 引用不触发自动下载。运行清单为 `<data-dir>/images/registry.json`，原子保存镜像引用、显示名、模板、来源、ID、大小和是否存在；删除的记录不会因重启重新播种。
- `ImageService` 在 bootstrap/主动刷新时只核对已管理条目的真实 Docker 状态，不自动纳入宿主机其他镜像。管理范围为默认清单、Web 导入/拉取/构建及通过“已有镜像”显式引用的条目；列表与设备库使用同一范围。外部删除后保留“未加载”记录，允许移出。导入结束只登记本次操作明确返回的镜像，不依据全机库存差集认领镜像。管理数据放在子目录，不参与实验 `*.json` 扫描。
- 支持仓库引用（`docker pull`）、HTTP(S) 未压缩 tar 镜像归档 URL、本地 `.tar` 归档（`docker load`）、Dockerfile 文件/文本加可选 tar/zip 构建上下文（`docker build`）。私有仓库复用后端账户 Docker 凭据；下载记录不保存 URL 查询参数。
- 镜像加载仅支持未压缩 `.tar`（已实现，替代原 XZ 自动解压方案）：上传前端及登记 API 校验 `.tar` 扩展名，任务执行前使用 `tarfile.open(..., "r:")` 只检查未压缩 tar 格式，随后原文件直接传给 `docker load --input`。URL 可不带扩展名，但下载内容遵循相同校验；压缩包改名仍会被拒绝。不依赖 pixz 等解压命令、不展开 tar 内部文件、不回退为 `docker import`；镜像清单内容由 Docker 校验。任务结束回收上传/下载临时文件。Dockerfile 的构建上下文继续独立支持 tar、tar.gz、tar.xz、zip。
- 大文件通过登记上传、二进制 PUT、提交任务三步处理，流式写盘，默认 8 GiB，可用 `--max-image-upload-gib` 调整；镜像管理 JSON 为 1 MiB，Dockerfile 为 512 KiB。构建上下文限制 16 GiB / 100000 项，拒绝路径越界、链接和特殊文件；选中的 Dockerfile 覆盖上下文根目录同名文件。
- 任务返回 202，每 2 秒轮询；记录 queued/running/success/error 和有界日志，Docker 子进程超时 60 分钟。关闭窗口不取消已提交任务，上传可取消。完成/失败回收临时文件；服务重启将未完成任务标为失败并清理 UUID 工作目录。历史任务文件暂不自动轮转，API 返回最近 30 项。
- 一次只执行一个镜像任务，启动时拒绝与正在执行的部署/清理任务并发；镜像任务期间拒绝新部署，允许清理已有设备。镜像管理只要求可访问本机 Linux Docker daemon；设计模式不能导入/删除，设备部署仍要求 root/ip/nsenter。
- 删除前重新核对归属：仅项目任务新建的标签记录 `owned_image_id`，与当前 Docker ID 一致才返回 `can_delete=true`；已有标签、默认条目、旧版本来源不明条目及纯 ID/digest 引用只能移出清单。外部替换或删除标签会撤销归属。物理删除还检查已保存实验及所有现存容器，使用非强制 `docker image rm <标签>`；失败保留管理记录。“移出清单”通过 `mode=forget` 仅移除记录及卡片，保留本地镜像、容器和已保存实验。`mode=local` 按完整引用显式纳入已有镜像，不拉取或取得删除权限。
- 旧清单读取时剔除自动发现且未设置的 `discovered` 条目；有手工名称/设备模板的旧发现条目迁移为 `local` 引用，保留配置且禁止物理删除。已导入历史条目保留，但不会推断删除归属。迁移不执行 Docker 删除；清单仍为 version 1，新增可选归属字段。设备库完全从管理记录生成，移除后刷新/重启不补回。
- 镜像管理的设备类型为路由器（`frr`）、交换机（`linux-bridge`）、PC（`linux-host`）、防火墙（`linux-firewall`）；一个镜像记录绑定一个类型，修改后卡片移动到对应分类。加载且绑定后生成卡片，“仅管理镜像”取消卡片。默认清单只绑定 FRR 与 PC，不再隐式生成交换机卡片；需要在镜像管理中设置交换机类型。动态卡片的 `id` 与基础 `template_id` 分开，前端按基础模板 ID 解析能力，节点写入基础模板 ID，保持拓扑版本 1 与适配器匹配。
- 真实模式隐藏未加载镜像；设计模式可显示仍在清单中的未加载绑定条目并标明“未加载 · 仅用于设计”，已删除记录在两种模式下均不会生成卡片。镜像清单元数据变化触发目录刷新，失败下次轮询重试，目录请求序号阻止迟到响应恢复已删条目；现有画布设备和配置保留。
- 导入镜像不会自动实现新的厂商 CLI、VPP 接入或配置保存；这些能力仍需模板/适配器，未来手动端口方案仍见第 11 节（未实现）。

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
| `GET /api/bootstrap` | 设备目录、环境、实验列表；不含默认示例 |
| `GET /api/environment` | Docker 与宿主机环境检查、本机镜像 |
| `GET /api/catalog` | 管理清单派生的设备卡片；真实模式仅返回已加载且绑定类型的条目 |
| `GET /api/images` / `POST /api/images/refresh` | 镜像与任务快照 / 主动核对 Docker 清单 |
| `POST /api/images/jobs` | 提交 pull/url/archive/build 后台任务 |
| `PUT /api/images/{id}` / `DELETE /api/images/{id}` | 更新名称/模板；提交镜像删除任务 |
| `POST /api/images/uploads` | 登记上传文件名、大小和 archive/context 类型 |
| `PUT /api/images/uploads/{id}` / `DELETE /api/images/uploads/{id}` | 二进制流上传 / 回收未使用上传 |
| `GET /api/capture/capabilities` / `GET /api/capture/client` | 抓包能力 / 本地启动器 ZIP 下载 |
| `GET/POST /api/labs/{id}/captures` | 抓包会话列表 / 创建（link、side、filter、snaplen） |
| `DELETE /api/labs/{id}/captures/{session}` | 停止抓包会话 |
| `POST /api/capture/claim` | 本地启动器兑换单次启动凭证，无长期 Web 令牌 |
| `POST /api/capture/client-report` | 独立单次凭证回传本地启动结果、手动认证模式和输出路径；不能启动流 |
| `POST /api/capture/stream` | SSH 转发程序使用单次流凭证；仅回环来源，返回 PCAP |
| `GET /api/labs` | 当前服务器项目列表 |
| `POST /api/labs` | `{name}` 创建空项目，服务器分配 ID，立即持久化并返回 201 LabRecord |
| `POST /api/labs/{id}/open` | `{}` 打开服务器项目并核对运行状态 |
| `POST /api/labs/{id}/save` | `{topology}` 保存项目及支持的设备配置；返回 record、逐设备 results、topology_saved |
| `POST /api/labs/{id}/close` | `{}` 关闭项目相关终端/抓包；保留项目文件与运行设备 |
| `GET /api/labs/{id}` | 拓扑与实际运行状态 |
| `PUT /api/labs/{id}` | 保存拓扑 |
| `DELETE /api/labs/{id}` | 删除已清理的实验记录 |
| `POST /api/labs/{id}/deploy` | 开始部署 |
| `POST /api/labs/{id}/update` | `{topology,base}` 乐观校验后增量应用，成功才保存新拓扑，关闭本实验终端和抓包 |
| `POST /api/labs/{id}/layout` | 兼容旧客户端的坐标和连线显示保存 |
| `POST /api/labs/{id}/rename` | 仅接受 `name`；保存显示名称，返回 `id` / `name`，不修改部署与配置 |
| `POST /api/labs/{id}/destroy` | 开始清理并关闭关联终端 |
| `GET /api/labs/{id}/configs` | 所有设备的配置持久化状态 |
| `GET /api/labs/{id}/configs/{node}` | 单设备磁盘配置、共享路径及更新时间 |
| `POST /api/labs/{id}/configs` | `{}` 保存全部支持设备；`{"node":"r1"}` 保存指定设备；返回逐台结果和 runtime |
| `POST /api/labs/{id}/terminals` | 申请终端连接凭证 |
| `WS /api/terminal` | 交互式终端 |
| `POST /api/labs/{id}/exec` | 保留的单次命令 API，等待上限 15 秒 |

- 启动时随机生成访问令牌，也可通过 `LWNS_TOKEN` 设置。前端从输入框、URL fragment 或 `sessionStorage` 读取；从 fragment 读取后移除 URL 中的令牌。
- 管理类 HTTP API 使用 Bearer 认证并校验 Origin；WebSocket 需要同源 Origin 和一次性凭证。抓包 claim/client-report/stream 使用各自短期单次凭证代替长期令牌，stream 额外限制回环来源，详见第 12 节。
- Vite 同时代理 HTTP 和 WebSocket，保留浏览器原始 Host/Origin，后端按规范化的协议、主机和有效端口验证同源；不放开任意 CORS，也不把外站 Origin 改写成可信来源。HTTPS 经同机 Caddy 时后端必须显式使用 `--trusted-proxy 127.0.0.1`，默认不信任任意转发头。
- 静态服务只开放构建首页和 `assets` 资源，不开放源代码、实验文件或整个项目目录。
- `lab_static.py` 使用 StaticFiles 流式读取及 ETag/Last-Modified，支持 HEAD/Range；哈希资源缓存一年且 immutable，首页及非哈希静态资源 no-cache，API/缺失资源继续 no-store。静态资源按需 gzip（至少 1 KiB、级别 6），使用弱 ETag 和 Vary，Range、API、WebSocket、PCAP 不经过压缩。
- `--trusted-proxy` 只接受明确 IP/CIDR、可重复指定，默认关闭且不接受 `*`。Caddy 保持流式上传、按后端大小限制处理镜像，配置重载为长连接保留宽限期。
- 用户输入经容器终端执行；宿主机命令使用参数数组，不拼接成宿主机 Shell 命令。

## 8. 关键代码位置

| 文件 | 职责 |
| --- | --- |
| [App.vue](web/src/App.vue) | 页面组合、认证初始化、状态轮询、全局快捷键 |
| [DeviceLibrary.vue](web/src/components/DeviceLibrary.vue) | 设备分类导航、分页、点击/拖入画布 |
| [ImageManager.vue](web/src/components/ImageManager.vue) | 镜像清单、导入/构建/设置、上传进度及任务日志 |
| [CaptureManager.vue](web/src/components/CaptureManager.vue) | 连线抓包、端点/BPF/长度选择、会话状态、停止及本地安装说明 |
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
| [lab_static.py](script/python/lab_static.py) | 静态文件传输、条件请求、缓存及 gzip |
| [Caddyfile](config/Caddyfile) | 可选 HTTPS / HTTP/2 / HTTP/3 入口及抓包通道隔离 |
| [lab_core.py](script/python/lab_core.py) | 实验存储、Docker/veth 生命周期和归属检查 |
| [lab_updates.py](script/python/lab_updates.py) | 已部署拓扑差异、增量应用、失败恢复与配置快照 |
| [lab_devices.py](script/python/lab_devices.py) | 模板注册、生命周期适配器和 FRR 配置共享/保存/备份 |
| [lab_images.py](script/python/lab_images.py) | 镜像清单持久化、核对、流式上传和后台任务 |
| [lab_capture.py](script/python/lab_capture.py) | 一次性凭证、tcpdump 子进程、PCAP 流与会话清理 |
| [launcher.py](clients/capture/launcher.py) | Windows/Linux 本地协议入口、连接配置与 Wireshark 参数生成 |
| [remote_relay.py](clients/capture/remote_relay.py) | SSH 普通用户运行的固定转发程序，回环流 → stdout |
| [images.defaults.json](config/images.defaults.json) | 初始默认镜像管理清单 |
| [SaveConfigButton.vue](web/src/components/SaveConfigButton.vue) | 单台或全部设备保存入口 |
| [DeviceConfigPanel.vue](web/src/components/DeviceConfigPanel.vue) | 配置持久化状态与磁盘预览 |
| [lab_terminal.py](script/python/lab_terminal.py) | 凭证、PTY、数据转发与会话回收 |

## 9. 构建、启动与开发

用户文档已补充“Python + Vite 两终端却访问 HTTPS”导致新建项目被判跨站的完整案例：`docs/user/workbench-start.rst` 的 `workbench-origin-error` 锚点是统一排错入口，HTTPS 教程与首次实验交叉引用。启动说明必须明确 HTTP 5173 使用 Vite、HTTPS 使用 Caddy 与 web/dist、手工后端的 `--trusted-proxy 127.0.0.1`、build 时机及本次 Token；systemd 的参数和环境文件不会自动应用于手工命令。维护时保留两种入口和服务管理方式的区别。

以下 Linux 命令均在项目根目录执行。完整前端开发环境建议使用 Node.js 24；具体版本约束以 `web/package.json` 和锁文件为准。完整步骤统一在 [部署与启动](docs/user/workbench-start.rst)，开发部署不要求预先 build。

```bash
# 源码首次安装依赖
npm --prefix web ci --include=optional

# 安装后端依赖
python3 -m venv .venv
.venv/bin/python -m pip install -r script/python/requirements.txt

# 开发部署：终端一启动后端
sudo .venv/bin/python script/python/lab_server.py --port 8090
```

另一个终端执行 `npm --prefix web run dev -- --host 0.0.0.0`，浏览器访问 `http://宿主机IP:5173`，输入后端的令牌。真实设备操作需要 Linux root、Docker CLI、本机 Docker daemon、`ip` 和 `nsenter`。

```bash
# 源码发布部署：首次或前端更新时 build，日常只运行后端
npm --prefix web run build
sudo .venv/bin/python script/python/lab_server.py --host 0.0.0.0 --port 8090
```

源码发布访问 `http://宿主机IP:8090`，不运行 Vite。目录包发布按安装教程由 systemd 启动。源码后端加 `--preview` 可仅设计拓扑；这与是否使用 Vite 无关。

- 开发默认地址为 `http://127.0.0.1:5173`。通过 `web/.env.local` 的 `LWNS_API_TARGET` 指定后端，默认 `http://127.0.0.1:8090`。
- 前端构建输出为 `web/dist`，可以跨平台复制；仅运行生产后端不需要 Node.js。
- Windows 设计模式使用独立虚拟环境及 `.venv\Scripts\python.exe` 安装依赖并启动。
- Windows 与 Linux 不能共用 `node_modules` 或 `.venv`。通过 Samba 共享代码时，应在实际运行环境安装依赖；不要在 Windows 安装依赖覆盖正在供 Linux 使用的目录。
- 遇到 Rolldown 原生模块缺失，在实际运行 Vite 的系统执行 `npm --prefix web ci --include=optional`，保留锁文件。`web/scripts/check-native.mjs` 会在开发和构建前检查原生绑定。
- `.lwns-labs`、`.venv`、`web/node_modules`、`web/dist` 和本地环境文件已被 Git 忽略。
- 更新后端代码后需要重启服务；更新生产前端代码后需要重新构建。

## 10. 验证与后续修改约定

2026-10-25 远程项目生命周期与来源校验验收：

- 新建/打开/保存/关闭和部署均使用当前页面同源 `/api`，创建由服务器分配 ID 并立即保存。统一保存包含拓扑/画布和受支持 FRR 运行配置，逐设备区分成功、失败、不支持；关闭回收服务端终端和抓包，项目、配置及运行设备保留。
- 实际部署问题定位为 Caddy HTTPS 转发到手工启动的 8090 后端，该进程缺少 `--trusted-proxy`，导致 HTTPS Origin 被按 HTTP 校验。已切回现有 `lwns-web.service`，使用相同数据目录及 `/etc/lwns/web.env` 中的固定 Token，显式信任同机代理 `127.0.0.1`。前端改为保留 Host/Origin 的 Vite 代理；这是一致性简化，不将未证实的 Vite 请求头修改作为根因。
- 前端 122 项单测、类型检查、格式检查与生产构建通过。Python 全量 145 项中 139 项通过、6 项显式集成测试跳过；随后独立启用并通过真实 FRR/veth 配置集成，验证新 `/save`、`/close`、`/open`，FRR 成功/PC 不支持提示、容器 ID/PID 与 deployment 保留，清理重建恢复配置/布局及 ping。
- Chromium 对隔离后端直连和 Vite 入口分别通过 8 组项目生命周期检查；部署画布 18 组、侧栏/中文命名 10 组及菜单回归通过。新建即远端可见，创建/保存/打开/关闭失败保留草稿，刷新重开保持部署；所有 API 请求同当前页面 origin。`check_proxy_websocket.cjs` 验证同源 WS 握手 101 后拒绝无效凭证，外站 WS 握手 403；未创建测试外的终端。
- Sphinx 严格构建通过。上线后通过实际 Caddy HTTPS 完成临时项目创建/打开/保存/关闭/删除，并检查 5173 API、外站 Origin 403；验收前后已有项目文件哈希和运行容器集合不变。测试使用隔离数据目录和带归属的临时设备，测试项目与容器已清理。
- 新验收入口为 `tests/test_project_lifecycle.py`、`web/tests/remote-projects.test.ts`、`tests/check_remote_projects.cjs`、`tests/check_proxy_websocket.cjs`；完整可移植项目包仍未实现，后续加入的通用设备配置保存见第 15 节。

加载优化及代理部署见 [HTTPS 与证书指南](docs/user/workbench-https.rst)：默认 Caddy 内部 CA 自动续期，也支持 mkcert 手动证书；每台客户端信任相同根证书，证书包含实际访问 IP/域名。Chrome/Chromium 对 QUIC 的自定义 CA 限制需要独立验证；HTTPS 成功或 Alt-Svc 并不能证明实际使用 h3。证书和私钥不提交，项目忽略 `.lwns-tls/`。

根据改动运行相应检查：

```bash
npm --prefix web run format:check
npm --prefix web run typecheck
npm --prefix web test
npm --prefix web run build

.venv/bin/python -m pip install -r tests/requirements.txt
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v

# 显式启用真实 Docker 终端测试：创建独立测试容器，结束时清理
LWNS_DOCKER_TESTS=1 .venv/bin/python -m unittest discover -s tests -p 'test_terminal.py' -v

# 显式启用真实 FRR/veth 配置恢复验证，需要 root；结束时清理独立测试设备
sudo env LWNS_CONFIG_DOCKER_TESTS=1 .venv/bin/python -m unittest discover -s tests -p 'test_config_docker.py' -v
```

- [check_workbench.cjs](tests/check_workbench.cjs)：Chromium 中验证圆形设备、单按钮临近行列对齐及视口保持、最近端点连线、注释编辑/拖动/样式/删除及 JSON 往返，也回归设备编辑、连线和底部面板；使用独立设计模式数据目录。
- `web/tests/canvas.test.ts`：旧尺寸兼容、32 端口、最近方向、平行连线、障碍绕行、循环/不连通图的布局、注释边界与草稿保护；`tests/test_lab.py` 验证注释字段校验及保存/重启恢复、失败不覆盖原文件。原设备手动拉伸测试已替换为圆形与布局测试。
- `tests/check_canvas_navigation.cjs`：真实 Chromium 验证两根原生滚动条、滚轮与 Ctrl/Shift 修饰键、鼠标缩放锚点、部署后移动/对齐/保存、注释增改删、设备与连线草稿应用、运行属性修改、应用期间编辑锁和刷新恢复；使用 `tests/serve_canvas_fixture.py` 的隔离 ImageHost/FakeHost 部署，不创建真实容器。`web/tests/workbench.test.ts` 与 `tests/test_lab.py` 覆盖布局保存白名单、运行状态保留、失败草稿及忙碌保护；`canvas.test.ts` 覆盖不同缩放下的滚动边界。
- `tests/test_topology_update.py`：16 项增量更新单测，覆盖设备与连线增删、属性重建/地址同步、保留不变容器、归属校验、空部署及失败恢复。`tests/test_topology_update_api.py`：5 项 API 测试，覆盖认证/Origin、请求体限制、基础版本校验、相关会话关闭及服务退出时等待任务。
- `web/tests/layout.test.ts` / `web/tests/project-name.test.ts`：侧边栏边界、窗口变窄、存储恢复/损坏/禁用、命名校验、保存失败、运行中改名保留终端和属性草稿。
- `tests/check_library_groups.cjs` + `tests/serve_library_fixture.py`：200 条模拟镜像下的横向分类入口、单分类子目录、双列设备卡片、无搜索框及返回按钮、分类切换/键盘导航、分批显示、固定分类栏与窄窗口布局、默认镜像删除同步、防火墙导入、修改类型/解绑和刷新恢复；不执行真实 Docker。`test_images.py` / `images.test.ts` 覆盖默认记录删除后重启不补回、删除失败保留、能力解析、目录刷新失败重试与旧响应拒绝。
- `tests/test_lab.py` 新增改名持久化、认证/Origin/参数校验、忙碌拒绝及运行中只修改名称的用例；`tests/check_sidebar_projects.cjs` 在 Chromium 验证实际拖动、收起、键盘、刷新、取消和中文项目命名。
- 2026-10-25 菜单与界面验收：91 项前端单元测试通过，114 项 Python 测试中 108 项通过、6 项需显式开启的集成用例跳过。Chromium 通过主工作台、菜单键盘/焦点/401重认证、中文项目与侧栏、FakeHost 部署布局和 200 条镜像设备库回归；1000×768 与 1440 宽窗口无整页溢出。生产构建无大分包警告，主 JS 约 167 kB，终端继续按需加载；文档严格构建与内部链接检查通过。验收使用隔离设计模式/FakeHost，未启动正式工作台服务、未操作用户容器。
- 2026-10-25 设备库导航改版验收：构建及 91 项前端单元测试通过；Chromium 验证四类横向入口、双列子目录、分类内搜索与分页、返回/方向键导航、镜像更新和删除同步、设备拖入、侧栏拉伸、菜单、部署后画布操作及 1000×768 布局。画布引导按可用高度收紧，面板最大高度包含画布外边距；没有新增 UI 框架依赖。验证使用隔离设计模式与模拟镜像服务，正式服务保持停止。
- 2026-10-25 操作栏精简（A/B/C 并行）：删除设备子目录搜索框并收紧卡片顶部留白；排版、对齐、连线优化、注释与保存/部署合为同一操作行，窄画布内部横向滚动，焦点控件完整滚入视野；菜单删除所有辅助说明。面板只统计外层工具栏高度，键盘调整前重测上限。生产构建、91 项前端单元测试、主工作台/设备库/菜单/部署画布浏览器回归通过；另检查同排控件高度、1000×768 横向滚动与 Tab 可达性。真实 Docker 导入用例未执行，正式服务保持停止。
- 2026-10-25 单行工具栏：进一步将项目名称、保存状态与所有排版/保存/部署控件合为同一横向滚动行；去掉独立项目图标与重复排版标签，保留连线优化开启/关闭可见文字、长名称省略及完整 title。1440 宽默认布局工具栏实测 51px。构建、格式检查、主工作台回归及单行几何检查通过；验证长中文名称、FRR 条件按钮、1000×768 行内滚动/Tab可达性和面板最大高度。正式服务保持停止。
- 2026-10-25 设备库圆形图标：分类入口和设备条目统一圆形类型色背景，设备图标直径 60px，移除方形白底卡片。配色直接复用画布 `colors`；深蓝线条在四种背景上保持清晰，选中/悬停/键盘聚焦用圆环提示。构建、格式及主工作台/设备库浏览器回归通过；实际核对四类导航颜色、设备背景与画布类型色一致、无方形底、200px 侧栏焦点环完整和页面无溢出。正式服务保持停止。
- 2026-10-25 临近行列自动对齐：去掉智能分层等模式下拉框，只保留“自动对齐”。24 单位内按行列吸附、跳过碰撞、保留视口且重复点击不漂移。96 项前端单测、类型检查/构建、格式检查及工作台/部署布局浏览器回归通过；同步用户与开发文档及界面截图。正式服务保持停止。
- 2026-10-25 设备库紧凑化：删除子分类标题前的返回箭头，直接通过顶部类别切换；设备圆形从 60px 缩至 40px，内部 SVG 25px，卡片间距 4px 并收紧上下留白。更新文档及总览截图。构建、格式和设备库浏览器回归通过，核对 200 条模拟镜像分页、分类键盘切换及 1000px 窗口无溢出；正式服务保持停止。
- 2026-10-25 部署后编辑拓扑：编辑设备/端口/地址/连线形成草稿，显式“应用拓扑”执行增量任务；纯布局和注释直接保存，不变容器保留，错误保留草稿并提示清理。Chromium 模拟部署回归验证增设备接线、地址修改、更新中编辑锁、终端可用性、注释增删、删除设备与网线、刷新恢复及空部署再次添加；后端均使用 ImageHost/FakeHost，未执行真实 Docker。用户与开发文档同步说明保存和应用区别、设备重建、会话断开及运行配置备份。前端 111 项通过；Python 共 135 项，其中 129 项通过、6 项需显式启用的真实 Docker 测试跳过；主工作台和运行中画布浏览器回归全部通过。真实 Docker 和正式服务未操作。
- [check_terminal.cjs](tests/check_terminal.cjs)：验证真实浏览器输入、FRR 配置、路由器 Shell、多标签、ping/Ctrl+C、尺寸同步、放大、重连和关闭。
- `web/tests/lazy-panels.test.ts` 验证管理面板按需挂载及保留；终端、镜像管理、抓包浏览器检查增加首页无对应分包、首次打开、关闭重开状态及隐藏时抓包轮询断言。
- `tests/test_web_delivery.py` 覆盖 gzip/identity/q=0、缓存/304、HTML 更新、HEAD/Range、路径边界、可信代理与 HTTP/WS Origin。`tests/check_caddy.py --caddy <binary> --http3` 使用隔离端口/CA 验证真实 H2/H3、gzip/304、流式上传、WSS 和 PCAP 拦截；仅测试环境需额外 httpx[http2]/aioquic，运行产品不依赖它们，不安装系统信任。
- 2026-10-24 加载与代理验证：生产构建无大分包警告，主 JS 约 158 kB（gzip 报告约 59 kB），终端约 335 kB 按需加载；78 项前端测试通过，107 项 Python 测试中 101 项通过/6 项显式集成用例跳过。另行通过真实 Docker 终端 Chromium 检查、镜像管理/抓包/画布浏览器检查、真实 Caddy HTTP/2 与 aioquic HTTP/3、流式上传及 WSS 校验；Sphinx 严格构建通过。自定义 CA 在浏览器中的 QUIC 协商仍按客户端策略验收。
- 2026-10-24 内网部署验收：`10.8.126.103` 已使用 Caddy 和 `lwns-web.service` 开机启动，后端监听 `127.0.0.1:8090`，保留原实验数据；Windows 信任服务端实际 CA 后，普通 HTTPS 和 HTTP/2 验证通过。独立 Chrome 配置使用经 CA 校验的当前证书 SPKI，页面、静态资源和认证 API 实测协议均为 `h3`，环境接口报告可部署。内网 CA 的普通浏览器窗口仍可能使用 HTTP/2；令牌及客户端启动参数保存在受限本地目录，不提交版本库。
- [serve_terminal_fixture.py](tests/serve_terminal_fixture.py)：为浏览器测试创建独立 Docker 设备，退出时清理；测试用的环境替换不能复制到生产入口。
- Docker 终端测试不验证 veth 数据平面，真实拓扑仍需按照用户指南检查跨设备连通性和清理结果。
- `test_configs.py` / `web/tests/configs.test.ts` 覆盖备份、恢复、旧容器导出、部分失败、归属和挂载校验、终端保留、草稿同步、过期响应。
- `test_config_docker.py` 验证真实 FRR 保存 API、清理重建、OSPF/Loopback 恢复、终端 write memory 保留和 veth ping；`serve_config_fixture.py` + `check_configs.cjs` 验证浏览器终端输入、单台/全部保存、预览与清理后恢复。
- `test_images.py` / `web/tests/images.test.ts` 覆盖镜像持久化、模板绑定、引用保护、上传认证与大小/解压边界、任务互斥及旧响应隔离；`LWNS_IMAGE_DOCKER_TESTS=1` 启用 `test_images_docker.py` 的真实构建/加载/下载/本机仓库拉取/删除（需已有 `registry:2`）。`serve_image_fixture.py --large-library` + `check_images.cjs` 验证长列表和真实浏览器镜像流程，使用独立临时数据及标签。
- 保持 `version: 1` 拓扑兼容、组件职责、状态隔离及资源生命周期；新增设备类型时同步前端类型、模板、展示和后端部署逻辑。
- 修改终端时同时检查输入/输出、尺寸、连接认证、断开、重连和清理；保留终端键盘与画布快捷键之间的隔离。
- 修改布局或品牌时保持草原狼头像、三栏工作台及可调整底部面板的设计，除非用户明确要求变更。
- 避免覆盖工作区已有修改；验证使用独立实验数据和测试设备，按记录归属清理资源。

更多细节见 [用户指南](docs/user/workbench.rst) 和 [开发指南](docs/developer/workbench.rst)。

## 11. 手动 CLI 配置、端口发现与动态接线方案（未实现）

**状态：未实现，仅记录 2026-10-23 的讨论方案。本节中的界面、端口发现、在线接线和 VPP 接入能力均为规划，不能作为当前功能使用说明；本次只更新文档。**

### 11.1 目标与职责

允许用户先启动设备，通过 Web Shell / 原生 CLI 手动创建接口和配置业务，再由 Web 发现可连接端口并在画布接线。用户负责设备内部业务配置，平台负责设备运行、端口登记、网线、状态核对及资源归属。

中间层优先收缩为“端口发现与连接管理”：不要求统一翻译所有设备 CLI，也不要求先实现完整的网络控制器。VPP、其他路由器的设备相关代码，初期集中在端口识别、接入方式及必要的恢复钩子。

目标交互流程：

```text
Web 添加并启动设备
    → 用户打开 Shell / 设备 CLI
    → 手动创建接口
    → Web 刷新接口列表
    → 用户将可连接接口登记为画布端口
    → 选择其他设备端口并连接
    → 平台验证实际链路与状态
```

### 11.2 接口显示与可连接性

“被发现的接口”与“可连接的端口”需要分开。平台应显示接口类型、状态、占用情况和可用的连接方式；发现接口不等于自动接管或允许接线。

| 接口形式 | 规划中的处理方式 |
| --- | --- |
| Linux veth pair | 已有两端互为固定对端；可使用明确预留的对端，不能把两个任意已有接口直接重新配成一对 veth |
| VPP TAP 与对应 Linux TAP 端 | 可将 Linux TAP 端登记为外接端口，通过专用接续结构连接网线 |
| VPP AF_PACKET host-interface | 绑定已有 Linux 接口，要求先准备好对应接口；记录 VPP 与 Linux 接口之间的映射 |
| VPP LCP pair | 用于 VPP 与 Linux 控制面的配对，应单独识别，不自动作为普通数据面接线端口 |
| Loopback、TUN、未支持的内部接口 | 可按能力展示；不默认允许接入以太网 veth 网线 |

Linux 接口可通过容器网络命名空间中的 `ip -j -d link` 等信息发现；需要显示 VPP 内部接口时再增加轻量查询。端口记录应包含稳定的逻辑 ID、实际端点位置、连接方式、归属与当前部署标识，不能只依赖可能在重建后变化的 PID 或接口索引。

### 11.3 模式 A：Web 创建 veth，用户手动接入数据面（未实现）

保持容器之间一条网线对应一对直接连接的 veth。Web 准备设备和网线后，用户通过 CLI 将 Linux 端口接入 VPP，再配置地址和路由。

```text
VPP host-eth0 ← AF_PACKET → 容器 A 的 eth0
                                   ║
                                veth pair
                                   ║
                            容器 B 的 eth0
```

在支持 AF_PACKET 的 VPP 镜像中，网线就绪后可手动执行：

```bash
vppctl create host-interface name eth0
vppctl set interface state host-eth0 up
```

此模式的接线结构接近现有实现，但当前项目尚未提供 VPP 模板、相应状态映射和在线接线流程。VPP 的业务 IP 应由用户配置到正确的数据面接口；不能沿用核心逻辑自动给 Linux 接口配置相同业务地址。

### 11.4 模式 B：用户先创建 TAP，Web 发现后接线（未实现）

用户在 VPP 内创建 TAP，容器 Linux 网络命名空间中出现对应接口，例如 `lab0`。Web 发现并登记该接口后，平台为其准备专用的接续结构，与另一设备连接。

```text
容器 A：VPP TAP ↔ Linux TAP lab0 ↔ 端口专用 bridge ↔ veth A
                                                              ║
                                                           veth pair
                                                              ║
容器 B：Linux 网络栈                              ↔ veth B
```

- 如果对端也是已经创建的 TAP 端口，对端同样需要相应的接续结构。
- 每个接线端口独立管理 bridge，不能把同一路由器的多个端口默认加入一个 bridge，避免意外的二层互通。
- 容器之间仍使用 veth，但增加容器内的 bridge 接续层；这与当前直接 veth 模型不同，需要单独验证功能及性能。
- 接线前检查接口类型、当前 master、使用状态和部署归属；有冲突时应报告，不能直接覆盖已有关系。
- 模板需满足创建 TAP 和 bridge 所需的容器设备与权限；具体镜像支持范围在实现时确认。

### 11.5 中间层与现有代码的调整范围（未实现）

拟提供五类能力：

1. **发现接口**：读取实际接口，区分 Linux 端点与设备内部接口，支持用户主动刷新。
2. **登记端口**：将可连接接口绑定到画布端口，保存类型、端点映射和连接方式。
3. **连接与断开**：创建、移除平台管理的 veth，按连接方式管理专用 bridge 等资源。
4. **状态核对**：检查接口是否仍存在、连接是否有效，接口删除或容器重启后明确报告失效状态。
5. **资源归属**：区分用户创建的接口与平台创建的网线，断线时保留用户接口；仅清理归属明确的平台资源。

与当前实现的差异：

- 当前部署将容器创建、veth 和初始配置合在一次任务中；目标流程需要拆分设备启动与接线操作。
- 当前支持已部署容器/veth 拓扑的显式增量应用；目标 VPP/TAP 流程仍需受控的运行中端口登记、接口发现和连接适配，不能直接复用普通 veth 路径。
- 当前端口主要来自拓扑 JSON，尚无实际接口发现及导入画布端口的能力。
- 当前链路核对假定两端直接为 veth 对端；模式 B 需要按连接类型验证 TAP、bridge 和 veth 之间的关系。
- 新操作仍需互斥、归属校验、失败结果记录和必要的回滚；接口发现结果不能代替执行前的再次核对。

### 11.6 保存与恢复边界（未实现）

- 保存端口映射和网线关系，不代表保存了用户手动创建接口的命令或完整设备配置。
- 用户创建的 VPP 接口要在清理后恢复，仍需对应的启动配置或恢复脚本；不自动将终端历史当作可重放配置。
- 模式 A 的恢复顺序拟为：启动设备 → 创建 veth → 接入 VPP → 加载业务配置 → 验证。
- 模式 B 的恢复顺序拟为：启动设备并恢复 TAP → 重新发现/匹配端口 → 恢复接续结构和网线 → 验证。
- 缺少恢复脚本、接口未出现或映射有歧义时，显示待处理/恢复失败，不伪报设备已完整恢复。
- 现有 FRR 保存能力保持第 5.2 节所述范围；本方案不代表 VPCS 或 VPP 已支持运行配置保存。

### 11.7 建议实施顺序与验收（均未实施）

建议先验证模式 A，复用直接 veth 接线；再增加模式 B，实现“手动创建 TAP → Web 发现 → 登记端口 → 在线接线”。实现阶段再确定接口协议、数据字段及兼容迁移方式。

验收应包含：手动创建后发现、连接后双向通信、断开后保留用户接口、多端口隔离、接口删除/容器重启后的失效检测、接线失败回滚，以及具备恢复脚本时的清理重建恢复。

技术参考：[VPP 接口创建](https://docs.fd.io/vpp/21.10.0/reference/cmdreference/interface/create_interface.html)、[VPP TAP CLI](https://s3-docs.fd.io/vpp/26.06/cli-reference/clis/clicmd_src_plugins_tap.html)、[VPP Linux Control Plane](https://docs.fd.io/vpp/25.02/developer/plugins/lcp.html)。命令与插件能力以实际镜像版本为准。

## 12. 连线抓包与本地 Wireshark（已实现，Windows 抓包验证通过）

状态：服务端、Web 入口、Windows/Linux 本地启动器与安装脚本已实现；真实 veth 两端抓包、普通用户转发及断线回收已验证。Windows 独立 exe 已构建并更新本机安装。初版桌面测试曾被自动审批拒绝；本次已通过真实浏览器的布局、认证提示、路径显示、关闭重开及停止检查，另使用 Windows Wireshark 4.2.6 图形程序、已有 Profile（未额外指定私钥）经 sshdump/SSH 抓取隔离实验中的 6 个 ICMP 报文，确认本地 pcapng 可读且路径回报一致。测试分别覆盖浏览器界面及原生 GUI/SSH 链路；浏览器外部协议确认仍需用户操作，Linux 桌面完整链路仍需目标环境验收。

用户先点击已部署连线，再选择 a/b 端点、BPF 过滤条件和抓包长度，启动本地 Windows/Linux Wireshark。设备镜像无需 SSH 或 tcpdump；抓取对象为当前 Docker/veth 网络命名空间中的接口。VPP 内部/DPDK 接口抓包不属于本阶段。

```text
Web 连线属性 → 后端创建抓包会话 → lwns://capture（短期启动凭证）
  → 本地启动器 → 本机 Wireshark + sshdump → SSH 普通用户登录 Docker 宿主机
  → Python 标准库转发程序 → 127.0.0.1 上的后端单次凭证流接口
  → root 后端 nsenter -n + 宿主机 tcpdump → PCAP 经原路径返回 Wireshark
```

- 本地首次配置 Wireshark 路径、SSH 主机/端口/用户名及已有 Wireshark Profile；支持可选私钥路径。用户名、密码、私钥和密钥口令不进入拓扑、Web 后端或协议 URL。密码与口令由 Wireshark 的 SSH 接口配置处理，其存储策略遵循 Wireshark；未配置凭据可先打开 Wireshark 配置后手动开始，配置好密钥/agent/Profile 后支持自动开始。
- Windows 注册当前用户 `lwns` URL 协议，Linux 注册 `.desktop`/`x-scheme-handler/lwns`。启动器仅信任用户确认的后端 origin，URL 参数不能作为本地命令执行。SSH 主机来自本地连接配置，避免 URL 任意指定登录目标。保留现有 Wireshark Profile，使用进程级参数覆盖抓包命令，不为每条连线永久修改配置。
- Web 使用原有 Bearer/Origin 认证创建、查询和停止会话。启动凭证短期、一次性兑换为独立流凭证；不在启动 URL 放长期 Web 令牌。流接口只接受回环地址连接及单次流凭证，SSH 用户只转发二进制数据，无须 sudo 或容器权限。两类凭证都绑定已核对的实验、部署、容器和接口。
- 后端重新读取 Docker 状态与 veth alias/对端索引，拒绝容器替换、外部重启、接口失效和部署/应用/清理期间抓包；捕获开始及运行中均复查。BPF 作为 tcpdump 参数传递，不通过 shell；标准输出仅包含 PCAP，错误信息另行记录。
- 后端管理 tcpdump 生命周期和会话状态，收到 PCAP 文件头才标记正在抓包；单纯协议唤起不表示成功。停止、连接断开、清理实验或后端退出均回收自己的子进程。会话和凭证仅在内存中保存，后端重启不恢复抓包；新版启动器指定本机独立目录中的 `capture.pcapng`，由 Wireshark 自动写入；后端不保存抓包副本。
- Web 使用“准备抓包 → 点击打开本机 Wireshark”两步流程，避免异步自动跳转被浏览器拦截；同端点待连接期间禁止重复创建。提供安装说明、可再次点击的启动链接及 `lwns://configure` 本地设置入口，处理浏览器外部应用确认与未安装情况。第一版支持一个会话抓一端，分别启动会话可观察两端；支持长度/BPF 和并发上限，SSH/磁盘/本机处理速度仍可能导致丢包。

验收包括认证与过期/重放拒绝、容器/接口归属核对、有效/无效 BPF、PCAP 流、停止与断线清理、Windows/Linux 参数生成和协议安装、真实 SSH → sshdump 抓到 veth 上的 ARP/ICMP，以及原有画布回归。

实现细节与验证入口：

- API、文件分工见第 7/8 节。启动/流凭证各 5 分钟；同时最多 8 个会话，历史最多保留 50 项，单会话最长 60 分钟。tcpdump stderr 最多 16 KiB，流读取块最多 64 KiB。
- `CaptureService` 通过网络命名空间 FD 启动 tcpdump，开始前重新核对；每 3 秒复查目标。BPF 在 `--` 后作为独立参数传递。PCAP 文件头校验通过才标记 running，清理/停止关闭自己的进程组。
- Windows 安装器注册 HKCU 用户级协议，独立版可由 PyInstaller 构建；Linux 安装器注册用户级 desktop entry。首次新后端会弹本地配置，保存非秘密连接信息。密码/密钥口令在 Wireshark 中输入；未保存认证时取消“自动开始”，在 Wireshark SSH 接口配置后手动开始。
- 启动器检测接口名及偏好前缀（例如 `sshdump.exe` / `sshdump_exe`），使用参数数组启动程序；远端仅执行本地包内固定的 Python 转发代码。URL 无 SSH 命令和凭据，本地配置决定 SSH 主机。下载包仅包含固定客户端文件，存在 Windows 构建产物时附带 exe。
- 新版启动器仅允许图形程序 Wireshark，校验 Profile、检测提前退出，并尝试还原/前置 Windows 窗口。配置窗口使用表格对齐和路径浏览；Web 表单统一控件高度，消除全局 input 间距影响，会话与路径按固定列排版。
- claim 同时发放独立的 `client_ticket`，5 分钟内单次回报启动结果、手动认证模式及目标文件路径；不能替代数据流凭证或将会话标为 running。Web 显示“等待在 Wireshark 中认证”及 SSH 接口齿轮 → Authentication → Start 步骤。密码登录无需私钥。
- 默认输出为本机用户主目录 `lwns/captures/<时间-端点-随机标识>/capture.pcapng`，可在本地配置修改目录。使用 `-w` / `-o capture.pcap_ng:TRUE` / `-S` 指定保存及实时显示；Web 仅显示启动器报告的目标路径并提供复制，不保证文件已写入或跟踪 Wireshark 后续另存。旧版缺少路径回报时提示手动另存及升级。
- 启动器等待 GUI 生命周期并持续排空 stderr，提前退出显示错误并回报 Web；简要诊断写入本地配置旁的 `capture-launcher.log`，不记录完整 URI，隐藏会话凭证。升级需重新安装本地客户端，保留已有非秘密连接配置。
- `test_capture.py` 和 `web/tests/captures.test.ts` 验证控制逻辑与状态边界；`LWNS_CAPTURE_DOCKER_TESTS=1` 启用真实 veth/PCAP 测试。`serve_capture_fixture.py` + `check_capture_relay.py` 验证非 root 转发和 SSH 通道 EOF 对应的进程回收；`check_capture_ssh.py` 为目标本机 sshdump 验收入口。
- `serve_capture_ui.cjs` + `check_capture_ui.cjs` 使用独立模拟状态检查界面，不应拿它替代真实 SSH/桌面端到端验证。不要将测试用的环境替换或模拟路由复制到生产入口。

## 13. 项目保存与可移植项目包机制

远程项目生命周期已实现：新建、打开、保存、关闭与部署都由当前 Web 连接服务器的后端处理；保存包含拓扑、画布及当前已支持的 FRR 配置，保留现有数据布局并报告逐设备结果。关闭保留项目与运行设备。

以下可移植项目包方案记录于 2026-10-23，仍是未实施的候选设计，不代表本次已经迁移目录或实现完整导入导出。目录、扩展名和包格式待确定；当前保存行为以第 4/5/7 节为准。

### 13.1 参考价值与当前缺口

参考 GNS3 的项目描述文件与可移植项目包分工：GNS3 2.2 的 `.gns3` 使用 JSON 描述拓扑和画布，`.gns3project` 使用 ZIP 打包项目相关文件，并支持选择携带镜像。格式版本校验和旧版本迁移也值得借鉴；参考其组织方式，不承诺兼容 GNS3 文件格式。

当前 `.lwns-labs/<实验ID>.json` 同时包含拓扑与本机运行状态；FRR 文件位于 `devices/<实验ID>/<设备ID>/frr/`。现有 Web 导出只携带拓扑及已同步的 `node.config` 文本，不包含完整的 `daemons`、`vtysh.conf` 等文件。因此，本机清理后能够恢复，不代表导出的 JSON 能在另一台宿主机完整恢复。

目标是支持“配置设备 → 保存 → 导出一个项目包 → 另一台宿主机导入 → 部署恢复”，同时保持项目目录适合查看和 Git 管理。

### 13.2 候选目录与项目包

```text
projects/<项目ID>/
  project.json                  # 格式版本、拓扑、画布、模板及镜像引用
  configs/<设备ID>/             # 设备原生配置文件，允许多文件及子目录
    frr.conf                    # FRR 示例，其他设备不限定文件名/格式
    daemons
    vtysh.conf
  assets/                       # 可选实验说明、图片等

state/<项目ID>/
  runtime.json                  # 本机容器、PID、部署状态等，不进入可移植包

OSPF实验.rovproject              # 建议扩展名，内部为 ZIP；尚未确定或实现
```

- 普通保存更新同一个项目目录；导出生成可下载的项目包。历史快照作为后续独立能力，不要求每次保存都生成新归档。
- 项目描述优先沿用 JSON，复用当前前后端模型和校验。配置正文保存为设备原生文件，由项目描述通过相对路径引用。
- 逐步消除 `node.config` 与磁盘文件重复维护的问题，为配置正文确定唯一权威来源；旧版 JSON 内嵌配置通过兼容导入迁移。
- 项目包包含项目描述、已保存配置、必要资源和文件清单；本机日志、临时文件、运行状态、SSH 凭据及抓包凭证不默认打包。备份历史是否附带留待确定。
- 镜像默认保存引用，尽量记录 digest 和平台信息；缺少 digest 的本地镜像需要明确标识，不能保证仅凭 `latest` 恢复相同环境。携带镜像的离线包可后续实现。

### 13.3 设备配置的通用管理边界

统一的是文件管理和生命周期接口，不要求不同设备使用同名文件或相同配置语法。

- 项目层记录设备 ID、模板 ID/版本、配置文件集合、相对路径、保存时间和结果，以及所需恢复能力。
- 平台负责保存任务、结果展示、文件清单、打包与导入校验；适配器负责设备保存命令、文件收集、恢复位置、权限和加载顺序。
- FRR 可以保存多个配置文件；未来 VPP 可以保存启动配置及接口恢复脚本；其他设备可以保存文本或二进制文件。具体范围仍需相应适配器实现。
- 导入项目不自动安装或执行包内任意适配器代码；缺少匹配模板/适配器时应明确报告。受支持的配置或恢复脚本在部署阶段按适配器规则应用。
- 手动 CLI 创建接口不会因打包自动变成可恢复配置；仍需第 11 节所述的持久化配置或恢复步骤，不把终端历史当作可重放脚本。
- 此设计不代表当前 VPCS/Linux 主机或 VPP 已支持运行配置保存。界面应区分完整保存、仅拓扑、部分失败等结果。

2026-10-25 补充的设备接入实现见第 15 节：使用声明式设备描述与通用 Docker 生命周期执行器，复杂行为由镜像内脚本处理，避免每接入一个镜像就新增 Python 适配器。`.lwns` 是已实现的设备定义与镜像交付包；本节的 `.rovproject` 是包含拓扑及设备实例配置的候选项目包，仍未实现，两者不能混用。

### 13.4 保存与导出交互

| 候选操作 | 语义 |
| --- | --- |
| 保存项目 | 保存拓扑、画布及配置文件引用，不隐含所有设备运行配置已经写盘 |
| 保存设备配置 | 调用设备适配器，将运行配置持久化并记录逐设备结果 |
| 导出项目 | 打包已保存的项目和设备配置，可选择先保存设备配置 |
| 保存并导出 | 组合前述流程，展示不支持保存或保存失败的设备，不伪报全部成功 |

部署中的多设备保存是逐台执行，不能称为整个网络同一时刻的运行快照。导出需明确使用的配置版本与保存时间；具体锁定、暂存和一致性机制待实现阶段确定。

### 13.5 导入、兼容与恢复规则

- 项目格式版本独立于应用版本和设备模板版本管理；迁移旧文件前保留备份，遇到不支持的新格式或适配器能力时明确提示。
- 导入默认创建新实验并分配新项目 ID，维护内部设备和连线引用，避免静默覆盖现有实验及配置。
- 导入时校验归档路径、文件类型、大小和必要文件；项目只使用相对资源路径，不接受任意宿主机挂载路径。文件清单与完整性校验的具体格式待定。
- 容器 ID、PID、接口索引和部署标识由新宿主机重新生成；导入不复用旧运行状态，也不自动启动实验。
- 部署前检查镜像、平台和模板能力，再按适配器要求恢复配置、创建链路并验证。缺少文件、接口未恢复或部分失败时准确报告。

### 13.6 Compose 定位与建议实施顺序

`compose.yaml` 暂作为未来可生成的部署产物，不作为当前候选项目主文件。Compose 的 `x-` 扩展可以携带自定义信息，但 Docker 会忽略这些字段；画布、veth 接线及设备恢复仍需 lwns 实现。

建议先基于现有存储布局实现完整项目导出/导入及 FRR 跨宿主机恢复，避免同时改动全部持久化代码。随后在实验清理后迁移为独立项目目录，不能移动正在被容器绑定挂载的 FRR 目录。后续再扩展项目级离线镜像收集、历史快照及 Compose 生成；设备级离线镜像包和通用保存机制已按第 15 节提供。

候选验收：两台宿主机间恢复拓扑与画布、FRR 三个配置文件及协议启用状态；导入同一包两次不覆盖原实验；旧 JSON 兼容导入；缺镜像/适配器、保存部分失败和损坏归档有明确结果；清理保留配置、删除实验按既有确认语义处理。

参考：[GNS3 2.2 项目格式与迁移](https://github.com/GNS3/gns3-server/blob/v2.2.61/gns3server/controller/topology.py)、[GNS3 项目导出](https://github.com/GNS3/gns3-server/blob/v2.2.61/gns3server/controller/export_project.py)、[Containerlab 拓扑定义](https://containerlab.dev/manual/topo-def-file/)、[Containerlab 配置管理](https://containerlab.dev/manual/config-mgmt/)、[Docker Compose 扩展字段](https://docs.docker.com/reference/compose-file/extension/)。

## 14. 任务列表与实现状态

未勾选项仍未实现；勾选项已完成代码、测试和对应文档。

- [x] **当前服务器项目生命周期与保存**：新建即远端持久化、从服务器打开、统一保存拓扑/画布及运行中受支持的 FRR 配置、关闭服务端终端和抓包但保留项目与设备；全部使用页面同源 API，修复开发代理来源校验，HTTPS 保留明确可信代理配置。部分失败和不支持的配置保存逐项提示。
- [ ] **完整可移植项目包**：第 13 节的多文件项目包导出、导入、新 ID 分配与跨宿主机恢复仍未实现；不能将本次远程保存称为全容器备份。
- [x] **通用设备保存配置第一版**：`device.json` 必需保存动作与结果文件检查、原生配置目录、首次初始化和权限、启动准备与就绪检查已实现；共用生命周期执行器保留 FRR 校验及旧模板兼容。
- [x] **Web / CLI 制作 `.lwns` 设备包**：共用格式校验和打包模块，支持镜像引用、离线镜像和 Dockerfile 配方，Web 生成服务端文件并下载；开发者构建定义固定为 `device.json` 与 Dockerfile。
- [x] **`.lwns` 导入与设备版本管理**：当前服务器准备镜像后注册设备，支持库显示名称、稳定 ID＋版本、固定实际镜像、失败重试和删除同步；项目引用的版本禁止删除，不自动升级旧实例。
- [x] **通用保存与恢复基础验收**：真实 Docker 验证两台通用容器独立保存/恢复、veth 连通及包式 FRR 原生配置/协议进程恢复；Web / CLI 包互通、版本冲突和引用保护覆盖自动化测试。
- [ ] **其他数据面完整配置适配**：VPCS/Linux 的全部 Shell 网络状态、VPP/OVS 与厂商设备的专用保存、接口映射及恢复仍需各自实现和验证。`config-demo` 只演示原生文件保存，不代表已支持这些设备的全部配置。
- [x] **现代化工作台与菜单栏**：统一布局、控件、空状态和管理窗口；实验/视图/工具菜单提供实际打开、保存、导入导出与视图控制，完整项目包仍按上项待实现。
- [x] **删除默认实验**：空白启动与刷新、取消自动示例和示例按钮、已保存实验通过打开窗口选择，保留用户数据与可手动导入的示例文件。
- [x] **草原狼品牌图标**：替换导航、登录窗口与浏览器图标共用 SVG。
- [x] **项目起名字（实验项目命名与重命名）**：新建时填写名称，顶部名称打开重命名窗口；已保存项目立即保存名称，已部署项目无需清理容器即可改名，原 ID、配置和终端保留。这是实验名称，与软件品牌独立。
- [x] **软件更名 lwns**：统一使用 Linux Web Network Simulator 全称，更新界面、CLI、目录包、服务、抓包协议、README、用户/开发文档与截图；保留旧数据、环境配置、容器归属及 `.lwns` 格式兼容，升级步骤见 `lwns-upgrade`。

更名验收（2026-10-25）：前端 135 项单测、格式检查、类型检查与生产构建通过；Python 全量 206 项中 197 项通过、9 项显式跳过。Chromium 工作台 35 组及抓包界面 9 组通过，新增页面标题/品牌与旧布局读取检查，三张文档截图重新生成。实际构建 Linux x86_64/glibc 的 lwns 目录包，在隔离根目录验证安装、启动、认证、WebSocket、升级保留配置及卸载保留数据；不安装到真实系统，不重启正式服务。Caddy 新变量解析和新旧文档版本归档兼容检查通过，Sphinx 严格检查与 HTML 构建通过。
- [x] **侧边栏收缩和拉伸**：左右两侧均支持收起、展开、拖动调宽、双击复位和键盘调整；浏览器记住宽度与收起状态，窗口变窄时保留画布空间。
- [ ] **FRR 容器支持 FTP、RTSP 服务器（未实现）**：在 FRR 设备容器中提供可选的 FTP、RTSP 服务程序，规划安装方式、配置文件、监听接口/端口及进程启停管理。应用服务作为容器内的独立进程运行；具体软件选型和镜像集成方式待设计。
- [ ] **Web FRR 设备应用协议配置（未实现）**：参考 eNSP 的配置交互，在 FRR 设备配置页面增加应用服务配置入口，支持按需配置、启动和停止 FTP server、DHCP server、DNS server 等服务，并展示运行状态与错误。与容器内服务能力匹配，后续规划服务配置的保存及清理重建后的恢复；具体字段和首批支持范围待设计。
- [x] **紧凑圆形设备**：圆形图标和外置名称，按端口数量自动留出接线位置，移除设备拉伸入口并兼容旧尺寸字段。
- [x] **顶部自动对齐**：单按钮将位置接近的设备对齐到同一行/列，保留整体布局，结果随项目保存。
- [x] **自动最近连线优化**：就近图形插槽、短路线及候选障碍避让，随设备移动自动重算；不更改真实端口连接关系。
- [x] **画布注释**：支持多行网段说明、字号/颜色/背景、拖动和删除，随 JSON 保存、导入导出与刷新恢复。
- [x] **画布滚动与 Ctrl 缩放**：横纵滚动条、滚轮平移、Shift 横移及 Ctrl＋滚轮围绕鼠标缩放；滚动视口不改变拓扑数据。
- [x] **部署后编辑拓扑**：允许增删设备/网线、修改端口/设备属性和注释；视觉内容直接保存，网络差异通过“应用拓扑”增量同步，保留未变容器，记录任务失败并保留草稿。
- [x] **设备库分组与镜像删除同步**：路由器、交换机、PC、防火墙横向四类入口，进入子目录才显示该类双列圆形设备，子目录不设搜索框；移除“全部”平铺入口、侧栏底部提示与镜像管理按钮，管理入口统一为顶部“工具”菜单；管理记录是卡片来源，删除/解绑/改名/改类型同步到侧边栏，失败重试且拒绝旧响应回写。
- [x] **镜像管理范围与界面优化**：只显示项目管理条目，停止全机自动纳入；已有镜像显式引用，移出清单与本地删除分开，后端执行时校验创建归属和标签 ID；增加筛选、数量概览、引用提示及可收起的任务日志，兼容旧清单迁移。
- [x] **终端及管理面板分包、静态压缩与缓存**：首次使用动态加载，之后保留会话/表单/轮询；gzip、静态条件请求与哈希长期缓存，API 保持 no-store；不调高构建警告阈值。
- [x] **可选 Caddy 与证书文档**：同机 HTTPS / HTTP/2 / HTTP/3 入口、明确可信代理、WSS/上传支持、PCAP 仍经 SSH；记录 Caddy 自动内网 CA、mkcert 制作与信任、证书续期、Chromium QUIC 限制及协议验证。
- [x] **Linux 目录包与系统安装教程**：PyInstaller onedir、tar.gz 与 SHA256 校验，`/opt` 版本目录及启动链接、独立 `/etc` 配置与 `/var/lib` 数据、systemd/前台启动、升级回退和保留数据卸载；不使用 deb/rpm。提供运行路径单元测试与隔离目录包验收入口，当前目标为 Linux x86_64/glibc。

目录包验收记录（2026-10-24）：Ubuntu 22.04 x86_64/glibc 2.35 构建并通过冻结程序静态 gzip、默认资源、认证 API、WebSocket 拒绝无效凭证、抓包客户端下载、校验失败拒绝安装、外部服务/路径保护、重复安装、升级保留配置与数据、每台主机独立 Token、卸载保留数据检查。Python 112 项测试中 106 项通过、6 项显式集成测试跳过；本次只在隔离系统根目录验收，未替换线上源码服务，也未宣称其他发行版、架构已验证。

## 15. 保存配置设计：通用设备描述与 .lwns 设备包（第一版已实现）

**状态：2026-10-25 第一版已实现。包含描述文件校验、容器内通用启动/保存动作、目录持久化、`.lwns` 制作/检查/导入、Web 与 CLI 入口及版本库；保留现有 FRR 和远程项目保存。已验证通用文件示例与 FRR 的清理后恢复，不代表所有数据面已经适配；完整项目包仍未实现。用户操作见 [设备包教程](docs/user/workbench-devices.rst)。**

### 15.1 目标、职责与文件边界

目标是让开发者提供设备描述与镜像构建定义，普通用户导入一个 `.lwns` 文件、确认设备名称后即可使用；设备保存与恢复按照描述执行，用户不必手工选择配置文件或配置挂载目录。

- 镜像提供设备程序及运行依赖，不预建实验接口。接口名称、数量、连线与实例网络参数属于项目拓扑，由外部平台创建和接入 veth，不固定在镜像或设备描述中。
- 设备分类只决定路由器、交换机、PC、防火墙等显示类别，不据此推断保存命令；例如 VPP 属于路由器，也不能自动执行 FRR 的命令。
- 平台统一负责设备实例 ID、容器归属、挂载、veth、任务互斥、终端、日志和结果展示。设备描述负责程序启动、配置位置、保存动作与恢复顺序；复杂行为由镜像内部脚本实现。
- 通用的是描述格式和执行流程，不是所有设备的配置语言。平台不自动把任意 CLI 历史或 Linux 运行状态转成配置，也不保证 VPP 自动识别 Linux veth；数据面接入仍需要明确动作或第 11 节的适配。

| 对象 | 保存内容 | 使用范围 |
| --- | --- | --- |
| 设备定义 / `.lwns` | 名称、版本、镜像来源、启动与保存规则、持久化声明，以及可选镜像资源 | 可复用、可分享的设备类型 |
| 设备实例数据 | R1、R2 各自保存的原生配置文件与保存结果 | 一个项目内的一台设备 |
| 项目文件 / 候选 `.rovproject` | 拓扑、画布、设备引用及实例配置资源 | 整个实验；完整项目包仍按第 13 节规划 |

制作或更新 `.lwns` 不自动收集当前实验的配置，导入设备包也不等于打开或部署项目。

### 15.2 开发者的构建定义固定为两个文件

```text
设备定义源码/
└── frr/
    └── 1.0.0/
        ├── device.json
        └── Dockerfile
```

- `device.json` 描述如何使用设备；Dockerfile 安装设备软件并准备默认配置和必要脚本。描述文件由平台读取，不要求嵌入镜像。
- 不要求开发者另交 `scripts/`、`defaults/` 等配套目录。需要的文件应由基础镜像提供，或直接在 Dockerfile 中生成；不能依赖未交付的 `COPY xxx.sh` 或目录外文件。构建所需源码或依赖的获取方式也应明确写在 Dockerfile 中并固定版本。
- 复杂启动、保存和恢复可以调用镜像内脚本；脚本内容通过 Dockerfile 生成，不改变两个文件的交付约定。普通设备可以直接声明原生命令，无需编写 Python 适配器。
- 当前启动执行器要求镜像有 `/bin/sh`、`sleep`、`tr`、`grep`，解析非数字属主另需 `id`/`awk`；服务保持前台运行。无 Shell 镜像暂不支持，默认配置或 prepare 应在首次启动前准备好声明的配置文件。
- 两个文件约束的是开发者维护的构建定义，不代表 `.lwns` 只能装两个文件。平台制作离线包时可自动加入 `image.tar`；使用已有镜像制作设备包也不要求用户重新编写 Dockerfile。
- 当前 FRR Dockerfile 使用 FRR 源码树作为构建上下文。迁移到此约定时须整理其源码获取与构建方式，不能仅移动 Dockerfile 后宣称支持独立构建；当前文件未作修改。

### 15.3 device.json 的内容与校验

描述格式当前为 `schema_version: 1`，由 `lab_device_schema.py` 校验和规范化，拒绝未知字段和重复 JSON 键。完整示例位于 `examples/device-packages/frr/` 与 `examples/device-packages/config-demo/`；未来格式版本迁移仍需单独实现，当前拒绝不支持的版本。

SDN 三个设备的发布版本统一为 `1.0`，对应镜像标签 `lwns/sdn-*:1.0` 和文件 `sdn-*-1.0.lwns`。设备版本校验兼容两段 `1.0` 与三段 `1.0.0`；保留原始版本字符串作为设备身份的一部分，不合并既有版本或迁移已安装实例。

2026-10-26 增加可选 `runtime.cap_add`，仅接受空数组或 `["SYS_ADMIN"]`，用于包含 FRR 的通用多服务设备；不接受任意 Docker 参数、privileged 或宿主网络。旧描述不变，新字段需要更新后端。`examples/device-packages/sdn-agent`、`sdn-controller`、`sdn-web` 各维护 device.json 与 Dockerfile，`build_sdn.py` 从本地原生镜像制作三份离线 `.lwns`；首次启动生成实例凭据，不打包运行 Token/身份/数据库。三种设备使用 generic profile，配置保存与 REL-004 恢复边界见 [SDN 设备用户教程](docs/user/sdn-devices.rst)。

本次验证：设备包相关 Python 测试 61 项（58 通过、3 项独立 Docker 测试默认跳过），前端 136 项测试、类型检查与生产构建通过；浏览器制作/下载 `.lwns`、导入、改名、引用保护及删除等 7 组检查通过，旧 `.rov` 上传、已安装文件和旧任务下载兼容有回归覆盖。另执行 `verify_sdn.py` 的真实 Docker/veth 验证，三个设备启动、Agent 注册、Web→Controller 认证请求、Agent 提交、Redis/FRR/etcd/Web 保存及重建后身份/revision/节点清单保留均通过；确认 Linux bridge 不自动重建，REL-004 状态保持未实现。用户文档严格 Sphinx 构建通过。离线包及 SHA256SUMS 位于制作机器 `~/lwns-devices/sdn/1.0/`，不自动导入用户设备库或替换现有服务。

| 字段或字段组 | 约定 |
| --- | --- |
| `schema_version` | 描述格式版本，与软件版本、设备定义版本分开 |
| `id`、`version` | 稳定设备定义 ID 与发布版本；名称变化不改变身份 |
| `name`、`category` | 默认显示名称、路由器/交换机/PC/防火墙分类 |
| 镜像与构建信息 | 镜像引用、可用的摘要/平台、仓库/归档/构建来源；构建路径相对包根目录解析 |
| `console` | 容器内交互终端入口及参数数组 |
| `persistent_dirs` | 容器目标目录、逻辑目录 ID、RW 模式、首次默认文件来源和属主/权限；可声明多个目录 |
| `startup` | 启动阶段、有序准备命令、长期服务进程、原生配置文件路径及就绪检查 |
| `actions.save_config` | 必需的保存动作，含容器内命令数组或脚本入口、超时及结果校验规则 |
| 可选生命周期动作 | 接线后配置加载、运行中链路变化处理等；仅在需要时声明 |

描述文件只提供容器内配置目标与包内相对资源路径；宿主机配置路径由平台在自己的数据目录中生成，用户不用填写绝对路径。配置文件名和格式由设备决定，不统一命名成 `config.txt`，也不要求平台解析配置语法。

启动及保存动作的简化片段如下，不是完整设备描述。完整描述还须提供身份、来源、profile、共享目录等字段；通用 profile 必须提供 `startup.ready`，FRR profile 复用协议进程检查，保存必须声明预期文件或使用 `startup.config_files` 作为结果检查：

```json
{
  "startup": {
    "phase": "after_links",
    "prepare": [
      {
        "name": "检查启动配置",
        "exec": ["test", "-r", "/etc/frr/frr.conf"],
        "timeout_seconds": 5
      }
    ],
    "service": {
      "exec": ["/usr/lib/frr/docker-start"]
    },
    "config_files": [
      "/etc/frr/daemons",
      "/etc/frr/frr.conf",
      "/etc/frr/vtysh.conf"
    ]
  },
  "actions": {
    "save_config": {
      "exec": ["vtysh", "-w"],
      "timeout_seconds": 30
    }
  }
}
```

### 15.4 启动、保存和清理后恢复

```text
读取项目中的设备定义版本、实例 ID 与拓扑
                    ↓
首次初始化默认配置，或使用该实例已有配置
                    ↓
创建容器并 RW 挂载实例配置目录
                    ↓
平台创建并接入项目要求的 veth
                    ↓
依次执行准备命令，启动服务并读取原生配置
                    ↓
就绪检查成功 → 设备可用 → 用户通过终端配置
                    ↓
保存前检查归属、挂载与设备状态，并备份
                    ↓
执行 actions.save_config → 校验持久化结果
                    ↓
记录逐设备保存结果、时间和实际使用的定义版本
                    ↓
清理容器与网线，保留实例配置目录
                    ↓
重新部署时挂载同一目录，重建接口并加载配置
```

- 首次部署从镜像取得默认配置并设置权限后再挂载；后续启动不能用默认文件覆盖实例已保存的配置。新实例使用独立 ID 和目录，不能因名称相同复用旧配置。
- 容器运行与设备服务启动是两个阶段。需要接口先就绪的设备使用统一等待/启动机制，由平台负责进程监督和信号处理，不能要求每个开发者重写等待脚本。特殊数据面允许声明不同阶段或接线后加载动作；不能强制所有服务使用同一种顺序。
- `prepare` 是按顺序执行的有限任务，失败或超时默认停止后续步骤；服务是长期进程，启动完成由独立就绪检查判断，不能等待服务退出才算成功。日志应明确标出阶段和失败命令，准备动作应可重复执行。
- 动作默认只在对应设备容器内执行；保存命令不能变成任意宿主机执行接口。JSON 使用参数数组，复杂 shell 逻辑交给镜像内脚本。
- `save_config` 必须将所承诺的运行配置写入持久化位置；不能用无效的空动作伪装支持。已直接写盘的设备也须明确定义验证/刷盘语义。保存结果检查应根据设备规则确认必要文件及命令结果。
- 保留现有 FRR 对协议进程、配置权限、可写挂载与保存内容的检查。缺失协议进程或命令失败时，保留备份并报告具体失败，不能覆盖状态为全部成功。
- 多设备保存逐台返回结果；保存与清理、重部署及拓扑应用互斥，不宣称全网络同一时刻快照。运行中拓扑草稿必须区分已应用版本，不能把旧运行配置直接标记为新草稿已完整恢复。
- 普通 `ip link`、`ip addr`、`ip route` 或 VPP CLI 运行修改，只有被设备保存动作覆盖并能在启动时恢复，才属于保存范围；不支持的部分必须明确显示。设备原生配置和项目网络参数还需约定归属，避免双方重复覆盖。
- 运行中新增连线与首次启动使用不同生命周期动作，避免每次拓扑变更重新启动整台设备。VPCS/Linux、VPP、OVS 的具体保存实现仍待各自验证。

### 15.5 .lwns 设备包与镜像来源

`.lwns` 采用 ZIP 容器格式，以包根目录的 `device.json` 为设备定义入口，另由工具生成 `manifest.json` 记录包格式和资源校验信息。包与资源关联由制作程序写入，不能只靠文件名或 Docker 标签猜测身份；设备包清单与内层 Docker 镜像的清单是不同文件。

| 来源 | 包中资源及导入行为 |
| --- | --- |
| 镜像仓库 | 描述文件记录引用及可用的摘要/平台；导入时使用匹配本地镜像或拉取，不能保证离线使用 |
| 已有 Docker 镜像 / 上传 `.tar` | 制作可分享离线包时，将 `docker save` 格式的镜像归档放入包内 `image.tar`；导入时直接 `docker load` |
| Dockerfile 构建 | 包含 `device.json` 与 Dockerfile，导入时构建；只有构建配方不代表已包含镜像或可以离线构建 |

- 制作界面必须说明包是否携带镜像，不能把仅记录本机镜像名称的包称为完整离线设备。
- 镜像资源的大小和 SHA256 由工具生成清单并校验，实际镜像 ID 在导入准备完成后固定到版本库；归档校验值、镜像 ID 与仓库 digest 分开处理。校验归档必须包含描述指定镜像。
- 外层 `.lwns` 由平台处理；内层未压缩 `image.tar` 交给 Docker 加载。`.lwns`、Docker 镜像 `.tar` 和完整项目包是不同格式，不把外层设备包直接传给 `docker load`。
- 同一包指定明确的镜像准备策略，已存在匹配镜像时可复用，不要求每次重新构建。直接上传普通 `.tar` 只准备镜像，不能自动获得正确的启动、配置保存和恢复能力。

### 15.6 Web 制作、关联和导入交互

用户教程 [workbench-devices.rst](docs/user/workbench-devices.rst) 按“已有包加载 → 画布部署 → FRR 离线制作 → Web 制作 → CLI 来源及导入”组织，提供完整可复制的 FRR `device.json` 与 `docker save` / pack / inspect 命令。锚点 `rov-import-device`、`rov-frr-offline`、`rov-web-pack`、`rov-cli-pack`、`rov-cli-import` 作为入口；明确浏览器选客户端文件、Web 操作发生在远程后端，以及源码 `.lwns-labs` 与安装包数据目录的区别。

```text
制作设备包窗口
  选择 device.json → 自动填充名称、分类、版本
  选择镜像来源 → 仓库 / 已有镜像 / .tar / Dockerfile
  确认信息 → 在当前服务器生成 .lwns → 可下载分享

导入设备窗口
  选择 .lwns → 读取默认名称，允许修改设备库显示名称
  校验并展示分类、版本和镜像准备方式
  导入 → 准备镜像 → 注册设备 → 加入左侧设备库
```

- 用户不需要重新填写启动命令、配置路径、挂载和保存规则；这些从包内描述读取。制作时对名称等字段的修改统一写入输出包的描述文件，不能产生两份互相冲突的元数据。
- 制作表单可以分别选择设备描述和镜像来源，但属于同一个任务。小文件可一次提交；大镜像分次上传时，每次携带服务端分配的 `import_id` 或制作任务 ID，后端只关联同一任务中明确登记的资源。
- 缺少资源或校验失败时保留任务草稿和错误信息，不生成可用设备条目；不按通用文件名 `device.json` / `Dockerfile` 在全局目录中配对。
- 导入失败保留已检查上传供重试；导入成功与制作任务完成后回收其临时上传，CLI 同步导入在成功/失败后均回收自身上传，避免连续使用耗尽暂存名额。制作失败可重新上传本地资源。生成产物、版本包、任务日志与配置备份尚不自动轮转。
- 制作只生成设备包，导入负责注册并准备镜像；制作离线包可能需要导出选定镜像，但不能顺带部署实验。
- Web 制作、存储、导入、镜像准备和后续部署均在当前页面所连接的远程后端完成，使用同源 API。浏览器只负责选择本地上传文件、展示进度以及下载生成的包。
- 顶部“工具 → 设备管理”提供已安装设备、导入设备包、制作设备包三个页面，首次打开异步加载；保留“镜像管理（兼容）”处理已有镜像记录和内置模板，不自动迁移旧清单。底层继续使用 `docker load` / `pull` / `build`。
- 导入时设置的是设备库显示名称，作为本机管理别名存储，不改原始包的 ID、版本或完整性记录。拖入画布后另行生成 R1、R2 等实例名称；实例改名不改变其配置目录定位。

### 15.7 CLI 与 Web 共用设备包模块

`lab_device_packages.py` 提供格式校验、打包、检查和版本库，`lab_device_service.py` 管理上传与后台任务，`lab_device_cli.py` 与 Web 共用这些模块。CLI 检查和制作不依赖 Web 服务运行；需要导出镜像或构建时才使用相应 Docker 能力。

以下命令适用于重新构建安装后的 Linux 目录包；源码版将 `lwns` 替换为 `python3 script/python/lab_server.py`。CLI 导入与后端共用数据目录锁，后端运行时使用 Web 导入，或停止同数据目录后端后再进行 CLI 导入；pack/inspect 不占用此锁：

```bash
# 制作离线镜像设备包
lwns device pack --descriptor device.json --image-tar frr.tar --output frr-1.0.0.lwns

# 制作构建配方设备包
lwns device pack --descriptor device.json --dockerfile Dockerfile --output frr-1.0.0.lwns

# 检查设备包信息与完整性；不执行包内动作
lwns device inspect frr-1.0.0.lwns

# 导入设备库并准备镜像；不部署项目
lwns device import frr-1.0.0.lwns
```

CLI 在执行命令的机器上读取文件并输出到指定路径，不能因为浏览器连接了某台服务器就自动操作那台服务器。Web 生成包可下载给 CLI 使用，CLI 生成包也可上传 Web；两者必须使用相同格式版本和校验规则。

### 15.8 软件数据目录、命名、版本与删除

当前存储布局如下；没有移动旧设备持久化目录，第 13 节的项目目录迁移仍未实施：

```text
<data-dir>/
├── device-library/
│   ├── registry.json
│   └── <设备定义ID>/
│       ├── 1.0.0/device.lwns
│       └── 1.1.0/device.lwns
├── device-packages/
│   ├── artifacts/<制作任务ID>.lwns
│   ├── jobs/<任务ID>.json
│   └── uploads/<上传ID>/
└── devices/<项目ID>/<设备实例ID>/
    ├── config-meta.json
    └── frr/                       # 示例：RW 挂载到该实例的 /etc/frr
```

- 使用可写软件数据目录，不放入只读程序安装目录或前端资源目录。部署安装包时沿用配置的数据根目录，软件升级不能覆盖设备库和项目配置。
- 设备库保存原始包、注册信息、显示别名和实际镜像关联；加载后的镜像由 Docker 存储。同一镜像可以被多个设备定义或实例引用，实例配置始终独立。
- 任务 ID 只关联一次制作/上传；设备定义 ID＋版本标识可复用设备；项目 ID＋实例 ID 标识具体配置。名称只用于显示，不作覆盖或删除的判断依据。
- 相同 ID、相同版本和相同内容视为已导入；同 ID 同版本但内容不同应报告冲突，要求新版本，不能静默替换。相同 ID 新版本可并存，同名不同 ID 不是同一设备。
- 项目记录设备定义版本、实际镜像身份和配置兼容信息。升级设备库不自动重建旧项目、不替换正在使用的镜像，也不自动迁移配置文件。
- 删除或停用设备条目应同步侧边栏；被项目引用的版本需保留恢复所需资源。移出设备库不删除实例配置，不以同名为由删除旧设备。
- 物理删除 Docker 镜像仍遵循现有归属和引用检查，不能因为删了一个 `.lwns` 就删除其他定义或系统容器共用的镜像。检查、镜像准备失败时不得提交虚假的可用状态，保留失败原因和重试入口。

### 15.9 实施状态与后续验收

1. 已实现描述校验、版本化设备包、通用生命周期与 FRR 兼容；不迁移活动 bind mount。新实例使用独立 ID，原有项目 ID 保持兼容。
2. 已实现共用设备包模块、CLI 检查/制作/导入与 Web 窗口，上传按任务关联，检查与制作不部署项目。
3. 已实现版本库、显示别名、侧边栏刷新、失败重试及引用保护；旧镜像清单保留兼容入口，未自动改造成设备包。
4. 待继续扩展 Linux/VPCS、VPP 等数据面的完整保存和恢复，设备定义升级后的配置迁移、数据来源归属策略及包/备份历史轮转也仍需后续处理。

当前自动化检查及后续设备适配应持续覆盖：

- 同一镜像部署 R1、R2，分别保存后清理并重建，各自恢复配置且不串用目录；改名不影响恢复，首次默认文件不覆盖已保存内容。
- FRR 恢复多个原生配置文件及启用的协议进程；保存失败、只读或错误挂载、服务未就绪和超时均准确报告，不能显示全部已保存。
- Web / CLI 生成的包互相检查和导入；离线包在没有目标镜像的宿主机上恢复，仓库或构建失败不生成可用卡片。
- 同时制作多个包时上传资源不混用；检查包不会执行设备动作；路径越界、损坏归档、不支持版本及缺少必需保存动作有明确错误。
- 重复导入、同名不同 ID、同版本不同内容、更新版本、删除有引用设备等情况不覆盖旧项目；库条目删除或停用同步侧边栏。
- 验证运行中接线动作与首次启动分离，不无故重启未变设备；完整项目跨宿主机恢复另按第 13 节验收，不能用设备包导入代替项目恢复。

本阶段验收记录（2026-10-25）：

- 前端 134 项单测、类型检查、格式检查与生产构建通过；设备管理为独立异步分包，未出现大包警告。浏览器设备包流程 7 组、工作台 35 组、部署画布 18 组、设备库 9 组通过，含 1000px 布局与同源请求验证。
- Python 最近一次全量回归为 201 项，其中 193 项通过、8 项显式集成测试跳过；随后安装入口 6 项与设备包 API 9 项专项通过，覆盖新增 CLI/Web 上传回收。设备包/CLI 单测 30 项、运行配置单测 16 项包含在相应回归中。
- 独立启用真实 Docker 测试：`test_device_runtime_docker.py` 两项通过，验证通用双实例保存/恢复、veth/ping 和 FRR 原生配置/协议进程恢复；`test_device_package_docker.py` 一项通过，验证本地镜像导出、离线 `docker load`、Dockerfile `docker build`、CLI 导入与镜像 ID 固定。
- 测试使用独立数据目录、模拟宿主机或带唯一标识的真实资源，测试标签/容器与浏览器辅助进程均已回收，未重启正式后端。Sphinx 严格检查与 HTML 构建通过；新功能需使用更新后的后端，已安装可执行目录包需重新构建发布后才包含新增命令。
