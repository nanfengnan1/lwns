.. _workbench-deploy:

部署与启动：开发部署和发布部署
========================================

.. container:: doc-lead

   选择一种部署方式，启动工作台，并从浏览器登录。
   开发部署使用 Vite + Python 两个进程；发布部署由后端直接提供已构建页面。

.. container:: doc-meta

   **操作位置**：Linux 宿主机，源码命令在项目根目录执行。

   **准备条件**：已 :doc:`获取代码并准备环境 <deployment>`。

   **完成结果**：浏览器可打开工作台，使用后端 Token 登录。

开发入口为 **5173**，普通发布入口为 **8090**。两者使用 HTTP/1.1；
HTTPS / HTTP/2 / HTTP/3 是发布部署的可选配置。

已有旧版部署时，先看 :ref:`lwns-upgrade`，保留原数据目录和配置后再启动新版。

.. contents:: 本页步骤
   :local:
   :depth: 2

获取代码或安装包
----------------------------------------

**从源码启动**：源码位于 `GitHub 项目仓库 <https://github.com/nanfengnan1/lwns>`_。
在 Linux 宿主机准备存放项目的目录中执行::

   git clone --branch main https://github.com/nanfengnan1/lwns.git
   cd lwns

后面的 ``npm --prefix web ...`` 和 ``.venv/bin/python ...`` 都从这个项目根目录执行。
若已下载源码，直接进入已有目录。Git 安装、ZIP 下载方式和文件核对见 :ref:`workbench-get-source`。

**使用目录安装包**：先按 :ref:`workbench-get-package` 确认实际可用的下载来源，取得
可执行目录包及校验文件，再走本页的目录包发布流程；GitHub 源码 ZIP 不能替代可执行目录包。

先选部署方式
----------------------------------------

.. list-table:: 根据使用目的选择一行
   :header-rows: 1
   :widths: 20 25 30 25

   * - 方式
     - 适用场景
     - 运行哪些进程
     - 默认浏览器入口
   * - :ref:`开发部署 <workbench-deploy-dev>`
     - 修改 Vue/TypeScript，查看热更新
     - Vite :5173 + Python 后端 :8090
     - ``http://宿主机IP:5173``
   * - :ref:`发布部署：源码构建 <workbench-deploy-source>`
     - 自己从源码构建，日常运行工作台
     - Python 后端 :8090，同时提供已构建页面
     - ``http://宿主机IP:8090``
   * - :ref:`发布部署：目录包 <workbench-deploy-package>`
     - 下载目录包，安装到系统目录
     - 打包后的后端 :8090，通常由 systemd 管理
     - ``http://宿主机IP:8090``

发布部署的两种形式提供相同的工作台功能，前端都已经构建，不运行 Vite。
HTTP/2、HTTP/3 可作为发布部署的 :ref:`可选 HTTPS 入口 <workbench-deploy-https>`，地址变为
``https://宿主机IP``，与是否使用目录包无关。

下面的 Linux 源码命令均在上面下载的项目根目录执行，默认 Vite 和后端位于同一台 Linux Docker 宿主机。
首次先按 :doc:`deployment` 准备 Docker、ip、nsenter 等宿主机环境。
Windows/Linux 客户端可以使用浏览器远程访问，不需要运行设备后端。

.. _workbench-deploy-dev:

一、开发部署：两个终端，访问 5173
----------------------------------------

首次准备
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

构建/开发环境需要 Node.js 22.12+ 的 22.x 或 24+，后端需要 Python 3.10+。
安装前后端依赖::

   npm --prefix web ci --include=optional
   python3 -m venv .venv
   .venv/bin/python -m pip install -r script/python/requirements.txt

此模式直接处理 ``web/src``，**不需要先执行 npm run build**。
Windows 与 Linux 不要共用 ``node_modules`` 或 ``.venv``；跨平台开发使用独立检出目录。

每次启动
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

分别打开两个终端，进入同一项目根目录。启动后保留终端运行。

.. code-block:: bash
   :caption: 终端一 · Linux 宿主机 · 启动后端

   sudo .venv/bin/python script/python/lab_server.py --port 8090

.. code-block:: bash
   :caption: 终端二 · Linux 宿主机 · 启动 Vite

   npm --prefix web run dev -- --host 0.0.0.0

浏览器访问 ``http://10.8.126.103:5173`` （换成实际宿主机 IP），输入 **后端终端显示的 Token**。
依赖已安装时，日常启动只需上述两条命令。

