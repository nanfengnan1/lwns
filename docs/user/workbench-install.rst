Linux 目录包：打包与系统安装
========================================

本项目支持制作 Linux 目录包，解压后使用安装脚本安装到系统目录，不依赖 deb/rpm。
这是 :doc:`workbench-start` 中的 **发布部署：目录包**，不运行 npm run dev。
需要修改前端并查看热更新时，使用 :ref:`workbench-deploy-dev` 的两个终端方式。
目录包含可执行后端、Python 运行环境、已构建前端、默认镜像清单、示例和抓包客户端脚本。
使用者无需安装 Node.js、npm，也无需为 Web 后端单独安装 Python 或 pip 依赖。

源码仓库为 `nanfengnan1/lwns <https://github.com/nanfengnan1/lwns>`_，
安装包下载入口为 `GitHub Releases <https://github.com/nanfengnan1/lwns/releases>`_。
实际发布状态、应该下载的附件以及没有安装包时如何获取，先看 :ref:`workbench-get-package`。
自行打包的用户先按 :ref:`workbench-get-source` 克隆源码，再阅读本页末尾的构建步骤。
设备镜像独立导入或拉取，不包含在工作台程序包中。

使用者先阅读“安装目录包”，按需继续修改配置、升级或卸载；需要制作发布包的维护者阅读本页最后的“发布者：构建目录包”。

.. contents:: 本页操作
   :local:
   :depth: 2

支持范围与环境
----------------------------------------

* 构建机和目标机均为 Linux，CPU 架构一致；当前验收环境为 Ubuntu 22.04 x86_64、glibc 2.35。
* 目录格式不依赖发行版的包管理器，但二进制仍有架构、glibc 和系统库要求。
  应在计划支持的最旧 glibc 系统构建，并在各目标系统验证；不能将此包直接用于 Alpine/musl。
  ARM64 必须单独在相应架构构建和验收，当前未验收。
* 安装脚本需要 Bash 和常用 GNU 工具，包括 tar、coreutils、grep、diff。
  自动服务管理使用 systemd；其他 init 系统可以使用 ``--no-systemd``，自行托管进程。
* 部署设备仍需要宿主机 root、Docker Engine/CLI、iproute2 的 ``ip``、util-linux 的 ``nsenter``。
  安装器不替换已有 Docker 或自动修改发行版的软件源。
* 远程抓包另需宿主机 ``tcpdump``、SSH 服务和供 SSH 转发脚本使用的 ``python3``；
  客户端需要 Wireshark 和抓包启动器。内置 Python 运行环境仅供打包后的 Web 后端使用。

安装目录包
----------------------------------------

先从 :ref:`workbench-get-package` 所述来源取得归档和校验文件，放在 Linux 宿主机同一目录中。
进入文件所在目录后，先核对，再解压（以下以 0.1.0/x86_64 文件名为例，实际版本以取得的包为准）::

   sha256sum -c lwns-0.1.0-linux-x86_64.tar.gz.sha256
   tar -xzf lwns-0.1.0-linux-x86_64.tar.gz
   cd lwns-0.1.0-linux-x86_64

普通 HTTP 方式，允许实验网客户端访问 8090::

   sudo bash install.sh --listen 0.0.0.0 --port 8090
   sudo systemctl start lwns-web
   systemctl status lwns-web

安装器校验包内文件、检测可执行文件能否启动，创建目录和访问令牌，注册并启用开机启动。
安装完成后需要执行上面的 ``start``；默认不自动启动，以便先检查网络监听和配置。
省略 ``--listen`` 时仅监听 ``127.0.0.1``，不能从其他机器直接访问。

客户端访问 ``http://宿主机IP:8090``。管理员在主机读取令牌并填写网页登录框::

   sudo grep '^LWNS_TOKEN=' /etc/lwns/lwns.env

每次首次安装生成独立 Token；升级不会重新生成。不要把当前主机的 Token 预置到发布包。
Docker、``ip`` 或 ``nsenter`` 未就绪时，网页可以显示环境诊断，但不能部署设备。
设备镜像准备和导入见 :doc:`deployment` 与 :doc:`workbench`。

