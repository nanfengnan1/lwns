用户指南
========================================

.. container:: doc-lead

   从第一次部署到日常组网，按你要完成的任务选择教程。
   如果已有工作台地址和 Token，可以直接开始第一次实验。

.. rubric:: 我应该从哪里开始

.. container:: doc-cards

   .. container:: doc-card

      :doc:`我要安装工作台 <deployment>`

      获取源码或目录包，准备 Linux 宿主机，再选择启动方式。

      :ref:`下载源码 <workbench-get-source>` · :ref:`获取安装包 <workbench-get-package>` · :doc:`启动 <workbench-start>`

   .. container:: doc-card

      :doc:`我要完成第一次实验 <quickstart>`

      连接工作台、导入示例 JSON、部署设备，并从 PC1 验证到 PC2 的连通性。

      :doc:`开始组网 → <quickstart>`

   .. container:: doc-card

      :doc:`我要操作已有实验 <workbench>`

      按功能查阅镜像、画布、终端、保存和抓包，无需重做安装步骤。

      :doc:`画布 <workbench-editor>` · :doc:`保存配置 <workbench-data>` · :doc:`抓包 <workbench-capture>`

   .. container:: doc-card

      :doc:`我要解决报错 <troubleshooting>`

      按页面打不开、部署失败、配置丢失、SSH 等待等现象定位。

      :doc:`查找处理方法 → <troubleshooting>`

修改源码请看 :ref:`开发部署 <workbench-deploy-dev>`；使用 ``frr_init.sh`` 等脚本请看 :doc:`legacy-cli`。

.. rubric:: 先分清操作位置

* **Linux 宿主机**：运行后端和 Docker，保存实验数据，创建容器和网线。
* **客户端电脑**：打开浏览器；抓包时在这台电脑运行 Wireshark 并保存报文文件。
* **设备终端**：网页中打开的容器命令行，命令作用于所选设备。

同一台 Linux 电脑可以兼任宿主机和客户端。教程会标明命令在哪执行；
源码命令在项目根目录执行，目录包命令在解压目录或系统路径执行。
网页登录使用后端 Token；Wireshark 的 SSH 连接使用宿主机账号，两者是不同凭据。

.. container:: doc-path

   **实验流程**　连接工作台 → 准备镜像 → 新建或导入拓扑 → 保存并部署 → ping 验证 → 保存设备配置 → 清理设备。

“清理设备”保留实验及已保存配置；“删除实验”会移除实验数据，详见 :doc:`workbench-data`。

首次使用与部署
----------------------------------------

按“获取 → 启动 → 实验”顺序阅读。目录包教程供已取得可执行安装包的用户使用。

.. toctree::
   :maxdepth: 1

   deployment
   workbench-start
   workbench-install
   quickstart

工作台操作
----------------------------------------

每篇围绕一个操作，说明入口、步骤、结果和当前限制。

.. toctree::
   :maxdepth: 1

   workbench
   workbench-images
   workbench-editor
   workbench-terminal
   workbench-data
   workbench-capture

维护与参考
----------------------------------------

需要排错、启用 HTTPS 或了解系统原理时再阅读。

.. toctree::
   :maxdepth: 1

   troubleshooting
   workbench-https
   architecture
   doc-deploy

旧版命令行工具与实验
----------------------------------------

这一组使用独立脚本管理实验，与 Web 工作台的操作和数据分开。

.. toctree::
   :maxdepth: 1

   legacy-cli
   topology
   vpcs
   network
   protocols/index
