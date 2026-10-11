# TG 图床 (Telegram Image Host)

基于 Telegram 的图床服务：**图片真实存储在 Telegram**（通过 `file_id` 引用），
对外提供稳定的 HTTP 直链、Web 上传页、REST API 和管理后台。零对象存储成本。

## 功能

- 📤 Telegram 私聊 / 群聊发图即得直链
- 🌐 Web 上传页（粘贴 API Token 即可上传）
- 👤 用户中心（用 API Token 登录，管理自己的图片与用量）
- 🔌 REST API，可对接 PicGo / ShareX / 自定义脚本
- 🗑 删除与权限管理（用户删自己的，管理员删全部）
- 🚫 封禁 / 解封用户、广播、用户用量查询
- 📊 管理后台：统计图表、图片列表、用户列表，支持批量勾选操作
- 🔐 管理后台无独立账号密码，管理员用自己的 API Token 登录即进入
- 🎯 按用户单独设置配额（后台或 `/quota` 命令）
- ⏱ 记录每张图片的上传时间
- 🧊 本地磁盘缓存 + LRU 淘汰，减轻 Telegram 取图压力
- 📦 单文件大小、用户配额限制

## 架构

```
Telegram 用户 ──▶ Bot (aiogram)  ──┐
                                   ├─▶ SQLite (元数据: file_id 等)
浏览器 / API ──▶ FastAPI ──────────┘
                     │
                     └─▶ Telegram Bot API (取图/存档到存储频道)
```

- 图片本体始终由 Telegram 保存；数据库只存 `file_id`、大小、尺寸等元数据。
- 建议配置一个私有频道 `STORAGE_CHAT_ID`，Bot 会把每条上传的原始文件转存进去，
  既是备份，也方便管理员翻查。
- 对外直链由本服务代理：请求 `/i/<id>` 时从 Telegram 拉取并按需缓存。

## 快速开始

### 1. 准备 Bot

