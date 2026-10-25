lwns 文档
========================================

.. container:: doc-lead

   lwns（Linux Web Network Simulator）让你在浏览器中搭建、配置和验证网络实验。设备运行在 Linux Docker 宿主机，
   用 veth 连接，通过网页终端操作，并可在本机 Wireshark 中查看报文。

`源码仓库 <https://github.com/nanfengnan1/lwns>`_ · :ref:`下载与获取 <workbench-get-source>` ·
:doc:`故障排查 <user/troubleshooting>`

.. container:: doc-cards

   .. container:: doc-card

      :doc:`安装与启动 <user/deployment>`

      从获取源码开始，准备 Linux 主机，选择开发或发布部署。

      :doc:`选择部署方式 → <user/workbench-start>`

   .. container:: doc-card

      :doc:`完成第一次实验 <user/quickstart>`

      已有工作台地址？导入双网段示例 JSON，让两台 PC 互通，再保存和清理。

      :doc:`打开入门教程 → <user/quickstart>`

   .. container:: doc-card

      :doc:`使用工作台 <user/index>`

      查找镜像导入、画布编辑、设备终端、配置保存和 Wireshark 抓包操作。

      :doc:`浏览操作指南 → <user/workbench>`

   .. container:: doc-card

      :doc:`参与开发 <developer/index>`

      了解工程结构，构建设备镜像，运行测试，维护和发布文档。

      :doc:`打开开发指南 → <developer/index>`

.. container:: doc-path

   **第一次使用的顺序**　获取代码 → 准备环境 → 启动工作台 → 准备镜像 → 部署示例。
   已有地址和 Token 的用户从“第一次实验”开始。

当前支持 FRR 路由器、Linux bridge 交换机和 Linux/VPCS 主机。
完整项目包、VPP 扩展等仍标注为未实现。旧版 OVS/FRR 命令行工具见 :doc:`user/legacy-cli`。

.. toctree::
   :hidden:
   :maxdepth: 1
   :caption: 用户指南

   user/index

.. toctree::
   :hidden:
   :maxdepth: 1
   :caption: 开发指南

   developer/index
