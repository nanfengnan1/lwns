HTTPS、HTTP/2 与 HTTP/3 启动
========================================

本页提供 Caddy 安装、后端启动、站点配置、证书制作/信任和协议验证的完整流程。
首次使用先完成 :ref:`workbench-start` 的前端构建与 Python 依赖安装。
只需普通 HTTP 的用户按 :ref:`workbench-start-http` 启动，无需安装 Caddy 或证书。

HTTPS 的 HTTP/2 与 HTTP/3 共用同一套启动流程，协议在 Caddy 中选择、由浏览器协商。
默认同时支持 HTTP/1.1、HTTP/2 和 HTTP/3；需要关闭 HTTP/3 时见 :ref:`workbench-http-versions`。

.. contents:: 本页操作
   :local:
   :depth: 2

.. _workbench-start-https:

安装并启动 HTTPS 入口
----------------------------------------

项目提供 ``config/Caddyfile``，在 Linux Docker 宿主机运行 Caddy：

.. code-block:: text

   浏览器 -- HTTPS / HTTP/2、HTTP/3 --> Caddy :443
          -- WSS 设备终端 ----------> Caddy :443
                                       |
                                       +-- HTTP / WebSocket --> 127.0.0.1:8090
                                                               lab_server.py

Caddy 负责 TLS 与协议协商；前端资源、缓存、gzip、API 和认证继续由后端统一处理。
保留 HTTP/1.1 兼容路径。WebSocket 不会因为页面使用 HTTP/3 就自动变为 QUIC 终端。
HTTP/3 只影响浏览器到 Caddy 的通信，不改变容器间的 veth 数据面。

按 `Caddy 官方安装说明 <https://caddyserver.com/docs/install>`_ 安装含 HTTP/3 的标准 Caddy 2。
以下示例使用官方 Linux systemd 服务，假设服务账户为 ``caddy``。

Ubuntu/Debian 首次安装可执行（使用官方 stable 软件源）::

   sudo apt-get update
   sudo apt-get install -y debian-keyring debian-archive-keyring apt-transport-https curl gnupg
   curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key \
     | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
   curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt \
     | sudo tee /etc/apt/sources.list.d/caddy-stable.list
   sudo chmod o+r /usr/share/keyrings/caddy-stable-archive-keyring.gpg /etc/apt/sources.list.d/caddy-stable.list
   sudo apt-get update
   sudo apt-get install -y caddy

安装包会启动默认 Caddy 服务。下列步骤再将其配置为工作台入口。

在项目根目录构建前端，然后启动后端::

   npm --prefix web run build
   sudo .venv/bin/python script/python/lab_server.py \
     --host 127.0.0.1 --port 8090 --trusted-proxy 127.0.0.1

已有后端时先结束旧进程，再使用同一数据目录重启；不要同时启动第二个占用该目录的实例。
重启会断开当前网页终端连接，设备容器不会因此被清理。
该 Python 命令以前台方式运行，需要保持终端运行；接下来的 Caddy 配置在另一个终端执行。

``--trusted-proxy`` 可重复指定明确的 IP/CIDR，默认关闭，不能填写 ``*``。
这里仅信任同机 Caddy 的回环连接；保留原始 Host/Origin，用可信代理传来的协议做同源校验，
并识别真实客户端地址。后端仍使用启动时显示的令牌，不能配置多个 worker。

将 ``config/Caddyfile`` 的内容合入 ``/etc/caddy/Caddyfile``；已有站点时保留原站点配置。
将站点行 ``{$ROUTE_OVS_SITE:localhost}`` 改为实际 IP，例如 ``10.8.126.103``。
后端默认 ``127.0.0.1:8090``；使用其他端口时同步修改 ``ROUTE_OVS_UPSTREAM`` 占位符或默认值。
这两个变量也可通过 Caddy 服务的环境配置设置；普通终端的 export 不会自动传入 systemd 服务。

对于首次安装、尚无自定义站点的主机，可在项目根目录直接执行::

   sudo cp -an /etc/caddy/Caddyfile /etc/caddy/Caddyfile.before-route-ovs
   sudo cp config/Caddyfile /etc/caddy/Caddyfile
   sudo sed -i 's/localhost/10.8.126.103/' /etc/caddy/Caddyfile

保留 ``tls internal`` 即可自动制作内网证书。已有其他站点时改为合并站点配置，不要整文件覆盖。

