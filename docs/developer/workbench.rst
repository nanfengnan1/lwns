Vue 工作台开发
========================================

工作台前端位于 ``web/``，使用 Vue 3 单文件组件、TypeScript、Vite 和 Pinia。
Python 后端使用 FastAPI / Uvicorn，负责实验持久化、Docker 生命周期及 veth 操作。
前后端通过 ``/api`` 通信，设备终端通过同端口 WebSocket 连接。

本地开发
----------------------------------------

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

  ROUTE_OVS_API_TARGET=http://Linux主机IP:8090

修改后重启 Vite。该设置仅供开发服务器代理使用，生产环境前端与后端使用同一源。
令牌由访问页面时输入，不写入环境文件或前端构建产物。
代理同时支持 HTTP 与 WebSocket，只改写当前开发页面的同源 Origin，
后端仍会拒绝其他站点的 Origin。Windows 使用独立的 ``.venv\Scripts\python.exe``。

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
``alignDevices`` 支持按连通关系分层、横排、竖排和网格，只返回新设备坐标，
保持设备配置、链路和注释位置不变。

拓扑新增可选 ``optimizeLinks`` 布尔值（缺省开启）及 ``annotations`` 数组。
每条注释包含 ``id``、``text``、``x``、``y``、``fontSize``、``color`` 和 ``background``；
前后端共同限制最多 100 条、每条非空且最多 1000 字符、坐标范围 ±100000、
整数字号 12–28、六位十六进制颜色，背景还可用 ``none``。
注释由 ``TopologyAnnotation.vue`` 使用 SVG 文本节点渲染，不解析 HTML；
``annotationBox`` 负责多行排版、自动换行和适应画布边界。
设备与注释拖动均使用 Pointer Events 和捕获，结束、失焦或卸载时释放。
``AnnotationInspector.vue`` 复用 editor 草稿提交机制，应用时保留最新拖动坐标；
无效草稿阻止切换和保存。新增/删除注释及编辑内容仍遵循部署编辑锁。

画布滚动与运行中布局
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``TopologyCanvas.vue`` 使用 ``overflow: scroll`` 容器提供原生横纵滚动条，
占位区域取 ``scrollBounds`` 算出的内容边界（含负坐标）及额外平移空间；
实际 SVG 通过 ``position: sticky`` 保持视口大小，避免创建巨大的 SVG。
``scrollLeft`` / ``scrollTop`` 与 ``editor.view`` 双向同步，适应画布、缩放和拖动沿用同一坐标系。
ResizeObserver 读取容器 clientWidth/clientHeight，扣除滚动条后再计算可见范围。
滚轮处理支持像素、行、页三种 deltaMode；普通滚轮平移，Shift 横移，Ctrl 围绕鼠标缩放，
取消画布区域的默认滚轮行为以避免页面缩放。视口变化不触发拓扑脏标记，不写入 JSON。

``layoutLocked`` 在忙碌、部署/清理阶段或本地操作期间禁用位置修改；
``locked`` 额外检查部署记录，继续禁止拓扑增删及属性编辑。
运行中可移动设备和已有注释、自动对齐及切换连线优化；顶部“保存布局”使用::

  POST /api/labs/{id}/layout
  {"nodes":[{"id":"r1","x":100,"y":200}],"annotations":[],"optimizeLinks":true}

nodes/annotations 必须完整覆盖已保存项目的各自 ID 集合；只接受 id/x/y，
禁止未知、重复、缺失 ID 和额外配置字段，坐标必须有限且范围 ±100000。
``LabManager.save_layout`` 持锁读取最新记录并原子写回，不执行宿主机命令，
保留非布局字段及 runtime。接口沿用 Bearer/Origin 检查，忙碌或部署/清理阶段拒绝写入。
普通 PUT 仍拒绝修改已部署拓扑。前端仅在成功后清除脏标记，不替换设备对象、
运行状态或 documentVersion，因此保留选中设备和终端连接；保存失败保留草稿。

设备由 ``lab_devices.py`` 的模板目录和适配器注册表描述；兼容现有模板的新镜像可直接在
Web 镜像管理中绑定，新增设备行为才需要注册模板及适配器。
前端校验用于及时反馈，Python 后端仍是 IP、网关和部署约束的最终校验方。

侧边栏与项目命名
----------------------------------------

``SidebarPanel.vue`` 包装左右侧边栏，使用 Pointer Events、捕获及键盘处理调整宽度。
``stores/layout.ts`` 保存首选宽度和收起状态，通过工作区 ResizeObserver 限制实际宽度，
为中间区域保留 460px；窗口变宽后恢复首选值。收起时保留 36px 操作栏，
内容使用 v-show 保留，避免丢失属性草稿和设备库筛选。
拖动结束、失焦或卸载时释放捕获及光标。布局状态不参与拓扑脏标记及部署编辑锁。
``route-ovs-sidebars`` 本地存储读取时校验类型和范围；存储失效不影响当前会话操作。

