Linux 程序打包与版本发布
============================================================

本页面向维护者，说明如何从确定的 Git 提交构建可直接安装的 Linux 程序包，
校验安装、运行和升级，再上传到 GitHub Release。接收方操作见 :doc:`/user/workbench-install`。
程序包包含后端及 Python 运行库、已构建 Web、离线手册和安装脚本；设备镜像单独分发。

.. contents:: 发布步骤
   :local:
   :depth: 2

发行范围与版本来源
------------------------------------------------------------

当前正式打包目标是 Linux x86_64、glibc 2.35 基线，构建机为 Ubuntu 22.04。
目录包安装到系统目录，不使用 deb/rpm；目标机无需 Node.js/npm 或后端 Python 虚拟环境。
宿主机仍需 Docker Engine/CLI、iproute2、util-linux；SSH 抓包另需 tcpdump、sshd 和 python3。
Alpine/musl、ARM64 和更旧 glibc 需要独立构建、测试和附件，不能只改文件名。

“正式发行包”指来源固定、安装可校验、配置与程序分离、保留升级/回退路径、发布前完成对应验收。
产品仍面向单用户、单台 Linux Docker 宿主机；不因打包而获得多租户隔离、高可用或跨宿主机能力。

.. list-table:: 不同文件的用途
   :header-rows: 1
   :widths: 35 65

   * - 内容
     - 含义
   * - Git tag v1.0
     - 指向确定的源码提交，本身没有二进制附件
   * - lwns-1.0-linux-x86_64.tar.xz
     - 可执行程序目录包，解压后运行 install.sh
   * - 同名 .sha256
     - 整个压缩包的校验值
   * - validation.json
     - 该具体归档的最终安装、运行与集成验证记录
   * - 设备包
     - 容器设备描述和镜像来源，与工作台可执行安装包不同
   * - GitHub Source code ZIP / tar.gz
     - 自动生成的标签源码，不是可执行安装包

原 ``v1.0`` 指向 ``bd8eab96d150fe6df70586b08f012535108d2b12``。
这个版本使用 ``.rov`` 设备包；后续 main 的设备包后缀、版本格式及 SDN 示例不自动进入它。
给已有 tag 增加程序附件时，应构建该 tag 的源码，不把当前 main 编译后标为旧版。
打包工具和发行说明可以独立改进，本次工具的 SHA256 与应用提交分别记录在 build-info.json。

1. 准备工具与干净快照
------------------------------------------------------------

在 Linux 发布机获取维护工具源码。已有工作区可直接进入，不要覆盖其他人的本地修改：

.. code-block:: bash

   git clone https://github.com/nanfengnan1/lwns.git
   cd lwns

需要 Python 3.10+（含 venv/pip）、Node.js 24 或满足 web/package.json 的版本、
Git、Bash、GNU tar/coreutils、xz、Docker 和 GitHub CLI。
使用计划支持的最旧 glibc 系统构建；本机 Node 20 不满足本版本前端的构建要求。

以下以重建已有 v1.0 为例，第 1～5 步保持同一 Bash 终端：

.. code-block:: bash

   set -euo pipefail
   LWNS_REPO="$PWD"
   LWNS_TAG=v1.0
   LWNS_VERSION=1.0
   git fetch origin "tag" "$LWNS_TAG"
   LWNS_COMMIT="$(git rev-parse "$LWNS_TAG^{commit}")"
   LWNS_OUT="$LWNS_REPO/release/$LWNS_TAG-$(date +%Y%m%d-%H%M%S)"
   LWNS_SOURCE="$LWNS_OUT/source/lwns"
   mkdir -p "$LWNS_OUT/source" "$LWNS_OUT/logs"
   git archive --format=tar.gz --prefix=lwns/ \
     --output="$LWNS_OUT/lwns-$LWNS_TAG-source.tar.gz" "$LWNS_COMMIT"
   tar -xzf "$LWNS_OUT/lwns-$LWNS_TAG-source.tar.gz" -C "$LWNS_OUT/source"
   python3 -m venv "$LWNS_OUT/build-env"
   LWNS_PYTHON="$LWNS_OUT/build-env/bin/python"
   "$LWNS_PYTHON" -m pip install \
     -r "$LWNS_SOURCE/packaging/linux/requirements-build.txt" \
     -r "$LWNS_SOURCE/tests/requirements.txt" \
     -r "$LWNS_SOURCE/docs/requirements.txt"

