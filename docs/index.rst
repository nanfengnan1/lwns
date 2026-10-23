route-ovs 文档
========================================

route-ovs 提供浏览器中的 Docker/veth 图形组网工作台，支持 FRR 路由器、Linux bridge 交换机、
Linux/VPCS 主机、Web 终端、FRR 配置保存、镜像管理及本机 Wireshark 远程抓包。
项目同时保留使用 Docker、Open vSwitch 和 Linux 网络命名空间的命令行实验工具。

用户指南介绍环境准备、实验操作和排障；开发指南介绍工程结构、镜像构建、
脚本维护、测试与文档发布。用户文档按当前已实现功能编写；完整项目包、VPP 扩展等讨论方案明确标注未实现，
尚未完成的协议实验以“待补充”标注。首次使用从 :doc:`user/quickstart` 开始。

.. toctree::
   :maxdepth: 1
   :caption: 用户指南

   user/index

.. toctree::
   :maxdepth: 1
   :caption: 开发指南

   developer/index
