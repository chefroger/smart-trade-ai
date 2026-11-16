// ═════════════════════ MAILBOXES VIEW（全局 IMAP 绑定，不按公司隔离）═════════════════════

/** 预设 IMAP 服务器（与 trade/mailbox.py PRESETS 一致） */
const MAILBOX_PRESETS = {
    '126': { host: 'imap.126.com', port: 993 },
    '163': { host: 'imap.163.com', port: 993 },
    'qq': { host: 'imap.qq.com', port: 993 },
    'gmail': { host: 'imap.gmail.com', port: 993 },
    custom: { host: '', port: 993 },
};

/** 连接指南正文（中文；英文界面仍显示本指南 + 顶部英文提示） */
const MAILBOX_GUIDE = {
    '126': `
        <ol style="margin:4px 0;padding-left:20px;">
            <li>浏览器打开 <b>mail.126.com</b> 并登录你的 126 邮箱。</li>
            <li>进入 <b>设置 → POP3/SMTP/IMAP</b>，开启 <b>IMAP/SMTP 服务</b>。</li>
            <li>按页面提示 <b>新增授权密码</b>（一般为 16 位字符，不是网页登录密码）。</li>
            <li>在下方表单选择「126」，填写邮箱地址与授权码，服务器一般已预填 <code>imap.126.com:993</code>。</li>
            <li>点 <b>「测试连接」</b>，测通后点 <b>「绑定」</b>。</li>
            <li>授权码过期或更换：在下方已绑定列表点 <b>「更新授权码」</b>，无需先解绑。</li>
        </ol>`,
    '163': `
        <ol style="margin:4px 0;padding-left:20px;">
            <li>浏览器打开 <b>mail.163.com</b> 并登录你的 163 邮箱。</li>
            <li>进入 <b>设置 → POP3/SMTP/IMAP</b>，开启 <b>IMAP/SMTP 服务</b>。</li>
            <li>按页面提示 <b>新增客户端授权密码</b>（16 位授权码，不是登录密码）。</li>
            <li>在下方表单选择「163」，填写邮箱与授权码，服务器一般为 <code>imap.163.com:993</code>。</li>
            <li>点 <b>「测试连接」</b>，测通后点 <b>「绑定」</b>。</li>
            <li>更换授权码：在列表点 <b>「更新授权码」</b>。</li>
        </ol>`,
    qq: `
        <ol style="margin:4px 0;padding-left:20px;">
            <li>浏览器打开 <b>mail.qq.com</b> 或 QQ 邮箱 App，登录 QQ 邮箱。</li>
            <li>进入 <b>设置 → 账户</b>，找到 <b>POP3/IMAP/SMTP</b> 并 <b>开启 IMAP</b>。</li>
            <li>按提示用密保手机 <b>生成授权码</b>（用作下方「密码/授权码」栏，不是 QQ 密码）。</li>
            <li>在下方表单选择「QQ 邮箱」，填 QQ 邮箱地址与授权码。</li>
            <li>点 <b>「测试连接」</b>，测通后点 <b>「绑定」</b>。</li>
            <li>授权码变更：在已绑定列表点 <b>「更新授权码」</b>，不要反复删绑重绑。</li>
        </ol>`,
    gmail: `
        <ol style="margin:4px 0;padding-left:20px;">
            <li>登录 Google 账号，确认已开启 <b>两步验证</b>（部分账号生成应用密码的前置条件）。</li>
            <li>在 Google 账号安全设置中 <b>生成应用专用密码</b>，用于 IMAP 登录。</li>
            <li>在 Gmail 网页版 <b>设置 → 转发和 POP/IMAP</b> 中 <b>启用 IMAP</b>。</li>
            <li>在下方表单选择「Gmail」，填完整 Gmail 地址与应用专用密码；服务器 <code>imap.gmail.com:993</code>。</li>
            <li>点 <b>「测试连接」</b>，测通后点 <b>「绑定」</b>。</li>
            <li>更换密码：在列表点 <b>「更新授权码」</b>。</li>
        </ol>`,
    custom: `
        <ol style="margin:4px 0;padding-left:20px;">
            <li>向邮箱服务商或 IT 索取 <b>IMAP 服务器地址、端口</b>，并在网页版开启 IMAP（若提供）。</li>
            <li>确认登录名：多数邮箱与邮箱地址相同；少数企业邮需单独用户名，可在下方展开填写。</li>
            <li>密码栏填 <b>IMAP 授权码或应用专用密码</b>，不是网页登录密码（除非服务商明确说明相同）。</li>
            <li>填齐后点 <b>「测试连接」</b>，测通后点 <b>「绑定」</b>。</li>
        </ol>`,
    faq: `
        <p><b>连不上 / 535 错误？</b> 密码栏要填 16 位授权码或应用专用密码，不是网页登录密码。</p>
        <p><b>提示该邮箱已经绑定？</b> 在同一台 Trade 上先对旧绑定点「解绑」，再重新绑定；不要重复绑同一地址。</p>
        <p><b>邮件什么时候进客户卡片？</b> 绑定后需在列表点 <b>「拉取」</b>（或客户卡片里刷新）；Trade 不会后台定时拉信，只读收件箱、不发信。</p>`,
};