.. important::

   上述两终端命令对应 **HTTP 的 5173 入口**。如果打开的是 ``https://10.8.126.103/``，
   请求会经过 Caddy，而不是 Vite；手工后端还需要 ``--trusted-proxy 127.0.0.1``。
   否则页面可能正常显示，但新建、保存或部署项目会提示“不接受跨站请求”。
   修复命令和两种入口的对照见 :ref:`workbench-origin-error`。

.. tip::

   **启动成功的标志**：5173 页面显示工作台，Token 登录成功，顶部环境状态可展开查看。
   页面打不开或 API 连接失败时，按 :doc:`troubleshooting` 检查对应端口和进程。

.. code-block:: text

   浏览器 http://宿主机IP:5173
        └─ Vite：页面、前端源码热更新
              └─ /api 和 WebSocket → http://127.0.0.1:8090 → Python 后端

后端未指定 ``--host`` 时默认监听 ``127.0.0.1``，同机 Vite 可以访问它。
因此，其他电脑通过 5173 使用页面时，后端无需监听 ``0.0.0.0``；需要放行的是 TCP 5173。
直接打开 8090 会访问后端提供的 ``web/dist``，可能是旧页面或缺少构建提示，不会显示 Vite 的热更新。

仅修改前端通常自动热更新；修改 Python 代码后，在后端终端 Ctrl+C，再执行后端命令。
停止开发环境时分别在两个终端 Ctrl+C。若 8090 已被现有 systemd 后端占用，不要重复启动：
可让 Vite 使用已有后端及其 Token，或停止旧后端后再启动；同一数据目录不能由两个后端同时管理。

若需隔离开发数据或改后端端口，例如使用 18090::

   sudo .venv/bin/python script/python/lab_server.py --port 18090 --data-dir "$HOME/lwns-dev-data"

另一个终端的 Vite 同步指定代理目标::

   LWNS_API_TARGET=http://127.0.0.1:18090 npm --prefix web run dev -- --host 0.0.0.0

前后端分别运行在不同机器上的配置见 :doc:`../developer/workbench` 的“本地开发”。

开发模式与设计模式的区别
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

“开发部署”表示使用 Vite；“设计模式”表示后端加了 ``--preview``，不创建设备。
两者可以组合。只测试界面、无需真实 Docker 操作时，将终端一换成::

   .venv/bin/python script/python/lab_server.py --preview --port 8090

终端二和访问 5173 的方式不变。设计模式能编辑、保存拓扑，但不能部署、清理容器、
打开设备终端或导入/删除镜像。普通开发部署以 root 启动且环境就绪时，可以进行真实实验。

二、发布部署：使用已构建页面
----------------------------------------

选择下面的源码构建或目录包安装之一。两者运行时都不启动 Vite。

.. _workbench-deploy-source:

方式 A：从源码构建，访问 8090
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

首次准备与发布构建
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

在项目根目录安装依赖并构建前端::

   npm --prefix web ci --include=optional
   npm --prefix web run build
   python3 -m venv .venv
   .venv/bin/python -m pip install -r script/python/requirements.txt

完整的 ``web/dist`` 是发布页面。可以在构建机生成，再将整个目录复制到 Linux 宿主机的同一位置；
仅运行已构建页面的主机不需要 Node.js。缺少 ``web/dist/index.html`` 时，后端首页会提示构建。

每次启动
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: bash
   :caption: Linux 宿主机 · 项目根目录 · 启动发布后端

   sudo .venv/bin/python script/python/lab_server.py --host 0.0.0.0 --port 8090

浏览器访问 ``http://10.8.126.103:8090``，输入后端显示的 Token。
**此模式不执行 npm run dev，也不访问 5173。**
``--host 0.0.0.0`` 允许其他电脑访问；若省略，只能从宿主机回环访问。防火墙按需放行 TCP 8090。

.. code-block:: text

   浏览器 http://宿主机IP:8090
        └─ Python 后端：web/dist 页面 + API + WebSocket

前台运行时保持终端打开，Ctrl+C 停止；需要系统服务安装和升级管理时可使用下一节目录包。
源码中的 Vue/TypeScript/CSS 改动要重新执行 ``npm --prefix web run build`` 才会出现在发布页面。
Python 改动需要重启后端，依赖文件变化时先更新虚拟环境。

.. _workbench-deploy-package:

