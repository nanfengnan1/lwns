SDN Agent、Controller、Web 设备包
========================================

三种设备分别交付为 ``sdn-agent-1.0.lwns``、``sdn-controller-1.0.lwns``、
``sdn-web-1.0.lwns``。每个离线包包含设备描述、校验清单及干净的 Docker 镜像，
不包含现有实验的 Token、节点身份或数据库。

它们适用于 Linux amd64 隔离实验。请先更新并重启工作台后端：Agent 描述使用新增的
``runtime.cap_add: ["SYS_ADMIN"]``，供 FRR 启动使用；旧后端会拒绝未知字段。
这个权限与平台内置 FRR 模板一致，设备包不启用 ``privileged`` 或宿主网络。

旧格式与当前格式
----------------------------------------

.. list-table::
   :header-rows: 1
   :widths: 25 38 37

   * - 形式
     - 内容
     - 启动与保存规则
   * - 旧镜像 ``.tar`` / ``.tar.xz``
     - Docker 镜像归档；压缩文件先解压再用于 Web 镜像导入
     - 由平台内置模板提供
   * - 旧设备包 ``.rov``
     - ZIP 内含 device.json、manifest.json 和可选镜像资源
     - 来自 device.json，仍兼容导入
   * - 新设备包 ``.lwns``
     - 沿用设备包 v1 结构和校验方式
     - 来自 device.json；新制作与下载使用此后缀

Docker 镜像归档不能通过改后缀变成设备包。``.lwns`` 也不是完整实验项目备份。
包内 ``route-ovs-device`` 标识保留用于兼容，详细格式见 :doc:`workbench-devices`。

三个设备的组成
----------------------------------------

.. list-table::
   :header-rows: 1
   :widths: 20 22 33 25

   * - 设备
     - 进程
     - 实例持久化目录
     - 设备库分类 / 端口
   * - sdn-agent
     - Agent、Redis、FRR
     - /etc/sdn-agent、/var/lib/sdn-agent、/var/lib/redis、/etc/frr
     - 路由器 / gRPC 9090
   * - sdn-controller
     - Controller、etcd
     - /etc/sdn-controller、/etcd-data
     - PC / gRPC 19090
   * - sdn-web
     - Nginx、Gateway
     - /etc/sdn-web
     - PC / HTTP 8080

三个描述都使用 ``generic`` profile。Agent 包含多个服务及持久化目录，无法使用只允许
标准 FRR 启动命令与单一 /etc/frr 目录的 ``frr`` profile。Controller/Web 在 PC 分类中
显示是当前分类体系的选择，不改变其服务功能。终端均进入 Shell。

制作离线包
----------------------------------------

在 Linux Docker 宿主机执行。需要先有 ``sdn-agent:alpine``、``sdn-controller:alpine``、
``sdn-web:alpine`` 三个原生镜像；各项目原有 Dockerfile 仍负责构建原生程序。
这里的两文件定义仅增加平台生命周期适配，不重新编译 SDN 程序::

   cd ~/program/github/lwns
   python3 examples/device-packages/build_sdn.py \
     --output ~/lwns-devices/sdn/1.0

每种定义位于 ``examples/device-packages/sdn-*/``，分别只有 ``device.json`` 和
``Dockerfile``。构建脚本固定本次实际使用的本地基础镜像 ID，再导出适配镜像，
调用工作台共用打包模块生成离线包和 SHA256SUMS。

输出已存在时默认拒绝覆盖；更换设备实现应发布新版本，不覆盖已经安装的版本。
复核本次构建产物可以执行::

   cd ~/lwns-devices/sdn/1.0
   sha256sum -c SHA256SUMS
   cd ~/program/github/lwns
   python3 script/python/lab_server.py device inspect \
     ~/lwns-devices/sdn/1.0/sdn-agent-1.0.lwns

通过 **工具 → 设备管理 → 导入设备包** 分别导入三个文件，见 :ref:`rov-import-device`。
检查包和构建镜像都不会修改现有实验；导入设备库也不会自动创建拓扑。

首次组网与匹配凭据
----------------------------------------

平台通过 veth 接线，设备默认没有 Compose 的 management 网络、容器 DNS 或宿主端口映射。
在画布创建三个设备，Controller 设置两个端口，按下面的示例配置并连接::

   Agent eth0                Controller eth0
   198.18.240.2/30 ---------- 198.18.240.1/30
                                |
                             Controller eth1              Web eth0
                             198.18.241.1/30 ------------- 198.18.241.2/30

