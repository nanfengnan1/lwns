.lwns 设备包：制作、导入与保存配置
========================================

``.lwns`` 将设备描述与镜像来源关联起来。导入时确认设备名称，后台准备对应镜像，
设备就会出现在左侧设备库；启动、共享配置目录和保存命令从包内读取。

新制作的设备包统一使用 ``.lwns`` 后缀。旧 ``.rov`` 设备包仍可导入，已安装设备无需迁移；
包内 ZIP 结构、``schema_version: 1`` 与清单标识 ``route-ovs-device`` 保持兼容。
此前使用的 Docker 镜像 ``.tar`` / ``.tar.xz`` 属于镜像归档，不能只改后缀变成设备包。

SDN Agent、Controller、Web 的三包制作与组网见 :doc:`sdn-devices`。

.. container:: doc-meta

   **操作位置**：浏览器顶部 **工具 → 设备管理**，或制作机器上的 CLI。

   **完成结果**：设备版本进入当前服务器的设备库，可以添加到项目并保存其支持的配置。

   **文件范围**：设备包保存可复用的设备定义；它不是包含实验拓扑和 R1/R2 配置的完整项目备份。

.. contents:: 本页操作
   :local:
   :depth: 2

先选择你的操作
----------------------------------------

* **已经拿到 .lwns 文件**：直接按 :ref:`rov-import-device` 加载，再添加到画布并部署。
* **已有 alpine/frr:latest，想制作可分享的包**：按 :ref:`rov-frr-offline` 创建描述、导出镜像并生成 ``frr.lwns``，无需重新编译镜像。
* **希望通过浏览器制作**：先准备 ``device.json``，再按 :ref:`rov-web-pack` 选择镜像来源并下载设备包。
* **只有 Dockerfile 或只需引用仓库**：使用 :ref:`rov-cli-pack` 中相应命令。

使用前确认工作台后端已更新并重启，页面中能看到 **工具 → 设备管理**。
旧版可执行安装包需要更新到包含该功能的版本；仅刷新浏览器不会更新后端。
导入和部署需要 Linux Docker 宿主机，部署还需要 root、``ip`` 和 ``nsenter``；
制作仓库引用包或检查包不需要运行 Docker。启动方式见 :doc:`workbench-start`。

.. _rov-import-device:

已有 .lwns 文件：导入设备
----------------------------------------

1. 将 ``.lwns`` 文件准备到 **打开浏览器的客户端电脑**。
   例如浏览器在 Windows 上，选择文件时读取的是 Windows 文件，不是远程 Linux 的目录。
   包只在服务器时，可以下载/复制到客户端，或使用本页后面的 :ref:`rov-cli-import`。
2. 打开 **工具 → 设备管理 → 导入设备包**，选择 ``.lwns`` 文件，等待上传和检查完成。
3. 检查显示的分类、版本和镜像来源。设备名称默认取自包内，可以改为便于辨认的名称。
4. 点击 **导入设备**，等待任务日志显示成功。需要的镜像会在当前连接的服务器上加载、拉取或构建。
5. 切换到 **已安装设备**，确认新条目及版本已出现，且没有“镜像缺失”提示。

.. tip::

   **导入成功的标志**：设备管理中出现新设备，左侧对应分类出现可用卡片。
   这一步只准备设备库，尚未创建实验中的路由器容器。

添加到画布并部署
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

1. 关闭设备管理，选择 **实验 → 新建项目**，填写项目名称；也可以打开已有项目。
2. 在左侧点击 **路由器** 等对应分类，按刚才设置的设备库名称找到卡片，点击或拖入画布。
3. 选择画布中的设备，设置 R1 等实例名称、所需端口数量与地址，连接其他设备的端口。
   接口由平台根据项目拓扑创建，设备包不预先携带实验网卡。
4. 点击 **保存项目**，再点击 **部署实验**。等待部署日志成功、设备进入运行状态。
   如果项目已经部署，新增设备和连线后点击 **应用拓扑**。
5. 双击设备打开终端。FRR 默认进入 ``vtysh``，可以执行 ``show version``、``show running-config`` 检查。

连接和地址设置的完整步骤见 :doc:`workbench-editor`。
新设备库条目不会自动替换已有项目中的旧设备；原镜像和内置模板继续兼容。