构建环境与正在运行的服务分开。git archive 不携带未提交文件、设备镜像、运行配置或实验数据。
``--source-archive`` 会逐项核对快照文件；打包前修改原始源码会失败，应重新提交并选择正确版本。

2. 构建前端与验证源码
------------------------------------------------------------

.. code-block:: bash

   npm --prefix "$LWNS_SOURCE/web" ci --include=optional
   npm --prefix "$LWNS_SOURCE/web" test
   npm --prefix "$LWNS_SOURCE/web" run format:check
   npm --prefix "$LWNS_SOURCE/web" run build
   (
     cd "$LWNS_SOURCE"
     "$LWNS_PYTHON" -B -m unittest discover -s tests -v
   )
   "$LWNS_PYTHON" -B -m unittest discover \
     -s "$LWNS_REPO/tests" -p test_release_build.py -v

仅构建前端时也可使用 Node 24 的临时 Docker 容器，编译出的 web/dist 与后端发行系统分离。
测试记录应列出通过、跳过和失败项，不能把显式跳过的 Docker/抓包用例当作通过。
真实设备用例使用唯一项目名和独立数据目录；不要重置正在使用的实验。

.. code-block:: bash

   (
     cd "$LWNS_SOURCE"
     sudo env LWNS_DEVICE_DOCKER_TESTS=1 "$LWNS_PYTHON" -B -m unittest \
       discover -s tests -p test_device_runtime_docker.py -v
     sudo env LWNS_DEVICE_PACKAGE_DOCKER_TESTS=1 "$LWNS_PYTHON" -B -m unittest \
       discover -s tests -p test_device_package_docker.py -v
   )

上述用例需要对应的本地设备镜像；镜像不可用造成的跳过应明确记录。
冻结程序还要单独验证设备部署与宿主机命令环境，不能只测试 Python 源码模式。

3. 构建离线手册并记录验证
------------------------------------------------------------

正常新版本应先把文档提交到待发布源码，再从该快照构建：

.. code-block:: bash

   "$LWNS_PYTHON" -m sphinx -W --keep-going -n -b html \
     -d "$LWNS_OUT/docs-cache" "$LWNS_SOURCE/docs" "$LWNS_OUT/html"

原 v1.0 没有本发布页。首次补发安装包时，在另一个仅用于文档的标签副本中补充本页、
实际下载地址和安装文件名，再构建该副本的 HTML；保留说明或补丁记录。
不要因此修改已校验的应用源码快照，也不要用当前 main 的全套新功能手册替代旧版手册。
HTML 应包含完整静态资源、搜索与下载文件。PDF 在具备 XeLaTeX/latexmk 的文档环境按
:doc:`build-docs` 另行构建；缺少该工具链时明确标注本次只提供 HTML。

将构建前真实执行的命令、结果、工具版本、跳过项和集成限制写入
``$LWNS_OUT/VERIFICATION.md``。最终归档生成后还有第 5 步的验证，结果记录为独立 validation.json，
其中包含最终归档 SHA256；不要为了把未来测试写成通过而预填结果。

4. 生成正式程序包
------------------------------------------------------------

使用维护工作区中的新版打包工具，但明确将应用输入指向固定快照：

