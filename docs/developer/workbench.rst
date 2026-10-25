Vue 工作台开发
========================================

工作台前端位于 ``web/``，使用 Vue 3 单文件组件、TypeScript、Vite 和 Pinia。
Python 后端使用 FastAPI / Uvicorn，负责实验持久化、Docker 生命周期及 veth 操作。
前后端通过 ``/api`` 通信，设备终端通过同端口 WebSocket 连接。

菜单、空白启动与界面约定
----------------------------------------

工作台使用现有 Vue 3 + Pinia 与集中式 ``workbench.css``，未新增 UI 框架依赖。
统一的颜色、边框、字号和控件样式覆盖设备库、画布、属性、日志与管理窗口；
``--topbar-height`` 统一顶栏、工作区及底部放大面板的定位。
``steppe-wolf.svg`` 是导航、登录窗口和 favicon 共用的草原狼品牌资源。

``WorkbenchMenu`` 提供实验、视图、工具菜单；``LabOpenDialog`` 从 ``GET /api/labs``
刷新并搜索已保存实验。``useProjectFiles`` 统一菜单和工具栏的保存、JSON 导入导出逻辑，
导入在异步读取结束后核对文档版本，并确认放弃未保存修改；同 ID 导入语义沿用旧协议。
打开窗口和菜单必须隔离画布快捷键，保留方向键、Esc、Tab 和焦点行为。
菜单项只显示操作名称、勾选状态与分隔线，不显示按钮下方或菜单底部的解释文字。

项目创建使用 ``POST /api/labs {name}``，服务器生成 ID 并原子保存空项目；
``POST /api/labs/{id}/open`` 加载服务器记录，``POST /api/labs/{id}/close`` 回收终端和抓包，
保留文件和运行设备。前端仅在请求成功后切换画布，失败和过期响应不能覆盖当前草稿。
``POST /api/labs/{id}/save {topology}`` 在服务器统一保存拓扑及运行中受支持的设备配置，
返回 ``record``、逐设备 ``results`` 和 ``topology_saved``；不支持项为 skipped，部分失败
不回滚已成功的保存，界面必须说明结果。旧 PUT 和单设备 configs 接口保留兼容。
这不是可移植项目包；前端请求全部使用相对 /api 路径。

Store 初始为干净空白画布；``bootstrap`` 只更新环境、目录与实验列表，不自动打开首项。
重新认证不替换当前草稿。后端不再返回 ``example``；``examples/basic-lab.json``
保留作显式文件导入与测试夹具，不属于默认实验，也不能清理用户数据来达到“空白启动”。

``LabToolbar`` 在唯一操作行中依次放置项目名称、排版/连线/注释、保存/配置/清理/部署；项目名称不再独占一行。
操作行空间不足时在内部横向滚动，控件保持同一行，键盘 Tab 可将焦点控件滚入视口。
``usePanelResize`` 观察工作区和外层工具栏尺寸，只计入外层工具栏总高度，避免重复扣除内部操作组。
测试包括 ``project-files.test.ts``、空白启动用例与 ``check_project_menu.cjs``；
已有浏览器夹具通过 ``browser_projects.cjs`` 显式打开已保存实验。

按需加载与生产传输
----------------------------------------

``TerminalWorkspace`` 使用异步 ``DeviceTerminal``，只在存在终端标签时加载 xterm 和对应 CSS。
终端仍通过 v-show 切换，不能改为隐藏时卸载，否则会中断会话。
``App`` 的 ``useRetainedPanel`` 在首次打开时挂载 ImageManager/CaptureManager，之后保持挂载，
使上传、任务轮询和表单状态不因关闭窗口而丢失。对话框 onMounted 同步当前打开状态，
解决异步加载完成时 watch 已错过首次打开的问题。

模块加载失败由 ``vite:preloadError`` 显示提示，不自动刷新未保存的画布。
不调高 Vite 的 chunkSizeWarningLimit；新增重功能应在功能入口建立动态 import 边界。
每次发布部署完整 dist，必要时保留上一版哈希文件，详见 :doc:`../user/workbench-https`。

``lab_static.py`` 基于 Starlette StaticFiles 提供流式文件、HEAD/Range 和条件请求。
gzip 仅作用于静态路由，API、WebSocket 和 PCAP 不压缩；Range 保持原始字节。
哈希资源 immutable 一年，首页/非哈希资源 no-cache，错误及 API no-store；
gzip 与 identity 共享弱 ETag，响应包含 Vary: Accept-Encoding。

可选 Caddy 配置全部代理到回环后端，避免重复实现静态缓存规则。
后端 ``--trusted-proxy`` 显式启用 Uvicorn 的可信代理头解析，默认关闭；
Caddy 保留 Host/Origin，提供可信 X-Forwarded-Proto/For，API 和终端继续校验同源。
Caddy 入口拒绝 PCAP stream 路径，数据通道继续通过 SSH。证书制作和部署步骤见用户指南。

相关自动化检查
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``web/tests/lazy-panels.test.ts`` 验证首次挂载和关闭后保留状态；浏览器检查
``check_terminal.cjs``、``check_managed_images.cjs``、``check_capture_ui.cjs`` 还断言
首页不请求对应分包、首次打开成功，以及会话/草稿/后台抓包轮询继续保留。

``tests/test_web_delivery.py`` 覆盖 gzip 协商、条件请求、哈希/非哈希缓存、HEAD/Range、
404/503、路径和符号链接边界、可信/不可信代理、HTTPS Origin、WebSocket 及抓包来源限制。

可选真实 Caddy 集成验证使用随机端口、临时 CA 和临时实验目录，不安装系统证书、不修改 Docker 镜像或设备。
上传测试需要本机 Docker info 可访问；仅登记、传输并删除临时上传，不提交 docker load。
在独立测试虚拟环境中执行::

   python3 -m venv /tmp/lwns-caddy-venv
   /tmp/lwns-caddy-venv/bin/pip install -r tests/requirements.txt 'httpx[http2]' aioquic
   npm --prefix web run build
   /tmp/lwns-caddy-venv/bin/python tests/check_caddy.py --caddy /实际路径/caddy --http3

该检查启动真实后端与 Caddy，验证 HTTP/2、通过证书校验的 HTTP/3 请求、gzip/304、
认证/跨站拒绝、流式上传、WSS 及公开 PCAP 路径拦截，最后停止进程并删除测试目录。
aioquic 是测试客户端依赖，不是产品运行依赖；此检查不能代替特定浏览器的 QUIC 信任策略验证。

