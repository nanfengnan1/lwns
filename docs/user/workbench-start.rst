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

.. contents:: 本页步骤
   :local:
   :depth: 2

获取代码或安装包
----------------------------------------

**从源码启动**：源码位于 `GitHub 项目仓库 <https://github.com/nanfengnan1/route-ovs>`_。
在 Linux 宿主机准备存放项目的目录中执行::

   git clone --branch main https://github.com/nanfengnan1/route-ovs.git
   cd route-ovs

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

   sudo .venv/bin/python script/python/lab_server.py --port 18090 --data-dir "$HOME/route-ovs-dev-data"

另一个终端的 Vite 同步指定代理目标::

   ROUTE_OVS_API_TARGET=http://127.0.0.1:18090 npm --prefix web run dev -- --host 0.0.0.0

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
下面以 x86_64、版本 0.1.0 为例；归档和校验文件放在同一目录::

   sha256sum -c route-ovs-0.1.0-linux-x86_64.tar.gz.sha256
   tar -xzf route-ovs-0.1.0-linux-x86_64.tar.gz
   cd route-ovs-0.1.0-linux-x86_64
   sudo bash install.sh --listen 0.0.0.0 --port 8090
   sudo systemctl start route-ovs-web

安装器启用开机启动，首次安装后按上述命令显式 start；重启主机后由 systemd 自动运行。
访问 ``http://宿主机IP:8090``，令牌从配置文件读取::

   sudo grep '^ROUTE_OVS_TOKEN=' /etc/route-ovs/route-ovs.env

日常管理按需要选择一条命令，不要整表依次执行：

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - 操作
     - Linux 宿主机命令
   * - 查看状态
     - ``systemctl status route-ovs-web``
   * - 停止服务
     - ``sudo systemctl stop route-ovs-web``
   * - 启动服务
     - ``sudo systemctl start route-ovs-web``
   * - 重启服务
     - ``sudo systemctl restart route-ovs-web``

程序位于 ``/opt/route-ovs``，配置位于 ``/etc/route-ovs``，默认数据位于 ``/var/lib/route-ovs``。
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

源代码发布部署使用教程中的 Python 命令；目录包发布部署修改 ``route-ovs.env`` 并重启服务。
两者都不需要启动 Vite。仅运行 ``npm run dev`` 或 ``npm run build`` 不会自动启用 HTTPS。
HTTP/3 是否协商成功，还取决于 UDP 443、证书和浏览器策略。

.. _workbench-deploy-update:

令牌、实验目录与更新
----------------------------------------

源码开发部署与源码发布部署默认都使用项目根目录的 ``.route-ovs-labs``；目录包默认使用
``/var/lib/route-ovs``。用 ``--data-dir`` 或目录包配置指定相同绝对路径，才能读取同一套实验。
更换启动方式不会自动迁移数据；有 FRR 共享挂载的运行实验不要直接移动数据目录。
后端固定连接本机 ``/var/run/docker.sock``，可用 ``--docker-socket`` 指定其他本机 socket，
不能用远程 Docker context 代替同一宿主机的网络命名空间操作。

源码后端未设置 ``ROUTE_OVS_TOKEN`` 时，每次启动生成新 Token；开发页面同样使用这个 Token。
需要固定令牌时先设置环境变量，并使用 ``sudo --preserve-env=ROUTE_OVS_TOKEN`` 启动后端。
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

项目操作提示“不接受跨站请求”
----------------------------------------

项目文件与设备部署都由当前 Web 入口对应的服务器处理。新建、打开、保存和部署使用
页面同源的 ``/api``，不需要给浏览器配置另一个 API 地址，也不应放开任意跨站来源。

* 访问 ``http://宿主机IP:5173``：使用本项目 Vite 代理，保持 Host/Origin 一致；
  修改 ``vite.config.ts`` 后重启 Vite。默认代理到同一宿主机的 8090。
* 访问 ``https://宿主机IP``：确认 Caddy 后面的实际 Python 进程使用可信代理参数，
  手工启动的旧进程可能并不是 systemd 中配置的进程。由同机 Caddy 转发时，后端启动为::

    sudo .venv/bin/python script/python/lab_server.py \
      --host 127.0.0.1 --port 8090 --trusted-proxy 127.0.0.1

  先停止占用 8090 的旧后端，再用相同数据目录启动；已部署设备与项目文件保留，终端需重连。
  如果已由 systemd 管理，检查其启动参数后只重启该服务，无须再手工运行第二个后端。
  后端默认不信任转发头；仅信任实际代理地址，不能用 ``*`` 或禁用来源校验代替正确配置。
