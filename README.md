# CodeBridge Host · 码桥 Mac 连接组件

这是码桥的独立 Mac 连接组件源码，用于审查和自行构建。组件提供本机配置网页、Android 配对与加密中继连接，接入正在运行的真实 Codex 桌面实例；不依赖 Codex 官方扫码连接。

当前提供 arm64 候选组件；中继部署在 https://aly-codex-mobile.pages.dev 。单元与模拟器检查不能替代第二台独立 Codex Mac、真实摄像头扫码和全部桌面业务验收。尚无 Developer ID 签名与公证。公开源码不等于完成独立安全审计。本项目组件源码采用 MIT 许可证，第三方依赖保持各自许可。

## 组件做什么

- 只读探测当前用户官方控制 socket 与既有码桥 socket；多个实例无法确认归属时拒绝选择，不通过另开桌面会话制造成功。
- 配置网页仅绑定随机端口的 `127.0.0.1`。短时一次性引导能力换取 HttpOnly/SameSite 会话，配置动作校验 Host、Origin 和 CSRF。
- 二维码两分钟有效且只能认领一次。Mac 确认手机静态公钥后批准，手机显式确认才切换原有连接。网络中断恢复原配对请求，不重复授权。
- 标准 Noise XX/IK（25519、ChaChaPoly、SHA256）提供端到端加密；中继仍能看到连接元数据、流量大小与时序。本文不宣称匿名或隐藏元数据。
- Mac 主动连接中继，无需开放路由器端口。`relay/v2` 源码同样提供，方便审查凭证隔离、撤销与密文转发。

## 数据与权限

身份私钥、设备凭证及待配对恢复状态保存在独立 macOS Keychain 项目 `dev.codebridge.host-v2`，通过原生 Security API 访问；系统拒绝授权时不能连接。运行目录是当前用户的 `~/Library/Application Support/CodexMobile/host-v2`，不携带作者电脑凭证。

组件会接入用户已有 Codex 服务，并按所选功能读取或操作项目、会话和附件。已配对手机可以向 Codex 发起任务；任务可能调用文件与命令工具，仍遵循真实桌面的审批配置。不要把手机授权理解成只能查看聊天。文件访问还受当前用户及 macOS 权限约束，组件不会自动授予完全磁盘访问权限。

启动项仅在用户启用后添加组件自己的 LaunchAgent。停用会移除该启动项并停止组件，保留聊天与身份记录；它不代表撤销已保存的所有设备。需要先在网页撤销设备，再按自己的数据清理需求处理 Keychain 与运行目录。组件不接管 Codex 的登录启动设置。

## 构建与运行

开发者需要 macOS、Python 3.14 和下列固定依赖；最终用户运行构建好的组件无需安装系统 Python。

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r mac/requirements-host.txt
.venv/bin/python mac/package_host.py
```

输出：`qa/host-build/dist/CodeBridge Host.app`。默认包含上述生产中继地址。开发构建使用 ad-hoc 签名，不是可直接商业分发的签名公证包。启动组件默认打开配置网页；未配置真实公网服务时配对按钮禁用。

自建服务后，构建时传入自己的真实 HTTPS origin：

```sh
.venv/bin/python mac/package_host.py --relay-origin https://YOUR-RELAY-HOST
```

此参数是公开服务地址，不是私密令牌。`relay/v2/wrangler.toml` 是本地模板，部署者需选择自己的 Worker 名称、账号与访问域名，勿把本地测试通过当作公网部署通过。

```sh
wrangler dev --local --config relay/v2/wrangler.toml --port 8789
```

当前发现机制不保证所有 Codex 版本均有可共享的桌面入口；无法发现或实例归属不明确时会显示错误，不启动替代服务。Mac 必须保持登录、联网并处于运行状态，组件不能从关机或睡眠状态自行运行。

## 独立 Codex App 安装与配对

1. 解压后将 CodeBridge Host.app 放入本机或当前用户的 Applications 文件夹；安装官方独立 Codex.app。
2. 打开码桥组件，在本机配置页启用桌面共享入口，再点击“打开 Codex”。码桥校验官方应用签名，只对这次指定进程设置启动入口，不修改系统全局环境或官方应用文件。
3. 如果 Codex 已经打开，现有任务继续运行；共享入口需等用户下次正常启动 Codex。码桥不会自动退出它。
4. 配置页确认真实桌面与中继连接后点击“连接手机”。手机扫码，核对两端指纹，在 Mac 批准并在手机确认。
5. 手机可保存多个主机，每次只连接一个，切换后项目、会话和草稿按主机隔离。

开发包只有 ad-hoc 签名。系统首次阻止打开时，按 macOS 正常“隐私与安全性 → 仍要打开”流程处理；不关闭 Gatekeeper、不移除隔离标记。无法确认真实桌面连接时不生成可用配对成功状态。当前无 Intel 构建，也未验证所有独立 Codex 版本。

## 检查

这些检查使用临时 socket 和存储替身，不读取用户 Keychain，不向真实桌面提交任务：

```sh
PYTHONPATH=mac .venv/bin/python -m unittest test_device_store test_desktop_discovery test_host_paths test_host_state test_local_console test_pairing test_secure_channel test_secure_messages test_bridge_cleanup test_peer_lifecycle
node --test relay/v2/test_pairing.mjs relay/v2/test_isolation.mjs
```

运行行为及限制以源码为准。未来发行包应绑定明确的 Git commit/tag，并提供 SHA-256、签名与构建环境，允许用户选择自行构建。当前不承诺跨机器生成字节完全一致的 PyInstaller 二进制。

## 源码范围与许可

`mac/` 包含实际运行入口、实例发现、网页、授权、Keychain、加密、中继客户端及共享项目/附件处理；`relay/v2/` 包含独立中继与隔离检查。商业手机客户端不在此组件仓库范围。

第三方依赖保持原有许可；`LICENSES/` 包含固定依赖随发行元数据提供的许可证。项目自身采用根目录 `LICENSE` 中的 MIT 许可证。公开源码仓库：https://github.com/Aaminly/codebridge-host 。目前仅发布源码，没有发布已签名的安装包。