let _mailboxList = [];
let _mailboxTestPassed = false;
let _mailboxPullingId = null;

/**
 * 渲染邮箱面板：连接指南 → 绑定表单 → 已绑列表。
 */
async function renderMailboxesViewInto(container) {
    const guideHtml = _renderMailboxGuideAccordion();
    const enTip = currentLang === 'en'
        ? '<p class="mailbox-guide-en-tip" style="font-size:12px;color:var(--text-muted);margin:0 0 12px 0;border:1px dashed var(--border);padding:8px 12px;border-radius:var(--radius-sm);">' + esc(t('mailbox.guide_en_tip')) + '</p>'
        : '';
    container.innerHTML = `
        <div class="panel-topbar">
            <h2>${typeof iconHtml === 'function' ? iconHtml('mail', 20) : ''} ${esc(t('mailbox.title'))}</h2>
        </div>
        <div class="panel-body" style="overflow-y:auto;padding:16px 20px;">`
        + enTip + `
            <div class="mailbox-guide-block" style="margin-bottom:20px;">
                <div style="font-size:13px;font-weight:600;color:var(--text-secondary);margin-bottom:8px;">${esc(t('mailbox.guide_title'))}</div>`
        + guideHtml + `
            </div>
            <div style="font-size:13px;font-weight:600;color:var(--text-secondary);margin:16px 0 10px 0;">${esc(t('mailbox.form_title'))}</div>
            <div class="mailbox-bind-card" style="border:1px solid var(--border);border-radius:var(--radius);padding:16px 18px;margin-bottom:24px;background:var(--bg);">
                <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px 16px;">
                    <label style="display:flex;flex-direction:column;gap:4px;font-size:12px;">
                        ${esc(t('mailbox.preset'))}
                        <select id="mb-preset" onchange="onMailboxPresetChange()">
                            <option value="126">126</option>
                            <option value="163">163</option>
                            <option value="qq">QQ</option>
                            <option value="gmail">Gmail</option>
                            <option value="custom">${esc(t('mailbox.preset_custom'))}</option>
                        </select>
                    </label>
                    <label style="display:flex;flex-direction:column;gap:4px;font-size:12px;">
                        ${esc(t('mailbox.email'))}
                        <input type="email" id="mb-email" placeholder="name@example.com" oninput="onMailboxFormDirty()">
                    </label>
                    <label style="display:flex;flex-direction:column;gap:4px;font-size:12px;">
                        ${esc(t('mailbox.secret'))}
                        <input type="password" id="mb-secret" autocomplete="off" placeholder="${esc(t('mailbox.secret_ph'))}" oninput="onMailboxFormDirty()">
                    </label>
                    <label style="display:flex;flex-direction:column;gap:4px;font-size:12px;">
                        ${esc(t('mailbox.display_name'))}
                        <input type="text" id="mb-display" placeholder="${esc(t('mailbox.display_name_ph'))}">
                    </label>
                    <label style="display:flex;flex-direction:column;gap:4px;font-size:12px;">
                        ${esc(t('mailbox.host'))}
                        <input type="text" id="mb-host" oninput="onMailboxFormDirty()">
                    </label>
                    <label style="display:flex;flex-direction:column;gap:4px;font-size:12px;">
                        ${esc(t('mailbox.port'))}
                        <input type="number" id="mb-port" min="1" max="65535" oninput="onMailboxFormDirty()">
                    </label>
                    <label id="mb-username-wrap" style="display:none;flex-direction:column;gap:4px;font-size:12px;">
                        ${esc(t('mailbox.username'))}
                        <input type="text" id="mb-username" placeholder="${esc(t('mailbox.username_ph'))}" oninput="onMailboxFormDirty()">
                    </label>
                </div>
                <div style="display:flex;flex-wrap:wrap;gap:10px;margin-top:14px;align-items:center;">
                    <button type="button" class="btn" id="mb-test-btn" onclick="testMailboxConnection()">${esc(t('mailbox.test'))}</button>
                    <button type="button" class="btn btn-primary" id="mb-bind-btn" disabled onclick="bindMailbox()">${esc(t('mailbox.bind'))}</button>
                    <span id="mb-test-status" style="font-size:12px;color:var(--text-muted);"></span>
                </div>
            </div>
            <div style="font-size:13px;font-weight:600;color:var(--text-secondary);margin-bottom:10px;">${esc(t('mailbox.list_title'))}</div>
            <div id="mailbox-list-wrap"></div>
            <div id="mailbox-list-empty" class="empty-state hidden" style="padding:24px 12px;">
                <div class="empty-icon">${typeof iconHtml === 'function' ? iconHtml('mail', 32) : '📬'}</div>
                <h2 style="font-size:15px;margin:8px 0;">${esc(t('mailbox.empty_title'))}</h2>
                <p style="font-size:13px;color:var(--text-muted);">${esc(t('mailbox.empty_hint'))}</p>
            </div>
        </div>`;
    onMailboxPresetChange(false);
    await loadMailboxesList();
}