本地开发
----------------------------------------

完整的开发/发布选择、首次准备、Linux 两终端启动与访问端口见
:doc:`../user/workbench-start`。本节补充仅预览和跨主机代理配置。
真实设备开发使用 root 后端且不加 ``--preview``，仍从 Vite 的 5173 访问。

使用 Node.js 22.12+ 的 22.x 或 24+，建议 Node.js 24 LTS。
以下命令均在项目根目录执行。先安装锁文件指定的依赖::

  npm --prefix web ci

在第一个终端安装依赖并运行后端（Python 3.10+）::

  python3 -m venv .venv
  .venv/bin/python -m pip install -r script/python/requirements.txt
  .venv/bin/python script/python/lab_server.py --preview --port 8090

在第二个终端运行 Vite::

  npm --prefix web run dev

访问 ``http://127.0.0.1:5173``，输入 Python 后端的令牌。
开发模式直接编译 ``web/src``，无需预先生成 ``web/dist``。
Vite 默认只监听本机；如需局域网开发访问，可显式传入 ``-- --host 0.0.0.0``。

若 Python 后端在其他主机或端口，将 ``web/.env.example`` 复制为
``web/.env.local`` 并修改::

  LWNS_API_TARGET=http://Linux主机IP:8090

修改后重启 Vite。该设置仅供开发服务器代理使用，生产环境前端与后端使用同一源。
令牌由访问页面时输入，不写入环境文件或前端构建产物。
代理同时支持 HTTP 与 WebSocket，使用 ``changeOrigin: false`` 保留原始 Host/Origin，
后端规范化协议、主机和默认端口后校验同源，仍拒绝其他站点的 Origin。Windows 使用独立的 ``.venv\Scripts\python.exe``。

跨平台依赖与原生模块错误
----------------------------------------

``node_modules`` 包含与操作系统、CPU 架构和 libc 对应的原生模块，不能直接在
Windows 和 Linux 之间复用。例如 Windows 上通过 Samba 安装依赖后，Linux
启动 Vite 可能报 ``Cannot find native binding``，并提示缺少
``@rolldown/binding-linux-x64-gnu``。

请在真正运行 Vite 的机器上，从项目根目录执行::

  npm --prefix web ci --include=optional
  npm --prefix web run dev -- --host 0.0.0.0

``npm ci`` 会重新安装当前平台的依赖。项目锁文件已包含 Linux 和 Windows
原生包，保留 ``package-lock.json``，无需删除锁文件或手动固定某个底层原生包版本。
开发与构建命令会先加载 Rolldown，依赖不匹配时给出上述修复提示。
长期在两端开发时，应使用独立检出目录，避免相互覆盖依赖。
编译生成的 ``web/dist`` 是浏览器静态资源，可以跨平台复制。

Node.js 20.20.2 满足当前 Vite 的运行要求，因此缺少 Linux 原生包不能归因于
该 Node 版本。但本项目的 Vitest 5 完整测试工具链需要 Node.js 22.12+ 的 22.x、
24.x 或 26+；完整开发与验证仍建议使用 Node.js 24 LTS。

目录与职责
----------------------------------------

.. code-block:: text

   web/
   ├── package.json / package-lock.json
   ├── vite.config.ts            开发代理与生产构建
   ├── vitest.config.ts          前端行为测试
   ├── tsconfig.json             严格 TypeScript 检查
   ├── src/
   │   ├── App.vue               页面组合、认证初始化和轮询生命周期
   │   ├── components/           设备库、工具栏、画布、节点、属性和终端面板
   │   │   ├── DeviceTerminal.vue    xterm.js、连接和尺寸同步
   │   │   └── TerminalWorkspace.vue 多标签和终端操作
   │   ├── stores/lab.ts         拓扑配置、部署状态和 API 操作
   │   ├── stores/editor.ts      选择、连线、视口及属性草稿
   │   ├── stores/ui.ts          消息、对话框和底部面板
   │   ├── stores/layout.ts      左右侧边栏宽度、收起及浏览器持久化
   │   ├── stores/terminals.ts   标签、会话状态和实验切换清理
   │   ├── api/client.ts         认证、JSON 请求和错误处理
   │   ├── domain/topology.ts    导入校验与连线约束
   │   ├── domain/canvas.ts      圆形节点、端口锚点、路径、自动对齐与注释几何
   │   ├── types/lab.ts          拓扑、设备、端口和 API 类型
   │   └── styles/workbench.css  工作台公共样式
   └── tests/                   拓扑与状态管理行为测试

画布使用声明式 SVG 和带稳定 key 的 Vue 节点组件，不再通过 ``innerHTML`` 重建画布。
鼠标事件、坐标换算与视口尺寸由画布组件管理；共享的编辑状态存放在 editor store 中。
组件卸载时释放轮询、键盘事件和 ResizeObserver。

拓扑文件保持 ``version: 1``，不包含 Vue、Pinia 或画布组件特有的数据。
拓扑配置、容器运行状态、表单草稿各自维护。切换选择、保存和导出前提交草稿；
运行状态刷新不会覆盖用户输入。切换实验时丢弃旧实验的延迟状态响应。
端口连接始终表示双向 veth，不具有路由或流量方向。

``domain/canvas.ts`` 统一画布几何。圆形节点半径为
``max(32, ceil(端口数 * 9 / (2π)))``，名称放在下方，端口分配独立的圆周位置。
旧节点的可选 ``width`` / ``height`` 仍校验并透传，供旧文件往返兼容，
但不再参与显示计算。设备尺寸属性和拉伸手柄已经移除。

``portAnchors`` 在整个拓扑上计算端口位置；开启连线优化时，已连接端口优先占据
朝向对端的空闲圆周位置。``routeLink`` 优先直连，遇到其他设备则尝试一至两次折弯，
选择较短的无碰撞候选；没有可行候选时仍直接连接。这是有限候选启发式算法，
不保证全局最短或消除交叉。关闭优化后使用固定端口位置与贝塞尔曲线。
任何情况下均不修改链路两端的设备 ID 和接口名。
``alignDevices(topology)`` 按原始 x/y 分别排序分组，每组最大跨度为
``ALIGN_TOLERANCE = 24`` 个画布单位，取组内最小坐标作为已有锚点，避免传递吸附和重复点击漂移。
只微调临近行列，不使用连接关系重新排布。碰撞检查包含圆形设备和名称区域，
同时取消发生冲突的移动，再检查恢复位置是否阻挡其他移动，直到稳定。
算法只返回坐标，不修改输入；最多 64 台设备。Store 返回实际移动数量，
只有坐标变化才标记 dirty；工具栏移除模式下拉框和自动 fit，保留缩放与平移。
设备配置、链路和注释位置不变。单测覆盖阈值边界、分组跨度、幂等、输入顺序、
碰撞、32 端口圆形尺寸、空布局及无变化时的保存状态。

