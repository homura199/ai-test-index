const assert = require('node:assert/strict');
const { test } = require('node:test');
const { createSession } = require('../caitian-ai/caitian-session.js');
const config = { profileAuthUrl: 'https://profiles.example/auth', profileBotId: '7706348792413011968',
    legacyAuthUrl: 'https://legacy.example', legacyBotId: '7703416522781720586' };
const profileRef = 'a'.repeat(43);
function ok(data) { return { ok: true, json: async () => ({ data }) }; }

test('student login passes only opaque reference; renewal fetches a new token', async () => {
    const requests = [];
    const fetcher = async (url, options) => {
        requests.push({ url, body: JSON.parse(options.body) });
        return ok({ token: `token-${requests.length}`, user_id_hash: 'safe', profile_ref: profileRef, bot_id: config.profileBotId });
    };
    const session = createSession(config, '8班_55_1', 'zh', fetcher);
    const options = await session.options({}, '同学55');
    assert.equal(options.config.bot_id, config.profileBotId);
    assert.deepEqual(options.config.botInfo.parameters, { language: 'zh', profile_ref: profileRef });
    assert.equal(options.auth.token, 'token-1');
    const refreshed = await Promise.all([options.auth.onRefreshToken(), options.auth.onRefreshToken()]);
    assert.deepEqual(refreshed, ['token-2', 'token-2']);
    assert.equal(requests.length, 2);
    assert.deepEqual(requests[1].body, { user_id: '8班_55_1', profile_ref: profileRef });
    assert.equal(await options.auth.onRefreshToken(), 'token-3');
    assert.equal(options.ui.chatBot.defaultInputType, 'text');
});

test('legacy mode still works until cloud integration is activated', async () => {
    const options = await createSession({ ...config, profileAuthUrl: '' }, '1班_1_1', 'en', async url => {
        assert.equal(url, 'https://legacy.example/');
        return ok({ token: 'legacy', user_id_hash: 'safe' });
    }).options({}, 'Student1');
    assert.equal(options.config.bot_id, config.legacyBotId);
    assert.deepEqual(options.config.botInfo.parameters, { language: 'en' });
});

test('missing profile stops login without falling back to a default grade', async () => {
    const session = createSession(config, '1班_1_1', 'zh', async () => ({ ok: false,
        json: async () => ({ error: { code: 'PROFILE_NOT_READY' } }) }));
    await assert.rejects(session.options({}, '同学'), { code: 'PROFILE_NOT_READY' });
});

test('refresh rejects changed identity, changed reference and a wrong bot', async () => {
    for (const changed of [{ user_id_hash: 'different' }, { profile_ref: 'b'.repeat(43) }, { bot_id: 'wrong' }]) {
        let count = 0;
        const session = createSession(config, '1班_1_1', 'zh', async () => ok({
            token: 'token', user_id_hash: 'safe', profile_ref: profileRef, bot_id: config.profileBotId,
            ...(count++ ? changed : {})
        }));
        const options = await session.options({}, '同学');
        await assert.rejects(options.auth.onRefreshToken());
    }
});

test('malformed credentials and other lessons are rejected', async () => {
    assert.throws(() => createSession(config, '1班_1_2', 'zh'));
    assert.throws(() => createSession({ ...config, profileAuthUrl: 'http://unsafe.example' }, '1班_1_1', 'zh'));
    await assert.rejects(createSession(config, '1班_1_1', 'zh', async () => ok({})).options({}, '同学'));
});
