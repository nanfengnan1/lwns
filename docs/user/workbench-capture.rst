Wireshark 抓包操作指南
========================================

从已部署实验的网线发起抓包，在 **浏览器所在电脑** 的 Wireshark 中实时查看报文。
Linux Docker 宿主机运行抓包后端，设备容器本身不需要安装 SSH 服务或 tcpdump。
此功能目前针对 Linux/veth 接口，不自动支持 VPP 内部或 DPDK 接口。

第一次使用按“准备环境 → 安装本地启动器 → 配置 SSH → 开始抓包”的顺序操作。
已经安装配置好的用户可直接阅读 :ref:`workbench-capture-run`，查文件位置见 :ref:`workbench-capture-files`。
网页登录 Token 与 SSH 密码是两套凭据；密码登录不要求提供私钥。

.. contents:: 本页导航
   :local:
   :depth: 2

准备宿主机和本机
----------------------------------------

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - 位置
     - 所需条件
   * - Linux Docker 宿主机
     - 后端以 root 运行，安装 tcpdump；SSH 服务可访问，SSH 用户能登录并运行 python3。
   * - Windows/Linux 客户端
     - 安装图形程序 Wireshark、tshark 和 SSH remote capture（sshdump）组件，以及本地启动器。
   * - 网络
     - 客户端能访问实际工作台地址（开发 5173、发布 8090 或 HTTPS 443）和宿主机 SSH 端口（通常为 22）。

SSH 用户可以是普通用户，不需要 sudo 或 Docker 权限；进入容器网络命名空间由后端处理。
在客户端先用 ``ssh 用户名@宿主机IP`` 确认主机和账号能够登录；OpenSSH 登录成功后，
Wireshark 的认证信息仍需要单独配置，不能假定两者自动共用全部设置。

后端监听端口需能在 SSH 登录的宿主机上通过 ``127.0.0.1`` 访问。
如果使用 Vite、反向代理或自定义端口，浏览器访问地址可以不同，但宿主机内的后端仍需可达。

安装或更新本地启动器
----------------------------------------

在抓包窗口展开“安装、密码登录与保存位置”，点击“下载本地启动器”，解压后安装。
**更新 Web 或后端不会自动更新已经安装在电脑上的启动器**，更新后需重新下载并运行安装脚本。
安装会保留已有连接设置。

Windows
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

在解压目录打开 PowerShell，执行::

  powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1

下载包包含 ``route-ovs-capture.exe`` 时不需要安装 Python。
如果包内只有源码，需要 Python 3.10+；安装脚本无法找到 Python 时可指定::

  powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -Python C:\Python310\python.exe

将示例路径替换为实际 Python 路径。安装只注册当前 Windows 用户的 ``route-ovs://`` 协议。
使用浏览器的用户必须与安装启动器的用户一致。

Linux 桌面
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

准备 Wireshark、tshark、sshdump、Python 3.10+、python3-tk 和 xdg-utils；
软件包拆分随发行版而异。在解压目录执行::

  bash install.sh

在桌面登录用户下安装，不需要 sudo。没有 Tk 时可先在终端配置；默认安装路径下的命令为::

  python3 ~/.local/share/route-ovs-capture/launcher.py --configure http://宿主机IP:8090 --terminal

如果设置了 ``XDG_DATA_HOME``，请改用安装脚本显示的实际路径。

配置 SSH 和保存目录
----------------------------------------

在 Web 点击“本机连接与保存设置”，确认浏览器打开外部应用后填写：

.. list-table::
   :header-rows: 1
   :widths: 28 72

   * - 字段
     - 填写方法
   * - Wireshark 程序
     - 选择 Wireshark.exe 或 wireshark；例如 ``D:\software\Wireshark\Wireshark.exe``。不能选择无图形界面的 tshark。
   * - SSH 主机 / 端口
     - Docker 宿主机的 SSH 地址，端口通常为 22；这里不是 Web 的 8090/5173 端口。
   * - SSH 用户名
     - 能登录宿主机的账号，例如 alexan。
   * - Profile
     - 可选。填写本机已经存在的 Wireshark 配置名称；留空使用默认配置。
   * - 私钥
     - 可选。密码登录可以留空；使用文件密钥时填写实际本机路径。
   * - 本机抓包保存目录
     - 选择当前用户可写的目录，每次抓包会创建独立子目录。
   * - 自动开始
     - 已有可用 Profile 或密钥认证时启用；需要手动输入密码时先不勾选。

连接设置按工作台地址分别保存。``http://宿主机IP:8090`` 与
``http://宿主机IP:5173`` 会使用不同的本地连接设置。
首次从“打开本机 Wireshark”进入时，如果尚未配置，也会先显示这个窗口。

密码登录不需要私钥
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

1. 本地设置填写 SSH 主机、端口和用户名，私钥留空，先不勾选自动开始。
2. 按下一节打开 Wireshark。在其首页找到 ``SSH remote capture``，点击旁边的齿轮。
3. 在 ``Authentication`` 中填写远程用户名和密码；密钥口令也在 Wireshark 中输入。
4. 点击 ``Start``。成功连接后，Web 会话状态变为“抓包中”。