校验并启动或重载服务::

   sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
   sudo systemctl enable --now caddy
   sudo systemctl reload caddy

允许客户端访问 TCP 443 和 UDP 443；HTTP 自动跳转通常还使用 TCP 80。
UDP 不通时浏览器可回退到 TCP 协议。Caddy 的 ``protocols h1 h2 h3`` 同时启用三种协议，
后端端口 8090 继续只监听回环。

使用 UFW 且已启用时，放行所需端口::

   sudo ufw status
   sudo ufw allow 80/tcp
   sudo ufw allow 443/tcp
   sudo ufw allow 443/udp

未启用 UFW 时无需为了此功能启用它；若使用其他防火墙或上游 ACL，则在对应位置放行。
用 ``sudo ss -lntup`` 确认 Caddy 同时监听 TCP/UDP 443。

默认配置没有整包上传缓冲和短请求体超时，大镜像流式转发，大小限制仍由后端
``--max-image-upload-gib`` 管理。配置重载对长连接有宽限期，但重启服务仍可能断开终端，
可通过“重连”恢复新会话。

.. _workbench-http-versions:

选择 HTTP/2 或 HTTP/3
----------------------------------------

项目 Caddyfile 默认在全局 ``servers`` 块中包含：

.. code-block:: text

   protocols h1 h2 h3

这会同时提供 HTTP/2 和 HTTP/3，并保留 HTTP/1.1 回退。浏览器访问地址统一为
``https://宿主机IP``，不需要为 HTTP/3 使用另一个 URL 或另一个 Python 后端。

若只需要 HTTP/2，修改同一行，保留 Caddyfile 其他配置和证书设置：

.. code-block:: text

   protocols h1 h2

这样关闭 HTTP/3、保留 HTTP/2 和 HTTP/1.1。两种配置修改后均执行::

   sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
   sudo systemctl reload caddy

.. list-table:: 协议与确认方式
   :header-rows: 1
   :widths: 20 25 25 30

   * - 模式
     - 浏览器地址
     - 客户端到入口的端口
     - Network 的 Protocol 列
   * - 后端直接 HTTP/1.1
     - ``http://宿主机IP:8090``
     - TCP 8090
     - ``http/1.1``
   * - Caddy HTTPS / HTTP/2
     - ``https://宿主机IP``
     - TCP 443
     - ``h2``；兼容客户端可能回退到 HTTP/1.1
   * - Caddy HTTPS / HTTP/3
     - ``https://宿主机IP``
     - UDP 443；保留 TCP 443 回退
     - ``h3`` 才表示实际使用 HTTP/3

第一次配置还需完成下面的客户端证书信任，再进行访问验证。
HTTP/2 模式使用普通浏览器窗口；不要使用后文强制 QUIC 的 HTTP/3 专用测试窗口。
HTTP/3 配置启用不保证所有浏览器立即使用 h3，UDP 可达性、自签发证书策略和客户端支持均需验证。

内网自动签发证书（默认方案）
----------------------------------------

配置中的 ``tls internal`` 使用 Caddy 自建 CA，自动签发并续期实际 IP/域名的服务器证书，
无需购买证书或使用公网域名。``skip_install_trust`` 禁止自动更改宿主机信任库，
访问客户端需要显式安装 CA 根证书。

官方 systemd 服务通常把根证书保存到：

.. code-block:: text

   /var/lib/caddy/.local/share/caddy/pki/authorities/local/root.crt

该路径取决于 Caddy 运行账户、HOME 和 XDG_DATA_HOME。应取正在运行的服务所使用的 CA，
不能用另一个账户运行 Caddy 后取出另一套 CA。复制根证书供客户端取回::

   sudo install -m 644 \
     /var/lib/caddy/.local/share/caddy/pki/authorities/local/root.crt \
     /tmp/route-ovs-root.crt

Windows 客户端在 PowerShell 中执行（替换 SSH 用户和地址）：

.. code-block:: powershell

   scp alexan@10.8.126.103:/tmp/route-ovs-root.crt .
   certutil -user -addstore Root .\route-ovs-root.crt

Debian/Ubuntu 客户端取得相同根证书后执行::

   sudo install -m 644 route-ovs-root.crt /usr/local/share/ca-certificates/route-ovs.crt
   sudo update-ca-certificates

