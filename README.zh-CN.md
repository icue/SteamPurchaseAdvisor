# Steam Purchase Advisor

[English](README.md)

Steam Purchase Advisor 是一组 Skills，用于筛选公开的 Steam 愿望单，以及在购买前评估游戏。

## 包含的技能

| 技能 | 用途 |
| --- | --- |
| [filter-steam-wishlist](.agents/skills/filter-steam-wishlist/SKILL.md) | 列出公开的用户愿望单，可按 Steam 商店打折、Steam 商店史低、抢先体验或正式发行状态筛选。 |
| [evaluate-steam-games](.agents/skills/evaluate-steam-games/SKILL.md) | 基于 Steam 评测、近期论坛动态、当前产品状态、Steam 商店定价及折扣规律分析、订阅服务，以及抢先体验开发信号，生成游戏评估报告。[^early-access-signals] |

[^early-access-signals]: 对处于抢先体验阶段的游戏，这些信号包括近期 Steam 论坛讨论、有明确日期的官方公告、更新及路线图、开发者活跃度与沟通情况、当前版本的技术与内容状态、Steam 标示的抢先体验开始日期以及开发者明确给出或可合理推导的正式发行日期、以及开发停滞或终止的证据。

## 提示词示例

- “列出我的愿望单中所有已经正式发行的游戏。”
- “列出我的 Steam 愿望单上达到史低的游戏。”
- “列出我的愿望单中正在打折的抢先体验游戏。”
- “Steam 游戏 XXX 现在值得入手吗？”
- “为我愿望单上的所有打折游戏给出购买建议。”

## 环境要求

- 支持 Agent Skills 的客户端和 Python 3。
- 筛选愿望单时，愿望单必须公开；可以提供 SteamID64、数字或自定义 Steam 个人资料 URL，或者准确的自定义个人资料 ID。
- 游戏评估需要 [Node.js 22.19+](https://nodejs.org/) 及 npm/npx，以连接 [Steam Review and Forum MCP](https://github.com/icue/SteamReviewAndForumMcp)。
- 只有查询 Steam 商店价格、折扣、史低、折扣规律、捆绑包或订阅服务时才需要 [IsThereAnyDeal API key](https://isthereanydeal.com/apps/)。

## 快速开始

1. 克隆或下载本仓库，让客户端能够发现 **.agents/skills/** 目录。
2. 直接选择任一工作流开始：

   - **愿望单筛选：** 请求列出或筛选愿望单；如果尚未配置 `steam_id`，请提供 SteamID64、数字个人资料 URL、自定义个人资料 URL，或准确的自定义个人资料 ID。
   - **游戏评估：** 使用游戏名称、AppID 或 Steam 商店 URL，询问一个或多个游戏是否值得购买。

在游戏评估时，如果 Steam Review and Forum MCP 尚未连接， Skill 会先征求一次许可，再按照当前客户端的官方配置方式尝试自动注册。

如果自动注册不可用或失败，请在客户端中手工注册以下 stdio 服务器：

- 服务器名称：`steam-review-and-forum`
- 命令：`npx`
- 参数：`-y`、`steam-review-and-forum-mcp`

常见的 JSON 表示如下：

```json
{
  "mcpServers": {
    "steam-review-and-forum": {
      "command": "npx",
      "args": ["-y", "steam-review-and-forum-mcp"]
    }
  }
}
```

具体配置格式和位置取决于客户端，请以其最新官方 MCP 文档为准。修改配置后，可能需要重启客户端。

## 配置

**config.json** 中的每个值都是 JSON 字符串，必须保留双引号。空字符串（**""**）表示未配置。格式见 [config.example.json](config.example.json)。

| 字段 | 格式与作用 |
| --- | --- |
| **steam_id** | 17 位 SteamID64 字符串，用于公开愿望单功能。 |
| **itad_api_key** | ITAD API key 字符串，用于当前价格、折扣、史低、捆绑包及美国区订阅访问情况查询。可在 [IsThereAnyDeal](https://isthereanydeal.com/apps/) 创建应用后获得。 |
| **pricing_country** | 大写两位 ISO 3166-1 国家代码，例如 **"US"** 或 **"CN"**，用于选择区域价格和捆绑包数据。 |
| **report_country** | 大写两位 ISO 3166-1 国家代码，用于选择生成报告和游戏标题的语言。 |

请求中提供的个人资料 URL 和自定义 ID 会自动解析；**config.json** 的 **steam_id** 仅存储规范的 17 位 SteamID64。

**config.json** 已被 Git 忽略。不要提交该文件、公开 API key、把 key 粘贴到对话中，或通过命令行传递。

## 许可证

[BSD 3-Clause](LICENSE)
