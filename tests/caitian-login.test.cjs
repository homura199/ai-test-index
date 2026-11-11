const assert = require('node:assert/strict');
const { test } = require('node:test');
const fs = require('node:fs');
const vm = require('node:vm');
const { createSession } = require('../caitian-ai/caitian-session.js');
const html = fs.readFileSync(require('node:path').join(__dirname, '../caitian-ai/index.html'), 'utf8');
const script = [...html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)].at(-1)[1];

function page({ denied = false, sdkFailure = false, questionnaire = null } = {}) {
    const stats = { mic: 0, stopped: 0, auth: 0, sdk: 0, shown: 0, alerts: [] };
    const elements = {};
    for (const id of ['className', 'studentId', 'sessionNum', 'input-group', 'loader-wrapper',
        'login-box', 'coze-container', 'loading-text', 'button']) {
        const classes = new Set();
        elements[id] = { value: '', style: {}, disabled: false,
            classList: { add: (...names) => names.forEach(n => classes.add(n)),
                remove: (...names) => names.forEach(n => classes.delete(n)), contains: n => classes.has(n) },
            replaceChildren() { this.cleared = true; } };
    }
    elements.className.value = '8'; elements.studentId.value = '55'; elements.sessionNum.value = '1';
    const window = { CAITIAN_CONFIG: { profileAuthUrl: 'https://profiles.example/auth', profileBotId: '7706348792413011968' },
        CaitianSession: { createSession: (config, identity, language) => createSession(config, identity, language,
            async () => { stats.auth++; return { ok: true, json: async () => ({ data: {
                token: 'test-token', user_id_hash: 'safe', profile_ref: 'x'.repeat(43), bot_id: config.profileBotId
            } }) }; }) },
        CozeWebSDK: { WebChatClient: class {
            constructor(options) { stats.sdk++; stats.options = options; if (sdkFailure) throw new Error('SDK unavailable'); }
            showChatBot() { stats.shown++; }
            sendMessage() { throw new Error('Automatic sends are forbidden'); }
        } }
    };
    if (questionnaire) {
        window.CAITIAN_CONFIG.questionnaireEnabled = true;
        window.CaitianQuestionnaire = { open: async input => { stats.survey = input.userId; return questionnaire(); } };
    }
    const context = vm.createContext({ window, navigator: { mediaDevices: { getUserMedia: async () => {
        stats.mic++; if (denied) throw new Error('denied');
        return { getTracks: () => [{ stop() { stats.stopped++; } }] };
    } } }, document: { getElementById: id => elements[id], querySelector: () => elements.button,
        addEventListener() {} }, alert: message => stats.alerts.push(message),
        setTimeout: callback => { callback(); return 1; }, console,
        localStorage: { clear() { throw new Error('Must not erase other pages'); } },
        sessionStorage: { clear() { throw new Error('Must not erase other pages'); } }
    });
    vm.runInContext(script, context);
    return { context, stats, elements, window };
}

test('simulated student login opens the configured bot once without automatic messages', async () => {
    const p = page();
    await Promise.all([p.context.startChat(), p.context.startChat()]);
    assert.equal(p.stats.mic, 1); assert.equal(p.stats.stopped, 1);
    assert.equal(p.stats.auth, 1); assert.equal(p.stats.sdk, 1); assert.equal(p.stats.shown, 1);
    assert.equal(p.stats.options.config.bot_id, '7706348792413011968');
    assert.equal(p.stats.options.userInfo.nickname, '学生55');
    assert.equal(p.elements['coze-container'].style.display, 'block');
    assert.equal(p.stats.alerts.length, 0);
    let prevented = false;
    p.window.onbeforeunload({ preventDefault() { prevented = true; } });
    assert.equal(prevented, true);
});

test('microphone denial prevents authentication and permits a retry', async () => {
    const p = page({ denied: true });
    await p.context.startChat(); await p.context.startChat();
    assert.equal(p.stats.mic, 2); assert.equal(p.stats.auth, 0);
    assert.equal(p.elements.button.disabled, false);
    assert.equal(p.window.onbeforeunload({ preventDefault() { throw new Error('Not chatting'); } }), undefined);
});

test('SDK initialization failure restores login and does not strand the loading screen', async () => {
    const p = page({ sdkFailure: true });
    await p.context.startChat();
    assert.equal(p.elements['login-box'].style.display, '');
    assert.equal(p.elements['loader-wrapper'].style.display, 'none');
    assert.equal(p.elements['coze-container'].style.display, 'none');
    assert.equal(p.elements['login-box'].classList.contains('card-exit'), false);
    assert.equal(p.elements.button.disabled, false);
    await p.context.startChat();
    assert.equal(p.stats.auth, 2);
});

test('questionnaire completion gates microphone and chat startup', async () => {
    const cancelled = page({ questionnaire: () => false });
    await cancelled.context.startChat();
    assert.equal(cancelled.stats.survey, '8班_55_1');
    assert.equal(cancelled.stats.mic, 0); assert.equal(cancelled.stats.auth, 0);
    const completed = page({ questionnaire: () => true });
    await completed.context.startChat();
    assert.equal(completed.stats.mic, 1); assert.equal(completed.stats.auth, 1);
});