.. code-block:: bash

   "$LWNS_PYTHON" "$LWNS_REPO/packaging/linux/build.py" \
     --release --version "$LWNS_VERSION" --source-tag "$LWNS_TAG" \
     --source-root "$LWNS_SOURCE" --source-revision "$LWNS_COMMIT" \
     --source-archive "$LWNS_OUT/lwns-$LWNS_TAG-source.tar.gz" \
     --docs-dir "$LWNS_OUT/html" \
     --verification-report "$LWNS_OUT/VERIFICATION.md" \
     --skip-web-build --compression xz --output "$LWNS_OUT"

PyInstaller 使用 onedir，程序与运行库放在 app/。临时构建目录使用 Linux 本地空间，
保持运行库符号链接，不要先在 Windows 解压再压回去。
默认 xz；需要旧交付格式时显式使用 ``--compression gz``。同名输出存在时拒绝覆盖。
``--release`` 要求来源、HTML 和验证记录齐全，但最终可用性仍由第 5 步实测确认。

.. code-block:: text

   lwns-1.0-linux-x86_64/
   ├── app/lwns                  可执行入口及 _internal/ 运行库
   ├── install.sh                系统安装器
   ├── lwns-web.service          systemd 模板
   ├── README.md                 安装、运行和维护说明
   ├── INSTALL.rst               标签原安装说明
   ├── Caddyfile.example         可选 HTTPS / HTTP2 / HTTP3 入口
   ├── docs/html/                离线手册
   ├── sources/                  原始 Git 标签源码
   ├── build-tools/              本次实际使用的打包工具
   ├── THIRD_PARTY/              可找到的第三方许可/版权文件
   ├── build-info.json           应用提交、工具摘要、glibc、Python、依赖
   ├── build-requirements.txt     构建环境依赖版本
   ├── VERIFICATION.md           构建前验证及最终验收记录位置
   ├── BUILD_ID                  安装目录中的唯一构建编号
   └── SHA256SUMS               包内文件校验

源码标签缺少独立项目 LICENSE 时，不由打包器另行选择许可证。
固定依赖版本、源码和工具可帮助重建；系统库和基础工具变化仍可能改变字节结果。
需要部署已验证的确切版本时，以归档 SHA256 和 build-info.json 为准。

5. 验证实际归档
------------------------------------------------------------

.. code-block:: bash

   LWNS_ASSET="lwns-$LWNS_VERSION-linux-x86_64.tar.xz"
   (
     cd "$LWNS_OUT"
     xz --test "$LWNS_ASSET"
     sha256sum --check "$LWNS_ASSET.sha256"
   )
   "$LWNS_PYTHON" "$LWNS_REPO/tests/check_linux_package.py" "$LWNS_OUT/$LWNS_ASSET"

新版验收器支持 tar.xz 和 tar.gz。它在隔离系统根目录检查安装、篡改拒绝、外部文件保护、
API 认证、WebSocket、gzip/缓存、重复安装、升级保留配置/数据、每机独立 Token，以及卸载保留数据。
验收器不向真实 /opt、/etc、/var/lib 安装，也不调用正式宿主服务。

还应使用解压后的实际二进制在独立环境验证：

* 最低目标系统与至少一个声明支持的较新 glibc 系统中启动；不借用开发虚拟环境。
* systemd 启动与停止、配置读取、回环监听、正常退出，以及已有数据锁。
* Docker/veth 部署、设备包导入、终端、保存、清理后恢复；抓包按实际支持范围单独验收。
* 测试完成后只清理本次唯一标识的容器、链路、数据目录及临时服务。

最终 validation.json 记录实际通过项、限制、测试时间、源码提交和该归档 SHA256。
它属于发布附件；本次工作区中的原始日志可留在被 Git 忽略的 release/ 下。

6. 创建或复用 tag
------------------------------------------------------------

给已经存在的 v1.0 增加附件时复用该 tag，不执行删除或强制移动。
首次发布后续版本时，先审核并提交源码/依赖/文档，记录 commit，构建验收通过后再执行：

