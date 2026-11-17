// ═════════════════════ INIT ═════════════════════
document.addEventListener('DOMContentLoaded', async () => {
    // 初始化语言
    initLang();
    // S-01 特效 / 图标 / 顶栏时钟（不依赖公司状态，尽早挂上）
    if (typeof initFxBackground === 'function') initFxBackground();

    // Hermes 版本过旧 → 只显示升级面板，不再走公司/聊天初始化：那些功能此刻全都
    // 依赖 Hermes，走下去只会让用户在坏掉的界面上乱点
    if (await checkHermesCompatOrShowPanel()) return;

    // 检测是否刚完成系统升级（页面 reload 后显示 toast）
    try {
        if (sessionStorage.getItem('_trade_upgrade_done')) {
            sessionStorage.removeItem('_trade_upgrade_done');
            setTimeout(() => toast('✅ 系统更新完成！'), 500);
        }
    } catch(_) {}

    // 许可证状态检查（等结果再恢复视图：避免试用用户先把付费页渲染出来）。
    // loadLicenseStatus 内部有 2 秒超时，到点走 fail-open，不会无限拖住初始化。
    await loadLicenseStatus();

    try {
        await loadCompanies();
    } catch(e) {
        console.error('Init loadCompanies failed:', e);
    }
    const savedCid = loadSavedCid();
    if (savedCid && companies.find(c => c.id === savedCid)) {
        currentCompanyId = savedCid;
    } else if (companies.length === 1) {
        currentCompanyId = companies[0].id;
    }

    // 检测重启前保存的浏览状态（避免 hard reload 丢失阅读位置）
    const reloadState = _restoreReloadState();

    if (currentCompanyId) {
        saveState();
        loadUsageToday();
        const sel = $('company-select');
        if (sel) sel.value = currentCompanyId;
        // 首个公司 + 引导未完成 → 显示新手引导
        if (companies.length === 1 && !isOnboardingCompleted()) {
            showOnboardingGuide();
            startCronPolling();
            startVersionCheck();
            return;
        }
        // 恢复之前的视图或默认打开今日简报；付费视图对试用用户回落到简报
        let restoreView = reloadState?.view || 'chat';
        let restoreCtx = reloadState?.chatCtx || 'daily';
        let restoreName = reloadState?.chatName || '今日简报';
        if (_isPaidDestination(restoreView, restoreCtx) && !_licenseGateAllowsPaid()) {
            restoreView = 'chat';
            restoreCtx = 'daily';
            restoreName = '今日简报';
        }
        navToView(restoreView, restoreCtx, restoreName);
        // 恢复滚动位置（等 DOM 渲染完成后）
        if (reloadState?.scrollY > 0) {
            setTimeout(() => { window.scrollTo({ top: reloadState.scrollY, behavior: 'instant' }); }, 200);
        }
        startCronPolling();
        startVersionCheck();
    } else {
        renderNoCompanyPage();
    }
});

// 页面关闭时清理轮询
window.addEventListener('beforeunload', () => { stopCronPolling(); stopVersionCheck(); });

// 许可证是整机一份：license.json 被删除/替换后，回到页面时重新判定。
// 后端会按 trial/expired 返回，前端据此立即隐藏付费入口，不需要刷新页面。
window.addEventListener('focus', () => { loadLicenseStatus(); });
document.addEventListener('visibilitychange', () => {
    if (!document.hidden) loadLicenseStatus();
});

function renderNoCompanyPage() {
    // 清除视图缓存
    for (const key in viewCache) {
        viewCache[key].element.remove();
        delete viewCache[key];
    }
    // 「创建公司」始终保留（试用用户也要能建第一家公司）；导入是付费能力
    const importBtn = _licenseGateAllowsPaid()
        ? '<button onclick="showImportCompanyDialog()">📦 导入已有公司数据</button>'
        : '';
    $('main-content').innerHTML = '<div class="empty-state"><div class="empty-icon">🏢</div>'
        + '<h2>请先选择或创建公司</h2><p>Trade AI 为多公司隔离架构</p>'
        + '<div style="display:flex;gap:10px;justify-content:center;flex-wrap:wrap;">'
        + '<button onclick="showAddCompanyModal()">➕ 创建公司</button>'
        + importBtn
        + '</div></div>';
}