镜像准备完成后才显示可部署的设备卡片。失败时查看任务日志，修复原因后重试；
单纯选择文件或检查设备包不会创建实验容器，也不会执行设备的启动和保存命令。

设备库名称与画布上的实例名称不同。例如设备库叫“FRR 路由器”，
拖入画布后可以叫 R1、R2。改名不会改变内部 ID 或配置目录。
设备包中的镜像与启动流程由版本固定，不能在实例属性中随意替换；需要改变时制作新版本。

普通镜像仍可通过 :doc:`workbench-images` 中的兼容入口管理。
这类镜像沿用原来的模板，导入普通镜像不会自动获得设备包声明的保存能力。

.. _rov-frr-offline:

FRR 示例：从已有镜像制作 frr.lwns
----------------------------------------

本例使用项目当前兼容的 ``alpine/frr:latest``，生成包含镜像的离线包。
**下面的命令在 Linux 宿主机执行，不是在 R1 的设备终端中执行。**
制作过程不启动实验，也不需要停止正在运行的 Web 服务。

一、准备工作目录
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

进入你的源码目录，确认镜像存在，并创建独立的输出目录::

  cd ~/program/github/lwns
  docker image inspect alpine/frr:latest --format '{{.Id}}'
  mkdir -p ~/lwns-devices/frr

项目如果放在其他目录，请替换第一行路径。若镜像不存在，先按 :doc:`workbench-images`
准备镜像。本例会创建 ``~/lwns-devices/frr/device.json``，已有同名自定义文件时应先保留它。

二、创建 device.json
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

复制执行下面的完整命令，生成描述文件::

  cat > ~/lwns-devices/frr/device.json <<'JSON'
  {
    "schema_version": 1,
    "id": "lwns-frr",
    "version": "1.0.0",
    "name": "FRR 路由器",
    "category": "router",
    "image": "alpine/frr:latest",
    "source": {
      "type": "archive",
      "path": "image.tar"
    },
    "profile": "frr",
    "console": ["vtysh"],
    "persistent_dirs": [
      {
        "id": "frr",
        "target": "/etc/frr",
        "initialize_from": "image",
        "owner": "frr:frr",
        "mode": "rw",
        "permissions": "0750"
      }
    ],
    "startup": {
      "phase": "after_links",
      "prepare": [],
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
        "user": "0",
        "timeout_seconds": 30,
        "expected_files": [
          "/etc/frr/daemons",
          "/etc/frr/frr.conf",
          "/etc/frr/vtysh.conf"
        ]
      }
    }
  }
  JSON

``image`` 必须与要导出的镜像标签一致。``persistent_dirs`` 让每个实例独立共享 ``/etc/frr``；
``startup`` 在接线后启动 FRR；``save_config`` 执行 ``vtysh -w``。
``profile: frr`` 保留 FRR 的权限、协议进程和配置检查，因此无需另写通用 ready 命令。
该描述要求镜像提供 ``/usr/lib/frr/docker-start``、``vtysh`` 和 FRR 用户及默认配置。

三、导出镜像并制作设备包
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

仍在 lwns 项目根目录执行::

  docker save \
    --output ~/lwns-devices/frr/frr.tar \
    alpine/frr:latest

  python3 script/python/lab_server.py device pack \
    --descriptor ~/lwns-devices/frr/device.json \
    --image-tar ~/lwns-devices/frr/frr.tar \
    --output ~/lwns-devices/frr/frr.lwns

使用 ``docker save`` 导出的未压缩 ``.tar``，不要使用 ``docker export``。
工具会校验归档中的镜像名称，自动将镜像存为包内 ``image.tar`` 并生成校验清单。
这里不需要 Dockerfile，也不需要重新构建已有镜像。

四、检查并分享
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

检查制作结果::

  python3 script/python/lab_server.py device inspect \
    ~/lwns-devices/frr/frr.lwns

命令成功退出，并输出设备定义和资源清单。结果中应能看到 ``alpine/frr:latest``、
``archive`` 来源和 ``image.tar`` 资源。最终目录为：

.. code-block:: text

   ~/lwns-devices/frr/
   ├── device.json
   ├── frr.tar
   └── frr.lwns       # 分享或上传这一个文件即可

按 :ref:`rov-import-device` 加载 ``frr.lwns``，再添加到画布并部署。
设备包不包含已有实验中 R1/R2 的个人配置，这些配置按项目独立保存。

.. _rov-web-pack:

通过 Web 制作设备包
----------------------------------------

1. 将 ``device.json`` 准备到浏览器所在电脑；可以使用上面的 FRR 描述，或设备开发者提供的文件。
2. 打开 **工具 → 设备管理 → 制作设备包**，选择描述文件，确认自动填充的名称、版本和分类。
3. 选择下面的一种镜像来源，填写引用或选择对应文件。
4. 点击 **制作 .lwns 设备包**，等待任务成功，再点击下载，保存到客户端。
5. 要在工作台使用，切换 **导入设备包**，加载刚下载的文件；制作与导入是两个独立操作。

.. list-table::
   :header-rows: 1
   :widths: 22 40 38

   * - 来源
     - 制作时
     - 导入时
   * - 镜像仓库
     - 记录镜像引用；制作时不拉取
     - 使用匹配镜像，缺少时拉取
   * - 已有镜像
     - 从当前后端的已管理镜像中选择并导出，包含在设备包中
     - 加载包内的离线镜像
   * - 镜像归档
     - 选择 ``docker save`` 生成的未压缩 ``.tar``，放入设备包
     - 加载包内镜像；归档必须包含描述中指定的镜像
   * - Dockerfile
     - 选择 Dockerfile，包含构建配方；制作时不构建
     - 执行构建，可能需要联网获取基础镜像和依赖

制作完成后，页面显示服务器保存路径，并提供下载按钮。制作成功不会自动注册设备；
要使用该文件，再从“导入设备包”加载。
只有包含镜像归档的包能在没有对应镜像且无法联网时加载；构建配方包不等于离线镜像包。

整个表单属于一个制作任务。即使设备描述与大镜像分开上传，后台也按任务关联，
不用用户填写关联编号。浏览器文件来自客户端，制作、镜像处理和设备库存储发生在
当前 Web 连接的服务器上；下载后的文件才保存在客户端。

例如制作本页的 FRR 离线包：上传 ``device.json``，选择 **已有镜像** 中的
``alpine/frr:latest``，即可由后台导出并打包；也可以选择 **镜像归档**，上传前面生成的 ``frr.tar``。
已有镜像列表没有目标镜像时，先通过 **镜像管理（兼容）→ 已有镜像** 将其加入管理清单。
上传文件从客户端读取；“已有镜像”使用的是远程后端中的镜像。

.. _rov-cli-pack:

通过 CLI 制作与检查
----------------------------------------

源码版在项目根目录执行。以下命令只制作和检查包，不要求启动 Web 服务。

使用项目提供的 FRR 示例，制作含 Dockerfile 的设备包::

  python3 script/python/lab_server.py device pack \
    --descriptor examples/device-packages/frr/device.json \
    --dockerfile examples/device-packages/frr/Dockerfile \
    --output frr-1.0.0.lwns

示例 Dockerfile 基于 ``alpine/frr:latest``，导入并构建前需准备该基础镜像。
它展示两文件设备定义，不替代 :doc:`../developer/build-images` 中的 FRR 源码构建流程。

使用已有 ``alpine/frr:latest`` 制作仓库引用包::

  python3 script/python/lab_server.py device pack \
    --descriptor examples/device-packages/frr/device.json \
    --image alpine/frr:latest \
    --output frr-reference.lwns

离线包按 :ref:`rov-frr-offline` 制作。仓库里的 Dockerfile 示例使用 ``lwns/frr:1.0.0``，
本页离线描述使用 ``alpine/frr:latest``，不要把不同镜像标签的描述与归档混用。
检查上面生成的构建配方包或引用包，例如::

  python3 script/python/lab_server.py device inspect frr-1.0.0.lwns

输出包括设备定义、来源和资源校验信息；不会执行包内动作。
输出文件已存在时默认拒绝覆盖，需要时显式使用 ``--force``。
设备版本冲突应修改描述中的 ``version`` 或使用 ``pack --version``，
不能通过覆盖输出文件强制替换已安装版本。

已安装 Linux 目录包时，将上面的 ``python3 script/python/lab_server.py``
替换为 ``lwns``，例如 ``lwns device inspect ~/lwns-devices/frr/frr.lwns``。
Web 与 CLI 使用相同模块，生成的设备包可以互相导入。

.. _rov-cli-import:

CLI 导入到指定服务器
----------------------------------------