拓扑新增可选 ``optimizeLinks`` 布尔值（缺省开启）及 ``annotations`` 数组。
每条注释包含 ``id``、``text``、``x``、``y``、``fontSize``、``color`` 和 ``background``；
前后端共同限制最多 100 条、每条非空且最多 1000 字符、坐标范围 ±100000、
整数字号 12–28、六位十六进制颜色，背景还可用 ``none``。
注释由 ``TopologyAnnotation.vue`` 使用 SVG 文本节点渲染，不解析 HTML；
``annotationBox`` 负责多行排版、自动换行和适应画布边界。
设备与注释拖动均使用 Pointer Events 和捕获，结束、失焦或卸载时释放。
``AnnotationInspector.vue`` 复用 editor 草稿提交机制，应用时保留最新拖动坐标；
无效草稿阻止切换和保存。部署后也可增删和编辑注释，只有操作期间锁定编辑。

画布滚动与运行中布局
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``TopologyCanvas.vue`` 使用 ``overflow: scroll`` 容器提供原生横纵滚动条，
占位区域取 ``scrollBounds`` 算出的内容边界（含负坐标）及额外平移空间；
实际 SVG 通过 ``position: sticky`` 保持视口大小，避免创建巨大的 SVG。
``scrollLeft`` / ``scrollTop`` 与 ``editor.view`` 双向同步，适应画布、缩放和拖动沿用同一坐标系。
ResizeObserver 读取容器 clientWidth/clientHeight，扣除滚动条后再计算可见范围。
滚轮处理支持像素、行、页三种 deltaMode；普通滚轮平移，Shift 横移，Ctrl 围绕鼠标缩放，
取消画布区域的默认滚轮行为以避免页面缩放。视口变化不触发拓扑脏标记，不写入 JSON。

``layoutLocked`` 与 ``locked`` 在忙碌、本地操作或 deploying/updating/destroying 阶段禁用编辑，
不因存在 deployment 而禁止草稿变化。前端保留已应用拓扑与当前草稿，区分视觉保存和网络应用；
新设备在成功应用前不能打开终端，终端/抓包/配置操作须核对真实运行对象。

部署后的“保存项目”通过 ``POST /api/labs/{id}/save`` 提交 topology 并保存受支持运行配置；
兼容旧客户端的纯拓扑保存仍可通过 ``PUT /api/labs/{id}`` 提交完整拓扑。
后端比较运行字段，只有节点身份及运行属性、端口和链路关系一致时才允许写入，
从而支持位置、尺寸、连线显示、注释增删/内容/样式及项目名变化，保留 runtime。
网络字段不同则拒绝普通保存，要求显式应用。兼容旧客户端的 ``POST /api/labs/{id}/layout``
仍只接受完整节点/注释 ID 集合的 id/x/y 和 optimizeLinks，不允许其他字段。
前端视觉保存保留 documentVersion、选中对象与终端，失败保留草稿。

运行中网络修改通过后台任务提交::

  POST /api/labs/{id}/update
  {"topology": {"...": "修改后的完整拓扑"}, "base": {"...": "编辑所基于的已应用拓扑"}}

``lab_updates.py`` 实现增量规划和资源更新；``LabManager.start_update`` 在锁内校验
当前状态、归属、参数和完整规范化 base，拒绝旧页面覆盖更新后的拓扑。
响应为任务接受时的记录，phase 为 updating；前端轮询状态，成功才替换已应用快照并清除待应用标记。
任务成功前，持久化 topology 保留旧版本；失败时前端保留新草稿，后端记录 error 并尝试恢复受影响资源。
发生失败后要求清理再部署，不能承诺原网络完全恢复或全程无中断。

增删节点只操作本实验所属容器。name/image/kind/template/command/config 变化重建对应节点，
未变化节点继续运行；端口、地址、网关及 veth 关系由运行环境增量同步。
空闲端口不会额外创建接口，未连接端口地址和没有活动接口的网关不执行。
容器和 veth 操作前复查标签、网络命名空间、接口 alias 与对端索引，避免删除非本实验资源。
共享配置目录保留，重建前做文件快照；不会自动保存终端运行配置，需由用户提前保存。
删除全部节点可得到 nodes 为空的部署记录，后续仍可应用新设备，清理后回到 idle。

任务开始关闭本实验的终端和抓包会话，其他实验不受影响；应用完成后由用户重新打开。
保存、改名、配置写入、更新、部署与清理遵循同一互斥约束。
HTTP 接口沿用 Bearer/Origin 校验，接口响应与忙状态不能共享可变任务对象。

设备兼容 ``lab_devices.py`` 的内置模板，同时支持导入 ``device.json`` 描述的 ``.rov`` 设备包。
普通设备通过声明启动、保存与持久化规则接入，复杂命令可由 Dockerfile 生成镜像内脚本；
不要求每个新镜像都编写 Python 适配器。
前端校验用于及时反馈，Python 后端仍是 IP、网关和部署约束的最终校验方。

侧边栏与项目命名
----------------------------------------

``SidebarPanel.vue`` 包装左右侧边栏，使用 Pointer Events、捕获及键盘处理调整宽度。
``stores/layout.ts`` 保存首选宽度和收起状态，通过工作区 ResizeObserver 限制实际宽度，
为中间区域保留 460px；窗口变宽后恢复首选值。收起时保留 36px 操作栏，
内容使用 v-show 保留，避免丢失属性草稿和设备库子目录状态。
拖动结束、失焦或卸载时释放捕获及光标。布局状态不参与拓扑脏标记及部署编辑锁。
``lwns-sidebars`` 本地存储读取时校验类型和范围；存储失效不影响当前会话操作。

``ProjectNameDialog.vue`` 共用新建和重命名表单；新建先校验名称，再确认是否放弃原草稿。
名称支持中文、首尾去空白、非空及最多 80 字符，项目身份仍由 ID 决定。
未保存项目只修改本地草稿；已保存项目通过以下接口立即保存名称::

  POST /api/labs/{id}/rename
  {"name": "OSPF 双网段实验"}