/** 指南手风琴 HTML（四提供商 + 自定义 + FAQ） */
function _renderMailboxGuideAccordion() {
    const sections = [
        { key: '126', title: '126 邮箱' },
        { key: '163', title: '163 邮箱' },
        { key: 'qq', title: 'QQ 邮箱' },
        { key: 'gmail', title: 'Gmail' },
        { key: 'custom', title: t('mailbox.preset_custom') },
    ];
    const cards = sections.map(function (s) {
        return '<details class="mailbox-guide-details" data-mailbox-guide="' + esc(s.key) + '" style="margin-bottom:8px;border:1px solid var(--border);border-radius:var(--radius-sm);overflow:hidden;">'
            + '<summary style="cursor:pointer;padding:10px 14px;font-weight:600;font-size:13px;background:var(--bg-muted);user-select:none;">' + esc(s.title) + '</summary>'
            + '<div style="padding:12px 16px;font-size:13px;line-height:1.75;color:var(--text-secondary);">' + MAILBOX_GUIDE[s.key] + '</div>'
            + '</details>';
    }).join('');
    return cards
        + '<details style="margin-top:8px;border:1px solid var(--border);border-radius:var(--radius-sm);">'
        + '<summary style="cursor:pointer;padding:10px 14px;font-weight:600;font-size:13px;background:var(--bg-muted);">' + esc(t('mailbox.faq')) + '</summary>'
        + '<div style="padding:12px 16px;font-size:13px;line-height:1.75;color:var(--text-secondary);">' + MAILBOX_GUIDE.faq + '</div>'
        + '</details>';
}

