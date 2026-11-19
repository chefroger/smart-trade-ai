// ═════════════════════ 客户开发向导 (b2b-customer-finder) ═════════════════════
let _wizardStep = 0;            // 0=hidden, 1=product, 2=market, 3=type, 4=running, 5=results
let _wizardAnswers = { product: '', market: '', customerType: '' };
let _wizardStreamCtl = null;
let _wizardResponse = '';

function isOnboardingCompleted() {
    try { return localStorage.getItem('_onboarding_completed') === '1'; } catch(_) { return false; }
}

// ═════════════════════ 客户开发向导 UI ═════════════════════
function showWizardInLeadView() {
    // 在 lead 聊天上下文中显示客户开发向导卡片。
    // 每个栏目都缓存了一份聊天 DOM（id 相同），必须限定在当前视图内查找，
    // 否则卡片会插进隐藏的「今日简报」那一份里。
    var scope = (typeof currentChatContainer !== 'undefined' && currentChatContainer) || document;
    var msgs = scope.querySelector('#chat-messages');
    if (!msgs) return;
    // 空态不一定存在（有历史消息时会被移除），不依赖它
    var empty = msgs.querySelector('#chat-empty');
    if (empty) empty.style.display = 'none';
    // 移除已有向导卡片
    var old = msgs.querySelector('#wizard-card');
    if (old) old.remove();
    _wizardStep = 1;
    var card = document.createElement('div');
    card.id = 'wizard-card';
    card.innerHTML = wizardRenderStep1();
    msgs.appendChild(card);
    setTimeout(function() {
        var inp = card.querySelector('#wizard-product-input');
        if (inp) inp.focus();
    }, 200);
}

function wizardRenderStep1() {
    return `<div class="onboarding-card" style="margin:0 auto;max-width:580px;">
        <div class="onboarding-step-indicator">
            <span class="onb-step active">● 卖什么</span><span class="onb-step-arrow">→</span>
            <span class="onb-step">○ 卖到哪</span><span class="onb-step-arrow">→</span>
            <span class="onb-step">○ 找谁</span>
        </div>
        <h2 class="onboarding-title" style="font-size:20px;">先告诉我：你卖什么产品？</h2>
        <p style="text-align:center;color:var(--text-secondary);font-size:14px;margin-bottom:16px;">
            随便说就行，"LED灯""五金""纺织品"都可以</p>
        <div class="onboarding-input-row">
            <input type="text" id="wizard-product-input" placeholder="例如：LED工矿灯、不锈钢螺丝、全棉T恤..."
                class="onboarding-text-input"
                onkeydown="if(event.key==='Enter')wizardNext()" autofocus />
        </div>
        <button class="btn btn-primary btn-lg" onclick="wizardNext()">下一步：卖到哪里去？ →</button>
        <div class="onboarding-skip" style="display:flex;justify-content:flex-end;">
            <a onclick="wizardClose()" title="跳过向导">跳过向导</a>
        </div>
    </div>`;
}

function wizardRenderStep2() {
    return `<div class="onboarding-card" style="margin:0 auto;max-width:580px;">
        <div class="onboarding-step-indicator">
            <span class="onb-step done">✓ 卖什么</span><span class="onb-step-arrow">→</span>
            <span class="onb-step active">● 卖到哪</span><span class="onb-step-arrow">→</span>
            <span class="onb-step">○ 找谁</span>
        </div>
        <h2 class="onboarding-title" style="font-size:20px;">想卖到哪个国家或地区？</h2>
        <p style="text-align:center;color:var(--text-secondary);font-size:14px;margin-bottom:16px;">
            比如"德国""美国""中东""东南亚"，可以写多个</p>
        <div class="onboarding-input-row">
            <input type="text" id="wizard-market-input" placeholder="例如：德国、美国、中东..."
                class="onboarding-text-input"
                onkeydown="if(event.key==='Enter')wizardNext()" autofocus />
        </div>
        <button class="btn btn-primary btn-lg" onclick="wizardNext()">下一步：找什么类型？ →</button>
        <div class="onboarding-skip" style="display:flex;justify-content:space-between;">
            <a onclick="wizardBack()">← 返回修改</a>
            <a onclick="wizardClose()">跳过向导</a>
        </div>
    </div>`;
}

function wizardRenderStep3() {
    return `<div class="onboarding-card" style="margin:0 auto;max-width:580px;">
        <div class="onboarding-step-indicator">
            <span class="onb-step done">✓ 卖什么</span><span class="onb-step-arrow">→</span>
            <span class="onb-step done">✓ 卖到哪</span><span class="onb-step-arrow">→</span>
            <span class="onb-step active">● 找谁</span>
        </div>
        <h2 class="onboarding-title" style="font-size:20px;">想找什么类型的客户？</h2>
        <div class="wizard-choice-row">
            <button class="wizard-choice-btn" onclick="wizardSelectType('distributor',this)">
                <span class="wc-icon">📦</span>
                <div class="wc-text">
                    <div class="wc-title">批发商 / 分销商</div>
                    <div class="wc-desc">大量采购再分销到本地市场</div>
                </div>
            </button>
            <button class="wizard-choice-btn" onclick="wizardSelectType('oem',this)">
                <span class="wc-icon">🏭</span>
                <div class="wc-text">
                    <div class="wc-title">品牌商 / OEM 工厂</div>
                    <div class="wc-desc">贴牌生产，长期大单</div>
                </div>
            </button>
            <button class="wizard-choice-btn" onclick="wizardSelectType('retailer',this)">
                <span class="wc-icon">🏪</span>
                <div class="wc-text">
                    <div class="wc-title">零售商 / 连锁店</div>
                    <div class="wc-desc">小批量多频次采购</div>
                </div>
            </button>
            <button class="wizard-choice-btn" onclick="wizardSelectType('any',this)">
                <span class="wc-icon">🌍</span>
                <div class="wc-text">
                    <div class="wc-title">都行，帮我一起找</div>
                    <div class="wc-desc">让 AI 自动判断最合适的类型</div>
                </div>
            </button>
        </div>
        <button class="btn btn-primary btn-lg wizard-launch-btn" id="wizard-launch-btn" disabled
            onclick="wizardLaunch()">🚀 开始找客户！</button>
        <div class="onboarding-skip" style="display:flex;justify-content:space-between;">
            <a onclick="wizardBack()">← 返回修改</a>
            <a onclick="wizardClose()">跳过向导</a>
        </div>
    </div>`;
}