重启浏览器后访问 ``https://10.8.126.103``，输入后端令牌。
Firefox 若使用独立证书库，还需在“证书颁发机构”中导入相同根证书并信任其网站证书。
每台访问电脑都需要信任同一个 CA；只分发根证书，不分发根私钥。
浏览器和本地 Wireshark 启动器都需要通过证书验证；仅点击浏览器“继续访问”不会替启动器建立信任。

手动制作证书（mkcert 替代方案）
----------------------------------------

如果希望自行维护证书文件，可以使用
`mkcert <https://github.com/FiloSottile/mkcert>`_。
在访问 Web 的 Windows 电脑安装 mkcert 后，在 PowerShell 中执行：

.. code-block:: powershell

   New-Item -ItemType Directory -Force .route-ovs-tls
   Set-Location .route-ovs-tls
   mkcert -install
   mkcert -cert-file route-ovs.pem -key-file route-ovs-key.pem 10.8.126.103
   Copy-Item (Join-Path (mkcert -CAROOT) 'rootCA.pem') .\route-ovs-root.crt
   scp .\route-ovs.pem .\route-ovs-key.pem alexan@10.8.126.103:/tmp/

证书必须包含实际访问的 IP 或域名；只有 Common Name 不够。
若添加域名，可把域名一起传给 mkcert，并配置 DNS/hosts，使其解析到服务器。
项目已忽略 ``.route-ovs-tls/``；生成的私钥不要提交到版本库。

在 Linux 服务器上安装服务器证书和私钥::

   sudo install -d -m 750 -o root -g caddy /etc/caddy/route-ovs-certs
   sudo install -m 644 -o root -g caddy /tmp/route-ovs.pem /etc/caddy/route-ovs-certs/server.pem
   sudo install -m 640 -o root -g caddy /tmp/route-ovs-key.pem /etc/caddy/route-ovs-certs/server-key.pem
   rm /tmp/route-ovs.pem /tmp/route-ovs-key.pem

将 Caddyfile 的 ``tls internal`` 替换为：

.. code-block:: text

   tls /etc/caddy/route-ovs-certs/server.pem /etc/caddy/route-ovs-certs/server-key.pem

校验并重载 Caddy。其他客户端安装上面导出的 ``route-ovs-root.crt``，方法与前节相同。
mkcert 生成的服务器证书由你手动续期：重新签发、替换文件、重载 Caddy；Caddy 不会自动续期手动加载的文件。
使用公网域名时也可删除 ``tls internal``，由 Caddy 自动申请公共 CA 证书；需要满足该 CA 的
域名验证条件，见 `Caddy 自动 HTTPS <https://caddyserver.com/docs/automatic-https>`_。

HTTP/2 与 HTTP/3 验证
----------------------------------------

打开浏览器开发者工具的 Network 面板，显示 Protocol 列。``h2`` 表示 HTTP/2，
``h3`` 表示 HTTP/3。HTTPS 能打开或响应出现 ``Alt-Svc`` 只表示可访问/已宣告，不能证明实际使用了 HTTP/3。
浏览器可能在首次连接后才通过 Alt-Svc 发现 HTTP/3，需再次请求观察。

Chrome/Chromium 对 QUIC 自定义 CA 有额外限制：导入本地 CA、普通 HTTPS 不再报错，
不保证 HTTP/3 同样可用。见
`Chromium QUIC 测试说明 <https://new.chromium.org/quic/playing-with-quic/>`_。
日常使用可以保留 HTTP/2 回退；对自签发证书测试 HTTP/3 时，可以用独立浏览器配置目录，
仅对当前服务器证书设置 SPKI 例外。

使用默认 ``tls internal`` 时，可直接读取 Caddy 当前提供的服务器证书并计算 SPKI。
在 Linux 宿主机执行；这里的 IP 必须与站点配置一致::

   openssl s_client -connect 127.0.0.1:443 -servername 10.8.126.103 </dev/null 2>/dev/null \
     | openssl x509 -pubkey -noout \
     | openssl pkey -pubin -outform DER \
     | openssl dgst -sha256 -binary | openssl base64 -A

例如使用 mkcert 方案时，在 Linux 上计算服务器证书的 SPKI（不要在旧 PowerShell 中执行二进制管道）::

   openssl x509 -in /etc/caddy/route-ovs-certs/server.pem -pubkey -noout \
     | openssl pkey -pubin -outform DER \
     | openssl dgst -sha256 -binary | openssl base64 -A