响应为 ``{"id":"...","name":"..."}``，接口只接受 name 字段，沿用 Bearer 和 Origin 校验。
``LabManager.rename`` 持锁读取并原子写回当前记录，仅更新名称及更新时间；
允许已有部署，拒绝正在部署/应用/清理的项目；只修改显示名称，不替代拓扑应用。
前端更新名称和列表，不调用 adopt、不更新 documentVersion，不覆盖运行状态、属性草稿或终端标签。
其他未保存的拓扑改动保持未保存，接口失败保留原名称。

设备模板与配置适配器
----------------------------------------

``lab_devices.py`` 的模板包含 ``id``、``version``、``adapter``、``kind``、镜像、
端口默认值、``console`` / ``console_command`` 和 ``capabilities``。
拓扑仍为版本 1，节点新增可选 ``template``；旧节点按 ``kind`` 映射到默认模板。
模板名称、镜像和画布类型分开：前端按模板 ID 创建节点，按能力显示保存按钮。
内置模板来自后端代码，设备包模板来自当前数据目录中的已安装设备定义。
拓扑不能内嵌任意描述、指定宿主机路径或选择未注册的执行器。

适配器接口为 ``prepare``（准备目录并返回 Docker 参数）、``command``、
``started``、``linked``、``config_status`` 和 ``save_config``。
FRR、Linux bridge 和普通 Linux 容器分别实现生命周期钩子；核心管理器负责公共的
归属校验、容器生命周期和 veth。后续可按同一接口扩展其他设备配置方式。

FRR 持久化目录和备份布局见 :doc:`../user/workbench`。
``config-meta.json`` 保存适配器版本、UID/GID、最后一次 Web 保存时间和启动文本哈希。
仅当拓扑的启动文本发生显式变更时才替换 ``frr.conf``，避免覆盖终端 ``write memory``
生成的文件。后续部署按镜像用户修正权限，保留现有协议启用设置。
原有无挂载部署可导出配置后重建；错误挂载则拒绝保存。

* ``GET /api/labs/{id}/configs``：所有设备的持久化状态。
* ``GET /api/labs/{id}/configs/{node}``：单设备磁盘内容、路径和更新时间。
* ``POST /api/labs/{id}/configs``：``{}`` 保存所有支持的设备，``{"node":"r1"}`` 保存单台。
  响应为 ``{results:[{node,ok,status?,config?,error?}],runtime}``。

保存复用部署锁，与部署、拓扑应用、清理互斥，先检查所有启用进程可用；每台独立汇报错误，
成功的配置立即同步拓扑并落盘。前端只更新成功设备及配置预览，不调用 ``adopt``，
因此保留选中设备和终端连接，同时刷新属性草稿并拒绝旧的异步响应。
当前 FRR 文本沿用每设备 32768 字符限制。备份目前不自动轮转，应按需归档。
完整迁移需复制数据目录；Compose/YAML 项目迁移属于后续阶段。

.rov 设备包与通用配置生命周期
----------------------------------------

``lab_device_schema.py`` 使用标准库校验并规范化 ``device.json``，拒绝未知字段、
重复 JSON 键及无效路径；当前 ``schema_version`` 为 1。
完整示例位于 ``examples/device-packages/frr/`` 与 ``examples/device-packages/config-demo/``，
每个目录只有设备描述和 Dockerfile。后者仅演示原生文件保存，不宣称能保存全部 Linux 网络状态。
用户操作见 :doc:`../user/workbench-devices`。

当前 Docker 生命周期入口要求镜像提供 ``/bin/sh``、``sleep``、``tr`` 和 ``grep``；
解析非数字属主还需要 ``id`` / ``awk``。Alpine BusyBox 可提供这些工具。
服务命令应保持前台运行，默认配置或 prepare 步骤需在首次服务启动前准备好声明的配置文件。
当前不支持缺少这些运行工具的极简无 Shell 镜像。

描述中必需的 ``actions.save_config`` 包含 ``exec`` 参数数组、超时和保存结果文件检查。
``persistent_dirs`` 描述容器内目录、首次默认文件来源及属主权限；宿主机路径由平台生成。
``startup`` 描述准备步骤、服务进程、配置文件及就绪检查；通用 profile 必须提供 ready，
FRR profile 使用已有协议进程检查。分类不参与选择 FRR 或 Linux bridge 行为。
保存动作在对应容器执行，不提供宿主机命令入口；阶段和有界日志写入部署日志。

``lab_device_packages.py`` 负责规范化、确定性打包、完整性检查和版本库。
包内有 ``device.json``、工具生成的 ``manifest.json``，以及来源需要的 ``image.tar`` 或 Dockerfile。
校验资源大小、SHA256、重复成员、路径、文件类型和 ZIP 内容；检查包不会执行设备动作。
镜像归档需为未压缩 Docker save 格式，并包含描述指定的镜像；
设备包的清单与 Docker 镜像内部的 ``manifest.json`` 是两层不同的文件。

``DeviceLibrary`` 位于每个 ``LabManager`` 的数据目录，不修改进程级全局 ``CATALOG``。
定义 ID＋版本生成长度兼容现有拓扑的 ``rov-...`` 模板键；
目录条目记录原始包校验值、显示别名和实际镜像 ID。
拓扑节点保存模板键和固定镜像 ID，禁止覆盖托管设备的镜像或启动命令。
每个新建节点使用独立实例 ID；旧节点仍可读取，显示名称与配置目录分离。
``manager.template`` / ``manager.adapter`` / ``manager.validate`` 是部署、保存、终端及增量拓扑的统一解析入口。

``lab_device_runtime.py`` 执行声明式生命周期：

* 首次暂存默认配置并验证文件树、属主和权限，再创建 RW 挂载；后续只重用原实例目录。
* 使用 Docker init 与只读 bootstrap 启动入口等待平台信号；接口准备完成后 exec 声明的服务，
  等待实际进程替换及设备 ready 检查。不能把长期服务放到无监督的 detached exec 中。
* ``container`` 阶段允许提前启动；``after_links`` 阶段在接线后启动。
  ``after_links`` 动作与 ``after_link_added`` 动作用于接线后的配置，未变设备不重启。
* 保存前检查归属和 RW 挂载、就绪状态，备份后执行动作并校验必要文件，再写入保存时间。
  通用状态返回 ``paths`` 和 ``files: [{path, size}]``；不把所有文件内容放入拓扑 JSON。
* ``profile: frr`` 复用已有 FRR 默认配置、权限、协议进程、内容检查和备份机制，
  保留内置 FRR 模板的数据格式。配置记录追加设备定义身份，不能把另一版本强行应用到旧实例目录。