.. code-block:: bash

   # 示例：此前按 v1.0.1 / 1.0.1 构建，并保存了准确的 LWNS_COMMIT。
   git tag -a v1.0.1 "$LWNS_COMMIT" -m "lwns v1.0.1"
   git show --no-patch v1.0.1
   git push origin main
   git push origin refs/tags/v1.0.1

新版本构建前标签尚未创建时，用已提交的 ``git rev-parse HEAD`` 获取 LWNS_COMMIT，
替代第 1 步的 fetch/tag 解析，并把 LWNS_TAG/LWNS_VERSION 改为新版本。
发布分支和构建提交应一致；并不需要创建名为 release/1.0 的分支。
Git push 上传源码和版本引用，不上传程序压缩包。

7. 发布 GitHub Release 附件
------------------------------------------------------------

在实际保存归档的主机登录 GitHub。SSH 可以 git push 不代表 gh 已有 API 授权：

.. code-block:: bash

   gh auth login --hostname github.com --web
   gh api user --jq .login

无桌面的服务器在另一台电脑打开 ``https://github.com/login/device`` 输入一次性码，
完成网页授权，并等上传终端显示 Authentication complete。

将版本变化、目标平台、下载/安装命令、主机依赖和验证限制写入
``$LWNS_OUT/release-notes.md``，先核对远程 tag 再创建 Release：

.. code-block:: bash

   gh api "repos/nanfengnan1/lwns/git/ref/tags/$LWNS_TAG" --jq .object.sha
   gh release create "$LWNS_TAG" --repo nanfengnan1/lwns \
     --title "lwns $LWNS_TAG" --notes-file "$LWNS_OUT/release-notes.md" \
     "$LWNS_OUT/$LWNS_ASSET" "$LWNS_OUT/$LWNS_ASSET.sha256" \
     "$LWNS_OUT/lwns-$LWNS_VERSION-linux-x86_64.validation.json"

如果已有该 Release，只补传缺少的附件，例如：

.. code-block:: bash

   gh release upload "$LWNS_TAG" --repo nanfengnan1/lwns \
     "$LWNS_OUT/$LWNS_ASSET" "$LWNS_OUT/$LWNS_ASSET.sha256"

默认不使用 --clobber 覆盖已发布文件。上传中断后先查看已存在的附件；只有 tag 没有 Release
时不能直接 upload，先 create。旋转进度符号表示请求仍在处理，不要因此重复启动上传。
需要先审阅时可加 --draft，上传校验后再在 GitHub 页面发布。

8. 核对下载并更新文档入口
------------------------------------------------------------

.. code-block:: bash

   gh api "repos/nanfengnan1/lwns/releases/tags/$LWNS_TAG" \
     --jq '{url: .html_url, draft: .draft, assets: [.assets[] | {name, size, state, digest}]}'
   LWNS_DOWNLOAD="$(mktemp -d)"
   gh release download "$LWNS_TAG" --repo nanfengnan1/lwns \
     --pattern "$LWNS_ASSET*" --dir "$LWNS_DOWNLOAD"
   (
     cd "$LWNS_DOWNLOAD"
     sha256sum --check "$LWNS_ASSET.sha256"
   )
   cmp "$LWNS_OUT/$LWNS_ASSET.sha256" "$LWNS_DOWNLOAD/$LWNS_ASSET.sha256"

确认公开 Release、附件状态 uploaded、大小与 SHA256 一致，原 tag 未移动。
随后更新 README、:doc:`/user/deployment` 的获取入口、安装文件名和 agent.md 的交付状态。
本地 release/ 文件不会自动上传；只更新文档也不会替换已有程序包。

参考：`PyInstaller 的系统兼容性 <https://pyinstaller.org/en/stable/usage.html#making-gnu-linux-apps-forward-compatible>`_、
`冻结程序调用外部命令 <https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html#launching-external-programs-from-the-frozen-application>`_、
`GitHub Release <https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases>`_。