1. 找 [@BotFather](https://t.me/BotFather) 新建 Bot，拿到 `BOT_TOKEN`。
2. **群聊使用方法**：默认 Bot 开启了 Privacy Mode，只会收到命令和回复它的消息。
   如需处理群里所有图片，发送 `/setprivacy` 关闭 Privacy Mode，并把 `.env` 里的
   `GROUP_PROCESS_ALL` 设为 `true`。
3. （推荐）建一个私有频道，把 Bot 设为管理员，频道的 ID 形如 `-1001234567890`，
   填入 `STORAGE_CHAT_ID`。

### 2. 配置

```bash
cp .env.example .env
# 编辑 .env，至少填写 BOT_TOKEN；建议填写 ADMIN_IDS、STORAGE_CHAT_ID 和对外地址
```

**怎么拿到 CHAT ID / 用户 ID**：把 Bot 拉进目标群或频道，在群里 @ 它（或发送 `/id`），
它会返回当前会话的 Chat ID 和你的用户 ID；在私聊里发送 `/id` 可拿到自己的用户 ID。
把结果分别填入 `STORAGE_CHAT_ID` 和 `ADMIN_IDS` 即可。
（注：Telegram Bot 无法获取用户 IP 地址，这是官方 API 的限制。）

### 3. 安装依赖

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 4. 启动

需要**两个进程**，分别运行 Bot 和 Web 服务（可放在同一台机器）：

```bash
# 进程 1：Bot
python run_bot.py

# 进程 2：Web / API
python run_web.py
```

> 以上为本地开发/临时运行方式；生产环境长期常驻请见下方[「部署方式」](#部署方式)。

## 使用

### Telegram

| 命令 | 说明 |
| --- | --- |
| 直接发图 | 返回直链 |
| `/id`（或 @ 机器人） | 返回当前会话 Chat ID、你的用户 ID（用于填 `.env`） |
| `/token` | 获取 API Token（Web / API 用） |
| `/stats` | 查看用量 |
| `/delete <ID>` | 删除图片（也可回复图片） |
| `/admin` | 管理员命令 |

管理员命令：`/ban <id>`、`/unban <id>`、`/promote <id>`、`/demote <id>`、`/userinfo <id>`、`/quota <id> [MB]`、`/broadcast <文本>`。

### Web

- 上传页：`http://<host>:8080/upload`
- 用户中心：`http://<host>:8080/my`（用 `/token` 拿到的 API Token 登录，可上传、查看/批量删除自己的图片、查看配额与上传趋势）
- 图片页面：`http://<host>:8080/v/<id>`
- 管理后台：`http://<host>:8080/admin`（无独立账号密码；管理员用自己的 API Token 在用户中心登录后自动进入）

管理后台没有单独的账号密码。**管理员 = `.env` 中 `ADMIN_IDS` 里的用户，或在后台/Telegram 里被设为管理员的用户**。
他们在 `/my/login` 用自己的 API Token（Telegram 发送 `/token` 获取）登录后会自动跳转到 `/admin`；
普通用户登录则进入自己的用户中心。管理后台可管理其他用户（封禁 / 解封、设为管理员 / 取消管理员、
查看与清空其图片、**为每个用户单独设置配额**）、按图片 ID 搜索、**批量勾选删除图片**、
**批量勾选用户操作**（封禁/解封/设管理员/取消/清空图片）。
概览页包含近 14 天上传趋势图与来源分布图。

### API

获取 Token：在 Telegram 发送 `/token`。

```bash
# 上传
curl -F "file=@cat.png" \
  -H "Authorization: Bearer <TOKEN>" \
  http://localhost:8080/api/upload

# 返回
# {"id":"a1B2c3D4e5","url":"http://.../i/a1B2c3D4e5.png","page":"...","size":12345,...}

# 查看账户
curl -H "Authorization: Bearer <TOKEN>" http://localhost:8080/api/me

# 列出我的图片（带上传时间 created_at）
curl -H "Authorization: Bearer <TOKEN>" "http://localhost:8080/api/images?limit=50&offset=0"

# 批量删除
curl -X POST -H "Authorization: Bearer <TOKEN>" -H "Content-Type: application/json" \
  -d '{"ids":["a1B2c3D4e5","f6G7h8I9j0"]}' \
  http://localhost:8080/api/images/bulk-delete

# 删除
curl -X DELETE -H "Authorization: Bearer <TOKEN>" \
  http://localhost:8080/api/images/<id>
```

也支持 `X-API-Token: <TOKEN>` 请求头。

## 配置项

| 变量 | 说明 |
| --- | --- |
| `BOT_TOKEN` | 必填，BotFather 提供 |
| `STORAGE_CHAT_ID` | 存储群/频道 ID，Web·API 上传必需（或用首个管理员私聊兜底） |
| `ADMIN_IDS` | 管理员 Telegram 用户 ID，逗号分隔 |
| `WEB_BASE_URL` | 页面地址（上传页/详情页/后台）。有域名时填，如 `https://pic.example.com` |
| `IMAGE_BASE_URL` | 图片直链地址。可独立域名，如 `https://img.example.com`；留空则同 `WEB_BASE_URL` |
| `PUBLIC_HOST` | 无域名时用于拼接地址的公网 IP/主机名 |
| `WEB_HOST` / `WEB_PORT` | Web 监听地址；无域名时也用于拼接 `http://host:port` |
| `DATABASE_URL` | 数据库连接，默认 SQLite |
| `CACHE_DIR` / `CACHE_MAX_MB` | 本地缓存目录与上限 |
| `MAX_UPLOAD_MB` | 单文件上限 |
| `DEFAULT_QUOTA_MB` | 全局默认配额，0 为不限；可在后台或 `/quota` 为单个用户单独覆盖 |
| `GROUP_PROCESS_ALL` | 群聊是否处理所有图片 |

### 对外链接的两种配置方式

- **没有域名（IP + 端口直连）**：只填 `PUBLIC_HOST` 为服务器公网 IP，`WEB_BASE_URL`、
  `IMAGE_BASE_URL` 留空，程序自动使用 `http://<PUBLIC_HOST>:<WEB_PORT>`。
- **有域名（Nginx 反代）**：分别填写 `WEB_BASE_URL`（页面）和 `IMAGE_BASE_URL`（直链），
  可让图片走独立域名/CDN。两者填了就以域名为准，留空回退到 `PUBLIC_HOST:WEB_PORT`。

## 部署方式

项目由**两个进程**组成：`run_bot.py`（Telegram Bot）与 `run_web.py`（Web / API）。
两者共享同一个 SQLite 数据库，建议部署在同一台机器上。下面提供三种方式，任选其一。

### 方式一：systemd（裸机 / VPS）

适合直接跑在 Linux 主机上，支持开机自启与进程崩溃自动拉起。

```bash
# 1. 拉取代码并安装依赖
git clone https://github.com/luolu1/tg-imagehost.git
cd tg-imagehost
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 2. 配置
cp .env.example .env
vim .env            # 至少填写 BOT_TOKEN，建议填写 ADMIN_IDS、STORAGE_CHAT_ID、对外地址

# 3. 安装 systemd 服务
sudo cp deploy/tg-imagehost-bot.service deploy/tg-imagehost-web.service /etc/systemd/system/
# unit 内使用绝对路径；若项目不在 /mnt/tg-imagehost，请编辑这两个文件中的：
#   WorkingDirectory=/your/path/tg-imagehost
#   ExecStart=/your/path/tg-imagehost/.venv/bin/python run_*.py
sudo systemctl daemon-reload
sudo systemctl enable --now tg-imagehost-bot tg-imagehost-web
```

常用管理命令：

```bash
systemctl status tg-imagehost-bot tg-imagehost-web   # 查看状态
systemctl restart tg-imagehost-web                   # 重启 Web
systemctl restart tg-imagehost-bot                   # 重启 Bot
journalctl -u tg-imagehost-bot -f                    # Bot 实时日志
journalctl -u tg-imagehost-web -f                    # Web 实时日志
```

### 方式二：Docker

先构建镜像，再分别以容器运行 Web 与 Bot：

```bash
# 构建镜像
docker build -t tg-imagehost .

# 启动 Web（映射 8080，挂载 ./data 持久化数据库与缓存）
docker run -d --name tg-imagehost-web \
  --env-file .env \
  -p 8080:8080 \
  -v "$PWD/data:/app/data" \
  --restart unless-stopped \
  tg-imagehost python run_web.py

# 启动 Bot
docker run -d --name tg-imagehost-bot \
  --env-file .env \
  -v "$PWD/data:/app/data" \
  --restart unless-stopped \
  tg-imagehost python run_bot.py
```

```bash
docker logs -f tg-imagehost-web                  # 查看 Web 日志
docker logs -f tg-imagehost-bot                  # 查看 Bot 日志
docker rm -f tg-imagehost-web tg-imagehost-bot   # 停止并删除容器
```

> 两个容器必须挂载**同一个** `./data` 目录，否则数据库与缓存无法共享。

### 方式三：Docker Compose（推荐）

仓库自带 `docker-compose.yml`，会构建一次镜像并同时管理 Web 与 Bot。

```bash
cp .env.example .env
vim .env

docker compose up -d --build     # 构建并后台启动
docker compose ps                # 查看状态（Web 带健康检查）
docker compose logs -f           # 查看全部日志
docker compose logs -f web       # 只看 Web 日志
docker compose down              # 停止并移除容器
docker compose up -d --build     # 更新代码后重建
```

- `./data` 会挂载到容器内 `/app/data`，持久化 SQLite 数据库与图片缓存。
- Web 容器带有健康检查（`/healthz`），状态可在 `docker compose ps` 中查看。
- **修改 `.env` 后需要重建容器才能生效**：`env_file` 只在容器创建时注入，
  `docker compose restart` 不会重新读取；请执行 `docker compose up -d`
  （变量变化时会自动 recreate），或 `docker compose up -d --force-recreate`。

#### 对外暴露方式

仓库里的 `docker-compose.yml` **默认不映射宿主端口**，而是把两个容器加入一个
外部网络（示例为 cloudflared 的 `cloudflared_default`），由隧道/反代按服务名
`http://tg-imagehost-web:8080` 访问：

```yaml
services:
  web:
    expose:
      - "8080"            # 仅容器网络内暴露，不发布到宿主

networks:
  tg_bot_image_net:
    external: true
    name: cloudflared_default   # 复用已存在的外部网络
```

> 这要求该外部网络已存在（`docker network ls` 可见）。cloudflared 隧道的
> service 指向 `http://tg-imagehost-web:8080` 即可。

如果你**没有外部网络、想直接用 IP:端口访问**，把 `web` 服务改成端口映射，
并删除 `networks` 相关配置即可：

```yaml
services:
  web:
    ports:
      - "8080:8080"       # 发布到宿主 8080
```

### 反向代理（可选）

有域名时，用 Nginx 反代到 `127.0.0.1:8080`，并在 `.env` 中填写
`WEB_BASE_URL` / `IMAGE_BASE_URL`：

```nginx
server {
    listen 80;
    server_name pic.example.com;

    client_max_body_size 25m;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

## 目录结构

```
app/
  config.py            # 配置
  models.py            # SQLAlchemy 模型
  db.py                # 异步引擎 / 会话（含轻量迁移）
  services.py          # 数据访问层
  uploads.py           # 上传（写 Telegram + 落库）
  telegram_files.py    # Telegram 取图 / 存图 / 缓存
  bot/                 # aiogram handlers
  web/                 # FastAPI 路由 + 模板
    pages.py           # 公共页面 / 直链
    user_portal.py     # 用户中心（Token 登录）
    api.py             # REST API
    admin.py           # 管理后台
deploy/                # systemd unit 模板
scripts/               # 冒烟 / 端到端测试
Dockerfile             # 容器镜像
docker-compose.yml     # Compose 编排（web + bot）
.env.example           # 配置模板
run_bot.py             # Bot 进程入口
run_web.py             # Web 进程入口
```

## 说明与注意

- Telegram 单文件下载上限为 20 MB（Bot API），因此 `MAX_UPLOAD_MB` 不要超过 20。
- `file_id` 与 Bot 绑定，换 Bot 后旧图片需重新上传。
- 直链内容由本服务代理并缓存，`CACHE_MAX_MB` 决定本地磁盘占用。