已有能连接的 Wireshark Profile 时，可以选用该 Profile 并启用自动开始。
启动器不会读取或转存 Profile 中的密码。密码、私钥内容和密钥口令不上传到 Web 后端；
如果用户在 Wireshark 中选择保存密码，其存储行为由 Wireshark 管理。

.. _workbench-capture-run:

开始、查看和停止
----------------------------------------

1. 确认实验已部署，在画布点击一根网线，再点击右侧“在 Wireshark 中抓包”。
2. 选择一个端点，例如 ``R1 / eth0``。任一端都能观察这条 veth 上的双向流量。
3. 按需填写 BPF，例如 ``arp or icmp``、``tcp port 179``；留空表示全部流量。
   这里使用抓包过滤语法，与 Wireshark 的显示过滤器语法不同。
4. 选择“完整报文”或指定抓取长度。较短长度可减少流量，但会截断报文内容。
5. 点击“准备抓包”，再点击出现的“打开本机 Wireshark”。第二次点击用于直接唤起本地应用。
6. 在浏览器提示中允许打开应用；根据本地设置自动开始，或在 Wireshark 中输入密码后开始。
7. 在设备终端运行 ping 等测试流量，观察 Wireshark 报文列表和 Web 的已接收字节数。
8. 完成后点击 Web 会话的“停止”，或在 Wireshark 停止抓包。已写入的文件保留。

.. figure:: /_static/images/workbench-capture.png
   :alt: 抓包窗口中的端点选择、认证步骤、会话状态和本机保存路径
   :width: 100%

   抓包窗口示例。图中使用示例会话和路径，实际路径由本机启动器回报。

关闭 Web 对话框后，已连接的抓包继续运行；再次点击连线即可查看及停止。
清理实验、关闭 SSH 通道或退出后端会结束相应会话。最多同时 8 个会话，单次最长 60 分钟。
启动凭证和 SSH 流凭证各有 5 分钟有效期，过期后需重新准备会话。
同一端点已有待连接会话时，先完成连接或停止旧会话，避免重复创建。

.. _workbench-capture-files:

保存文件在哪里
----------------------------------------

新版启动器默认写入以下 **本机目录**：

.. code-block:: text

   Windows：%USERPROFILE%\route-ovs\captures\<时间-端点-随机标识>\capture.pcapng
   Linux：  ~/route-ovs/captures/<时间-端点-随机标识>/capture.pcapng

例如浏览器运行在 Windows 上时，文件保存在该 Windows 用户目录下，
不在 Linux 宿主机的 ``.route-ovs-labs`` 中，也不在容器内。宿主机后端不保留副本。

Web 会话显示启动时指定的完整路径，并提供“复制路径”。复制后可在本机文件管理器打开所在目录，
或在 Wireshark 使用“文件 → 打开”读取。只有成功开始抓包后才会写入文件；
“目标路径已显示”不代表已经收到报文。停止抓包后再复制文件给其他人，以取得完整文件。
如果在 Wireshark 中修改了输出路径或另存，以 Wireshark 的设置为准。

旧版启动器没有指定持久化路径时，需要在 Wireshark 使用“文件 → 另存为”。
升级客户端与后端后再开启新会话，才能看到新版路径回报。

按状态排查
----------------------------------------

.. list-table::
   :header-rows: 1
   :widths: 32 68

   * - 状态或现象
     - 下一步
   * - 等待打开本机程序
     - 点击“打开本机 Wireshark”，允许浏览器打开应用。没有程序时先安装启动器；不要连续点击“准备抓包”。
   * - 启动器已连接，正在打开 Wireshark
     - 查看任务栏和本地错误弹窗，核对 Wireshark 程序和 Profile。旧启动器不回报后续状态，需要更新。
   * - 等待在 Wireshark 中认证
     - 没有启用自动开始，在 SSH 接口齿轮 → Authentication 输入用户名/密码，再点击 Start。
   * - Wireshark 已启动，等待 SSH
     - 查看 Wireshark 的 SSH 错误；核对主机、SSH 端口、账号、Profile 和宿主机内的后端端口。
   * - 抓包中，但没有报文
     - 在目标链路上产生流量，检查端点及 BPF 是否匹配。后端收到 PCAP 文件头即可进入抓包中，字节数包含文件头。
   * - 连接已过期
     - 完成本地设置后重新准备会话。旧链接和已经使用的连接凭证不可重复使用。
   * - 没有路径或仍提示旧版
     - 重启更新后的后端，重新下载并安装启动器，然后开始新会话。仅刷新 Web 不能更新已安装程序。
   * - 已显示路径但找不到文件
     - 先确认实际开始过抓包，再确认查看的是浏览器所在电脑；检查 Wireshark 是否修改路径或报告磁盘错误。

启动器配置和简要诊断日志分别位于：

.. code-block:: text

   Windows：%LOCALAPPDATA%\route-ovs\capture-client.json
            %LOCALAPPDATA%\route-ovs\capture-launcher.log
   Linux：  ~/.config/route-ovs/capture-client.json
            ~/.config/route-ovs/capture-launcher.log

Linux 设置了 ``XDG_CONFIG_HOME`` 时，以该目录替代 ``~/.config``。
排错时结合本地错误弹窗、日志和 Web 会话错误；本地日志不是报文文件。
更多工作台问题见 :doc:`troubleshooting`。
