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
   │   ├── stores/terminals.ts   标签、会话状态和实验切换清理
   │   ├── api/client.ts         认证、JSON 请求和错误处理
   │   ├── domain/topology.ts    导入校验、连线约束及 SVG 几何
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

节点可选 ``width`` / ``height`` 保存画布尺寸，缺省宽度 128、高度至少 100。
前后端均校验宽度 96–640、高度 72–640；实际高度还需容纳端口，
最小为 ``max(72, ceil(端口数 / 2) * 13 + 20)``。
``nodeWidth`` / ``nodeHeight`` / ``portPoint`` 统一节点、端口、网线和适应画布的几何计算。
八方向手柄使用 Pointer Events 和捕获，按视口缩放换算位移，固定对侧边缘；
手柄保持屏幕尺寸，结束、失焦或卸载时释放捕获。应用属性草稿保留最新位置和尺寸。

添加设备类型时，需要同时扩展类型定义、设备展示及后端目录和部署逻辑。
前端校验用于及时反馈，Python 后端仍是 IP、网关和部署约束的最终校验方。

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

``tests/check_workbench.cjs`` 在真实 Chromium 中验证拖动、编辑、连线、保存、
导入导出和重新加载，既可检查 Python 提供的构建页面，也可检查 Vite 开发页面。
运行方式与隔离数据目录要求见 :doc:`../user/workbench` 的验证范围。
Docker/netns 行为测试使用模拟执行器，真实容器连通性仍须在 Linux 主机验收。

``tests/test_terminal.py`` 包含凭证、Origin 和归属检查，并提供显式启用的真实
Docker 终端测试。浏览器终端测试可先运行 ``tests/serve_terminal_fixture.py``，
它创建两台独立测试设备，退出时清理；再运行::

  node tests/check_terminal.cjs http://127.0.0.1:9340 \
    'http://127.0.0.1:8098/#token=terminal-browser-check' /tmp/terminal-check

需预先启动指定调试端口的 Chromium。该测试验证键盘输入、FRR 配置、多标签、
实时输出、Ctrl+C、拖动尺寸同步、放大、重连和关闭连接。
