// ── Skills 帮助 ──
const _ALL_SKILLS = [
    {g:"客户开发",items:[
        {n:"b2b-osint",d:"客户背景调查（6 层检测：WHOIS/邮箱/制裁/技术栈/LinkedIn/评分）",t:"背调、查公司、查域名、查邮箱、due diligence"},
        {n:"b2b-email-intel",d:"邮箱情报 — 120+ 平台检测邮箱注册状态",t:"查邮箱、邮箱注册、邮箱背调、email lookup"},
        {n:"b2b-lead-generation",d:"多通道客户搜索与开发（Google Maps/LinkedIn/Facebook）",t:"找客户、开发客户、lead generation、cold email"},
        {n:"b2b-customer-finder",d:"傻瓜式客户开发向导 — 三问启动 + 自动搜索 + 开发信生成",t:"怎么找客户、客户开发向导、customer finder、找客户"},
        {n:"b2b-china-leads",d:"国内企业线索挖掘 — 找货源厂家（主）/ 挖竞品国内厂家（重点）/ 找国内客户，免费公开渠道（产业带+搜索引擎+海关记录+人工核对，不依赖付费接口）",t:"找货源、竞品厂家、找厂家、代工厂、国内客户、同类厂家、找供应商、厂商挖掘、1688、企查查、天眼查"},
        {n:"b2b-cold-outreach",d:"B2B 冷 outreach 邮件撰写（开发信/推广信/跟进信）",t:"开发信、写推广信、cold email、outreach"},
        {n:"b2b-email-imitation",d:"开发信仿写与再创作 — 分析优秀邮件样本，学结构学风格",t:"仿写开发信、按照样本、模仿邮件、email imitation"},
        {n:"b2b-buyer-persona",d:"买家画像与角色分层 — 按角色定制 FAB 价值主张",t:"买家画像、按角色写、给采购写、buyer persona"},
        {n:"auto-trade-customer-development",d:"全自动客户开发流水线 — 搜索→背调→评分→写信→交付草稿",t:"全自动客户开发、一键开发、auto customer dev"},
    ]},{g:"内容营销",items:[
        {n:"b2b-social-media",d:"社媒营销（Facebook/Instagram/TikTok/YouTube）",t:"社媒、Facebook、TikTok、内容日历、social media"},
        {n:"b2b-linkedin-marketing",d:"LinkedIn 营销策略与内容（Profile/帖子/InMail）",t:"LinkedIn、领英、linkedin marketing、InMail"},
        {n:"b2b-kol-imitation",d:"LinkedIn/社媒 KOL 风格模仿 — 分析风格应用到自家品牌",t:"模仿风格、学大V、KOL imitation、imitate influencer"},
        {n:"b2b-reddit-engagement",d:"Reddit 社区互动 — 通过专业评论建立信任引流",t:"Reddit、社区评论、reddit comment、专业评论"},
        {n:"b2b-seo-aeo",d:"SEO+AEO 文章生成 — 针对 Google + AI 搜索优化",t:"SEO文章、AEO文章、搜索引擎优化、seo article"},
        {n:"b2b-short-video",d:"外贸 B2B 短视频脚本生成（TikTok/Shorts/Reels）",t:"短视频、视频脚本、TikTok脚本、short video"},
        {n:"b2b-market-analysis",d:"市场分析作战地图 — 认证/关税/关键词/3 秒 Hook",t:"市场分析、目标市场、作战地图、market analysis"},
        {n:"b2b-daily-automation",d:"定时任务（早安简报/日报/周报/LinkedIn/社媒文案生成）",t:"每日任务、定时任务、早安简报、cron、日报"},
    ]},{g:"文档管理",items:[
        {n:"b2b-document",d:"本地文档分析与提取（PDF/Word/Excel 等）",t:"分析文档、读报价、看合同、analyze document"},
        {n:"b2b-doc-generation",d:"生成报价/合同/提案/PPT（DOCX/XLSX/PPTX）",t:"生成报价单、生成合同、做 PPT、generate doc"},
        {n:"b2b-tech-drawing",d:"工程图纸分析（实验性）— 从 PDF 图纸提取材料/尺寸/公差",t:"图纸、工程图、铸件图、技术图纸、blueprint"},
        {n:"b2b-data-directory",d:"数据目录结构管理与初始化",t:"数据目录、数据结构、我的数据存在哪"},
    ]},{g:"招投标",items:[
        {n:"b2b-tender-info",d:"招标信息抓取与筛选 — 按关键词定时搜招标公告",t:"找招标、查招标、招标信息、招标公告、tender opportunities"},
        {n:"b2b-tender-mail",d:"招标邮件与附件归档 — 从邮箱拉取，全程不置已读",t:"招标邮件、邮件归档、抓邮件、补附件、监控邮箱"},
        {n:"b2b-tender-processing",d:"招标文件转询价单 — 生成固定 11 列 Excel",t:"询价单、生成询价单、整理招标、招标文件整理"},
        {n:"b2b-tender-download",d:"招标附件批量下载 — 分块续传 + 大小/校验双验",t:"下载招标文件、断点续传、分块下载、按清单下载"},
        {n:"b2b-tender-archive",d:"压缩包批量解压归档 — 嵌套包多轮展开，原包进回收站",t:"解压、压缩包、批量解压、包中包、归档清理"},
        {n:"b2b-tender-doc-match",d:"按清单匹配归档文件 — 编号+名称匹配，成套打包",t:"按清单归档、按编号匹配、图纸匹配、招标清单匹配"},
    ]},{g:"平台与数据",items:[
        {n:"b2b-platform",d:"B2B 平台店铺诊断优化（阿里/MIC/独立站）",t:"平台诊断、阿里国际站、关键词优化、店铺诊断"},
        {n:"b2b-customs-data",d:"海关数据分析找采购商与市场趋势",t:"海关数据、进出口记录、找买家、customs data"},
    ]},{g:"客户与销售",items:[
        {n:"b2b-customer-intel",d:"单一客户深度画像 — 15 维度全方位情报档案",t:"客户画像、深度画像、送礼建议、回扣、了解客户"},
        {n:"b2b-customer-mgmt",d:"客户档案与分级管理（A/B/C 级、订单跟踪）",t:"客户管理、客户档案、客户分级、CRM"},
        {n:"b2b-sales-pipeline",d:"销售管线策略 — 30 天跟进表 + KPI 追踪 + 健康度看板",t:"销售推进、跟进计划、怎么跟进、sales pipeline"},
        {n:"b2b-inquiry-training",d:"询盘回复与 Top Sales 训练 — 双AI对抗训练法",t:"询盘训练、回复练习、模拟买家、反对意见"},
        {n:"b2b-exhibition",d:"展会全流程管理 — 展前邀约、展中跟进、展后转化",t:"展会、参展、广交会、trade show"},
        {n:"b2b-product-description",d:"产品描述生成器 — FAB 方法生成产品卖点与销售资料",t:"产品描述、产品文案、Sales Kit、product description"},
        {n:"b2b-trade-ops",d:"外贸履约与售后沟通（催款/索赔/展会/验厂/物流/售后）",t:"催款、索赔、展会、验厂、节日问候、物流"},
        {n:"b2b-inquiry-meeting",d:"询盘分析会主持 — 周度复盘/逐人点评/重点询盘/跟进行动表",t:"询盘分析会、询盘复盘、周会、业务员复盘"},
        {n:"b2b-sales-playbook",d:"销冠经验封装器 — SOP/话术库/新人路线/避坑清单/钩子武器库",t:"销冠经验、销售SOP、话术库、新人培训"},
        {n:"b2b-guarantee-proposal",d:"商业提案生成器 — 三档方案/ROI分析/实施路线图",t:"商业提案、战略建议书、ROI分析、方案建议书"},
    ]},{g:"合规与支持",items:[
        {n:"b2b-trade-compliance",d:"外贸合规检查 — 文化禁忌/缩写/Incoterms/翻译二审/投标",t:"文化禁忌、Incoterms、翻译二审、Amazon上架检查"},
        {n:"b2b-onboarding",d:"新公司全套部署方案（公司介绍/产品/营销/竞品分析）",t:"新公司、部署、全套方案、怎么开始、首次设置"},
        {n:"b2b-skill-generator",d:"根据需求描述自动创建新的 B2B Skill",t:"生成 skill、创建技能、create skill、new skill"},
        {n:"b2b-six-thinking-hats",d:"六顶思考帽决策教练 — 系统化分析复杂外贸决策",t:"决策分析、思考帽、利弊分析、decision making"},
        {n:"chat-memory",d:"历史对话查询（按今天/本周/本月/全部检索）",t:"之前说过、上周聊的、历史记录、chat history"},
        {n:"auto-smtp-email",d:"[已禁用] 点此了解设计理念",t:"【此技能已禁用】发邮件、群发、SMTP 发送"},
    ]},
];