``lab_device_service.py`` 将公共包模块接入流式上传和后台任务，使用独立的
``device-packages/uploads``、``jobs``、``artifacts`` 目录。
注册设备前先验证并准备镜像；失败不会生成可部署卡片，上传可重试。
与镜像任务及部署共享互斥标志，旧镜像删除也检查设备定义引用。
删除库条目不删除实例配置或 Docker 镜像，项目引用的版本禁止删除。

HTTP 接口沿用 Bearer、同源与请求大小校验：

* ``GET /api/device-packages``、``POST /api/device-packages/refresh``：设备版本及任务状态。
* ``POST /api/device-packages/uploads``：``{name,size,kind:"package"|"archive"}``；
  ``PUT /api/device-packages/uploads/{id}`` 上传二进制，``DELETE`` 回收未使用资源。
* ``POST /api/device-packages/inspect``：``{upload_id}``，只检查设备包。
* ``POST /api/device-packages/jobs``：``mode=pack`` 制作，``mode=import`` 导入，返回 202。
* ``GET /api/device-packages/artifacts/{job_id}``：经过认证下载制作完成的包。
* ``PATCH /api/device-packages/{id}``：``{name}`` 修改库显示名；``DELETE`` 删除未引用的定义。

``lab_device_cli.py`` 与 Web 使用同一套包模块，源码入口为
``python3 script/python/lab_server.py device ...``，冻结入口为 ``lwns device ...``。
pack/inspect 在导入 Web 依赖前分流，能够独立运行；import 使用与后端相同的数据目录锁，
防止 CLI 与运行中的服务竞争清单。目录包启动脚本将 device 子命令直接交给可执行文件。

测试入口为 ``test_device_packages.py``、``test_device_package_api.py`` 和
``test_device_runtime.py``；真实 Docker 恢复测试需要显式启用
``LWNS_DEVICE_DOCKER_TESTS=1`` 并以 root 执行 ``test_device_runtime_docker.py``。
浏览器验证使用 ``serve_device_package_fixture.py`` 的模拟 Docker，
``check_device_packages.cjs`` 覆盖制作、下载、导入、名称、引用保护及设备库同步。

镜像服务与设备库
----------------------------------------

``lab_images.py`` 的 ``ImageService`` 负责 Docker 清单核对、流式上传、后台任务和原子持久化。
``config/images.defaults.json`` 只在运行时清单缺失时初始化；运行数据位于数据目录的
``images/registry.json``、``images/jobs/<任务ID>.json`` 和临时 ``images/uploads/<上传ID>/``。
子目录布局避免镜像清单被实验的 ``*.json`` 扫描误识别。临时文件在完成/失败时回收，
重启将未结束任务标为失败并清理残留工作目录；历史任务保存日志尾部，API 返回最近 30 项。

接口均沿用 Bearer 令牌和 Origin 校验：

* ``GET /api/catalog``：从镜像管理清单生成设备卡片；真实模式仅包含已加载且绑定类型的镜像。
* ``GET /api/images``、``POST /api/images/refresh``：缓存快照/主动核对 Docker。
* ``POST /api/images/uploads``：登记文件名、大小与 archive/context 类型；
  ``PUT /api/images/uploads/{id}`` 使用原始二进制流上传；``DELETE`` 回收未使用上传。
* ``POST /api/images/jobs``：pull/url/archive/build/local/forget 任务，返回 202；删除由
  ``DELETE /api/images/{id}`` 创建后台任务，成功后才移除管理记录。
* ``PUT /api/images/{id}``：修改显示名称和绑定模板。

普通 JSON 限制 1 MiB，拓扑更新的 topology/base 请求体限 2 MiB（单个拓扑仍限 1 MiB）；大文件使用 ``request.stream()`` 分块写盘，不读入完整内存。
执行使用参数数组，不经过宿主机 shell。构建上下文拒绝路径逃逸、链接、特殊文件和解压超限。
镜像归档仅支持未压缩 tar；前端及上传登记 API 对 archive 类型要求 ``.tar`` 扩展名。
上传与 URL 下载共用 ``validate_load_archive``，通过 ``tarfile.open(..., "r:")`` 检查原始 tar 格式，
拒绝压缩归档或非 tar 内容，随后将原文件直接传给 ``docker load --input``。
URL 不强制后缀，内容校验不可绕过；不解压、不复制成另一份 tar、不展开内部文件或限定 Docker/OCI 清单格式。
任务 finally 回收上传/下载文件；Dockerfile 构建上下文的解压逻辑独立保留。
Docker 返回缺少 manifest.json 时保留原错误并补充归档来源说明，不回退为 docker import。
任务开始与部署互斥；镜像任务执行中拒绝新部署，允许清理已有实验。
删除前核对保存实验及 Docker 全部容器，使用非强制删除；失败后重新核对实际镜像，
避免多镜像归档部分成功后 UI 与 Docker 状态不一致。

管理范围由持久化清单明确限定，``sync`` 只更新记录状态，不将 Docker 全机库存追加到清单。
``snapshot``、``catalog`` 与按 ID 操作均校验受支持的管理来源；导入只登记命令明确返回的引用，
不认领同时出现的无关镜像、构建中间镜像或其他同 ID 标签。部分导入失败后未登记的镜像可显式引用。
``mode=local`` 按完整引用登记本机已有镜像；``mode=forget`` 只移除记录，不检查或删除容器/实验。
任务新建标签才记录 ``owned_image_id``；已拥有的标签可由项目任务更新，已有引用不会自动获得归属。
API 提供 ``can_delete``，执行删除前重新同步并校验标签与归属 ID；外部替换/删除会撤销归属，
纯镜像 ID/digest 不允许物理删除，避免误删共享标签。前端默认调用 forget，只有明确删除时调用 DELETE。
旧版 ``discovered`` 条目无名称/模板定制则从清单剔除，有定制则迁移为受保护 local 引用；
旧导入记录保留但不推断创建归属。迁移不执行 Docker 操作，清单版本仍为 1。

