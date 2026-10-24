route-ovs 文档
========================================

route-ovs 提供浏览器中的 Docker/veth 图形组网工作台，支持 FRR 路由器、Linux bridge 交换机、
Linux/VPCS 主机、Web 终端、FRR 配置保存、镜像管理及本机 Wireshark 远程抓包。
项目同时保留使用 Docker、Open vSwitch 和 Linux 网络命名空间的命令行实验工具。

**使用工作台**：从 :doc:`user/index` 按任务选择入口。已有地址和 Token 的用户直接阅读
:doc:`user/quickstart`；需要安装主机的用户先阅读 :doc:`user/deployment` 和 :doc:`user/workbench-start`。

**开发和维护项目**：从 :doc:`developer/index` 查阅工程结构、镜像构建、测试和文档发布。
旧版命令行工具单独放在用户指南末尾，不需要为了使用 Web 工作台先学习 OVS 脚本。

文档按当前可用功能编写；完整项目包、VPP 扩展等方案标注未实现，协议实验模板标注待补充。

.. toctree::
   :maxdepth: 1
   :caption: 用户指南

   user/index

.. toctree::
   :maxdepth: 1
   :caption: 开发指南

   developer/index