/** 按预设展开对应指南段 */
function _expandMailboxGuide(preset) {
    document.querySelectorAll('[data-mailbox-guide]').forEach(function (el) {
        el.open = el.getAttribute('data-mailbox-guide') === preset;
    });
}

/** 预设切换：预填 host/port，custom 显示用户名 */
function onMailboxPresetChange(resetTest) {
    if (resetTest !== false) onMailboxFormDirty();
    const preset = ($('mb-preset') && $('mb-preset').value) || '126';
    const p = MAILBOX_PRESETS[preset] || MAILBOX_PRESETS.custom;
    const hostEl = $('mb-host');
    const portEl = $('mb-port');
    const userWrap = $('mb-username-wrap');
    if (hostEl) hostEl.value = p.host || '';
    if (portEl) portEl.value = String(p.port || 993);
    // custom 才展示独立用户名栏
    if (userWrap) userWrap.style.display = preset === 'custom' ? 'flex' : 'none';
    _expandMailboxGuide(preset);
}

/** 表单改动后需重新测试才能绑定 */
function onMailboxFormDirty() {
    _mailboxTestPassed = false;
    const bindBtn = $('mb-bind-btn');
    const status = $('mb-test-status');
    if (bindBtn) bindBtn.disabled = true;
    if (status) status.textContent = '';
}

/** 读取绑定表单 payload */
function _mailboxFormPayload() {
    const preset = $('mb-preset').value;
    const email = ($('mb-email').value || '').trim();
    const secret = $('mb-secret').value || '';
    const host = ($('mb-host').value || '').trim();
    const port = parseInt($('mb-port').value, 10) || 993;
    const payload = {
        preset: preset,
        email_address: email,
        secret: secret,
        host: host || null,
        port: port,
        display_name: ($('mb-display').value || '').trim(),
    };
    // 非 custom：username 由后端默认邮箱；custom 可填
    if (preset === 'custom') {
        const un = ($('mb-username') && $('mb-username').value || '').trim();
        payload.username = un || email;
    }
    return payload;
}

/** POST /mailboxes/test */
async function testMailboxConnection() {
    const payload = _mailboxFormPayload();
    if (!payload.email_address || !payload.secret) {
        toast(t('mailbox.need_email_secret'));
        return;
    }
    const btn = $('mb-test-btn');
    const status = $('mb-test-status');
    if (btn) btn.disabled = true;
    if (status) status.textContent = t('mailbox.testing');
    _mailboxTestPassed = false;
    if ($('mb-bind-btn')) $('mb-bind-btn').disabled = true;
    const res = await api('POST', '/api/trade/mailboxes/test', payload);
    if (btn) btn.disabled = false;
    if (res && res.ok) {
        _mailboxTestPassed = true;
        if ($('mb-bind-btn')) $('mb-bind-btn').disabled = false;
        if (status) status.textContent = t('mailbox.test_ok');
        toast(t('mailbox.test_ok'));
    } else {
        if (status) status.textContent = t('mailbox.test_fail');
    }
}

/** POST /mailboxes 绑定 */
async function bindMailbox() {
    if (!_mailboxTestPassed) {
        toast(t('mailbox.test_first'));
        return;
    }
    const payload = _mailboxFormPayload();
    const res = await api('POST', '/api/trade/mailboxes', payload);
    if (!res) return;
    toast(t('mailbox.bind_ok'));
    $('mb-secret').value = '';
    onMailboxFormDirty();
    await loadMailboxesList();
}