安装后的目录
----------------------------------------

.. code-block:: text

   /opt/lwns/
     releases/<BUILD_ID>/      可执行文件、_internal 运行资源和启动脚本
     current -> releases/...  当前使用的版本
   /usr/local/bin/lwns    指向当前版本的启动脚本
   /etc/lwns/
     lwns.env            监听地址、端口、数据目录、可信代理、Token
   /var/lib/lwns/         默认实验数据、设备配置和镜像管理记录
   /etc/systemd/system/
     lwns-web.service    后台服务

配置文件权限为 600；程序目录由 root 管理。实验数据不放在程序目录里。
日志通过 ``journalctl -u lwns-web`` 查看；启动日志含访问令牌，不要直接公开完整日志。

修改配置与启用 HTTPS
----------------------------------------

编辑 ``/etc/lwns/lwns.env``，其内容是启动脚本读取的 Bash 变量，例如：

.. code-block:: bash

   LWNS_HOST=127.0.0.1
   LWNS_PORT=8090
   LWNS_DATA_DIR=/var/lib/lwns
   LWNS_TRUSTED_PROXY=127.0.0.1
   LWNS_TOKEN=保留安装器生成的实际值

这是参数示例，不要把示例 Token 覆盖到实际文件。修改后执行::

   sudo systemctl restart lwns-web

使用 Caddy 时，首次安装也可直接指定回环和可信代理::

   sudo bash install.sh --listen 127.0.0.1 --trusted-proxy 127.0.0.1
   sudo systemctl start lwns-web

随后按 :doc:`workbench-https` 安装配置 Caddy，并使用归档中的 ``Caddyfile.example``
代替源码中的 ``config/Caddyfile``。教程的前端构建和 Python 后端启动步骤已由目录包取代。
安装器不会覆盖现有 Caddy 站点或分发证书私钥。HTTP/2、HTTP/3 和客户端证书信任步骤保持不变。

非 systemd 系统和解压试运行
----------------------------------------

不注册服务、仅安装到系统目录::

   sudo bash install.sh --no-systemd --listen 0.0.0.0
   sudo /usr/local/bin/lwns

该启动方式读取相同配置并以前台运行，可以交给自己的 init/supervisor 管理。
启动、停止、开机启动和日志轮转由所选进程管理器负责。
同一数据目录只能运行一个后端，不能与 systemd 实例重复启动。

也可不安装，直接以普通用户验证设计模式::

   ./app/lwns --preview --host 127.0.0.1 --port 18090 --data-dir "$HOME/lwns-preview"

直接运行包内二进制时不读取系统 ``lwns.env``，未指定 ``LWNS_TOKEN`` 环境变量时
每次生成新令牌。脱离安装器运行时务必明确指定可写数据目录。

升级、回退与卸载
----------------------------------------

升级前先结束部署、镜像导入、保存配置等后台任务，关闭网页终端并保存草稿。
在旧服务停止后备份数据和配置，然后解压新版本并运行安装器::

   sudo systemctl stop lwns-web
   sudo tar -czf /root/lwns-backup-20261024.tar.gz /etc/lwns /var/lib/lwns
   cd /解压后的新版本目录
   sudo bash install.sh
   sudo systemctl start lwns-web

备份文件名请改为本次时间，避免覆盖旧备份；自定义数据目录时相应调整备份路径。
后端停止不会自动清理实验容器。运行中的设备仍可能写共享配置，要求一致备份时应先完成设备保存，
并按实验需要停止写入或清理设备后再备份。

安装器要求已有服务停止，保留原 ``lwns.env`` 和所有实验数据。
安装参数只用于首次生成配置；已有安装请直接编辑配置文件。
旧程序目录继续保留，``current`` 切换到新版本；不会自动迁移数据格式。

若新版本启动异常，可停服务后回退程序链接::

   ls /opt/lwns/releases
   sudo systemctl stop lwns-web
   sudo ln -sfn releases/实际旧BUILD_ID /opt/lwns/current
   sudo systemctl start lwns-web

