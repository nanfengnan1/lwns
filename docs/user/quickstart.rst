快速开始
========================================

首次使用图形界面时，按下面的 Web 流程完成一次双网段实验。
需要直接使用 ``frr_init.sh`` 的用户，可继续阅读本页后半部分的命令行流程。

Web：完成第一次组网
----------------------------------------

1. 按 :ref:`workbench-start` 完成共用准备，并选择 :ref:`workbench-start-http` 或 :ref:`workbench-start-https` 启动。
2. HTTP/1.1 方式打开 ``http://宿主机IP:8090``；HTTPS 方式完成 Caddy 和证书配置后打开 ``https://宿主机IP``，输入当前后端显示的访问令牌。
3. 确认本机 Docker 已加载 ``alpine/frr:latest`` 和 ``alpine/vpcs:latest``；也可从左侧“镜像管理”导入。
4. 点击左下角“双网段路由实验”，核对设备镜像，点击“保存”及“部署实验”，等待“运行中”。
5. 双击 PC1，在 Web 终端执行 ``ping -c 3 10.10.2.10``，验证经过 R1 到 PC2 的通信。
6. 需要抓包时，点击网线并按 :doc:`workbench-capture` 打开本机 Wireshark。
7. 若修改过 FRR 配置，点击“保存设备配置”并确认成功，再“清理设备”；重新部署可验证配置恢复。

只希望设计拓扑时可使用 ``--preview``，但设计模式不会创建容器，也无法执行上述 ping 和抓包。
设备拖动、自动对齐、连线优化、画布注释和端口属性见 :doc:`workbench`；保存与完整备份的区别见 :doc:`workbench-data`。

命令行：创建和管理 FRR 容器
----------------------------------------

以下流程使用旧版脚本，只先验证容器和管理入口；业务链路、IP 地址和路由协议需另行配置。
Web 工作台不会接管这些脚本创建的容器。

创建 FRR 容器
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

完成 :doc:`deployment` 后，从项目根目录进入脚本目录，创建两个容器::

  cd script
  bash frr_init.sh --help
  bash frr_init.sh -n 2

脚本创建 ``frr_A``、``frr_B``，登记同名 netns，并启用和启动 ``ospfd``。
创建数量范围为 1 到 26。操作记录写入当前目录的 ``.frr_containers.tmp``。

查看运行状态
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

在同一工作目录执行::

  docker ps
  sudo ip netns list
  docker exec frr_A vtysh -c 'show version'
  docker exec frr_A vtysh -c 'show interface'

如果容器仍在运行，但缺少同名 netns 登记，可针对清单中的容器执行::

  bash frr_init.sh --netns

已有同名映射指向其他网络命名空间时，脚本会报错，应先核对映射归属。

后续操作
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* 按 :doc:`topology` 规划 OVS 链路并采集拓扑。
* 按 :doc:`vpcs` 接入测试终端。
* 按 :doc:`network` 配置 DHCP 服务端和客户端，验证地址与连通性。
* 按 :doc:`protocols/index` 编写和执行具体协议实验。

结束实验
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

先按各工具或实验步骤清理 VPCS 和 OVS 连接，再在原工作目录执行::

  bash frr_init.sh -s

该命令删除清单中容器的同名 netns 登记，停止并删除容器。
它不是完整实验回收器，不代替 VPCS、OVS 或协议实验自身的清理步骤。
