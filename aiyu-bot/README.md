<div align="center">

# 🐋 aiyu · QQ 群 AI 聊天机器人（邪恶鲸鱼娘）

**登录你自己的 QQ 小号，在群里被 `@邪恶鲸鱼娘` 时，由 DeepSeek 以角色人设自动回复。**

基于 OneBot v11 协议与 DeepSeek 大模型，从协议对接、消息解析到一键部署的全栈实现。

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows-orange)](https://www.microsoft.com/windows)
[![Protocol](https://img.shields.io/badge/Protocol-OneBot%20v11-purple)](https://github.com/botuniverse/onebot-11)

</div>

---

## 📖 项目简介

`aiyu` 是一个**可登录个人 QQ 账号**的群聊 AI 机器人。别人的群里发 `@邪恶鲸鱼娘 + 内容`，机器人会提取 **@ 后面的文字**，交给 DeepSeek 生成「邪恶鲸鱼娘」人设的回复，再发回群里。

它解决了这类项目的核心痛点：**腾讯官方不开放个人 QQ 账号的群消息 API**。本项目通过 **OneBot v11 正向 WebSocket** 对接能登录 QQ 的协议实现（NapCat），把「登录 QQ + 收发消息」和「AI 回复业务」彻底解耦。

> ⚠️ **风险提示**：本项目依赖 NapCat 等第三方协议实现登录 QQ，**违反腾讯用户协议**，存在账号被风控/封禁的风险。**强烈建议使用小号运行**，切勿使用主号。本项目仅供学习交流。

---

## ✨ 功能特性

- 🎯 **@ 触发**：只响应群里 `@机器人` 的消息，精准提取 @ 之后的文本作为对话输入
- 🔀 **双格式解析**：兼容 OneBot v11 的 CQ 码字符串与消息段数组两种消息格式，边界情况稳健（@全体成员不触发、@他人不触发、@后无文本兜底）
- 💬 **私聊支持**：可直接私聊机器人对话（可开关）
- 🧠 **独立会话记忆**：按「群 + 人」维度各自维护最近 N 轮对话上下文，互不干扰
- 🧹 **清空记忆**：对机器人说「清空记忆 / 重置对话 / 失忆」即可重置当前会话
- ✂️ **长回复拆分**：超过 QQ 单条上限自动拆成多条发送
- 🔁 **断线自动重连**：WebSocket 掉线指数退避重连，无需人工干预
- 🎭 **可编程人设**：通过 `system_prompt` 自由定义角色性格与说话风格
- 🚀 **一键启动/停止**：Windows 下双击即可拉起 NapCat + 机器人，也能一键精准停止

---

## 🏗️ 工作原理

```mermaid
flowchart LR
    A[你的 QQ 小号] <--> B[NapCat Shell 协议实现\n负责登录QQ / 收发消息]
    B <-->|OneBot v11 正向 WebSocket| C[bot.py\nPython + asyncio + aiohttp]
    C <-->|HTTPS  OpenAI 兼容接口| D[DeepSeek API\ndeepseek-chat]
    B -.监听 ws://127.0.0.1:3001 .-> C
```

- **NapCat**：连接层，登录 QQ 并把群消息转成标准 OneBot v11 事件推送出来，同时执行发消息等动作调用。
- **bot.py**：业务层，以客户端连上 NapCat 的 WebSocket，接收消息 → 解析 @ → 调用 DeepSeek → 发回回复。
- **DeepSeek API**：推理层，用 OpenAI 兼容接口生成人设回复。

---

## 📁 目录结构

```
aiyu-bot/
├── bot.py                 # 机器人主程序（连接 OneBot、解析@、调 DeepSeek、发消息）
├── config.example.json    # 配置模板（复制为 config.json 后填写，勿提交真实配置）
├── requirements.txt       # 依赖（仅 aiohttp）
├── speedtest.py           # DeepSeek 接口测速脚本（排查回复慢用）
├── 启动ai鱼.bat / .ps1      # 一键启动（NapCat + 机器人）
├── 停止ai鱼.bat / .ps1      # 一键停止（按端口精准杀进程）
├── 一键安装.bat / .ps1      # 环境检查 + 自动装依赖
├── README.md
├── .gitignore             # 已排除含密钥的 config.json
└── LICENSE                # MIT
```

---

## 🚀 快速开始

### 环境要求

| 依赖 | 版本 | 说明 |
| --- | --- | --- |
| Python | 3.10+ | 运行 bot.py（用 aiohttp） |
| Node.js | LTS | NapCat Shell 需要 |
| QQ NT | 最新版 | 新版 QQ 客户端，需先登录过一次 |

### Step 1：安装协议实现（NapCat）

NapCat 负责登录 QQ 并把消息转成 OneBot 协议（本项目**不内置** NapCat，请单独下载）：

1. 到 [NapCatQQ Releases](https://github.com/NapNeko/NapCatQQ/releases) 下载 **`NapCat.Shell.zip`**（或自带 Node 的 **`NapCat.Shell.Windows.Node.zip`**）；
2. 解压到本项目目录下的 **`napcat\`** 文件夹（需包含 `launcher-user.bat`）；
3. 运行 `napcat\launcher-user.bat`，在弹出的 QQ 窗口**扫码登录**（用小号）；
4. 浏览器打开 NapCat WebUI（默认 `http://127.0.0.1:6099/webui`），进入「网络配置 → OneBot11」，**开启 WebSocket 服务器（正向）**，记下端口（默认 `3001`）和访问令牌。
   - 若 WebUI 提示登录，令牌见 `napcat\config\webui.json` 的 `token` 字段。

> 备用协议实现：[Lagrange.OneBot](https://github.com/LagrangeDev/Lagrange.OneBot)，接口同为 OneBot v11，地址填进 `onebot_ws_url` 即可。

### Step 2：安装依赖

```bash
pip install -r requirements.txt
```

### Step 3：配置

```bash
# 复制模板并编辑
cp config.example.json config.json      # Windows: copy config.example.json config.json
```

编辑 `config.json`，必填 3 项：

```jsonc
{
  "bot_qq": "123456789",                  // 登录的 QQ 小号（纯数字）
  "onebot_access_token": "your-napcat-token", // Step1 里记录的访问令牌，没设就留空
  "deepseek_api_key": "sk-xxxxxxxxxx"     // DeepSeek API Key（https://platform.deepseek.com）
}
```

### Step 4：运行

```bash
python bot.py --selftest     # 先跑离线自测（消息解析）+ 无需联网
python bot.py                # 正式启动
```

看到 `✅ 已连接，开始监听消息` 后，去群里发 `@邪恶鲸鱼娘 你好` 即可。

> 🐳 **一键方式**：配置好后直接双击 `启动ai鱼.bat` 同时拉起 NapCat 和机器人；退出用 `停止ai鱼.bat`；新电脑环境检查用 `一键安装.bat`。

---

## ⚙️ 配置项说明

| 配置项 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `onebot_ws_url` | string | `ws://127.0.0.1:3001` | OneBot 正向 WebSocket 地址 |
| `onebot_access_token` | string | `""` | NapCat OneBot 设置的令牌（重要，不匹配则操作被拒） |
| `bot_qq` | string | `""` | **必填**，登录的 QQ 号 |
| `bot_name` | string | `邪恶鲸鱼娘` | 昵称（仅展示） |
| `deepseek_api_key` | string | `""` | **必填**，DeepSeek API Key |
| `deepseek_base_url` | string | `https://api.deepseek.com` | API 地址（OpenAI 兼容） |
| `deepseek_model` | string | `deepseek-chat` | `deepseek-chat`(快) / `deepseek-reasoner`(慢但会思考) |
| `temperature` | float | `1.0` | 0~2，越高越放飞 |
| `max_tokens` | int | `1024` | 回复最大 token 数（调小更快） |
| `history_limit` | int | `20` | 每会话记忆轮数（调小更快） |
| `reply_with_at` | bool | `true` | 回复时是否 @ 提问者 |
| `enable_private` | bool | `true` | 是否回复私聊 |
| `system_prompt` | string | 鲸鱼娘人设 | **角色人设在此编辑** |

---

## 🎭 自定义人设

编辑 `config.json` 的 `system_prompt` 即可完全改写角色（想换人格、换说话风格、换世界观都在这）。注意 JSON 要求整段写一行，换行用 `\n`。

> 💡 **提速技巧**：人设里「回答控制在 300 字以内」改成「控制在 100 字以内」，并把 `max_tokens` 调小、`history_limit` 调小，日常回复会明显更快。可用 `speedtest.py` 一键定位瓶颈（网络 / 字数 / 历史）。

---

## 🧾 使用说明

| 操作 | 说明 |
| --- | --- |
| 群里 `@邪恶鲸鱼娘 + 内容` | 机器人只回复 @ 后面的内容 |
| 直接「回复」机器人的上一条消息 | 也能触发对话 |
| 私聊机器人 | 直接对话（可用 `enable_private: false` 关闭） |
| 说「清空记忆 / 重置对话 / 失忆」 | 重置当前会话 |

---

## ❓ 常见问题

- **双击 `启动ai鱼.bat` 没反应 / 中文乱码**：本项目脚本已做「纯 ASCII 壳 + PowerShell EncodedCommand」处理，彻底规避编码问题；若仍报错，看 `启动ai鱼` 窗口提示。
- **提示 `连接被拒绝`**：NapCat 没起来或 QQ 没登录；确认端口 `3001` 被监听、令牌两边一致。
- **群里 @ 没反应**：`bot_qq` 填的是登录账号（不是昵称）；确认控制台没有「处理消息出错」。
- **回复提示「深海信号不好」**：DeepSeek 调用失败，看终端报错（401=Key错/没余额，429=限流）。
- **日志刷 `[Rkey] 异常`**：NapCat 的第三方图片服务挂掉所致，**不影响文字聊天**，可忽略或升级 NapCat。
- **账号被风控/封禁**：非官方协议固有风险，只能换小号、控制频率。

---

## 📊 性能参考（本机实测）

| 场景 | 耗时 |
| --- | --- |
| 网络往返（不含生成） | ~1.2s |
| 50 字回复 | ~1.3s |
| 200 字回复 | ~2.8s |
| 20 轮历史对话 | ~1.9s |

> 见上方「提速技巧」，回复长度是最大耗时因素。

---

## ⚠️ 免责声明

- 本项目仅用于技术学习与交流，请勿用于任何违法违规或骚扰用途。
- 使用第三方协议实现登录 QQ 违反腾讯用户协议，**存在封号风险**，请自行评估并仅用小号运行。
- 本仓库**不包含**任何真实账号信息、API Key 或令牌（详见 `.gitignore`）。

---

## 📄 许可证

[MIT](LICENSE)

## 🗺️ Roadmap

- [ ] 图片理解（多模态）
- [ ] 语音回复
- [ ] 多群独立人设
- [ ] 定时任务 / 群公告
- [ ] Web 管理面板
- [ ] 多模型接入（Qwen / GPT / 本地模型）
