// ═════════════════════ MAILBOXES VIEW（全局 IMAP 绑定，不按公司隔离）═════════════════════

/** 预设 IMAP 服务器（与 trade/mailbox.py PRESETS 一致） */
const MAILBOX_PRESETS = {
    '126': { host: 'imap.126.com', port: 993 },
    '163': { host: 'imap.163.com', port: 993 },
    'qq': { host: 'imap.qq.com', port: 993 },
    'gmail': { host: 'imap.gmail.com', port: 993 },
    custom: { host: '', port: 993 },
};

/** 连接指南正文（附录全文；仅按设计稿改三处措辞） */
const MAILBOX_GUIDE = {
    intro: `
        <p><b>先在邮箱那边开好，再回这里填。</b></p>
        <p>trade 只读你的收件箱，不删信、不标已读、不发信。连接分两步：第一步去你的邮箱网页版开 IMAP、
        拿一个 16 位授权码；第二步回这里填表、点「测试连接」。</p>
        <p><b>最重要的一句话：密码栏填的是「授权码」，不是你的邮箱登录密码。</b>
        四家邮箱都不许用登录密码连 trade 这类软件，填登录密码一定连不上（报错 535）。
        授权码是邮箱专门给 trade 发的另一把钥匙，只显示一次，拿到就立即复制保存；丢了可以重新生成一个，旧的作废。</p>`,
    '126': `
        <ol style="margin:4px 0;padding-left:20px;">
            <li>电脑浏览器打开 mail.126.com，用邮箱账号和密码登录（这是唯一一次用登录密码的地方）。</li>
            <li>点页面上方的「设置」，在下拉菜单里选「POP3/SMTP/IMAP」。</li>
            <li>找到「IMAP/SMTP 服务」，点右边的「开启」。如果页面推荐你装「邮箱大师」，不用装，点「继续开启」。</li>
            <li>按提示验证身份：用绑定手机扫码发一条短信，或点「手动发送短信」，发完回页面点「我已发送」。</li>
            <li>页面会出现一串 16 位字母和数字，这就是授权码。<b>立即复制，存到一个你找得到的地方</b>
            （记事本、备忘录都行）。关掉页面就再也看不到了，丢了只能在同个页面点「新增授权密码」重新生成一个。</li>
            <li>回 trade 填表：邮箱类型选 126，邮箱地址填完整地址（比如 name@126.com），密码栏粘贴刚才的授权码。
            服务器和端口不用动（已经给你填好了：imap.126.com，端口 993）。</li>
            <li>点「测试连接」。测通后点「绑定」。点「手动拉取」开始收信。</li>
        </ol>`,
    '163': `
        <p>和 126 一模一样，只换地址：</p>
        <ol style="margin:4px 0;padding-left:20px;">
            <li>打开 mail.163.com 登录。</li>
            <li>「设置」→「POP3/SMTP/IMAP」。</li>
            <li>开启「IMAP/SMTP 服务」，短信验证。</li>
            <li>复制 16 位授权码，立即保存。</li>
            <li>回 trade：类型选 163，地址填 name@163.com，密码栏粘贴授权码。服务器 imap.163.com，端口 993。</li>
            <li>点「测试连接」。测通后点「绑定」。</li>
        </ol>`,
    qq: `
        <ol style="margin:4px 0;padding-left:20px;">
            <li>电脑浏览器打开 mail.qq.com 登录。</li>
            <li>点页面顶部的「设置」，选「帐户」标签页（如果你的页面是新版，在「设置」→「账号与安全」→「安全设置」里找）。</li>
            <li>往下翻，找到「POP3/IMAP/SMTP/Exchange/CardDAV/CalDAV 服务」这一栏。</li>
            <li>点「IMAP/SMTP 服务」后面的「开启」，按提示用绑定手机发短信验证，点「我已发送」。</li>
            <li>点「生成授权码」，按提示再验证一次（短信或 QQ 手机版确认）。页面会弹出 16 位授权码，
            <b>立即复制保存</b>，关掉就看不到了。</li>
            <li>回 trade：类型选 QQ，地址填完整 QQ 邮箱，密码栏粘贴授权码。服务器 imap.qq.com，端口 993。</li>
            <li>注意两点：QQ 开完 IMAP 有时要等几小时才生效，刚开完连不上先等一等再试；
            以后你改了 QQ 密码，授权码会失效，要重新生成一个，到 trade 列表点「更新授权码」。</li>
        </ol>`,
    gmail: `
        <p>Gmail 要多做一步：先开「两步验证」，才能生成「应用专用密码」（这就是 Gmail 的授权码）。</p>
        <ol style="margin:4px 0;padding-left:20px;">
            <li>打开 mail.google.com 登录，点右上角齿轮「设置」→「查看所有设置」。</li>
            <li>点「转发和 POP/IMAP」标签页，在「IMAP 访问」一栏选「启用 IMAP」，拉到页面最下面点「保存修改」。</li>
            <li>点右上角头像 →「管理您的 Google 账号」→ 左边选「安全性」。</li>
            <li>找到「两步验证」，点进去按提示开启（要收一条手机短信验证码，或用验证器 App）。</li>
            <li>开完两步验证，回到「安全性」页面，找到「应用专用密码」（找不到就直接打开
            myaccount.google.com/apppasswords）。如果没开两步验证，这个入口是不显示的。</li>
            <li>在应用名那栏填 trade（随便写个你认得出的名字就行），点「创建」。页面会显示 16 位密码，
            分成 4 组、每组 4 个字母，<b>立即复制保存</b>，关掉就看不到了。</li>
            <li>回 trade：类型选 Gmail，地址填完整 Gmail 地址，密码栏粘贴这 16 位密码。
            <b>粘贴后把中间的空格去掉</b>（比如 abcd efgh ijkl mnop 要变成 abcdefghijklmnop）。
            服务器 imap.gmail.com，端口 993。</li>
            <li>点「测试连接」。测通后点「绑定」。</li>
        </ol>`,
    custom: `
        <ol style="margin:4px 0;padding-left:20px;">
            <li>向邮箱服务商或 IT 索取 <b>IMAP 服务器地址、端口</b>，并在网页版开启 IMAP（若提供）。</li>
            <li>确认登录名：多数邮箱与邮箱地址相同；少数企业邮需单独用户名，可在下方展开填写。</li>
            <li>密码栏填 <b>IMAP 授权码或应用专用密码</b>，不是网页登录密码（除非服务商明确说明相同）。</li>
            <li>填齐后点「测试连接」。测通后点「绑定」。</li>
        </ol>`,
    faq: `
        <ul style="margin:4px 0;padding-left:20px;">
            <li><b>报「密码不对 / 535」</b>：十有八九是把登录密码填进去了。回去确认密码栏里是 16 位授权码
            （Gmail 是应用专用密码），不是登录密码。</li>
            <li><b>授权码前后多了空格</b>：粘贴后检查一下，前后不要有空格；Gmail 的密码要去掉中间的空格。</li>
            <li><b>提示「IMAP 没开」</b>：回去确认第一步里的 IMAP 服务已经是「已开启」状态。</li>
            <li><b>QQ 刚开完 IMAP 就连</b>：QQ 有时要等几小时才生效，等一等再点测试连接。</li>
            <li><b>授权码找不到了</b>：授权码只显示一次，关掉页面就没有了。回邮箱设置里重新生成一个
            （126/163 点「新增授权密码」，QQ 点「生成授权码」，Gmail 重新创建一个应用专用密码），
            再到 trade 列表点「更新授权码」。</li>
            <li><b>改了邮箱密码或 QQ 密码</b>：旧授权码会失效，重新生成一个，trade 列表点「更新授权码」。</li>
            <li><b>授权码不小心给别人看到了</b>：立即回邮箱设置里删掉它、重新生成一个；trade 里还是安全的
            （授权码只存在你自己的电脑上，不上传、不进导出包）。</li>
        </ul>`,
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
                        <select id="mb-preset" data-onchange="onMailboxPresetChange">
                            <option value="126">126</option>
                            <option value="163">163</option>
                            <option value="qq">QQ</option>
                            <option value="gmail">Gmail</option>
                            <option value="custom">${esc(t('mailbox.preset_custom'))}</option>
                        </select>
                    </label>
                    <label style="display:flex;flex-direction:column;gap:4px;font-size:12px;">
                        ${esc(t('mailbox.email'))}
                        <input type="email" id="mb-email" placeholder="name@example.com" data-oninput="onMailboxFormDirty">
                    </label>
                    <label style="display:flex;flex-direction:column;gap:4px;font-size:12px;">
                        ${esc(t('mailbox.secret'))}
                        <input type="password" id="mb-secret" autocomplete="off" placeholder="${esc(t('mailbox.secret_ph'))}" data-oninput="onMailboxFormDirty">
                    </label>
                    <label style="display:flex;flex-direction:column;gap:4px;font-size:12px;">
                        ${esc(t('mailbox.display_name'))}
                        <input type="text" id="mb-display" placeholder="${esc(t('mailbox.display_name_ph'))}">
                    </label>
                    <label style="display:flex;flex-direction:column;gap:4px;font-size:12px;">
                        ${esc(t('mailbox.host'))}
                        <input type="text" id="mb-host" data-oninput="onMailboxFormDirty">
                    </label>
                    <label style="display:flex;flex-direction:column;gap:4px;font-size:12px;">
                        ${esc(t('mailbox.port'))}
                        <input type="number" id="mb-port" min="1" max="65535" data-oninput="onMailboxFormDirty">
                    </label>
                    <label id="mb-username-wrap" style="display:none;flex-direction:column;gap:4px;font-size:12px;">
                        ${esc(t('mailbox.username'))}
                        <input type="text" id="mb-username" placeholder="${esc(t('mailbox.username_ph'))}" data-oninput="onMailboxFormDirty">
                    </label>
                </div>
                <div style="display:flex;flex-wrap:wrap;gap:10px;margin-top:14px;align-items:center;">
                    <button type="button" class="btn" id="mb-test-btn" data-act="testMailboxConnection">${esc(t('mailbox.test'))}</button>
                    <button type="button" class="btn btn-primary" id="mb-bind-btn" disabled data-act="bindMailbox">${esc(t('mailbox.bind'))}</button>
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

/** 指南手风琴 HTML（共用开头 + 四提供商 + 自定义 + FAQ 七条） */
function _renderMailboxGuideAccordion() {
    const sections = [
        { key: '126', title: '126 邮箱' },
        { key: '163', title: '163 邮箱' },
        { key: 'qq', title: 'QQ 邮箱' },
        { key: 'gmail', title: 'Gmail' },
        { key: 'custom', title: t('mailbox.preset_custom') },
    ];
    const intro = '<div class="mailbox-guide-intro" style="padding:12px 14px;margin-bottom:10px;border:1px solid var(--border);border-radius:var(--radius-sm);font-size:13px;line-height:1.75;color:var(--text-secondary);background:var(--bg-muted);">'
        + MAILBOX_GUIDE.intro + '</div>';
    const cards = sections.map(function (s) {
        return '<details class="mailbox-guide-details" data-mailbox-guide="' + esc(s.key) + '" style="margin-bottom:8px;border:1px solid var(--border);border-radius:var(--radius-sm);overflow:hidden;">'
            + '<summary style="cursor:pointer;padding:10px 14px;font-weight:600;font-size:13px;background:var(--bg-muted);user-select:none;">' + esc(s.title) + '</summary>'
            + '<div style="padding:12px 16px;font-size:13px;line-height:1.75;color:var(--text-secondary);">' + MAILBOX_GUIDE[s.key] + '</div>'
            + '</details>';
    }).join('');
    return intro + cards
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
    var restore = (status && typeof TradeWait !== 'undefined')
        ? TradeWait.inline(status, {en: 'TESTING', zh: '测试连接中'}) : null;
    if (!restore && status) status.textContent = t('mailbox.testing');
    _mailboxTestPassed = false;
    if ($('mb-bind-btn')) $('mb-bind-btn').disabled = true;
    let res = null;
    try {
        res = await api('POST', '/api/trade/mailboxes/test', payload);
    } finally {
        if (restore) restore();
        if (btn) btn.disabled = false;
    }
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
    const bindBtn = $('mb-bind-btn');
    var restore = (bindBtn && typeof TradeWait !== 'undefined')
        ? TradeWait.inline(bindBtn, {en: 'BINDING', zh: '绑定中'}) : null;
    let res = null;
    try {
        res = await api('POST', '/api/trade/mailboxes', payload);
    } finally {
        if (restore) restore();
    }
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
        + '<button type="button" class="btn-xs"' + (pulling ? ' disabled' : '') + ' data-act="pullMailbox" data-arg="' + m.id + '">' + pullLabel + '</button> '
        + '<button type="button" class="btn-xs" data-act="updateMailboxSecret" data-arg="' + m.id + '">' + esc(t('mailbox.update_secret')) + '</button> '
        + '<button type="button" class="btn-xs" style="color:var(--accent-red);" data-act="unbindMailbox" data-arg="' + m.id + '">' + esc(t('mailbox.unbind')) + '</button>'
        + '</td>'
        + '</tr>';
}

/** 单箱手动拉取 */
async function pullMailbox(id) {
    _mailboxPullingId = id;
    await loadMailboxesList();
    let pullingBtn = null;
    document.querySelectorAll('#mailbox-list-wrap button').forEach(function (b) {
        if (b.getAttribute('onclick') === 'pullMailbox(' + id + ')') pullingBtn = b;
    });
    var restore = (pullingBtn && typeof TradeWait !== 'undefined')
        ? TradeWait.inline(pullingBtn, {en: 'PULLING', zh: '拉取中'}) : null;
    let res = null;
    try {
        res = await api('POST', '/api/trade/mailboxes/' + id + '/pull');
    } finally {
        if (restore) restore();
    }
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