/** GET /mailboxes 列表 */
async function loadMailboxesList() {
    _mailboxList = await api('GET', '/api/trade/mailboxes') || [];
    const wrap = $('mailbox-list-wrap');
    const empty = $('mailbox-list-empty');
    if (!wrap) return;
    if (!_mailboxList.length) {
        wrap.innerHTML = '';
        if (empty) empty.classList.remove('hidden');
        return;
    }
    if (empty) empty.classList.add('hidden');
    const rows = _mailboxList.map(_renderMailboxRow).join('');
    wrap.innerHTML = '<table class="data-table" id="mailbox-table">'
        + '<thead><tr>'
        + '<th>' + esc(t('mailbox.col_email')) + '</th>'
        + '<th>' + esc(t('mailbox.col_status')) + '</th>'
        + '<th style="width:220px;">' + esc(t('mailbox.col_actions')) + '</th>'
        + '</tr></thead>'
        + '<tbody>' + rows + '</tbody>'
        + '</table>';
}

function _renderMailboxRow(m) {
    const label = m.display_name ? esc(m.display_name) + ' · ' : '';
    const sync = m.last_error
        ? '<span style="color:var(--accent-red);font-size:11px;">' + esc(m.last_error) + '</span>'
        : (m.last_sync_at
            ? '<span style="font-size:11px;color:var(--text-muted);">' + esc(t('mailbox.synced_at')) + ' ' + esc(m.last_sync_at) + '</span>'
            : '<span style="font-size:11px;color:var(--text-muted);">' + esc(t('mailbox.never_synced')) + '</span>');
    const count = typeof m.email_count === 'number' ? m.email_count : 0;
    const pulling = _mailboxPullingId === m.id;
    const pullLabel = pulling ? esc(t('mailbox.pulling')) : esc(t('mailbox.pull'));
    return '<tr>'
        + '<td>'
        + '<div style="font-weight:600;font-size:13px;">' + label + esc(m.email_address || '') + '</div>'
        + '<div style="font-size:11px;color:var(--text-muted);">' + esc(m.preset || '') + ' · ' + esc(m.host || '') + ':' + esc(String(m.port || '')) + '</div>'
        + '<div style="font-size:11px;margin-top:2px;">' + esc(t('mailbox.email_count', { n: count })) + '</div>'
        + '</td>'
        + '<td>' + sync + '</td>'
        + '<td style="white-space:nowrap;">'
        + '<button type="button" class="btn-xs"' + (pulling ? ' disabled' : '') + ' onclick="pullMailbox(' + m.id + ')">' + pullLabel + '</button> '
        + '<button type="button" class="btn-xs" onclick="updateMailboxSecret(' + m.id + ')">' + esc(t('mailbox.update_secret')) + '</button> '
        + '<button type="button" class="btn-xs" style="color:var(--accent-red);" onclick="unbindMailbox(' + m.id + ')">' + esc(t('mailbox.unbind')) + '</button>'
        + '</td>'
        + '</tr>';
}

/** 单箱手动拉取 */
async function pullMailbox(id) {
    _mailboxPullingId = id;
    await loadMailboxesList();
    const res = await api('POST', '/api/trade/mailboxes/' + id + '/pull');
    _mailboxPullingId = null;
    if (res) {
        toast(t('mailbox.pull_done', { n: res.pulled != null ? res.pulled : 0 }));
    }
    await loadMailboxesList();
}

/** 更新授权码 */
async function updateMailboxSecret(id) {
    const secret = prompt(t('mailbox.secret_prompt'));
    if (!secret) return;
    const res = await api('PUT', '/api/trade/mailboxes/' + id + '/secret', { secret: secret });
    if (res && res.ok) toast(t('mailbox.secret_updated'));
    await loadMailboxesList();
}

/** 解绑 */
async function unbindMailbox(id) {
    if (!confirm(t('mailbox.unbind_confirm'))) return;
    const res = await api('DELETE', '/api/trade/mailboxes/' + id);
    if (res && res.ok) {
        toast(t('mailbox.unbind_ok'));
        await loadMailboxesList();
    }
}