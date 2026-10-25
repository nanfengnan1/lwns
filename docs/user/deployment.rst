获取代码与环境准备
========================================

本页先说明从哪里取得源码或安装包，再准备宿主机工具和设备镜像。下一步在 :doc:`workbench-start` 选择
**开发部署** （Vite + 后端，访问 5173）或 **发布部署** （已构建页面，访问 8090）。
前端构建是发布步骤，开发部署不需要先 build；HTTPS 是发布部署的可选入口。

如果管理员已经提供工作台地址和 Token，你只需浏览器，直接阅读 :doc:`quickstart`。
以下安装和检查命令由维护 Linux 宿主机的人执行。

.. container:: doc-meta

   **操作位置**：Linux 宿主机。

   **完成结果**：取得代码或安装包，确认 Docker 和网络工具可用。
   已具备这些条件时，直接阅读 :doc:`workbench-start`。

.. contents:: 本页步骤
   :local:
   :depth: 1

.. _workbench-get-source:

第一步：获取项目源码
----------------------------------------

项目仓库：`nanfengnan1/lwns <https://github.com/nanfengnan1/lwns>`_。
开发部署、源码发布部署和自行制作目录包，都从这里取得代码。

在 **Linux 宿主机** 的普通用户终端执行，下面以 ``~/program/github`` 存放源码为例::

   mkdir -p ~/program/github
   cd ~/program/github
   git clone --branch main https://github.com/nanfengnan1/lwns.git
   cd lwns

HTTPS 克隆公开仓库不需要配置 GitHub SSH 私钥。若提示找不到 ``git``，先用发行版包管理器安装；
Debian/Ubuntu 可运行 ``sudo apt-get update`` 和 ``sudo apt-get install git``，再执行上述命令。

进入目录后核对工作台文件::

   ls web/package.json script/python/lab_server.py packaging/linux/build.py

看到上述文件后，当前位置就是后续命令所说的 **项目根目录**。
已下载过源码的用户直接进入已有目录，不必再次 clone。

不使用 Git 时，也可在仓库网页点击 **Code → Download ZIP**。解压后进入 ``lwns-main``，
该目录同样是项目根目录。这个 ZIP 是源码归档，需要安装依赖并按所选部署方式启动，
不能当作 Docker 设备镜像上传到镜像管理。

源码下载完成后，继续本页环境准备，再按 :doc:`workbench-start` 的开发或源码发布流程操作。
``web/dist``、``node_modules``、Python 虚拟环境和你自己的实验数据不随 Git 克隆提供。

.. _workbench-get-package:

另一种选择：获取 Linux 目录安装包
----------------------------------------

安装包发布入口为 `GitHub Releases <https://github.com/nanfengnan1/lwns/releases>`_。
有可用版本时，在其 **Assets** 中选择目标架构的 ``lwns-<版本>-linux-<架构>.tar.gz``
及同名 ``.sha256``，两份文件都要下载。GitHub 自动生成的 **Source code (zip/tar.gz)**
是源码归档，不是包含可执行程序的目录安装包。

.. note::

   **截至 2026-10-24 核对时，该仓库尚未发布 Release 安装包。** 当前可以取得维护者提供的目录包，
   或先克隆源码，再按 :doc:`workbench-install` 最后的“发布者：构建目录包”自行生成。

构建产物位于构建机项目根目录的 ``release/``，这个目录不会随 Git 提交或自动上传到 GitHub。

取得 ``.tar.gz`` 和 ``.sha256`` 后，按 :doc:`workbench-install` 校验、解压并安装。
使用目录包运行工作台无需另行克隆源码；Docker 设备镜像仍需按本页后文单独准备。

宿主机要求
----------------------------------------

先确定使用 Web 工作台还是旧版命令行工具；两者管理的实验相互独立。
Web 工作台在 Linux Docker 宿主机部署设备，Windows/Linux 客户端只需浏览器。
下列 Python/Node.js 要求针对源码开发或构建；:doc:`workbench-install` 的 Linux 目录包已包含 Web 后端运行环境和前端成品，宿主机网络工具及抓包依赖仍需准备。