首次部署时，Controller 生成三个独立 Token；Agent 默认以独立节点启动；Web 的本地服务启动，
但尚未连接目标 Controller。**本地就绪检查通过不代表三个组件已经完成认证互通。**

1. 在 Controller 终端查看 ``/etc/sdn-controller/controller.conf``，取得
   ``controller.agentToken``、``controller.adminToken``、``controller.viewerToken``。
   凭据仅保存在该实例目录，不要写回设备定义或共享包。
2. 在 Agent 终端编辑 ``/etc/sdn-agent/agent.conf`` 中的 ``agent`` 对象：
   ``controller`` 设为 ``198.18.240.1:19090``，``endpoint`` 设为
   ``198.18.240.2:9090``，``token`` 使用 Controller 的 agentToken，保留其他字段。
3. 在 Web 终端编辑 ``/etc/sdn-web/web.conf``：``controller`` 设为
   ``198.18.241.1:19090``，``adminToken``、``viewerToken`` 与 Controller 对应字段一致。
4. 在修改过配置的 Agent 和 Web 终端分别执行::

      sdn-device check
      sdn-device restart

``restart`` 重启该设备内的服务，保留容器和平台已接好的接口；Agent 内部 FRR 同时重启，
协议需要重新收敛。此命令不实现 REL-004 中缺失的 Linux 网络配置重建。
多个 Agent 使用同一 Controller 的 agentToken，但保留各自身份目录和可达的 endpoint。

从客户端访问 Web
----------------------------------------

Web 监听容器内 8080，平台当前不直接映射宿主端口。可在宿主机使用临时回环代理，
再通过 SSH 转发给客户端。以下示例使用未占用的 28081 端口，需要宿主机安装 socat。

宿主机终端执行，先从 ``docker ps`` 找到画布上 Web 对应的容器名::

   sudo apt-get install -y socat
   WEB_CONTAINER=替换为Web容器名
   WEB_PID=$(docker inspect -f '{{.State.Pid}}' "$WEB_CONTAINER")
   sudo socat TCP-LISTEN:28081,bind=127.0.0.1,reuseaddr,fork \
     "EXEC:nsenter -t ${WEB_PID} -n socat STDIO TCP:127.0.0.1:8080"

保持该终端运行，在浏览器所在客户端另开终端::

   ssh -N -L 28081:127.0.0.1:28081 alexan@10.8.126.103

浏览器访问 ``http://127.0.0.1:28081``，使用上面 Controller/Web 共同配置的 adminToken 登录。
宿主机 IP 和用户名按实际环境替换。重新部署导致 Web 容器 PID 改变后，需要重建临时代理；
两个转发终端按 Ctrl+C 即可停止，不修改系统服务。

保存范围与恢复限制
----------------------------------------

点击 **保存设备配置 / 保存项目** 时，Agent 执行 ``vtysh -w`` 与 Redis ``SAVE``；
Controller 使用 ``etcdctl snapshot save`` 生成 ``/etc/sdn-controller/etcd-snapshot.db``；
Web 校验并同步原生配置文件。数据库的运行目录也按设备实例独立持久化。

重新部署会复用原生数据库目录及身份，Controller 快照另供人工恢复。
工作台保存前的普通文件复制备份不保证是在线数据库的一致快照，不能代替 Redis/etcd
原生持久化或备份。当前通用目录有每文件 64 MiB、每目录 256 MiB 的限制，本包仅面向小规模实验。

**REL-004 仍未实现**：旧 Running revision、成功任务和数据库恢复，不会自动重建丢失的
bridge、VRF、VXLAN 或完整后端网络配置。动态 MAC/ARP 和协议会话需要重新学习。
不要把保存项目成功解释为全网配置已经具备自动重建能力。

维护者验证
----------------------------------------

构建三个镜像后，在宿主机执行下面的独立集成检查。它创建唯一命名的实验和容器，
测试结束清理自己创建的容器，保留仅 root 可读的证据目录::

   cd ~/program/github/lwns
   sudo python3 examples/device-packages/verify_sdn.py

检查包括实际服务启动、Agent 注册、Web 到 Controller 的认证请求、Agent 提交、
三种保存动作、清理后重新部署的身份/版本/节点清单，以及 REL-004 的网络对象缺失边界。
