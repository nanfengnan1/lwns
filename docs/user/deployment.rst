环境准备
========================================

宿主机要求
----------------------------------------

先确定使用 Web 工作台还是旧版命令行工具；两者管理的实验相互独立。
Web 工作台在 Linux Docker 宿主机部署设备，Windows/Linux 客户端只需浏览器。
各功能所需环境如下：

* Web 后端：Python 3.10+、项目后端依赖、Docker CLI 和同一主机上的 Docker daemon。
* Web 部署：``ip``（iproute2）、util-linux 的 ``nsenter``，以宿主机 root 运行后端。
* 前端构建：Node.js 22.12+ 的 22.x 或 24+，建议使用 Node.js 24 LTS；仅运行已构建前端时无需 Node.js。
* Web 抓包：宿主机增加 ``tcpdump`` 和可登录的 SSH 服务；客户端增加 Wireshark 和本地启动器。
* 旧版脚本：按功能使用 ``bash``、GNU ``getopt``、``sudo``；OVS 实验另需 ``ovs-vsctl`` 和 OVS 服务。
* 旧版 SVG 拓扑采集：按采集方式使用 Docker/OVS，以及 Graphviz 的 ``dot``。

Web 工作台的交换机使用容器内 Linux bridge，不需要为此安装 OVS 或 Graphviz。
后端应直接运行在 Docker 所在 Linux 宿主机上，不能只通过远程 Docker context 代替宿主机访问。

先在 Linux 主机核对环境::

  sudo docker version
  ip -Version
  nsenter --version
  python3 --version

Docker 安装以发行版对应的官方步骤为准，例如
`Ubuntu 安装 Docker Engine <https://docs.docker.com/engine/install/ubuntu/>`_。
Debian/Ubuntu 上可按需要安装基础工具::

  sudo apt-get update
  sudo apt-get install python3 python3-venv iproute2 util-linux tcpdump

远程抓包还需 SSH 服务；已有 SSH 服务时无需重复安装。后端虚拟环境、前端构建和启动命令见
:ref:`workbench-start`，抓包客户端安装见 :doc:`workbench-capture`。
设备数量和镜像决定资源需求，目前没有统一的规模与性能保证。

需要 HTTPS、HTTP/2 或 HTTP/3 时，可选择同机 Caddy 反向代理；配置、内网自动签发证书、
mkcert 手动制作和客户端信任安装见 :doc:`workbench-https`。普通 HTTP 入口仍可独立使用。

准备镜像
----------------------------------------

项目已提供镜像归档，可以在项目根目录加载::

  docker load -i devices/route/frr.tar.xz
  docker load -i devices/vpcs/vpcs.tar.xz
  docker image ls

应以加载输出为准核对镜像标签。当前 ``script/frr_init.sh`` 中的
``CONTAINER_IMG`` 为 ``alpine/frr:latest``；VPCS 工具默认使用
``alpine/vpcs:latest``。归档文件名不保证内部标签与上述默认值相同。

VPCS 镜像也可从项目中的 Dockerfile 构建，见开发指南“镜像构建”章节。
该镜像当前安装的是 DHCP 客户端 ``dhcpcd``，不是 DHCP 服务端。

实验目录
----------------------------------------

Web 工作台默认将实验写入项目根目录的 ``.route-ovs-labs``，也可通过 ``--data-dir`` 指定目录。
配置备份与迁移见 :doc:`workbench-data`。保持数据目录不变即可在后端重启后继续管理原实验。

使用旧版脚本时，建议每个实验使用独立目录，保存容器清单、VPCS 状态、协议配置和采集结果。
由于 FRR 名称固定从 ``frr_A`` 开始，不同实验目录并不能避免同一 Docker 主机上的同名冲突。