``ProjectNameDialog.vue`` 共用新建和重命名表单；新建先校验名称，再确认是否放弃原草稿。
名称支持中文、首尾去空白、非空及最多 80 字符，项目身份仍由 ID 决定。
未保存项目只修改本地草稿；已保存项目通过以下接口立即保存名称::

  POST /api/labs/{id}/rename
  {"name": "OSPF 双网段实验"}

响应为 ``{"id":"...","name":"..."}``，接口只接受 name 字段，沿用 Bearer 和 Origin 校验。
``LabManager.rename`` 持锁读取并原子写回当前记录，仅更新名称及更新时间；
允许已有部署，拒绝正在部署/清理的项目，不放宽普通 PUT 拓扑的编辑锁。
前端更新名称和列表，不调用 adopt、不更新 documentVersion，不覆盖运行状态、属性草稿或终端标签。
其他未保存的拓扑改动保持未保存，接口失败保留原名称。

设备模板与配置适配器
----------------------------------------

``lab_devices.py`` 的模板包含 ``id``、``version``、``adapter``、``kind``、镜像、
端口默认值、``console`` / ``console_command`` 和 ``capabilities``。
拓扑仍为版本 1，节点新增可选 ``template``；旧节点按 ``kind`` 映射到默认模板。
模板名称、镜像和画布类型分开：前端按模板 ID 创建节点，按能力显示保存按钮。
模板注册来自后端代码，拓扑不能指定宿主机路径或任意适配器实现。

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

保存复用部署锁，与部署、清理互斥，先检查所有启用进程可用；每台独立汇报错误，
成功的配置立即同步拓扑并落盘。前端只更新成功设备及配置预览，不调用 ``adopt``，
因此保留选中设备和终端连接，同时刷新属性草稿并拒绝旧的异步响应。
当前 FRR 文本沿用每设备 32768 字符限制。备份目前不自动轮转，应按需归档。
完整迁移需复制数据目录；Compose/YAML 项目迁移属于后续阶段。

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
* ``POST /api/images/jobs``：pull/url/archive/build 任务，返回 202；删除由
  ``DELETE /api/images/{id}`` 创建后台任务，成功后才移除管理记录。
* ``PUT /api/images/{id}``：修改显示名称和绑定模板。

JSON 仍限制 1 MiB；大文件使用 ``request.stream()`` 分块写盘，不读入完整内存。
执行使用参数数组，不经过宿主机 shell。构建上下文拒绝路径逃逸、链接、特殊文件和解压超限。
任务开始与部署互斥；镜像任务执行中拒绝新部署，允许清理已有实验。
删除前核对保存实验及 Docker 全部容器，使用非强制删除；失败后重新核对实际镜像，
避免多镜像归档部分成功后 UI 与 Docker 状态不一致。

前端 ``stores/images.ts`` 管理上传进度、任务和每 2 秒轮询，拒绝旧响应覆盖新任务；
``ImageManager.vue`` 提供清单、导入表单、设置与日志。清单元数据变化或任务结束时刷新设备目录和环境；
刷新失败保留旧同步标记，下次轮询重试。``refreshCatalog`` 使用请求序号拒绝过期响应。
``DeviceLibrary.vue`` 提供 router/switch/host/firewall 四组可折叠条目，每组每批 60 项，
搜索名称/镜像时自动展开结果，清除后恢复折叠状态；没有“全部”平铺入口。
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

``clients/capture/launcher.py`` 注册后的入口接收完整 ``route-ovs://capture`` 链接；``route-ovs://configure?server=...`` 只打开本地连接设置。
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
下载 API 使用固定文件清单打包，存在 ``clients/capture/dist/route-ovs-capture.exe`` 时附带独立版；
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

设备终端与会话生命周期
----------------------------------------

``lab_server.py`` 提供 FastAPI 应用，阻塞的文件和 Docker 操作在线程中执行。
``lab_core.py`` 继续管理拓扑和部署，``lab_terminal.py`` 管理交互会话。
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

``tests/check_workbench.cjs`` 在真实 Chromium 中验证圆形设备、四种对齐、端口与连线一致性、
注释编辑和拖动、保存、导入导出及重新加载，既可检查 Python 提供的构建页面，
也可检查 Vite 开发页面。``web/tests/canvas.test.ts`` 覆盖圆形端口、绕行、
对齐边界、注释校验、草稿和部署保护；``tests/test_lab.py`` 验证新字段持久化及非法请求拒绝。
``tests/check_sidebar_projects.cjs`` 验证实际侧边栏拖动、收起、键盘调宽、刷新恢复、窄窗口布局，
以及中文命名、取消、空白校验、保存与改名时保留未保存属性。
两个浏览器脚本都应连接独立的设计模式后端，不使用日常实验数据。例如先构建前端，然后运行::

  ROUTE_OVS_TOKEN=layout-browser-check .venv/bin/python script/python/lab_server.py \
    --preview --port 8097 --data-dir /tmp/route-ovs-layout-check

本例数据目录必须是全新空目录。在已开启远程调试端口的专用 Chromium 测试实例上运行::

  node tests/check_sidebar_projects.cjs http://127.0.0.1:9348 \
    'http://127.0.0.1:8097/#token=layout-browser-check' /tmp/route-ovs-layout-results