方式 B：安装 Linux 目录包
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

适用于直接使用发布者构建的包。获取途径与当前发布状态见 :ref:`workbench-get-package`。
无需在目标机安装前端构建工具或 Web 后端 Python 依赖。
下面对应 x86_64、v1.0 程序包；归档和校验文件放在同一目录::

   sha256sum -c lwns-1.0-linux-x86_64.tar.xz.sha256
   tar -xJf lwns-1.0-linux-x86_64.tar.xz
   cd lwns-1.0-linux-x86_64
   sudo bash install.sh --listen 0.0.0.0 --port 8090
   sudo systemctl start lwns-web

安装器启用开机启动，首次安装后按上述命令显式 start；重启主机后由 systemd 自动运行。
访问 ``http://宿主机IP:8090``，令牌从配置文件读取::

   sudo grep '^LWNS_TOKEN=' /etc/lwns/lwns.env

日常管理按需要选择一条命令，不要整表依次执行：

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - 操作
     - Linux 宿主机命令
   * - 查看状态
     - ``systemctl status lwns-web``
   * - 停止服务
     - ``sudo systemctl stop lwns-web``
   * - 启动服务
     - ``sudo systemctl start lwns-web``
   * - 重启服务
     - ``sudo systemctl restart lwns-web``

程序位于 ``/opt/lwns``，配置位于 ``/etc/lwns``，默认数据位于 ``/var/lib/lwns``。
已经安装时，监听地址等参数通过配置文件修改；再次运行安装器会保留已有配置。
完整打包配置、兼容范围、非 systemd 启动、升级、回退、卸载及源码迁移步骤见 :doc:`workbench-install`。

.. _workbench-deploy-https:

三、发布部署可选：HTTPS / HTTP/2 / HTTP/3
------------------------------------------------------------

在上述发布部署基础上增加 Caddy，浏览器统一访问 ``https://宿主机IP``。
后端改为监听回环，并信任同机 Caddy；完整步骤见 :doc:`workbench-https`。

.. code-block:: text

   浏览器 https://宿主机IP
        └─ Caddy :443（HTTP/2、HTTP/3）
              └─ 127.0.0.1:8090（已构建页面 + API + WebSocket）

源代码发布部署使用教程中的 Python 命令；目录包发布部署修改 ``lwns.env`` 并重启服务。
两者都不需要启动 Vite。仅运行 ``npm run dev`` 或 ``npm run build`` 不会自动启用 HTTPS。
HTTP/3 是否协商成功，还取决于 UDP 443、证书和浏览器策略。

.. _workbench-deploy-update:

令牌、实验目录与更新
----------------------------------------

源码开发部署与源码发布部署默认都使用项目根目录的 ``.lwns-labs``；目录包默认使用
``/var/lib/lwns``。用 ``--data-dir`` 或目录包配置指定相同绝对路径，才能读取同一套实验。
更换启动方式不会自动迁移数据；有 FRR 共享挂载的运行实验不要直接移动数据目录。
后端固定连接本机 ``/var/run/docker.sock``，可用 ``--docker-socket`` 指定其他本机 socket，
不能用远程 Docker context 代替同一宿主机的网络命名空间操作。

源码后端未设置 ``LWNS_TOKEN`` 时，每次启动生成新 Token；开发页面同样使用这个 Token。
需要固定令牌时先设置环境变量，并使用 ``sudo --preserve-env=LWNS_TOKEN`` 启动后端。
目录包由安装器生成并保存 Token，重启及升级继续使用它。
切换到新的浏览器地址后，按页面提示重新输入对应后端令牌。

.. list-table:: 修改后如何生效
   :header-rows: 1
   :widths: 22 26 26 26

   * - 改动
     - 开发部署
     - 源码发布部署
     - 目录包发布部署
   * - Vue/TypeScript/CSS
     - Vite 通常自动热更新
     - 重新 build，刷新页面
     - 发布者重新打包，使用者安装新包
   * - Python 后端
     - 重启 Python 后端
     - 重启 Python 后端
     - 发布者重新打包，使用者安装新包
   * - 拓扑、设备配置
     - 在 Web 保存/应用
     - 在 Web 保存/应用
     - 在 Web 保存/应用
   * - 文档
     - 重新构建 docs/html
     - 重新构建 docs/html
     - 查看更新后的发布文档