将输出填入 Windows 测试命令：

.. code-block:: powershell

   & 'C:\Program Files\Google\Chrome\Application\chrome.exe' `
     --user-data-dir="$env:TEMP\route-ovs-h3-test" `
     --no-proxy-server `
     --enable-quic `
     --ignore-certificate-errors-spki-list='替换为上述SPKI值' `
     --origin-to-force-quic-on=10.8.126.103:443 `
     https://10.8.126.103

这个独立配置用于协议验收；修改启动参数前先关闭该测试窗口。
服务器更换密钥后 SPKI 需重新计算，Caddy 自动续期也可能更换密钥。
日常使用保留 HTTP/2 回退；若希望浏览器默认自动使用 HTTP/3，可采用满足浏览器信任策略的公共 CA 证书。
支持 HTTP/3 的 curl 也可使用 ``--http3-only --cacert route-ovs-root.crt`` 验证；
先用 ``curl --version`` 确认包含 HTTP3。普通发行版 curl 可能只有 HTTP2。

HTTP/2 可用以下命令验证（在根证书文件所在客户端执行）::

   curl --http2 --cacert route-ovs-root.crt -I https://10.8.126.103/

静态压缩验证需请求实际 JS 文件，并查看 ``Content-Encoding: gzip``、``Cache-Control`` 和 ``Vary``::

   curl --cacert route-ovs-root.crt -H 'Accept-Encoding: gzip' -D - -o /dev/null \
     https://10.8.126.103/assets/实际构建的文件名.js

确认管理 API 正常、终端能连接和调整尺寸、上传完成后能提交镜像任务。
``/api/capture/stream`` 在 Caddy 入口明确返回 403，PCAP 数据继续通过 SSH 访问宿主机回环后端；
claim/client-report 则通过 HTTPS 验证证书后访问。前端页面协议不会改变抓包数据通道。

前端按需加载与缓存
----------------------------------------

工作台首页只加载画布和基础操作。首次打开设备终端时加载 xterm，首次打开镜像管理、
抓包管理时分别加载对应组件。终端切换标签、隐藏或收起后保持会话；管理面板关闭后
保留表单及后台任务轮询，再次打开不重新创建面板。

``npm --prefix web run build`` 会生成多个 JS/CSS 文件。Vite 的 500 kB 提醒针对单个
压缩前的 JS 文件，不是构建失败；当前通过按需加载拆分，不提高警告阈值。
日志中的 gzip 数字只是体积报告；实际传输是否压缩应查看响应头。

后端直接提供 ``web/dist`` 时已经支持：

* 静态响应按客户端能力使用 gzip（至少 1 KiB）；API、WebSocket、PCAP 不经过此压缩层。
* 带内容哈希的 ``/assets/`` 文件缓存一年，标记 ``immutable``。
* 首页及其他未带哈希资源使用 ``no-cache``，通过 ETag/Last-Modified 重新验证。
* API、缺失文件和错误响应仍为 ``no-store``；静态文件支持 HEAD 和 Range。

这些优化通过普通 HTTP 即可生效。前端修改后重新构建，后端修改后重启；无需重新构建设备镜像。
发布时应将整套 ``web/dist`` 一起部署。对于持续运行的页面，建议保留上一版本的哈希资源
一段时间，避免旧页面首次打开功能时找不到旧分包。若模块加载失败，页面提示检查网络、
导出未保存拓扑后刷新，不会自动刷新并丢弃草稿。

排查顺序
----------------------------------------

* 页面提示“不接受跨站请求”或终端立即断开：检查后端的 ``--trusted-proxy``、Caddy 的上游地址，
  保留原始 Host/Origin，不要关闭同源校验。
* HTTPS 证书错误：核对访问地址是否在证书中、客户端是否信任正在使用的 CA，以及系统时间。
* 只有 h2：检查 UDP 443、浏览器 QUIC 策略、自定义 CA 限制；这不代表 HTTPS 或应用失败。
* 502：检查后端是否运行、Caddy 上游端口和日志。
* 更新后功能模块加载失败：确认发布完整 dist；保留旧哈希文件或导出草稿后刷新。
* Wireshark 启动器兑换失败：检查客户端系统/Python 的 CA 信任库与配置的 HTTPS 地址，
  不要把浏览器可绕过证书警告当作原生程序也已信任。
