# 无忧28

无忧28是面向 VIP100 历史预测、YU28 历史开奖、回测和策略实验的 Windows 数据分析工具。

## 核心流程

```text
VIP100_HISTORY + YU28 历史开奖
        -> 历史预测与回测
        -> 策略实验室
        -> 自动运行与日报
```

程序不读取桌面窗口，不执行 OCR/UI Automation，也不包含外部窗口控制或任务采集队列。

## 数据目录

- 产品数据库：`%LOCALAPPDATA%\无忧28\data\le28.db`（保留历史文件名）
- VIP100 历史库：`%LOCALAPPDATA%\无忧28\data\vip100_history.sqlite3`
- 策略实验库：`%LOCALAPPDATA%\无忧28\data\strategy_lab.db`
- 日报：`%LOCALAPPDATA%\无忧28\reports\strategy_daily`
- 日志：`%LOCALAPPDATA%\无忧28\logs`

已有旧数据库文件不会被自动删除；新版运行流程不会再依赖其旧采集表。

## 页面

- 首页
- 数据中心
- 历史分析、走势图、遗漏分析
- VIP100
- 策略实验室
- 策略自动运行
- 模拟测试

## 命令行

```powershell
python main.py --self-test
python main.py --strategy-auto-run
```

## 开发检查

```powershell
python -m compileall app strategy_lab
python -m pytest
```

版本唯一来源为 `resources/version.json`。发布使用根目录 `release.py`，安装脚本位于 `packaging/wuyou28.nsi`。