停止后端会断开网页终端和抓包会话，但不会自动清理设备容器。
升级前先完成后台任务、保存配置与草稿；同一数据目录只运行一个后端。
Wireshark 本地启动器更新需在客户端单独下载安装。

Windows 仅设计预览
----------------------------------------

Windows 本机后端不创建 Linux veth；需要真实实验时，浏览器连接上述 Linux 后端即可。
如需 Windows 本机预览，从独立 Windows 检出目录先构建前端，再运行::

   npm --prefix web ci --include=optional
   npm --prefix web run build
   py -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r script/python/requirements.txt
   .\.venv\Scripts\python.exe script/python/lab_server.py --preview --port 8090

在同一台 Windows 的浏览器访问 ``http://127.0.0.1:8090``。

.. container:: doc-next

   **下一步**

   启动成功后，按 :doc:`quickstart` 部署第一个实验；需要 HTTPS 时阅读 :doc:`workbench-https`。

.. _workbench-origin-error:

项目操作提示“不接受跨站请求”
----------------------------------------

**典型现象**：在两个终端分别执行 ``sudo .venv/bin/python script/python/lab_server.py --port 8090``
和 ``npm --prefix web run dev -- --host 0.0.0.0``，却在浏览器打开 ``https://10.8.126.103/``。
页面能够显示，填写项目名称后点击创建，收到“不接受跨站请求”。

这时实际链路是 **浏览器 HTTPS → Caddy → HTTP 后端 127.0.0.1:8090**。
Caddy 终止 TLS，并通过 ``X-Forwarded-Proto: https`` 告知原始协议。
后端默认不信任转发头；缺少 ``--trusted-proxy`` 时，它按 HTTP 校验浏览器的 HTTPS Origin，
协议不一致，因而拒绝请求。启动 Vite 不会改变这个 HTTPS 入口的转发路径。

先确认访问入口
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table:: 地址栏决定使用哪条链路
   :header-rows: 1
   :widths: 27 34 39

   * - 浏览器地址
     - 页面与 API 的来源
     - 启动方式
   * - ``http://宿主机IP:5173``
     - Vite 处理前端源码，代理 API/终端到后端
     - Python 后端 + Vite 两终端，前端通常自动热更新
   * - ``http://宿主机IP:8090``
     - Python 直接提供 web/dist、API 和终端
     - 已 build 的前端 + 监听 0.0.0.0 的后端
   * - ``https://宿主机IP``
     - Caddy 转发到 Python，页面来自 web/dist
     - Caddy + 已 build 的前端 + 显式信任 Caddy 的后端

使用 HTTPS：修正手工后端命令
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

以下命令在 **Linux Docker 宿主机的项目根目录** 执行，前提是已按 :doc:`workbench-https`
配置同机 Caddy、证书及上游 ``127.0.0.1:8090``。

1. 在旧后端终端按 Ctrl+C，确认 8090 已释放。保留原数据目录；若之前使用过 ``--data-dir``，
   新命令也必须指定相同目录。停止后端会断开终端和抓包，但不会删除项目及设备容器。
2. 首次使用 HTTPS 或修改过前端源码时，先生成发布页面；已有最新 web/dist 时省略::

      npm --prefix web run build

3. 使用下面的命令启动并保持终端运行::

      sudo .venv/bin/python script/python/lab_server.py \
        --host 127.0.0.1 \
        --port 8090 \
        --trusted-proxy 127.0.0.1

4. 打开 ``https://10.8.126.103/``，换成实际宿主机 IP；使用 **本次后端输出的 Token** 登录，
   再创建测试项目。成功后项目应出现在当前服务器的“打开项目”列表中。

HTTPS 入口无需运行 Vite。若同时需要开发热更新，可以另开终端执行
``npm --prefix web run dev -- --host 0.0.0.0``，但热更新页面应访问 ``http://10.8.126.103:5173``。
上述带可信代理参数的同机后端可以同时服务这两个入口；HTTPS 页面仍需 build 才会更新。

令牌、服务管理与其他错误
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* 手工启动未指定 ``LWNS_TOKEN`` 时，每次启动生成新 Token；浏览器保存的旧 Token
  可能失效，重新输入本次输出的令牌。手工 Python 命令不会自动读取 systemd 的环境文件。
* 由 systemd 管理时，应检查该服务实际使用的启动参数或配置文件，确认可信代理已设置，
  再重启对应服务；不要另外启动第二个后端占用 8090。停止 systemd 后改成手工启动，
  也需要在手工命令中明确提供 ``--trusted-proxy``。
