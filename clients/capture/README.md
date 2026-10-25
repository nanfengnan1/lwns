# lwns 本地 Wireshark 启动器

属于 lwns（Linux Web Network Simulator）。从旧版升级时重新运行本页安装脚本，
注册 `lwns://` 协议；新启动器在没有新配置时继续使用旧 `route-ovs` 目录中的连接配置，
保留用户已选择的保存位置，也兼容解析旧协议链接。

在使用浏览器的 Windows/Linux 电脑安装一次。Docker 宿主机后端需以 root 运行并安装 tcpdump；SSH 用户只需能登录宿主机并运行 python3，不需要 sudo 或 Docker 权限。

## Windows

安装完整 Wireshark（包括 SSH remote capture/sshdump），解压客户端包，在该目录运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
```

包含 `lwns-capture.exe` 的包无需 Python。源码包需要 Python 3.10+，也可通过 `-Python C:\实际路径\python.exe` 指定。安装仅注册当前用户协议；不会修改系统执行策略。已有其他协议处理程序时拒绝覆盖。

在 Web 点击“准备抓包”，再点击“打开本机 Wireshark”，确认浏览器打开外部应用。首次使用在本地弹窗填写 Wireshark 路径、SSH 主机、端口、用户名和本机保存目录，Profile 可选。
例如 Wireshark 路径可填 `D:\software\Wireshark\Wireshark.exe`，Profile 可填 `SSH-10.8.126.103-eno4`。

## Linux 桌面

安装 Wireshark、tshark、sshdump、Python 3.10+、python3-tk 和 xdg-utils（软件包拆分随发行版而异），在解压目录运行：

```bash
bash install.sh
```

安装用户级 `.desktop` 处理程序，不需要 root。无 Tk 时可先在终端配置：

```bash
python3 ~/.local/share/lwns-capture/launcher.py --configure http://宿主机IP:8090 --terminal
```

## SSH 用户名、密码与密钥

本地配置只保存用户名、主机、Wireshark 路径/Profile、可选私钥路径、本机保存目录及自动开始选项，不保存密码或密钥口令。配置文件位于 Windows `%LOCALAPPDATA%\lwns\capture-client.json` 或 Linux `$XDG_CONFIG_HOME/lwns/capture-client.json`（默认 `~/.config/lwns/`）。每个后端地址分别配置，开发代理地址也视为独立后端。

- 已经能连接的 Profile：选择该 Profile，勾选“已有可用 Profile / 密钥认证，打开 Wireshark 后自动开始”，之后按 Web 的两步按钮操作即可开始。
- 密钥/ssh-agent：可指定私钥文件，或留空沿用 Profile/agent。可用的密钥类型及 agent 支持由本机 sshdump 版本决定。
- 密码认证无需私钥：先不勾选自动开始，启动 Wireshark 后在首页找到 SSH remote capture，点击旁边的齿轮，在 Authentication 中填写远程用户名和密码，再点击 Start。连接凭证有 5 分钟有效期，超时返回 Web 重新开始。
- 若在 Wireshark 中选择保存密码，其明文存储行为由 Wireshark 管理；本启动器不会替你开启密码保存。密码不会进入拓扑、Web API 或抓包链接。

Web 的“本机连接与保存设置”链接可直接重新打开本地设置，无需创建会话；升级旧版后须重新运行安装脚本。

设置也可通过 `launcher.py --configure http://宿主机IP:8090` 重新打开；Windows 独立版使用 `lwns-capture.exe --configure http://宿主机IP:8090`。

启动器按实际安装检测 `sshdump`/`sshdump.exe` 及偏好名称。保留所选 Profile，通过单进程 `-o` 参数将远端命令设为会话数据转发，不永久修改 Profile。Wireshark 保存配置的行为仍由用户操作决定。

## 使用与排错

选择已部署的 veth 连线 → 抓包 → 选端点/BPF → 准备抓包 → 打开本机 Wireshark。Web 区分等待打开程序、启动器已连接、等待在 Wireshark 中认证、等待 SSH 和实际抓包中；关闭 Web 对话框不会停止已连接会话。停止、SSH 断开、清理实验和后端退出会回收抓包进程；单会话最多 60 分钟。

需要从本机同时访问 Web 后端和 SSH 宿主机；远端 Python 通过宿主机回环地址连接后端。使用容器化后端、反向代理或开发代理时，后端自身监听端口必须仍能在 SSH 所在宿主机的 `127.0.0.1` 访问。HTTPS 需有效证书，不跳过证书校验。

“等待在 Wireshark 中认证”表示本地设置没有勾选自动开始，需在 SSH 接口配置中输入密码并启动。“等待 SSH”长时间不变时检查 Wireshark 的 SSH 错误、认证配置和主机指纹。没有本地启动器时浏览器无法直接执行 Wireshark，可从 Web 下载并完成安装。

启动器仅允许选择图形程序 Wireshark，不能选择 tshark。它检查 Profile 是否存在、检测程序提前退出，并在 Windows 尝试还原和前置新窗口。简要诊断位于本地连接配置同目录的 `capture-launcher.log`，不记录启动 URL，诊断中的会话凭证会隐藏。启动失败会显示本地错误，兑换会话后的失败还会回传 Web。

## 报文文件保存位置

默认目录为 Windows `%USERPROFILE%\lwns\captures` / Linux `~/lwns/captures`，每次创建独立子目录及 `capture.pcapng`，不会覆盖之前的文件。可通过“本机连接与保存设置”修改目录。

启动器回传完整目标路径，Web 提供复制按钮；只有成功开始后才会写入文件，在 Wireshark 修改路径或另存后以 Wireshark 为准。停止抓包后再复制文件，以取得完整内容。宿主机后端不保存抓包副本。旧版没有自动保存路径，需要在 Wireshark 另存；更新后端和本地启动器后，重新开始新会话即可使用路径回报。

## 构建独立启动器

Windows 独立版构建（开发者，在 Windows Python 环境执行）：

```powershell
python -m pip install pyinstaller
python -m PyInstaller --noconfirm --clean --onefile --windowed --name lwns-capture --add-data "remote_relay.py;." --add-data "configure.ps1;." launcher.py
```

在此目录生成的 `dist/lwns-capture.exe` 可随客户端包分发；后端下载包在该产物存在时自动包含它。安装产物与构建缓存不提交到 Git。