前端 ``stores/images.ts`` 管理上传进度、任务和每 2 秒轮询，拒绝旧响应覆盖新任务；
``ImageManager.vue`` 提供清单、导入表单、设置与日志。清单元数据变化或任务结束时刷新设备目录和环境；
列表包含状态筛选与数量概览，四种来源入口及引用保护提示；日志可折叠，执行任务时展开，
用户向上滚动后不再强制跟随输出。移出/删除后清理已失效的设置选择。
刷新失败保留旧同步标记，下次轮询重试。``refreshCatalog`` 使用请求序号拒绝过期响应。
``DeviceLibrary.vue`` 使用 router/switch/host/firewall 四个横向分类入口；初始 selected=null，
只有进入子目录才渲染对应分类，双列圆形设备每批 60 项，不再提供搜索框或查询状态。
分类入口和设备圆形背景通过 ``--device-color`` 使用 ``domain/topology.colors``，与画布共用类型配色；
设备条目外层透明无方框，圆形直径 40px、内部 SVG 25px，行列间距 4px；
名称/镜像在圆形下方，悬停和键盘焦点以圆环提示。
子分类标题不设返回按钮，点击顶部类别直接切换并重置分页与滚动；
方向键与 Home/End 可切换分类，焦点停留在对应分类按钮。
目录刷新保留当前类别，只更新卡片和数量；折叠侧栏保留状态，刷新页面回到分类首页。
没有“全部”平铺列表、侧栏镜像管理按钮或底部连接提示；镜像管理统一从顶部“工具”菜单按需加载。
``domain/library.ts`` 统一分类和镜像类型选项。防火墙使用 ``linux-firewall`` 模板与既有 Linux 适配器，
新增 kind、图标和 FW 命名前缀，不包含防火墙规则编排或持久化功能。
``ImageService.catalog`` 不再预先加入 CATALOG 固定卡片；CATALOG 仅定义设备适配能力。
已删、解绑及未加载条目不会出现在真实模式设备库；设计模式允许仍存在的未加载绑定记录，显式标注 present=false。
动态卡片 ``id`` 为镜像记录派生 ID，``template_id`` 指向已注册模板；创建拓扑节点时
写入基础 ``template_id``，保证后端适配器匹配和旧拓扑格式兼容。
能力查找同样按基础模板 ID 解析，不能将动态卡片 ID 误当适配器 ID。
镜像导入不等于新增厂商适配器，也不改变当前 FRR 配置保存范围。

抓包服务与本地启动器
----------------------------------------

``lab_capture.py`` 的 ``CaptureService`` 管理内存会话、启动、数据流和启动结果回报的一次性凭证和 tcpdump 子进程。
``LabManager.capture_target`` 核对实验/部署标签、两端容器当前 PID、veth alias、ifindex
及对端索引。启动抓包时打开网络命名空间 FD 并重新验证，子进程通过该 FD 进入命名空间，
降低 PID 重用风险。每 3 秒复查目标；运行时间不超过 60 分钟。

协议分为：

* ``GET /api/capture/capabilities`` 和 ``GET /api/capture/client``：环境能力及客户端 ZIP，沿用 Bearer/Origin。
* ``GET/POST /api/labs/{id}/captures``：列表/创建会话；创建输入 ``link``、``side``、``filter``、``snaplen``。
* ``DELETE /api/labs/{id}/captures/{session}``：停止指定会话，保留已结束状态供 UI 查看。
* ``POST /api/capture/claim``：本地启动器用 5 分钟启动凭证兑换独立流凭证与一次性客户端回报凭证；不需要长期 Web 令牌。
* ``POST /api/capture/client-report``：使用独立一次性凭证报告本地启动结果、手动认证模式和目标文件路径。
  路径只作显示信息，不能指定宿主机文件操作；此接口不能将会话标为 running，启动失败可结束 pending 会话。
* ``POST /api/capture/stream``：只允许回环来源，使用独立 5 分钟凭证。成功返回 PCAP 二进制流，
  不使用 PTY；请求上限 4 KiB，不允许重定向凭证到其他目标。

三种单次凭证均由服务端生成，绑定同一抓包会话，不可互换。会话最多 8 个，结束历史最多保留
最近 50 项，所有凭证在重启后失效；数据流不写入实验文件。只有验证 PCAP 文件头后才进入
running，stderr 单独保存有界日志。数据块最大 64 KiB，按客户端读取速度提供背压。
停止、流断开、目标变化和后端生命周期结束时终止进程组；清理实验同步关闭其抓包会话。

``clients/capture/launcher.py`` 注册后的入口接收完整 ``lwns://capture`` 链接；``lwns://configure?server=...`` 只打开本地连接设置。
本地配置按可信后端 origin 隔离，URL 只携带启动凭证；SSH 目标由用户本地配置确定。
通过 tshark 检测实际接口名及偏好前缀（Windows 的 ``sshdump.exe`` 可对应 ``sshdump_exe``），
复用 Wireshark Profile，以进程参数覆盖捕获命令，不读取/转存 Profile 密码。
仅接受图形程序 Wireshark；检查指定 Profile、检测启动提前退出，并在 Windows 尝试前置窗口。
每会话创建唯一输出目录，使用 ``-w``、``-o capture.pcap_ng:TRUE`` 和 ``-S`` 指定本机文件及实时显示；
通过一次性回报接口通知 Web 路径和认证模式。启动器持续排空子进程 stderr 并等待 GUI 退出，
避免提前关闭 stderr 管道；日志有界且隐藏凭证，不记录完整启动 URI。
``remote_relay.py`` 由固定代码通过 SSH 执行，普通 SSH 用户访问宿主机回环流接口并转发 stdout；
stdin EOF/SIGHUP/SIGTERM 结束转发。后台 root 权限不需要授予 SSH 用户。

Windows 使用 PowerShell Forms 配置和当前用户协议注册；Linux 使用 Tk/终端配置及 desktop entry。
可在 Windows 通过 PyInstaller 构建独立 exe，具体命令见 ``clients/capture/README.md``。
下载 API 使用固定文件清单打包，存在 ``clients/capture/dist/lwns-capture.exe`` 时附带独立版；
发布源码之外还需保留 ``clients/capture``，不能只复制 Python 和前端目录。

``stores/captures.ts`` / ``CaptureManager.vue`` 管理端点选择、BPF、启动 URI、环境提示及状态轮询。
切换实验忽略过期响应，并回收迟到的创建结果；关闭窗口保持后台会话。原生协议被浏览器拦截时
使用“准备抓包 → 点击链接打开本机程序”两步流程，避免异步 location 跳转丢失用户点击上下文。
界面不将程序启动当作抓包成功；展示手动认证步骤、启动结果及可复制的本机目标路径。

构建与发布
----------------------------------------

.. code-block:: bash

   npm --prefix web run build

该命令先执行 ``vue-tsc`` 检查组件和 TypeScript，再生成 ``web/dist``。
将构建产物随项目复制到 Linux，运行::

  sudo .venv/bin/python script/python/lab_server.py --host 0.0.0.0 --port 8090

