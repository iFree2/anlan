# 客户版女声演示制作计划

> **For agentic workers:** Use executing-plans to execute inline; user explicitly requested direct replacement without an audition checkpoint.

**Goal:** 保留现有真实业务录像，重写客户版口语旁白，生成柔和女声、稍慢语速的视频新版本。

**Architecture:** 不改应用、不重部署、不调用业务模型。复用已校准录像切点，新建独立媒体目录保留男声原版；按新旁白长度重排章节、字幕与停帧。

**Tech Stack:** 现有 Edge TTS、FFmpeg、Python 媒体环境。

## 已确认设计

用户选择直接换整条，不需要试听。声音目标为柔和、成熟女声，略带妩媚感，不采用真人声音模仿；合成声音实际表现以供应商音色为限。语速慢于标准，先采用 `zh-CN-XiaoxiaoNeural`、`rate=-10%`、`pitch=-4Hz`。文案围绕“申请人不知道怎么填、材料反复补、安全人员核查和反馈”展开，不提后台架构、持久化等技术词，不虚构自动审批、真实设备接入或量化收益。保留合成数据与人工审核说明。

## 制作步骤

- [x] 新建 `.runtime/anlan-demo-20261022-female/`：原创十章口语文案；复用三份录像报告，原素材不变。
- [x] 现有 `.runtime/make_demo_voice.py`、`.runtime/render_demo_movie.py` 增加独立输出目录及声音参数；默认行为兼容原版。生成十章女声及字幕，任一章失败时不渲染不完整成片。
- [x] 导出1080p/30fps成片；完整解码视频及音轨，检查章节非静音、字幕边界及业务关键帧；核对原版SHA-256保持不变。
- [x] 保存客户版旁白稿及制作证据；只提交本次文档，不提交ignored媒体与其他用户改动；直接交付新视频。

## 结果

成片 `.runtime/anlan-demo-20261022-female/Anlan-Product-Demo-ZH-Female.mp4`，约4分18秒、10,114,141字节。完整解码退出0，十章非静音、字幕文字与旁白逐章一致、字幕时间在音频范围内。封面、确认任务、事件核查与反馈关键帧目视通过。原版SHA-256保持不变，业务模型调用为0。证据见 `docs/phases/phase-11-conversation/evidence/female-demo-20261022.json`。

验证命令：`.runtime/media-venv/Scripts/python.exe .runtime/make_demo_voice.py --root .runtime/anlan-demo-20261022-female --voice zh-CN-XiaoxiaoNeural --rate=-10% --pitch=-4Hz`；随后运行同目录参数的 `render_demo_movie.py`，并以FFmpeg完整解码到null，必须退出0。每章音量RMS须大于100，输出必须含H.264视频与AAC音轨。旧成片SHA-256须为 `63165ba0b7117b5a26590fe5ce8a369d7bbdef9b025a14883b3f74465552fdf1`。
