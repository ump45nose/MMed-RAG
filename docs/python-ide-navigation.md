# Python 依赖源码跳转配置

本项目后端依赖 LangChain、SQLAlchemy 等大型第三方库。为了在 VS Code 中稳定查看 `import` 方法定义，建议使用项目本地虚拟环境，并让 Pylance 读取第三方库源码。

## 初始化本地虚拟环境

在仓库根目录执行：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r backend\requirements.txt
```

如果本机没有 Python 3.11，可使用 Python 3.12。当前仓库配置默认指向 `.venv`，创建后 VS Code 会自动优先使用该解释器。

## VS Code 检查项

1. 安装推荐扩展：`ms-python.python`、`ms-python.vscode-pylance`。
2. 重新打开 VS Code，或执行 `Developer: Reload Window`。
3. 在右下角确认 Python 解释器为 `${workspaceFolder}\.venv\Scripts\python.exe`。
4. 对第三方库符号优先使用 `Go to Definition`；如果只跳到 `.pyi` 类型声明，再使用 `Go to Implementations` 查看源码实现。

## 已提交的仓库配置

- `.vscode/settings.json`：开启 `useLibraryCodeForTypes`，并加深 LangChain、SQLAlchemy 等包的索引层级。
- `pyrightconfig.json`：把 `backend` 加入分析路径，统一 Pyright/Pylance 的解析入口。
- `.vscode/extensions.json`：提示安装 Python 与 Pylance 扩展。

这些配置只影响本地编辑器分析，不改变 Docker 启动方式和运行时代码。
