"""M139-B · 全屏 TUI 监控台（Textual）。

只读观察者：轮询统一 SQLite（factory_states + factory_events）渲染
工厂状态表与增量事件流，绝不写入 DB。
"""