Python 提供 ``web/dist/index.html`` 和 ``web/dist/assets/``；生产环境不运行 Vite，
也不需要 Node.js 或 npm。Python 依赖见 ``script/python/requirements.txt``。
可用 ``--web-dir`` 指定其他构建目录。
HTTP 服务不会暴露 ``web/src``、锁文件或项目其他源代码。
构建产物与 ``node_modules`` 被 Git 忽略；在新检出或发布流程中须先运行构建。

Linux 目录包由 ``packaging/linux/build.py`` 构建，PyInstaller onedir 内包含前端、运行库和
固定清单中的模板、示例与抓包客户端脚本。构建配置、系统目录安装、升级与卸载见
:doc:`../user/workbench-install`。构建输出 ``release/`` 和构建虚拟环境 ``.venv-build/`` 不提交。

``lab_paths.py`` 统一源码/冻结程序的资源路径；冻结程序默认数据目录为 ``/var/lib/lwns``，
源码默认仍为 ``.lwns-labs``。所有 Docker、终端和抓包子进程使用 ``host_environment()``
恢复宿主机动态库路径，避免 PyInstaller 的 LD_LIBRARY_PATH 影响系统命令。
测试使用 ``test_packaging.py`` 以及 ``check_linux_package.py <归档路径>``；后者在临时根目录
验收真实打包程序和安装脚本，不替换正在运行的系统服务。版本包采用 BUILD_ID 目录，配置和数据不随程序替换。

设备终端与会话生命周期
----------------------------------------

``lab_server.py`` 提供 FastAPI 应用，阻塞的文件和 Docker 操作在线程中执行。
``lab_core.py`` 管理拓扑和部署，``lab_updates.py`` 负责运行中增量拓扑应用，
``lab_terminal.py`` 管理交互会话。
服务保持单进程运行，数据目录锁、后台部署任务、连接凭证和会话共享同一实例。
Linux、Docker 和 root 权限要求保持不变，使用方法见 :doc:`../user/workbench`。

1. 前端以 Bearer 令牌调用 ``POST /api/labs/{id}/terminals``，传入设备 ID 和
   ``default`` 或 ``shell`` 模式。后端检查设备归属，签发有效期 30 秒的一次性凭证。
2. 前端连接 ``/api/terminal``，在首条 JSON 消息中发送 ``connect``、凭证及行列数。
   令牌和凭证均不放进 WebSocket URL。服务核验 Origin、凭证、部署版本和容器状态。
3. 后端分配 Linux PTY，启动交互式 ``docker exec``。输入与尺寸变化使用 JSON，
   输出使用二进制帧，保持 UTF-8 和 ANSI 序列的字节边界。
4. 浏览器在 xterm.js 完成写入后发送 ``ack``，服务才继续发送下一块，避免输出
   无限堆积。每块最多 16 KiB，输出确认等待上限 30 秒；WebSocket 帧上限 64 KiB。
5. 会话每三秒复查设备状态。断开、清理或服务退出时结束 Docker 客户端，并根据
   随机环境标识回收容器内对应会话进程；不会通过容器名称替换已记录的容器 ID。

输入只写入容器终端，不通过宿主机 shell 解释。启动校验仅短暂持有部署锁，
不会在整个交互会话期间占用它。原有 ``/exec`` 接口继续兼容。

验证
----------------------------------------

.. code-block:: bash

   npm --prefix web run format:check
   npm --prefix web run typecheck
   npm --prefix web test
   npm --prefix web run build
   .venv/bin/python -m pip install -r tests/requirements.txt
   .venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v

使用 ``npm --prefix web run format`` 统一前端代码格式。
依赖更新后提交 ``package-lock.json``，在其他机器使用 ``npm ci`` 复现版本。

``tests/check_workbench.cjs`` 在真实 Chromium 中验证圆形设备、单按钮临近行列对齐与视口保持、端口与连线一致性、
注释编辑和拖动、保存、导入导出及重新加载，既可检查 Python 提供的构建页面，
也可检查 Vite 开发页面。``web/tests/canvas.test.ts`` 覆盖圆形端口、绕行、
对齐边界、注释校验、草稿和部署保护；``tests/test_lab.py`` 验证新字段持久化及非法请求拒绝。
``tests/check_sidebar_projects.cjs`` 验证实际侧边栏拖动、收起、键盘调宽、刷新恢复、窄窗口布局，
以及中文命名、取消、空白校验、保存与改名时保留未保存属性。
两个浏览器脚本都应连接独立的设计模式后端，不使用日常实验数据。例如先构建前端，然后运行::

  LWNS_TOKEN=layout-browser-check .venv/bin/python script/python/lab_server.py \
    --preview --port 8097 --data-dir /tmp/lwns-layout-check

本例数据目录必须是全新空目录。在已开启远程调试端口的专用 Chromium 测试实例上运行::

  node tests/check_sidebar_projects.cjs http://127.0.0.1:9348 \
    'http://127.0.0.1:8097/#token=layout-browser-check' /tmp/lwns-layout-results

脚本使用 Node.js 22+，创建并删除自己的测试项目，输出断言结果和截图。
``web/tests/layout.test.ts`` / ``web/tests/project-name.test.ts`` 覆盖布局存储和命名状态；
``tests/test_lab.py`` 覆盖改名 API 的认证、参数、持久化及部署保护。
Docker/netns 行为测试使用模拟执行器，真实容器连通性仍须在 Linux 主机验收。

``tests/check_canvas_navigation.cjs`` 验证实际原生滚动条拖动、普通/Shift/Ctrl 滚轮、
鼠标缩放锚点、运行中移动与对齐、增改删注释纯保存，以及设备/连线草稿、
应用期间编辑锁、应用后保留不变容器、地址更新和删除同步、刷新恢复。
使用独立 ImageHost/FakeHost 服务提供运行中的实验，不操作 Docker；先启动专用 Chromium 调试端口，然后运行::

  .venv/bin/python tests/serve_canvas_fixture.py --port 8106
  node tests/check_canvas_navigation.cjs http://127.0.0.1:9350 \
    'http://127.0.0.1:8106/#token=canvas-scroll-check' /tmp/canvas-navigation-results

每次验证使用新启动的 fixture 服务；停止服务即回收临时数据目录。

运行中拓扑应用另有两组后端测试：

* ``tests/test_topology_update.py`` 的 16 项测试覆盖增删容器和 veth、
  属性重建、地址同步、保留未变化设备、资源归属、空部署和失败恢复。