脚本使用 Node.js 22+，创建并删除自己的测试项目，输出断言结果和截图。
``web/tests/layout.test.ts`` / ``web/tests/project-name.test.ts`` 覆盖布局存储和命名状态；
``tests/test_lab.py`` 覆盖改名 API 的认证、参数、持久化及部署保护。
Docker/netns 行为测试使用模拟执行器，真实容器连通性仍须在 Linux 主机验收。

``tests/check_canvas_navigation.cjs`` 验证实际原生滚动条拖动、普通/Shift/Ctrl 滚轮、
鼠标缩放锚点、运行中移动与对齐、保存后刷新恢复以及增删改限制。
使用独立 FakeHost 服务提供运行中的实验，不操作 Docker；先启动专用 Chromium 调试端口，然后运行::

  .venv/bin/python tests/serve_canvas_fixture.py --port 8106
  node tests/check_canvas_navigation.cjs http://127.0.0.1:9350 \
    'http://127.0.0.1:8106/#token=canvas-scroll-check' /tmp/canvas-navigation-results

每次验证使用新启动的 fixture 服务；停止服务即回收临时数据目录。

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

  sudo env ROUTE_OVS_CONFIG_DOCKER_TESTS=1 .venv/bin/python -m unittest discover -s tests -p 'test_config_docker.py' -v

浏览器完整流程测试使用独立临时数据目录，不修改现有实验::

  sudo .venv/bin/python tests/serve_config_fixture.py --port 8102
  node tests/check_configs.cjs http://127.0.0.1:9343 \
    'http://127.0.0.1:8102/#token=config-browser-check' /tmp/config-check

需先启动指定调试端口的 Chromium。完成后停止 fixture 服务，会清理它创建的设备和文件。

``tests/test_images.py`` 覆盖清单持久化、导入/删除同步、引用保护、路径边界及上传 API。
真实镜像测试使用随机标签、临时文件和本机临时仓库，不推送到外部仓库；
需要可访问 Docker，且本机已存在 ``registry:2``::

  ROUTE_OVS_IMAGE_DOCKER_TESTS=1 .venv/bin/python -m unittest discover -s tests -p 'test_images_docker.py' -v

浏览器测试使用 ``tests/serve_image_fixture.py --large-library --metadata /tmp/image-check/fixture.json``，
它只向测试目录注入 200 张模拟设备卡片，并为真实导入准备隔离归档。
将生成的 ``fixture.json`` 及其 ``archive`` 指向的文件（命名为 ``image.tar.xz``）放入浏览器
测试输出目录，启动 Chromium 调试端口后执行::

  node tests/check_images.cjs http://127.0.0.1:9344 \
    'http://127.0.0.1:8104/#token=image-browser-check' /tmp/image-check

验证长设备列表、搜索分类、固定底栏、归档和 URL 导入、Dockerfile 构建、设置、删除及刷新恢复。
停止 fixture 后清理其专属镜像及临时文件，不操作现有实验。

``tests/serve_library_fixture.py`` 使用 ImageHost 模拟 200 个镜像条目及镜像任务，不执行宿主机命令。
``tests/check_library_groups.cjs`` 验证分类折叠、搜索、分批加载、默认镜像删除、防火墙导入、
改类型、取消绑定以及刷新后不恢复已删条目。每次验证启动新的 fixture::

  .venv/bin/python tests/serve_library_fixture.py --port 8107
  node tests/check_library_groups.cjs http://127.0.0.1:9351 \
    'http://127.0.0.1:8107/#token=library-check' /tmp/library-results

抓包验证
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``test_capture.py`` 覆盖凭证过期/重放、归属与两端接口核对、PCAP 头、错误过滤器、停止/断线、
回环限制、下载认证以及本地启动器输入边界；前端 ``captures.test.ts`` 覆盖链接内容和异步状态隔离。
真实 veth 抓包测试在 root/Linux 环境显式运行::

  sudo env ROUTE_OVS_CAPTURE_DOCKER_TESTS=1 .venv/bin/python -m unittest discover -s tests -p 'test_capture_docker.py' -v

它创建两个独立 Linux 容器，分别抓取两端 ICMP 请求/回复，验证 BPF 和进程回收。
普通用户转发验证可先以 root 启动独立 ``serve_capture_fixture.py --metadata /tmp/capture-check/fixture.json``
（需先创建 metadata 的父目录），再以普通用户运行 ``check_capture_relay.py --metadata ... --output ...``。
后者不要求 sudo；测试产生 ping 的步骤需要 Docker 权限，产品转发程序本身不需要。

``check_capture_ssh.py`` 使用真实本机 tshark/sshdump 和指定的现有 Profile，通过 SSH 抓取同一
隔离 fixture 的流量，命令参数见文件头。``serve_capture_ui.cjs`` + ``check_capture_ui.cjs`` 是
独立的 UI 模拟验证，仅模拟运行状态和抓包状态，不接触 Docker 或 SSH；真实桌面协议唤起仍需
在目标 Windows/Linux 浏览器与 Wireshark 版本下验证。
