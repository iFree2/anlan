# 本地两类事件回放

先加载数据库环境，使用既有venv，避免占用中的anlan.exe安装问题：

```powershell
scripts/dev-postgres.ps1 -Action Env
.venv/Scripts/python.exe -m anlan.interfaces.events_cli init
.venv/Scripts/python.exe -O evals/evaluate_events.py --output .runtime/events-replay-new.json
```

输出路径必须是新路径。回放自动为两类事件各创建一个SYNTHETIC材料任务，生成带task/revision/run的宿主binding，先接收、跨进程读取，再关联、重复接收、读取和验证越权拒绝。示例时间固定2026-09-22T04:00Z，来源为`examples/synthetic/events-v1.json`；不是实际设备读数。报告保留原始记录与每条命令退出码。

单步读取已有回执：

```powershell
.venv/Scripts/python.exe -m anlan.interfaces.events_cli --tenant synthetic-p5-replay --user safety-manager-demo --as-of 2026-09-22T04:00:00Z show <receipt-id>
.venv/Scripts/python.exe -m anlan.interfaces.events_cli --tenant synthetic-p5-replay --user safety-manager-demo --as-of 2026-09-22T04:00:00Z process <receipt-id>
```

`received_at`与`observed_at`不同；`result=null`表示原事件已提交、关联尚未完成。锁忙/进程退出后可显式process恢复；重复返回同一结果。`linked`只是当时材料版本的关联，不是作业批准或当前性保证。即使expired/out_of_order/task_unavailable，raw.alarm_state仍是active；没有解除告警接口。

CLI身份和binding文件是本地可信模拟配置；不能把此调用方式当成面向任意用户的服务认证。未知来源留unknown_source，不猜测任务。现场生产阈值、报警控制和原设备系统均不在本例范围。
