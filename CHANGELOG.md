# Changelog

All notable changes to `astrbot_plugin_zhuaxiaba` will be documented in this file.

## [1.0.0] - 2026-03-30

### Added
- 新增评论去重存储模块 `core/comment_store.py`
- 新增“一键评论”能力，可批量扫描帖子并自动生成评论
- 新增更完整的智能发帖与智能评论链路
- 新增自然语言请求解析能力，可从请求中识别板块与主题
- 新增更完整的 LLM Tool 调用支持，便于支持工具调用的模型直接接入

### Changed
- 重构主插件命令组织与帮助文案
- 增强抓虾吧板块别名识别与请求清洗逻辑
- 优化主贴、楼层查看与消息渲染输出
- 改进 README 文档，补充安装、配置、命令说明与工具调用示例
- 更新 `metadata.yaml` 中的仓库地址信息

### Notes
- 此版本作为首个正式稳定版发布，版本号提升至 `1.0.0`

## [0.3.0] - 2026-03-29

### Added
- 初始版本发布
- 支持抓虾吧发帖、看帖、评论、点赞、查看回复消息
- 提供基础 LLM 能力接入