回退程序不等于回退数据。版本涉及数据格式变化时，必须按该版本说明恢复匹配备份。
卸载程序和服务::

   sudo bash /opt/lwns/current/uninstall.sh

非 systemd 安装先自行停止进程，再加 ``--no-systemd`` 卸载。
卸载保留 ``/etc/lwns``、实验数据、Docker 镜像及设备容器；若需要移除设备，应先在 Web 清理实验。
重新安装会复用保留的配置与令牌。

从源码部署迁移
----------------------------------------

不要把已有 ``.lwns-labs`` 直接移动到新目录：运行中的 FRR 容器可能仍绑定旧绝对路径。
最简单的迁移是停止旧后端，保留原数据位置，在首次安装时指定::

   sudo bash install.sh --data-dir /原项目绝对路径/.lwns-labs --listen 0.0.0.0

源码服务的名称也可能是 ``lwns-web.service``。安装器会拒绝覆盖不属于目录包的同名服务。
应先停止并备份旧 unit，再移走原 unit、执行 ``systemctl daemon-reload``，然后安装。
实际切换前记录旧端口、可信代理和 Token；如需沿用 Token，由管理员写入新配置，不放进分发包。
安装器也会拒绝其他位置的同名 unit 或已有 systemd drop-in；应先备份并核对、移走这些覆盖配置，
避免继续覆盖 ExecStart 或环境设置。
当前生产主机不会因为构建目录包而自动迁移，迁移需要单独安排。

确需迁移数据位置时，先保存设备配置并清理实验容器，再停止后端、复制数据、修改配置，
启动后重新部署验证。不要同时运行源码后端和目录包后端管理同一批实验。

发布者：构建目录包
----------------------------------------

先按 :ref:`workbench-get-source` 克隆源码并进入 ``lwns`` 目录。
在 Linux 源码根目录准备 Node.js（22.12+ 的 22.x 或 24+）和 Python 3.10+。
以下构建环境与运行中的后端虚拟环境分开，避免升级线上依赖::

   python3 -m venv .venv-build
   .venv-build/bin/python -m pip install -r packaging/linux/requirements-build.txt
   npm --prefix web ci --include=optional
   .venv-build/bin/python packaging/linux/build.py --version 0.1.0

脚本默认执行前端构建，再通过 PyInstaller ``onedir`` 打包后端。
已有确认过的完整 ``web/dist`` 时可添加 ``--skip-web-build``。
构建临时目录使用 Linux 本地临时空间，保留运行库符号链接；不要在 Windows 解压后再重新打包。

默认产物（以 x86_64 为例）：

.. code-block:: text

   release/
     lwns-0.1.0-linux-x86_64.tar.gz
     lwns-0.1.0-linux-x86_64.tar.gz.sha256

``--output /目标目录`` 可以修改输出位置；脚本拒绝覆盖同名发布文件。
``--version`` 是发行版本；每次构建另外生成唯一 BUILD_ID，安装后保留各构建目录。
归档包含 ``build-info.json``，记录架构、构建机 glibc、Python 和依赖版本，便于诊断兼容性。

打包按固定资源清单收集，不包含 ``.lwns-labs``、宿主机令牌、证书私钥、设备镜像或
``node_modules``。Caddy 只提供示例配置，二进制和证书由部署者单独准备。
Windows 抓包 exe 也需单独在 Windows 构建；包内附带的是跨平台客户端脚本。

发布前，在隔离目录执行目录包验收::

   .venv-build/bin/python tests/check_linux_package.py \
     release/lwns-0.1.0-linux-x86_64.tar.gz

该检查不向真实系统目录安装、不调用宿主机 systemctl，不操作设备容器。
它检查资源、认证接口、WebSocket、安装升级和卸载保留数据；实际部署与抓包还需按既有集成测试验收。
构建工具行为参考 `PyInstaller 运行资源路径 <https://pyinstaller.org/en/stable/runtime-information.html>`_
和 `外部程序环境说明 <https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html#launching-external-programs-from-the-frozen-application>`_。