* Web 后端：Python 3.10+、项目后端依赖、Docker CLI 和同一主机上的 Docker daemon。
* Web 部署：``ip``（iproute2）、util-linux 的 ``nsenter``，以宿主机 root 运行后端。
* 前端构建：Node.js 22.12+ 的 22.x 或 24+，建议使用 Node.js 24 LTS；仅运行已构建前端时无需 Node.js。
* Web 抓包：宿主机增加 ``tcpdump`` 和可登录的 SSH 服务；客户端增加 Wireshark 和本地启动器。

Web 工作台的交换机使用容器内 Linux bridge，不需要为此安装 OVS 或 Graphviz。
后端应直接运行在 Docker 所在 Linux 宿主机上，不能只通过远程 Docker context 代替宿主机访问。

先在 Linux 主机核对环境::

  sudo docker version
  ip -Version
  nsenter --version

预期能看到 Docker 客户端/服务端版本、ip 与 nsenter 版本。只有 Docker CLI、没有可用的
Docker daemon 时仍不能部署。源码后端另需 ``python3 --version`` 显示 3.10 或更高版本；
目录包的 Web 后端使用内置 Python。

Docker 安装以发行版对应的官方步骤为准，例如
`Ubuntu 安装 Docker Engine <https://docs.docker.com/engine/install/ubuntu/>`_。
Debian/Ubuntu 的宿主机网络工具可按需安装::

  sudo apt-get update
  sudo apt-get install iproute2 util-linux

源码运行需要 ``python3 python3-venv``；远程抓包额外需要 ``tcpdump``、SSH 服务以及
SSH 转发脚本使用的 ``python3``。按实际使用功能安装，不必为了浏览网页在客户端安装这些宿主机工具。

远程抓包还需 SSH 服务；已有 SSH 服务时无需重复安装。后端虚拟环境、前端构建和启动命令见
:doc:`workbench-start`，抓包客户端安装见 :doc:`workbench-capture`。
设备数量和镜像决定资源需求，目前没有统一的规模与性能保证。

需要 HTTPS、HTTP/2 或 HTTP/3 时，可选择同机 Caddy 反向代理；配置、内网自动签发证书、
mkcert 手动制作和客户端信任安装见 :doc:`workbench-https`。普通 HTTP 入口仍可独立使用。

准备镜像
----------------------------------------

工作台目录包不包含设备镜像，需要自行准备兼容镜像或使用已有本地镜像。
默认示例使用 ``alpine/frr:latest`` 和 ``alpine/vpcs:latest``；这两个标签不是可用下载地址的保证，
请以你实际取得的镜像为准。

若已取得用 ``docker save`` 导出的镜像文件，在 Linux 宿主机的归档所在目录加载
（下列文件名请替换为实际文件名）::

  sudo docker load -i frr.tar
  sudo docker load -i vpcs.tar
  sudo docker image ls

应以加载输出和 ``docker image ls`` 核对标签，归档文件名不决定镜像标签。
工作台不会自动纳入全机所有镜像：在“镜像管理”通过“已有镜像”引用，再绑定所需设备类型。
也可直接从网页上传未压缩的 ``.tar``；完整导入、Dockerfile 构建和设备库绑定步骤见 :doc:`workbench-images`。

VPCS 镜像也可从项目中的 Dockerfile 构建，见开发指南“镜像构建”章节。
该镜像当前安装的是 DHCP 客户端 ``dhcpcd``，不是 DHCP 服务端。

实验目录
----------------------------------------

源码启动默认写入项目根目录的 ``.lwns-labs``，目录包安装默认写入 ``/var/lib/lwns``。
可通过 ``--data-dir`` 或目录包配置指定其他位置。
配置备份与迁移见 :doc:`workbench-data`。保持数据目录不变即可在后端重启后继续管理原实验。

下一步：按 :doc:`workbench-start` 启动工作台。旧版命令行工具的额外环境与操作见 :doc:`legacy-cli`。
