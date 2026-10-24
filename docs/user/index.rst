用户指南
========================================

适用于搭建路由实验、连接测试终端、查看拓扑和验证路由协议的使用者。
首次使用建议依次阅读 :doc:`deployment`、:doc:`quickstart` 和 :doc:`workbench`。
启动入口统一在 :ref:`workbench-start`：HTTP/1.1 直接启动见 :ref:`workbench-start-http`，
HTTPS / HTTP/2 / HTTP/3 的安装、配置与证书见 :ref:`workbench-start-https`。
抓包的安装、密码认证及文件位置见 :doc:`workbench-capture`；实验保存和迁移见 :doc:`workbench-data`。
遇到问题先查看 :doc:`troubleshooting`。

命令示例以 Linux 宿主机上的项目根目录为起点；Windows 客户端操作和旧版 FRR 管理命令另有位置说明。
Web 工作台与旧脚本工具相互独立，请按所选入口的章节操作。

.. toctree::
   :maxdepth: 2

   architecture
   deployment
   quickstart
   workbench
   workbench-https
   topology
   vpcs
   network
   protocols/index
   troubleshooting
   doc-deploy
