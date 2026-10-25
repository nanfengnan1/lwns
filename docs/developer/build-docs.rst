文档构建与版本发布
========================================

实现约定
----------------------------------------

本工程沿用参考 docs 的 Sphinx、Read the Docs 主题、中文、双 PDF 和不可覆盖版本归档方式。
配置与脚本已改为 lwns 命名；文档版本保存在本目录的 ``docs/.version``，
初始值为 ``v0.1``，表示文档框架版本，不代表 FRR 或 OVS 软件版本。

HTML 使用统一首页；用户和开发章节分别生成一本 PDF。
Sphinx 配置可参考 `官方配置文档 <https://www.sphinx-doc.org/en/master/usage/configuration.html>`_；
侧栏选项可参考 `主题文档 <https://sphinx-rtd-theme.readthedocs.io/en/stable/configuring.html>`_。

内容组织与排版约定
----------------------------------------

文档布局参考 `containerlab 快速开始 <https://containerlab.dev/quickstart/>`_ 的任务顺序与页内目录、
`GNS3 第一次拓扑 <https://docs.gns3.com/docs/getting-started/your-first-gns3-topology>`_ 的操作引导、
`Caddy 入门教程 <https://caddyserver.com/docs/getting-started>`_ 的目标与前提说明。
内容和命令以本项目实现为准，不照搬其他项目的功能或安装方式。

新增或修改用户教程时，遵循以下顺序：

1. **目标与前提**：用一段话说明这篇能完成什么，再标明操作位置、必需条件和完成结果。
2. **操作步骤**：一个标题对应一个任务。需要按顺序执行的步骤编号；互斥的部署方式明确写成选择。
3. **命令与结果**：命令块不带 Shell 提示符；有多个终端时用 ``:caption:`` 标明运行位置。
   管理命令若只能按需选一条，放在操作对照表，不拼成可整体复制的命令块。
4. **异常与下一步**：先写成功标志，再链接故障处理和后续操作，避免让入门教程变成参数手册。

布局使用原生 reStructuredText，不增加主题或扩展依赖：

* ``.. container:: doc-lead``：页面导语；``doc-meta``：操作位置与前提。
* ``doc-cards`` 内放多个 ``doc-card``：首页任务入口，内部使用 ``:doc:`` 或 ``:ref:`` 链接。
* ``doc-path``：简短操作路线；``doc-next``：页尾下一步。
* 提示使用 ``note`` / ``tip``，可能导致已有数据变化的必要提醒才使用 ``warning``。
* 长页保留 ``.. contents::``，设置 ``:local:`` 和合适的 ``:depth:``，供窄屏和 PDF 阅读。

``_templates/page.html`` 为宽屏增加右侧目录；``_static/reading.css`` 管理内容宽度、字号、
任务卡片、表格和窄屏布局；``_static/reading.js`` 增加复制按钮和当前位置提示。
左侧目录只列章节，详细步骤在页内目录展示，避免两个导航重复展开。
脚本不可用时正文和链接仍可阅读；复制失败时提供选中代码的手动操作。
资源随 HTML 一起交付，不依赖 CDN，保持 ``file://``、静态托管、历史归档可用。
原生容器内容也进入 LaTeX/PDF，右侧导航和复制按钮仅用于 HTML。

排版改动后除 ``make check html`` 外，应检查宽屏、窄屏、长命令横向滚动、
复制内容是否完整，以及旧锚点和版本切换入口。不要直接修改生成的 ``html/`` 文件。

构建环境
----------------------------------------

需要 GNU Make 和 Python 3.10 或更高版本。建议从项目根目录进入文档目录创建独立环境::

  cd docs
  python3 -m venv .venv
  . .venv/bin/activate
  python -m pip install -r requirements.txt

固定的依赖版本为 Sphinx 8.1.3、sphinx-rtd-theme 3.1.0。
如已具有兼容环境，也可直接使用系统中的 Sphinx。

PDF 另需 XeLaTeX、latexmk 和中文字体。Debian/Ubuntu 的安装示例::

  sudo apt-get install latexmk texlive-xetex texlive-lang-chinese \
    texlive-latex-extra texlive-fonts-recommended fonts-freefont-otf

构建命令
----------------------------------------

在 ``docs/`` 目录执行::

  make help
  make check
  make html
  make latex
  make pdf
  make all
  make versions
  make serve

``make check`` 检查文档与交叉引用；默认构建把 Sphinx 警告作为失败处理。
``make html`` 使用 ``-a`` 重写全部 HTML 并同步静态资源；即使只修改 CSS、脚本或模板，
也会更新页面中的资源版本，避免继续使用旧排版。文档源码的解析仍可复用 Sphinx 缓存。
``make latex`` 只生成两本书的 LaTeX 源码，不需要安装 TeX，也不等于 PDF 编译成功。
``make pdf`` 在缺少 latexmk 或 XeLaTeX 时会明确报错。

产物位置：

* HTML：``html/index.html``。
* 用户 PDF：``pdf/user/lwns-user.pdf``。
* 开发 PDF：``pdf/developer/lwns-dev.pdf``。
* LaTeX 中间文件：``_build/latex/``。

``make serve`` 在本机 ``127.0.0.1:8000`` 提供静态预览，入口为 ``/html/index.html``。
``make clean`` 删除当前 HTML、PDF 和中间产物，保留 ``versions/``。
也可指定 ``SPHINXBUILD``、``PYTHON`` 和 ``SPHINXOPTS`` 使用其他构建环境。

按版本归档
----------------------------------------

将 ``docs/.version`` 改为本次文档发布标识，再执行::

  make archive
  make versions

归档需要 HTML 和两本 PDF 都构建成功。脚本核对版本与源码摘要，
拒绝归档缺失的产物、旧源码对应的产物或已有版本，不会覆盖历史记录。
生成的目录如下::

  versions/
  ├── index.html
  ├── catalog.js
  └── v0.1/
      ├── html/
      ├── pdf/user/lwns-user.pdf
      ├── pdf/developer/lwns-dev.pdf
      ├── source/
      ├── .version
      └── manifest.json

``source/`` 保存可重新构建的文档源码，包括本目录自己的 ``.version``。
``manifest.json`` 记录构建时间、源码摘要和归档文件 SHA-256。
同一功能版本下的文档修订应使用新标识，例如 ``v0.1-doc2``。

部署整个 ``docs/`` 对应的构建目录时，可同时访问当前版本与历史 HTML/PDF。
历史页面通过共享的 ``versions/catalog.js`` 更新版本列表，选择器兼容本地文件打开。
