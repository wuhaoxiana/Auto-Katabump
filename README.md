## 🚀 katabump 多账号自动续期（GitHub Actions）

这是一个基于 GitHub Actions 的自动化脚本，用于定时登录自动续期 [katabump](https://dashboard.katabump.com) 应用。
**当前版本为多账号模式**：一次运行依次处理所有账号，单个账号失败不影响其他账号。

⚠️ 有cf盾,太垃圾的机房节点可能过不了，建议用稍微干净点的节点,[B2proxy住宅代理](https://www.b2proxy.com/signup?code=0F5133)

━━━━━━━━━━━━━━━━━━━━━━

## 🔧 Variables 配置（Settings → Secrets and variables → Actions → **Variables**）

| Variable 名称       | 是否必填 | 说明                                              |
|---------------------|----------|---------------------------------------------------|
| KATABUMP_EMAIL     | ✅ 必填  | katabump 登录邮箱，**每行一个**                      |
| KATABUMP_PASSWORD  | ✅ 必填  | katabump 登录密码，**每行一个**，与邮箱按行一一对应      |
| NODE_LINK          | ❌ 可选  | 代理链接，如 vless:// vmess:// tuic:// hysteria2:// anytls:// socks5:// |

## 🔐 Secrets 配置（Settings → Secrets and variables → Actions → **Secrets**）

| Secret 名称         | 是否必填 | 说明                                              |
|---------------------|----------|---------------------------------------------------|
| TG_BOT_TOKEN       | ❌ 可选  | Telegram Bot Token（用于发送通知）                     |
| TG_CHAT_ID         | ❌ 可选  | Telegram Chat ID（接收通知的用户或群组 ID）              |

━━━━━━━━━━━━━━━━━━━━━━

## 👥 多账号填写示例

`KATABUMP_EMAIL`（Variable，多行）：

```text
account1@example.com
account2@example.com
account3@example.com
```

`KATABUMP_PASSWORD`（Variable，多行，与上面**按行对应**）：

```text
password1
password2
password3
```

> 两个变量的行数必须一致，否则脚本会直接报错退出，避免用错密码。
> 也支持用 `,` / `;` / `|` 分隔单行写法，例如 `a@x.com,b@y.com`。

━━━━━━━━━━━━━━━━━━━━━━

## 🔄 运行流程

1. 载入 Variables 中的多账号列表，校验邮箱与密码数量是否匹配
2. 启动一次浏览器（可选挂代理），复用同一浏览器实例依次处理账号
3. 每个账号：登录 → 过 Cloudflare Turnstile → 进入服务器详情 → 点击 Renew → 提交 → 读取结果
4. 处理完一个账号后自动 **logout + 清理 cookie/localStorage**，再进入下一个
5. 每个账号单独发一条 TG 通知，全部跑完再发一条**汇总通知**
6. 全部账号都失败时以非零退出码结束，方便 Actions 标红告警

━━━━━━━━━━━━━━━━━━━━━━

## 🌐 代理格式（确认在v2rayN里使用正常的节点）

`NODE_LINK` 支持以下任意一种代理协议的完整分享链接（不配置则直连）：

- **VLESS**：`vless://uuid@server:port?security=reality&sni=...&type=ws&...`
- **VMess**：`vmess://base64encoded...`
- **Trojan**：`trojan://password@server:port?sni=...&type=ws&...`
- **tuic**：`tuic://uuid:password@server:port...`
- **anytls**：`anytls://uuid@server:port...`
- **hysteria2**：`hysteria2://base64@server:port...`
- **SOCKS5**：`socks5://user:pass@server:port` 或 `socks://user:pass@server:port`

## 📌 注意事项

- 尽量添加一个干净的节点，以免过不了cf盾
- cron时间根据自己的服务到期时间的前一天来修改
- 账号数量较多时注意 job 总时长，必要时调大 `timeout-minutes`
- 失败截图会作为 artifact 上传（保留 7 天），文件名带脱敏邮箱便于区分账号
- ⚠️ Variables 是**明文可见**的（仓库协作者/Fork 可读）。把密码放 Variables 是按需求实现，
  如果仓库不是私有的，建议改回 Secrets 存密码
