# GMAT Focus AI Tutor

GMAT Focus Edition Verbal 备考助手，内含 149 道 OG 真题（Critical Reasoning），支持 AI 讲解、错误归因、弱项追踪和自适应练习。

## 快速部署到 Streamlit Cloud（推荐）

手机随时随地使用，无需电脑开着。

### 第一步：上传代码到 GitHub

1. 登录 [github.com](https://github.com)（没有账号就注册一个）
2. 点右上角 **+** → **New repository**
3. 仓库名填 `gmat-tutor`，选 **Private**（私有），点 **Create repository**
4. 在仓库页面点 **uploading an existing file**
5. 把本压缩包里的**所有文件和文件夹**（包括 `.streamlit` 和 `.gitignore`）拖进去
6. 点 **Commit changes**

> ⚠️ 重要：`.streamlit` 是隐藏文件夹，Windows 下可能看不到。解压后在文件资源管理器 → 查看 → 勾选「隐藏的项目」。

### 第二步：在 Streamlit Cloud 部署

1. 打开 [share.streamlit.io](https://share.streamlit.io)
2. 用 GitHub 账号登录
3. 点 **New app**
4. 选你的仓库 `gmat-tutor`，Branch 选 `main`，Main file path 填 `app.py`
5. 点 **Deploy!**

等 1-2 分钟，会给你一个永久地址（如 `https://xxx.streamlit.app`）。

### 第三步：配置 AI 讲解（可选但推荐）

在 Streamlit Cloud 后台配置 API Key：

1. 在你的 app 页面，点右上角 **⋯** → **Settings** → **Secrets**
2. 粘贴以下内容（替换为你的真实 Key）：

```toml
[ai]
api_key = "你的API-Key"
base_url = "https://ark.cn-beijing.volces.com/api/v3"
model = "doubao-seed-1-6-251015"
```

3. 点 **Save** → 应用会自动重启

> 推荐用火山方舟标准 API（doubao 系列），便宜且中文好。
> 在 [火山方舟控制台](https://console.volcengine.com/ark) 获取 API Key。

### 完成！

手机浏览器打开你的 `.streamlit.app` 地址即可使用。建议收藏到主屏幕。

---

## 本地运行

```bash
# 安装依赖
pip install streamlit pandas pypdf openai

# 启动（Windows 可直接双击 start.bat）
streamlit run app.py
```

## 项目结构

```
gmat-tutor/
├── app.py              # Streamlit 主界面
├── database.py         # SQLite 数据库层
├── scheduler.py        # 自适应练习调度器
├── tutor.py            # AI 讲解层（兼容 OpenAI API）
├── og_questions.json   # 149 道 OG CR 真题
├── extract_og.py       # PDF 提取工具（可选）
├── requirements.txt    # Python 依赖
├── .streamlit/         # Streamlit 配置
│   └── config.toml     # 主题和服务器设置
└── .gitignore
```