function showUpgradeHelp() {
    showModal('upgrade-help-modal');
}

function copySkillTrigger(name, trigger) {
    /** O-17：技能帮助行点击复制（替代内联 onclick）。 */
    navigator.clipboard.writeText(name || '');
    toast(t('skills.copied') + (trigger || ''));
}

function showSkillsHelp() {
    var container = $('skills-help-content');
    if (!container) return;
    var html = '';
    for (var gi = 0; gi < _ALL_SKILLS.length; gi++) {
        var group = _ALL_SKILLS[gi];
        html += '<div style="margin-bottom:16px;"><h4 style="font-size:14px;font-weight:600;margin:0 0 6px;padding-bottom:4px;border-bottom:2px solid var(--primary);color:var(--primary);">' + esc(group.g) + '</h4>';
        for (var si = 0; si < group.items.length; si++) {
            var sk = group.items[si];
        var firstTrigger = sk.t.split('、')[0];
        html += '<div class="skill-copy-row" data-act="copySkillTrigger" data-arg="' + esc(sk.n) + '" data-arg2="' + esc(firstTrigger) + '" style="display:flex;align-items:flex-start;gap:8px;padding:6px 8px;border-radius:4px;cursor:pointer;" title="' + (currentLang==='en'?'Click to copy prompt':'点击复制提示词') + '">';
            html += '<code style="font-size:12px;white-space:nowrap;background:var(--bg-muted);padding:1px 6px;border-radius:3px;min-width:130px;">' + esc(sk.n) + '</code>';
            html += '<span style="flex:1;font-size:12px;color:var(--text-secondary);">' + esc(sk.d) + '</span>';
            html += '<span style="font-size:11px;color:var(--text-muted);white-space:nowrap;">💬 ' + esc(sk.t.split('、').slice(0,2).join(' | ')) + '</span>';
            html += '</div>';
        }
        html += '</div>';
    }
    container.innerHTML = html;
    showModal('skills-help-modal');
}

// ── Skills 更新 ──
async function updateSkills(e) {
    const btn = (e && (e.currentTarget || e.target)) || document.querySelector('#skills-update-btn');
    if (!btn) return;
    const restoreBtn = _setBtnWait(btn, 'UPDATING', '更新中');
    try {
        const resp = await api('POST', '/api/trade/skills/update');
        if (resp?.ok) {
            toast(t('sys.skills_ok'));
        } else if (resp) {
            toast(t('sys.skills_fail') + (resp.error || ''));
        }
    } catch(e) {
        toast(t('sys.skills_error') + e.message);
    } finally {
        restoreBtn();
    }
}

