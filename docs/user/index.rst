用户指南
========================================

route-ovs 用浏览器搭建 Docker/veth 网络实验。先按你的任务选择入口，不必从头读完所有章节。

.. rubric:: 我应该从哪里开始

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - 你现在的情况
     - 推荐路线
   * - 已经拿到工作台地址和 Token
     - 直接按 :doc:`quickstart` 完成第一次实验，不需要在自己电脑安装后端。
   * - 要在 Linux 主机安装工作台
     - :ref:`下载源码 <workbench-get-source>` 或 :ref:`获取安装包 <workbench-get-package>` → 环境准备 → :doc:`workbench-start`。
   * - 要修改源码并调试页面
     - 按 :ref:`开发部署流程 <workbench-deploy-dev>` 打开两个终端，浏览器访问 5173。
   * - 已在使用，想完成某项操作
     - 下方“工作台操作”按镜像、画布、终端、保存和抓包分别查阅。
   * - 出现报错或连接不上
     - :doc:`troubleshooting`，按现象定位对应操作。
   * - 使用旧版 frr_init.sh 等脚本
     - :doc:`legacy-cli`，后续阅读旧版 OVS、VPCS 和协议实验章节。

.. rubric:: 先分清操作位置

* **Linux 宿主机**：运行后端和 Docker，保存实验数据，创建容器和网线。
* **客户端电脑**：打开浏览器；抓包时在这台电脑运行 Wireshark 并保存报文文件。
* **设备终端**：网页中打开的容器命令行，命令作用于所选设备。

同一台 Linux 电脑可以兼任宿主机和客户端。教程会标明命令在哪执行；
源码命令在项目根目录执行，目录包命令在解压目录或系统路径执行。
网页登录使用后端 Token；Wireshark 的 SSH 连接使用宿主机账号，两者是不同凭据。

第一次实验的顺序是：连接工作台 → 准备镜像 → 加载示例 → 保存并部署 → ping 验证 → 保存设备配置 → 清理设备。
“清理设备”保留实验及已保存配置；“删除实验”会移除实验数据，详见 :doc:`workbench-data`。

首次使用与部署
----------------------------------------

.. toctree::
   :maxdepth: 1

   deployment
   workbench-start
   workbench-install
   quickstart

工作台操作
----------------------------------------

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

.. toctree::
   :maxdepth: 1

   troubleshooting
   workbench-https
   architecture
   doc-deploy

旧版命令行工具与实验
----------------------------------------

.. toctree::
   :maxdepth: 1

   legacy-cli
   topology
   vpcs
   network
   protocols/index
