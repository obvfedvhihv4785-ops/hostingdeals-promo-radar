# AGENTS.md

This file is written in I-Lang and is intended to be read by any AI that picks
this repository up next. The short version: do not change the site's rules
without changing `.ilang/site.ilang` first, and do not invent data.

::ILANG
[TYPE:agents][PROJECT:hostingdeals][LANG:zh]

::STATE{@SELF, role:agents.md, audience:下一个接手这个仓库的 AI}
::STATE{@PROJECT, kind:优惠细分垂直站, niche:主机云 VPS 优惠, lang:en-US}

::OBJECTIVE{keep_pipeline_alive|pri:OVERRIDE}
target: 让这个仓库在没人盯的情况下 自己继续抓数据 自己继续渲染 自己继续部署
ACCEPT: scraper.py 跑通 build.py 跑通 workflow 每六小时跑一次 站还在线
NON_GOALS: 编优惠 编价格 编折扣码 编佣金 编热度 编评论

::RULE{站点的所有规则只在 .ilang/site.ilang 一处定义 scraper.py 和 build.py 真的读它}
::RULE{改一条厂商 站上就该出现或消失 改不动就是改动没被代码读到 重做}
::RULE{抓不到的字段一律不写 进页面前后任何字段都不得拿估的填}
::RULE{valid_until 已过 不许冒充有效 过期就从 data/offers.json 里下架}
::RULE{运行时零推理 零密钥 零外部包 纯 Python 白嫖 GitHub Actions + Cloudflare Pages}
::RULE{站点规则改完先本地 python scraper.py && python build.py 自测 再 commit}

::MODULE{PROVIDER_DATA|title:每家厂商必须能指向一个公开入口}
entry_kind:
  page:    抓这个 URL 的 HTML
  sitemap: 抓这个 sitemap(子) 把含关键词的页面也抓
  api:     抓这个 JSON 接口
[RULE] 入口必须是公开的 必须遵守 robots.txt 不许绕反爬 不许装浏览器
[RULE] 同一个厂商允许多个入口 取并集去重
[RULE] 入口被反爬挡住就在 data/offers.json 的 status 里写 error 站上如实标注 不要换路径绕

::MODULE{ALLOWED|title:允许的动作清单}
- 改 .ilang/site.ilang 来加厂商 改抓取字段 改渲染文案
- 改 scraper.py 的解析 但解析必须有原文证据 不许凭空造
- 改 build.py 的模板 但任何插值前必须 html.escape
- 加新的模板文件 但要在 build.py 引用
- 改 cron 频率 改 workflow 触发条件
- 加新 provider 的 affiliate 链接(填在 .ilang/site.ilang 的第 5 列)

::MODULE{FORBIDDEN|title:绝对不许的动作}
- 编价格 编折扣 编有效期
- 编优惠名 让它读起来更像一个 deal
- 编佣金
- 把抓不到的字段用相邻页面的字段凑
- 把 page 入口里找到的另一个 add-on 的价格当套餐价
- 改 scraper 的 robots 检查让它"假装没看到" Disallow
- 在 site/ 目录手改任何 HTML 因为下一次 build 会被覆盖
- 把 secret 或 token 直接 commit 进来
- 把 .ilang/site.ilang 删了或重命名 因为 scraper 和 build 找不到就报错

::MODULE{OUTPUT|title:改动完了你必须能证明的事}
[MUST] python scraper.py 跑通 写出 data/offers.json
[MUST] python build.py 跑通 写出 site/index.html
[MUST] 打开 site/index.html 浏览器看 能看到新内容
[MUST] data/offers.json 里每条 offer 都能溯源到 source_url 那个页面上有原话
[NEVER] 给用户看结果时只能说"已经改好了" 必须给一个可以打开的本地或线上地址

::MODULE{MONETIZE|title:变现这一块}
[ALLOW] 联盟链接 填在 .ilang/site.ilang 厂商行的第 5 列 公开平台的公开条款
[NEVER] 品牌词竞价 cookie 注入 自买自推 任何需要绕开平台规则才成立的玩法

::MODULE{EDITORIAL|title:每日缺口页}
editorial/gaps.json 是对标缺口表 唯一缺口来源 每个 gap_id 只能完成一次
editorial/articles.json 是已发布文章清单 每篇必须有 gap_id title answer sections sources
第一屏必须直接回答问题 独家补充必须来自独立计算或公开来源 不许改写对标站原文
每次只认领一个 status=open 的 gap 写一篇 写完把它变成已发布文章 不许重复 gap_id
发布前必须 python build.py 并检查 site/sitemap.xml 含 /articles/ 新地址
Reddit 等被反爬挡住的来源保持 blocked 不许用别的站替代 不许猜社区意见

::MODULE{WORKFLOW|title:和这个仓库的关系}
git init git add . git commit
main 分支公开 repo 名 hostingdeals-promo-radar
只让 GitHub Actions commit data/offers.json 它是仓库里唯一的时间戳源
site/ 不进库 在 .gitignore 里 部署走 wrangler pages deploy site
每日编辑任务只提交 editorial/ 下的内容和 build/template 支持 不改 scraper 数据规则

::LESSON{id:provider_branding|scope:project}
a2hosting.com 已整体 301 到 hosting.com 抓的时候写 https://hosting.com/hosting/ 跳转后真实页在那个 URL 上 A2 Hosting 页面没有服务端价格 因此只在覆盖率表里出现 在 offer 列表里不出现

::LESSON{id:vultr_blocked|scope:project}
www.vultr.com 配 Cloudflare 人机验证(403) api.vultr.com 公开 robots 是 Disallow:/
两条都按规矩不抓 不写假价格 只在覆盖率表里标注 blocked

::LESSON{id:cloudways_pricing_url|scope:project}
https://www.cloudways.com/en/pricing 301 跳到 /wp-content/uploads/2020/07/Pricing.jpg 是张图片
Cloudways 真正的入口是 /en/pricing.php(.php 是真的) 和 /en/promo-code 以及通过 /en/page-sitemap.xml 过滤出来的所有 /en/ 开头的 promo|coupon|pricing|discount URL

::LESSON{id:price_selection|scope:project}
同一个页面里有很多 \$\d+\.(mo|month) 价格 很多是 add-on 不是套餐
scraper 会用 plan_score 取带 plan 语境且不带 add-on 语境的最低非零月价格
挑错了的话看 .ilang/site.ilang 的 ADDON_WORDS / PLAN_WORDS 这两个词表再调 不要在代码里加特例