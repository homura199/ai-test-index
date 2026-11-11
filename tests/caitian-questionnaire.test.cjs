const assert = require('node:assert/strict');
const { test } = require('node:test');
const { questions, validate, createApi } = require('../caitian-ai/caitian-questionnaire.js');
const { createSession } = require('../caitian-ai/caitian-session.js');
const complete = () => ({ q3: 'B,C', q4: 'C', q5: 'C', q6: '', q7: 'C', q8: 'C', q9: 'B', q10: 'C', q11: '我不知道', q12: '' });

test('questionnaire preserves special Q9 and does not contain scoring rules', () => {
    assert.equal(questions.find(q => q.id === 'q9').options[1], 'AI 学习时看的这类画特别多，所以画出来就像');
    assert.equal(questions.length, 10);
    assert.deepEqual(validate(complete()), {});
    assert.ok(questions.every(q => !('score' in q) && !('points' in q)));
});

test('required questions, unknown responses and exclusive none option', () => {
    for (const key of ['q3', 'q4', 'q5', 'q7', 'q8', 'q9', 'q10', 'q11']) assert.ok(validate({ ...complete(), [key]: '' })[key]);
    for (const q3 of ['A,B', 'B,B', 'F']) assert.ok(validate({ ...complete(), q3 }).q3);
    assert.deepEqual(validate({ ...complete(), q3: 'A' }), {});
    assert.ok(validate({ ...complete(), q11: 'x'.repeat(4001) }).q11);
});

test('submission sends answers without grade variables or admin credentials', async () => {
    const calls = [];
    const api = createApi('https://profiles.example/root/auth', async (url, options) => {
        calls.push({ url, options });
        return { ok: true, json: async () => ({ data: { status: calls.length === 1 ? 'missing' : 'ready' } }) };
    });
    assert.equal(await api.status('8班_55_1'), 'missing');
    assert.equal(await api.submit('8班_55_1', complete()), 'ready');
    assert.equal(calls[1].url, 'https://profiles.example/root/questionnaire/submit');
    assert.deepEqual(JSON.parse(calls[1].options.body), { user_id: '8班_55_1', answers: complete() });
    assert.deepEqual(calls[1].options.headers, { 'Content-Type': 'application/json' });
});

test('existing autonomous bot mode sends no hidden grades through SDK parameters', async () => {
    const config = { profileAuthUrl: 'https://profiles.example/auth', profileBotId: '7706348792413011968', profileTransport: 'variables' };
    const options = await createSession(config, '8班_55_1', 'zh', async () => ({ ok: true, json: async () => ({ data: {
        token: 'fresh', user_id_hash: 'safe', profile_ref: 'a'.repeat(43), bot_id: config.profileBotId
    } }) })).options({}, '学生55');
    assert.deepEqual(options.config.botInfo.parameters, { language: 'zh' });
});