在要运行设备的 Linux 宿主机上执行；命令不会自动连接浏览器所连接的另一台机器::

  sudo .venv/bin/python script/python/lab_server.py device import ~/lwns-devices/frr/frr.lwns \
    --name "FRR 路由器" \
    --data-dir .lwns-labs

上例使用源码默认数据目录，并在项目根目录运行。如果后端通过 ``--data-dir`` 使用其他目录，
应将该参数替换为相同路径，否则浏览器看不到刚导入的设备。
从旧版升级时可能仍沿用旧数据目录，以后端启动日志为准，详见 :ref:`lwns-upgrade`。
目录包可执行，默认数据目录来自安装配置::

  sudo lwns device import ~/lwns-devices/frr/frr.lwns --name "FRR 路由器"

指定与工作台一致的数据目录。CLI 导入与后端共用数据目录锁：后端正在使用该目录时，
通过 Web 导入即可；如需使用 CLI 导入，应先停止使用该目录的后端，完成后再启动。
制作和检查包不占用这个锁。导入只注册设备及准备镜像，不自动部署项目。

完成后启动使用同一数据目录的后端，刷新浏览器中的设备管理和设备库，再按
:ref:`rov-import-device` 中的“添加到画布并部署”操作。

设备如何保存和恢复配置
----------------------------------------

``device.json`` 声明原生配置目录、启动步骤和必需的 ``actions.save_config``。
第一次部署时准备默认文件；以后重新部署使用该实例已保存的文件。
平台创建接口、挂载实例目录，然后按设备声明启动程序并检查就绪。

部署后，在设备终端配置，再点击 **保存设备配置** 或 **保存项目**。
后台检查设备归属、共享目录和状态，备份后执行保存动作，校验必要文件并报告逐设备结果。
通用设备的属性面板显示持久化路径和文件列表；FRR 仍可查看 ``frr.conf`` 内容。

验证顺序为：**终端配置 → 保存并确认成功 → 清理设备 → 重新部署 → 检查设备配置**。
同一镜像创建的 R1、R2 有独立目录，不会共享彼此的配置。

保存范围取决于设备定义。手工 Linux 路由、VRF、VXLAN 或 VPP CLI 修改，
只有被保存动作写入文件，并由启动流程恢复时才会保留。
现有 Linux/VPCS 和 Linux bridge 内置模板仍不自动保存全部 Shell 运行状态；
通用机制也不代表已经完成所有 VPP、OVS 或厂商设备适配。
FRR 的具体操作见 :ref:`workbench-data-frr`。

名称、更新与删除
----------------------------------------

设备定义用 **ID＋版本** 识别。导入时修改的是本机设备库显示名，原始包内容和身份保持不变。
新建画布设备使用独立实例 ID，旧项目中的 ID 保持兼容。

* 重复导入同一包时复用已有版本。
* 同一 ID、同一版本但内容不同会拒绝导入，应发布新版本。
* 新版本与旧版本并存；已有项目继续使用原来的版本和镜像内容标识。
* 同名不同 ID 的定义可以并存，名称不用于自动覆盖或删除。
* 已被项目引用的版本不能直接删除。先处理引用，再从设备管理删除条目。
* 删除设备库条目同步移除侧边栏卡片，不删除项目配置或物理 Docker 镜像。

导入时会固定实际镜像 ID。若以后标签指向不同镜像，旧项目不会自动升级；
原镜像已缺失且仓库标签已变化时，应恢复原镜像或发布新设备版本。

文件保存在哪里
----------------------------------------

所有路径以启动时选择的数据目录为根；源码默认 ``.lwns-labs``，
目录包默认 ``/var/lib/lwns``。

.. code-block:: text

   <data-dir>/
     device-library/
       registry.json
       <设备定义ID>/<版本>/device.lwns
     device-packages/
       artifacts/<制作任务ID>.lwns
       jobs/<任务ID>.json
       uploads/<上传ID>/
     devices/<项目ID>/<实例ID>/
       config-meta.json
       <配置目录ID>/
       backups/

设备库中的包、制作产物与任务历史目前不自动轮转；删除设备定义不同时清除历史制作产物。
临时上传有数量、大小和过期限制；成功后自动回收，导入失败时保留供重试，
制作失败可重新选择资源提交。重启会清理中断的暂存上传。
配置数据随项目备份；完整项目迁移仍按 :doc:`workbench-data` 操作，不能只复制 ``.lwns``。