function wizardNext() {
    if (_wizardStep === 1) {
        var inp = document.getElementById('wizard-product-input');
        _wizardAnswers.product = (inp?.value || '').trim();
        if (!_wizardAnswers.product) { toast(t('toast.wizard_product')); return; }
        _wizardStep = 2;
        updateWizardCard(wizardRenderStep2());
        setTimeout(function() { var el = document.getElementById('wizard-market-input'); if (el) el.focus(); }, 200);
    } else if (_wizardStep === 2) {
        var inp2 = document.getElementById('wizard-market-input');
        _wizardAnswers.market = (inp2?.value || '').trim();
        if (!_wizardAnswers.market) { toast(t('toast.wizard_market')); return; }
        _wizardStep = 3;
        updateWizardCard(wizardRenderStep3());
    }
}

function wizardBack() {
    if (_wizardStep === 2) {
        _wizardStep = 1;
        updateWizardCard(wizardRenderStep1());
        setTimeout(function() { var el = document.getElementById('wizard-product-input'); if (el) { el.value = _wizardAnswers.product; el.focus(); } }, 200);
    } else if (_wizardStep === 3) {
        _wizardStep = 2;
        updateWizardCard(wizardRenderStep2());
        setTimeout(function() { var el = document.getElementById('wizard-market-input'); if (el) { el.value = _wizardAnswers.market; el.focus(); } }, 200);
    }
}

function wizardSelectType(type, btn) {
    _wizardAnswers.customerType = type;
    document.querySelectorAll('.wizard-choice-btn').forEach(function(b) { b.classList.remove('selected'); });
    btn.classList.add('selected');
    var launch = document.getElementById('wizard-launch-btn');
    if (launch) { launch.disabled = false; launch.style.opacity = '1'; }
}

function updateWizardCard(html) {
    var card = document.getElementById('wizard-card');
    if (!card) return;
    var inner = card.querySelector('.onboarding-card');
    if (inner) inner.outerHTML = html;
    else card.innerHTML = html;
}

function wizardClose() {
    _wizardStep = 0; _wizardAnswers = { product: '', market: '', customerType: '' };
    var card = document.getElementById('wizard-card'); if (card) card.remove();
    var empty = document.getElementById('chat-empty'); if (empty) empty.style.display = '';
}

async function wizardLaunch() {
    var a = _wizardAnswers;
    var typeNames = { distributor: '批发商/分销商', oem: '品牌商/OEM工厂', retailer: '零售商/连锁店', any: '所有类型' };
    var typeName = typeNames[a.customerType] || a.customerType;
    var promptText = '帮我找客户。产品=' + a.product + '，市场=' + a.market + '，客户类型=' + typeName;

    _wizardStep = 4;
    updateWizardCard(`<div class="onboarding-card" style="margin:0 auto;max-width:580px;text-align:center;">
        <div class="onboarding-icon">🔍</div>
        <h2 class="onboarding-title">正在帮你找客户...</h2>
        <p style="text-align:center;color:var(--text-secondary);font-size:14px;margin-bottom:8px;">
            自动多通道搜索中，请稍候</p>
        <div style="width:60px;height:4px;background:var(--border-light);border-radius:2px;margin:0 auto;overflow:hidden;">
            <div style="width:30%;height:100%;background:var(--primary);border-radius:2px;animation:wizardProgress 1.5s ease-in-out infinite;"></div>
        </div>
    </div>`);

    // 发送消息到聊天区
    var textarea = document.getElementById('msg-input');
    if (textarea) {
        textarea.value = promptText;
        // 移除向导卡片，用正常聊天流展示
        setTimeout(function() { wizardClose(); }, 500);
        setTimeout(function() { sendMsg(); }, 600);
    }
}

// 向导进度条动画
(function() {
    var style = document.createElement('style');
    style.textContent = '@keyframes wizardProgress { 0% { transform: translateX(-100%); } 100% { transform: translateX(400%); } }';
    document.head.appendChild(style);
})();
function saveState() {
    if (currentCompanyId) sessionStorage.setItem('trade_cid', currentCompanyId);
    else sessionStorage.removeItem('trade_cid');
    sessionStorage.setItem('trade_view', currentView);
    if (currentChatContext) sessionStorage.setItem('trade_ctx', currentChatContext);
}
function loadSavedCid() { return parseInt(sessionStorage.getItem('trade_cid') || '0') || null; }

