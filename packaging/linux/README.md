# lwns Linux 目录安装包

本包包含已编译的 Web 前端、可执行后端及其 Python 运行库。运行工作台不需要安装 Node.js、npm 或 Python 虚拟环境。设备运行仍需要宿主机 Docker Engine/CLI、iproute2 和 util-linux。

版本、原始源码提交、架构、glibc 基线及依赖版本见 `build-info.json`。本次正式发行目标是 **Linux x86_64 / glibc 2.35 或兼容的更新系统**；实际验证范围见 `VERIFICATION.md`。ARM64、Alpine/musl 需要单独构建和验证。程序目前面向单用户、单台 Docker 宿主机。

## 1. 获取与校验

在 Linux 主机从 <https://github.com/nanfengnan1/lwns/releases> 下载程序包及同名 `.sha256` 文件。GitHub 的 Source code 归档不是程序包。以 v1.0 为例：

```bash
sha256sum -c lwns-1.0-linux-x86_64.tar.xz.sha256
tar -xJf lwns-1.0-linux-x86_64.tar.xz
cd lwns-1.0-linux-x86_64
sha256sum --check --quiet SHA256SUMS
```

包内 `docs/html/index.html` 是完整离线手册。`INSTALL.rst` 保留对应源码版本的安装说明；压缩格式、实际附件名称及本次验证以本 README、build-info.json 和 VERIFICATION.md 为准。

## 2. 检查宿主机依赖

```bash
docker version
ip -Version
nsenter --version
```

Docker daemon 应已启动；真正部署设备需要后端以 root 运行。安装器不安装或替换 Docker。
SSH/Wireshark 抓包还需宿主机 tcpdump、sshd 和 python3，客户端另需 Wireshark 与抓包启动器。
设备镜像和设备包独立管理，不随工作台程序包分发。

## 3. 安装和启动

普通实验网 HTTP 入口：

```bash
sudo bash install.sh --listen 0.0.0.0 --port 8090
sudo systemctl start lwns-web
systemctl status lwns-web --no-pager
```

浏览器打开 `http://宿主机IP:8090`，在 Linux 主机读取本机专属令牌并填写登录框：

```bash
sudo grep '^LWNS_TOKEN=' /etc/lwns/lwns.env
```

首次安装随机生成令牌，升级保留原值。不要向其他人发送配置文件或含令牌的服务日志。
安装器默认启用开机启动，但安装后需显式 `systemctl start`；不加 `--listen` 时仅监听 127.0.0.1。

需要 HTTPS 时，安装为回环后端，再按 `docs/html/user/workbench-https.html` 配置 Caddy：

```bash
sudo bash install.sh --listen 127.0.0.1 --trusted-proxy 127.0.0.1
sudo systemctl start lwns-web
```

以上两种首次安装方式择一。包内 `Caddyfile.example` 支持可选 HTTP/2、HTTP/3 入口；Caddy 二进制、站点地址和证书由部署方配置。安装器不覆盖已有 Caddy 服务。

## 4. 文件位置与日常维护

| 路径 | 内容 |
| --- | --- |
| `/opt/lwns/releases/<BUILD_ID>` | 每次构建的独立程序目录 |
| `/opt/lwns/current` | 当前程序链接 |
| `/usr/local/bin/lwns` | 启动命令 |
| `/etc/lwns/lwns.env` | 监听地址、数据目录及令牌；权限 600 |
| `/var/lib/lwns` | 默认项目、设备配置和镜像管理数据 |
| `/etc/systemd/system/lwns-web.service` | 服务定义 |

```bash
sudo systemctl stop lwns-web
sudo systemctl start lwns-web
journalctl -u lwns-web -n 50 --no-pager
```

同一数据目录只运行一个后端。已有源码服务或其他安装器管理的同名服务需先安排迁移；本安装器会拒绝直接覆盖它们。详细迁移步骤见离线安装手册。

## 5. 升级、回退和卸载

升级前保存实验和设备配置，结束后台任务，并停止旧后端；对配置和实际数据目录做一致备份。运行中的设备可能继续写共享配置，备份前应按实验需要停止设备写入。

```bash
sudo systemctl stop lwns-web
# 进入新版本解压目录
sudo bash install.sh
sudo systemctl start lwns-web
```

安装器保留配置、令牌、数据和旧程序目录。`--listen` 等参数仅用于首次安装，已有配置请编辑 `/etc/lwns/lwns.env`。
需要回退时先停止服务，再将 `/opt/lwns/current` 指回已保留的 `releases/<旧BUILD_ID>`。
程序回退不会撤销数据变化，格式不兼容时还需恢复匹配的数据备份。

卸载程序与服务：

```bash
sudo bash /opt/lwns/current/uninstall.sh
```

卸载保留配置、实验数据、Docker 镜像和设备容器。设备清理应通过工作台单独执行。

## 非 systemd 与解压试用

```bash
sudo bash install.sh --no-systemd --listen 0.0.0.0
sudo /usr/local/bin/lwns
```

由自己的进程管理器托管；不要与 systemd 方式同时运行。仅检查界面、暂不部署设备：

```bash
./app/lwns --preview --host 127.0.0.1 --port 18090 --data-dir "$HOME/lwns-preview"
```

直接运行二进制不读取系统环境文件；未指定 LWNS_TOKEN 时使用本次进程生成的令牌。

## 来源与重建

`sources/` 保存原始标签源码，`build-tools/` 保存实际使用的打包脚本及说明，`build-requirements.txt` 记录完整构建环境依赖。打包工具可以独立于应用标签更新，应用源码提交在 build-info.json 中单独记录。
`THIRD_PARTY/` 保留构建环境可找到的第三方许可/版权文本。原标签若没有独立的项目 LICENSE，本包不替项目另行指定许可证。

维护者的构建、验证、tag 和 GitHub Release 发布流程见 `docs/html/developer/release.html`。升级版本前核对该版本的源码和数据兼容性；本次 v1.0 安装包不会自动包含 main 分支后来增加的设备包格式或 SDN 示例。
