# Nullbr Search Bot

![Nullbr Search Bot](https://img.shields.io/badge/Telegram-Bot-blue.svg) ![Python 3.10+](https://img.shields.io/badge/Python-3.10+-yellow.svg)

这是一个为 **Nullbr影视库** 量身定制的私有化 Telegram 交互式机器人程序。支持全接口精准查询、115网盘/磁力一键提取、多API高并发负载均衡以及可视化的 SQLite 白名单权限管理系统等核心特征。

## ✨ 核心特性

- **🎬 完美适配 Nullbr API：** 内置高度稳健的异步接口轮询与防丢字结构，支持全局搜索与精确 ID 查询（电影/剧集/人物）。
- **📊 颜值拉满的图文交互：** 利用内嵌隐藏短链，实现无框原始海报 + 中文简介 + 分辨率/字幕组/容量大小清单等极度优雅的 Telegram 排版。
- **🌐 磁力及 115 获取：** 一键点击即可获取对应资源的直达分享链接；针对 Telegram 的限制对磁力链接专门实现了复制框代码。
- **🎛️ Inline 本地化内联搜索：** 在任何聊天框任意好友界面，输入 `@机器名字 关键词` 即可调用弹窗检索资源库并分享。
- **🛡️ 数据库白名单系统：** 程序内置 SQLite 权限控制，默认锁区防止额度被刷。包含 `/admin` 的超级可视化数据面板及一键 `/auth` TG指令热控制。
- **🔄 API Key 轮询容灾功能：** 除了基础的 `.env` 配置文件，管理员还能在 Telegram 会话中直接通过指令热加载小号的 AppID/APIKey。机器人会在数据库中随意抽取 Token 替你发请求分摊配额消耗。
- **🤖 自动挂载命令词典：** 完全开箱即用，运行瞬间即可自动把 `/s`，`/admin` 等操作菜单部署进 Telegram 左下角。

---

## 🛠️ 安装与部署指南

### 1. 软件及环境要求
本机器人完全由 Python 编写并使用 `python-telegram-bot` 库封装。你需要：
- 一台已安装 **Python 3.10 及以上** 代码的服务器。
- 网络必须畅通无阻碍（可以正常访问 `api.telegram.org` 和 `api.nullbr.eu.org`）。

### 2. 克隆仓库与安装依赖
```bash
git clone https://github.com/atpx4869/nullbr-search-bot.git
cd nullbr-search-bot

# 安装主要依赖库
pip install -r requirements.txt
```

### 3. 配置核心环境变量
请将目录下的隐藏文件副本创建成你自己的设置文件（Linux 中请手动创建 `.env`）：
1. 在项目根目录创建一个名词为 `.env` 的文件。
2. 填入如下对应的信息：

```ini
# (必须) 从 Telegram 的 @BotFather 获取的机器人 Token
BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrSTUvwxYZ

# (必须) 你的个人 Telegram ID （机器人的全能最高主人管理员），也是白名单里的第一个人
ADMIN_ID=1122334455

# (必需其一) 你的 Nullbr 账号 API 认证凭证。如果你后面在数据库面板加了新号，这里填什么都无所谓了。
X_APP_ID=你注册生成的AppID
X_API_KEY=你注册生成的ApiKey
```
*(注：怎么获取个人 ID ？在电报里找官方机器人 `@userinfobot` 即可看到你的具体长串数字)*

### 4. 运行机器人

配置好上面这些后，启动机器人程序：

```bash
python bot.py
```

显示 `Application started` 后，请打开你的手机 Telegram 进入你的那个小机器人即可：
- 看到左下角弹出的 Menu 图标，代表自动挂载完毕。
- 点击菜单或者发送 `/s 蜘蛛侠` 畅享体验吧！

### 5. 使用脚本托管（推荐 1Panel 计划任务）

项目已提供进程管理脚本：`scripts/bot_manager.sh`

```bash
# 首次赋予执行权限
chmod +x scripts/bot_manager.sh

# 启动
bash scripts/bot_manager.sh start

# 停止
bash scripts/bot_manager.sh stop

# 重启
bash scripts/bot_manager.sh restart

# 状态
bash scripts/bot_manager.sh status
```

如果你在 1Panel 的计划任务里做“每日定时重启”，可直接设置任务命令：

```bash
cd /你的项目目录 && bash scripts/bot_manager.sh restart
```

如果你希望任务自动完成“拉取最新代码 + 更新依赖 + 重启”，可使用：

```bash
cd /你的项目目录 && bash scripts/update_and_restart.sh
```

首次使用请赋予执行权限：

```bash
chmod +x scripts/update_and_restart.sh
```

如果你用了虚拟环境且不在默认 `.venv`，可以在任务中覆盖变量：

```bash
cd /你的项目目录 && VENV_PATH=/opt/nullbr-venv bash scripts/bot_manager.sh restart
```

默认日志与 PID 文件：
- 日志：`bot_runtime.log`
- PID：`bot.pid`

---

## 📖 管理员操作指令 / 使用手册

**常规搜索指令 (任何白名单成员都可用此操作)**
- `/s <影视名字>` ：最常用的直接搜索。
- `/sid <类型> <ID>` : 直接用 TMDB ID 查询详情。比如 `/sid tv 1399` (权游)。

**管理员管理指令 (只认你的 `.env` Admin ID)**
- `/admin` : 弹出一个超级数据看板，查看当前有多少人在白名单、挂载了几个备用 API。
- `/auth add <TG用户ID或者群号>` : 将朋友或者群拉入白名单。
- `/auth del <TG用户ID或者群号>` : 踢出白名单。
- `/key add <App_ID> <API_Key>` : 当你找朋友借了个小号的资源，可以在这里随时丢进机器人的轮播随机选号池内。
- `/key del <App_ID>` : 随时删掉失效过期的账号防报错。

*(注意：如何开启炫酷的 `@机器名字 关键词` 的全局悬浮窗口 Inline Search 模式？)*
*答：去给 `@BotFather` 发消息，然后选中 `Bot Settings -> Inline Mode -> Turn on`，它就自动全网激活了！*