* HTTP 开发入口仍报错：检查地址栏的完整协议、主机和端口，确认使用当前项目的 Vite 配置。
  修改 ``vite.config.ts`` 或代理目标后重启 Vite；浏览器继续使用相对 ``/api``，不直接请求另一个端口。
* ``401`` 或提示令牌无效：检查 Token；``403`` 且提示“不接受跨站请求”：检查入口与来源校验；
  Caddy 返回 ``502``：检查 Python 后端是否已启动及上游端口是否一致。

后端仅应信任实际代理地址；本例是同机 ``127.0.0.1``。保留 Host/Origin 校验，
不要用 ``*``、放开任意跨站来源或禁用校验代替正确的启动参数。

.. _lwns-upgrade:

更名与已有数据
----------------------------------------

项目现名 **lwns（Linux Web Network Simulator）**，旧名称为 ``route-ovs``。
仓库和本地源码目录改名后，需更新自己维护的服务启动路径；改名不会自动更新正在运行的后端。
新命令为 ``lwns``，服务为 ``lwns-web``，新配置变量使用 ``LWNS_`` 前缀。

源码部署沿用数据
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

新环境默认写入 ``.lwns-labs``。如果这个目录不存在而源码根目录中已有
``.route-ovs-labs``，程序会继续读取旧目录，不会搬迁文件或修改容器挂载。
两者都存在时默认使用新目录；也可明确指定已有数据的位置，例如在新的源码根目录执行::

  sudo .venv/bin/python script/python/lab_server.py \
    --host 0.0.0.0 --port 8090 --data-dir .route-ovs-labs

同一时刻只启动一个使用该数据目录的后端。``--data-dir`` 优先于环境变量；环境变量优先于默认目录。
后端兼容旧 ``ROUTE_OVS_DATA_DIR``、``ROUTE_OVS_TOKEN``，设置了对应的 ``LWNS_*`` 值时优先使用新值。
Vite 同样兼容 ``ROUTE_OVS_API_TARGET``，推荐更新为 ``LWNS_API_TARGET``。

如果源码目录本身已从 ``route-ovs`` 改为 ``lwns``，已创建容器的 bind mount 仍记录旧的绝对路径。
不要直接在运行中搬动配置目录；应先保存配置并清理旧设备，再改目录并重新部署。
已经改名且旧容器仍在运行时，先确认旧挂载源仍可访问，必要时恢复原目录位置，完成保存和清理后再更名。

目录包切换
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

新目录包使用 ``/opt/lwns``、``/etc/lwns/lwns.env`` 和 ``/var/lib/lwns``，不会卸载旧目录包。
如果原来通过旧目录包安装，首次切换时在解压后的新安装包目录执行下面的步骤。
先备份原配置和数据；自定义数据路径以旧环境文件中的配置为准::

  sudo systemctl disable --now route-ovs-web
  sudo bash install.sh --data-dir /var/lib/route-ovs
  sudo install -m 600 /etc/route-ovs/route-ovs.env /etc/lwns/lwns.env
  sudo systemctl start lwns-web

复制旧环境文件是为了保留原 Token、监听地址、代理设置及数据路径；新包装器兼容其中的
``ROUTE_OVS_*`` 变量。后续可逐项改为 ``LWNS_*``。未使用旧目录包或没有该环境文件时，
按 :doc:`workbench-install` 正常安装，不执行复制步骤。新版不会自动重命名或移动旧项目数据。

抓包与 HTTPS
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* 抓包 URL 已改为 ``lwns://``。在客户端重新下载并运行抓包客户端安装脚本，注册新协议；
  新启动器仍可读取旧连接配置和解析旧链接，原来选择的抓包保存目录继续有效。
* 更新到新版 ``config/Caddyfile`` 时，将启动 Caddy 的 ``ROUTE_OVS_SITE``、
  ``ROUTE_OVS_UPSTREAM`` 更新为 ``LWNS_SITE``、``LWNS_UPSTREAM``。旧 Caddy 配置本身可继续使用；
  域名或 IP 不变时，无需因软件更名重新签发证书。
* 新设备包后缀改为 ``.lwns``，导入兼容旧 ``.rov``。设备描述 schema、包内 v1 标识、拓扑版本和容器归属协议保持兼容；已安装包和旧制作任务无需改名。
  包内原始设备 ID 和镜像标签不会因品牌更名而自动替换。