* ``tests/test_topology_update_api.py`` 的 5 项测试覆盖认证与 Origin、
  JSON 请求体限制、base 版本校验、关闭相关终端/抓包会话和退出时等待任务。

2026-10-25 验收：111 项前端测试通过；Python 共 135 项，其中 129 项通过，
6 项需要显式启用的真实 Docker 测试跳过。主工作台及运行中画布浏览器回归通过；
这些测试使用模拟执行器，未操作真实 Docker 或正式服务，不能替代真实容器连通性验收。


``tests/test_terminal.py`` 包含凭证、Origin 和归属检查，并提供显式启用的真实
Docker 终端测试。浏览器终端测试可先运行 ``tests/serve_terminal_fixture.py``，
它创建两台独立测试设备，退出时清理；再运行::

  node tests/check_terminal.cjs http://127.0.0.1:9340 \
    'http://127.0.0.1:8098/#token=terminal-browser-check' /tmp/terminal-check

需预先启动指定调试端口的 Chromium。该测试验证键盘输入、FRR 配置、多标签、
实时输出、Ctrl+C、拖动尺寸同步、放大、重连和关闭连接。

``tests/test_configs.py`` 验证共享目录、备份、显式启动配置替换、旧容器导出、
部分失败和权限/归属边界；``web/tests/configs.test.ts`` 验证保存后保留终端、
更新草稿及拒绝过期响应。真实 FRR/veth 测试需要 Linux root::

  sudo env LWNS_CONFIG_DOCKER_TESTS=1 .venv/bin/python -m unittest discover -s tests -p 'test_config_docker.py' -v

浏览器完整流程测试使用独立临时数据目录，不修改现有实验::

  sudo .venv/bin/python tests/serve_config_fixture.py --port 8102
  node tests/check_configs.cjs http://127.0.0.1:9343 \
    'http://127.0.0.1:8102/#token=config-browser-check' /tmp/config-check

需先启动指定调试端口的 Chromium。完成后停止 fixture 服务，会清理它创建的设备和文件。

``tests/test_images.py`` 覆盖清单持久化、导入/删除同步、引用保护、路径边界及上传 API。
还覆盖全机镜像不自动纳入、旧清单迁移、已有镜像引用、移出清单保留本地镜像、
新建标签的删除权限、外部替换撤销归属，以及绕过前端直接调用删除接口的保护。
另覆盖 tar 上传/URL 原文件直传、非 tar 扩展名、压缩包伪装 tar、无效内容、
Docker 拒绝归档时的错误提示和临时文件回收。
仅验证真实 tar 上传与 URL 加载（无需 registry 镜像）可执行::

  PYTHONPATH=tests LWNS_IMAGE_DOCKER_TESTS=1 .venv/bin/python -m unittest test_images_docker.ImageDockerTests.test_tar_upload_and_url_load_directly -v

真实镜像测试使用随机标签、临时文件和本机临时仓库，不推送到外部仓库；
需要可访问 Docker，且本机已存在 ``registry:2``::

  LWNS_IMAGE_DOCKER_TESTS=1 .venv/bin/python -m unittest discover -s tests -p 'test_images_docker.py' -v

浏览器测试使用 ``tests/serve_image_fixture.py --large-library --metadata /tmp/image-check/fixture.json``，
它只向测试目录注入 200 张模拟设备卡片，并为真实导入准备隔离归档。
将生成的 ``fixture.json`` 及其 ``archive`` 指向的文件（命名为 ``image.tar``）放入浏览器
测试输出目录，启动 Chromium 调试端口后执行::

  node tests/check_images.cjs http://127.0.0.1:9344 \
    'http://127.0.0.1:8104/#token=image-browser-check' /tmp/image-check

验证长设备列表、分类切换、固定分类导航、归档和 URL 导入、Dockerfile 构建、设置、删除及刷新恢复。
停止 fixture 后清理其专属镜像及临时文件，不操作现有实验。

``tests/serve_library_fixture.py`` 使用 ImageHost 模拟 200 个镜像条目及镜像任务，不执行宿主机命令。
``tests/check_managed_images.cjs`` 复用该 fixture，验证管理范围、显式引用、移出与删除、
状态筛选、搜索、日志折叠及 1000px 窗口布局；第三个参数为截图输出目录::

  node tests/check_managed_images.cjs http://127.0.0.1:9222 'http://127.0.0.1:8107/#token=library-check' /tmp/managed-images-check

``tests/check_library_groups.cjs`` 验证横向分类入口、单分类子目录、双列卡片、搜索框已移除、
无返回按钮及分类键盘导航、分批加载、默认镜像删除、防火墙导入、改类型、取消绑定及刷新后不恢复已删条目；
同时检查窄窗口下画布引导不遮挡控件，日志面板最大高度不超出窗口。每次验证启动新的 fixture::

  .venv/bin/python tests/serve_library_fixture.py --port 8107
  node tests/check_library_groups.cjs http://127.0.0.1:9351 \
    'http://127.0.0.1:8107/#token=library-check' /tmp/library-results

抓包验证
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``test_capture.py`` 覆盖凭证过期/重放、归属与两端接口核对、PCAP 头、错误过滤器、停止/断线、
回环限制、下载认证以及本地启动器输入边界；前端 ``captures.test.ts`` 覆盖链接内容和异步状态隔离。
真实 veth 抓包测试在 root/Linux 环境显式运行::

  sudo env LWNS_CAPTURE_DOCKER_TESTS=1 .venv/bin/python -m unittest discover -s tests -p 'test_capture_docker.py' -v

它创建两个独立 Linux 容器，分别抓取两端 ICMP 请求/回复，验证 BPF 和进程回收。
普通用户转发验证可先以 root 启动独立 ``serve_capture_fixture.py --metadata /tmp/capture-check/fixture.json``
（需先创建 metadata 的父目录），再以普通用户运行 ``check_capture_relay.py --metadata ... --output ...``。
后者不要求 sudo；测试产生 ping 的步骤需要 Docker 权限，产品转发程序本身不需要。

``check_capture_ssh.py`` 使用真实本机 tshark/sshdump 和指定的现有 Profile，通过 SSH 抓取同一
隔离 fixture 的流量，命令参数见文件头。``serve_capture_ui.cjs`` + ``check_capture_ui.cjs`` 是
独立的 UI 模拟验证，仅模拟运行状态和抓包状态，不接触 Docker 或 SSH；真实桌面协议唤起仍需
在目标 Windows/Linux 浏览器与 Wireshark 版本下验证。
