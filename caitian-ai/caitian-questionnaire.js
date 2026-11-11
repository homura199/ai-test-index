(function (root) {
    'use strict';
    const questions = [
        { id: 'q3', number: 3, title: '你用过下面哪些 AI 画图工具？', type: 'checkbox', options: ['没用过', '豆包 / 即梦', '通义万相', 'Midjourney', '其他'] },
        { id: 'q4', number: 4, title: '你用 AI 画图的次数大概是？', options: ['没用过', '试过 1—2 次', '偶尔用', '经常用'] },
        { id: 'q5', number: 5, title: '小明让 AI 画一只“穿宇航服的猫”，这只猫在现实中从来不存在。你觉得 AI 是怎么画出这张图的？', options: ['AI 脑子里有想法，自己构思出来的', 'AI 在网上搜到最像的图，改一改就给你', 'AI 以前看过很多猫和宇航服的照片，记住了它们的样子，再拼出一个新的', '我也说不清'] },
        { id: 'q6', number: 6, title: '请用一句话说说你选第 5 题这个选项的理由。', type: 'text', optional: true },
        { id: 'q7', number: 7, title: '如果 AI 从来没有见过“戴帽子的企鹅”，它还能画出来吗？', options: ['能，它很聪明，能自己想象出来', '不能，网上没有这张图，它找不到', '能，它学过企鹅和帽子长什么样，可以把两者组合起来', '不知道'] },
        { id: 'q8', number: 8, title: '你觉得 AI 学画画，更像下面哪一种？', options: ['像人一样有天赋，练着练着就会了', '像一个超大的图片仓库，要什么就去里面拿', '像一个学生，看了很多范画，总结出规律，自己画', '不知道'] },
        { id: 'q9', number: 9, title: 'AI 画了一张画，和你以前见过的一张几乎一样。最可能的原因是？', options: ['AI 记性特别好，把看过的画都记住了', 'AI 学习时看的这类画特别多，所以画出来就像', 'AI 故意模仿那张画', '说不清'] },
        { id: 'q10', number: 10, title: 'AI 画得好看，最主要的原因是？', options: ['它有艺术天赋', '它数据库里的图多', '它看过很多画，学到了画得好的规律', '说不清'] },
        { id: 'q11', number: 11, title: '用你自己的话说说：AI 画的画，是从哪里来的？', type: 'text', hint: '想到什么写什么，写两三句也可以。不知道也可以如实写“我不知道”。' },
        { id: 'q12', number: 12, title: '如果让你教 AI 画鸡蛋，你会怎么做？', type: 'text', optional: true }
    ];

    function validate(answers) {
        const errors = {};
        for (const question of questions) {
            const value = answers[question.id] || '';
            if (typeof value !== 'string' || value.length > 4000) errors[question.id] = '回答过长，请控制在 4000 字以内。';
            else if (!question.optional && !value.trim()) errors[question.id] = '请按你的真实想法回答这一题。';
            else if (question.type === 'checkbox' && (!/^[A-E](,[A-E])*$/.test(value) || (value.includes('A') && value !== 'A') || new Set(value.split(',')).size !== value.split(',').length)) errors[question.id] = '“没用过”不能和其他工具同时选择。';
            else if (question.options && question.type !== 'checkbox' && !/^[A-D]$/.test(value)) errors[question.id] = '请选择一个选项。';
        }
        return errors;
    }

    function createApi(authUrl, fetcher = root.fetch.bind(root)) {
        const url = new URL(authUrl);
        if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash || !url.pathname.endsWith('/auth')) throw new Error('Invalid classroom endpoint');
        const base = url.href.slice(0, -5);
        async function request(path, body, timeout = 30000) {
            const controller = new AbortController();
            const timer = setTimeout(() => controller.abort(), timeout);
            try {
                const response = await fetcher(base + path, { method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body), signal: controller.signal, cache: 'no-store', credentials: 'omit', redirect: 'error' });
                const result = await response.json();
                if (!response.ok) { const error = new Error('Questionnaire request failed'); error.code = result.error?.code; throw error; }
                if (!['missing', 'ready', 'processing', 'needs_review'].includes(result.data?.status)) throw new Error('Invalid questionnaire response');
                return result.data.status;
            } finally { clearTimeout(timer); }
        }
        return { status: userId => request('/questionnaire/status', { user_id: userId }),
            submit: (userId, answers) => request('/questionnaire/submit', { user_id: userId, answers }, 110000) };
    }

    async function open({ userId, authUrl, loginBox, onDirty = () => {} }) {
        const document = root.document;
        const api = authUrl ? createApi(authUrl) : null;
        let busy = false, pending = false, ready = false;
        const panel = document.createElement('section');
        panel.id = 'questionnaire-panel'; panel.className = 'questionnaire-panel';
        panel.setAttribute('aria-labelledby', 'questionnaire-title');
        const header = document.createElement('header');
        header.innerHTML = '<p class="questionnaire-eyebrow">第一课时 · 课前准备</p><h2 id="questionnaire-title" tabindex="-1">课前小调查</h2>';
        const identity = document.createElement('p'); identity.className = 'questionnaire-identity';
        const [className, student] = userId.split('_');
        identity.textContent = `${className} · ${student} 号`;
        header.append(identity);
        const intro = document.createElement('p'); intro.className = 'questionnaire-intro';
        intro.textContent = '这不是考试，请按第一感觉作答，大约需要 5 分钟。回答会与班级和学号关联，用于安排本次学习，页面不展示分数或等级。';
        header.append(intro); panel.append(header);
        const status = document.createElement('p'); status.className = 'questionnaire-status';
        status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite'); panel.append(status);
        const form = document.createElement('form'); form.noValidate = true;
        const controls = {}, errors = {};
        for (const question of questions) {
            const field = document.createElement('fieldset');
            const legend = document.createElement('legend'); legend.textContent = `${question.number}. ${question.title}${question.optional ? '（选做）' : ''}`;
            field.append(legend); controls[question.id] = [];
            if (question.hint) { const hint = document.createElement('p'); hint.className = 'questionnaire-hint'; hint.textContent = question.hint; field.append(hint); }
            if (question.options) {
                question.options.forEach((option, index) => {
                    const label = document.createElement('label'); label.className = 'questionnaire-option';
                    const input = document.createElement('input'); input.type = question.type || 'radio';
                    input.name = question.id; input.value = 'ABCDE'[index]; input.setAttribute('aria-describedby', `error-${question.id}`);
                    if (question.id === 'q3') input.addEventListener('change', () => {
                        if (input.checked) controls.q3.forEach(other => { if (other !== input && (input.value === 'A' || other.value === 'A')) other.checked = false; });
                    });
                    const span = document.createElement('span'); span.textContent = `${input.value}. ${option}`;
                    label.append(input, span); field.append(label); controls[question.id].push(input);
                });
            } else {
                const input = document.createElement('textarea'); input.name = question.id; input.rows = question.id === 'q11' ? 4 : 2;
                input.maxLength = 4000; input.setAttribute('aria-label', question.title); input.setAttribute('aria-describedby', `error-${question.id}`);
                field.append(input); controls[question.id].push(input);
            }
            const error = document.createElement('p'); error.id = `error-${question.id}`; error.className = 'questionnaire-error';
            errors[question.id] = error; field.append(error); form.append(field);
        }
        const footer = document.createElement('footer'); footer.className = 'questionnaire-actions';
        const back = document.createElement('button'); back.type = 'button'; back.className = 'questionnaire-secondary'; back.textContent = '返回选择身份';
        const submit = document.createElement('button'); submit.type = 'submit'; submit.textContent = '提交问卷并进入课堂';
        footer.append(back, submit); form.append(footer); panel.append(form);
        document.body.append(panel); loginBox.style.display = 'none';
        panel.querySelector('h2').focus();
        const read = () => Object.fromEntries(questions.map(q => [q.id, q.options ? controls[q.id].filter(c => c.checked).map(c => c.value).join(',') : controls[q.id][0].value.trim()]));
        let resolveDone;
        const done = new Promise(resolve => { resolveDone = resolve; });
        const finish = result => { onDirty(false); panel.remove(); loginBox.style.display = ''; resolveDone(result); };
        const lock = value => { busy = value; for (const list of Object.values(controls)) list.forEach(c => { c.disabled = value || pending || ready; }); back.disabled = value; submit.disabled = value || !api; };
        const applyStatus = value => {
            pending = value === 'processing' || value === 'needs_review'; ready = value === 'ready';
            if (value !== 'missing') onDirty(false);
            status.textContent = ready ? '课前问卷已完成，可以进入课堂。' : value === 'processing' ? '问卷已收到，正在准备课堂，请稍后检查状态。' : value === 'needs_review' ? '问卷已收到，需要老师确认后才能进入课堂。' : '';
            submit.textContent = ready ? '进入课堂' : pending ? '检查准备状态' : '提交问卷并进入课堂';
            lock(false);
        };
        back.addEventListener('click', () => {
            if (busy) return;
            if (!pending && !ready && Object.values(read()).some(Boolean) && !root.confirm('返回会清除尚未提交的回答，确定返回吗？')) return;
            finish(false);
        });
        form.addEventListener('input', () => { if (!pending && !ready) onDirty(true); });
        form.addEventListener('change', () => { if (!pending && !ready) onDirty(true); });
        form.addEventListener('submit', async event => {
            event.preventDefault(); if (busy || !api) return;
            if (ready) { finish(true); return; }
            const answers = read();
            if (!pending) {
                const invalid = validate(answers);
                Object.keys(errors).forEach(id => { errors[id].textContent = invalid[id] || ''; controls[id].forEach(c => c.setAttribute('aria-invalid', invalid[id] ? 'true' : 'false')); });
                if (Object.keys(invalid).length) { controls[Object.keys(invalid)[0]][0].focus(); return; }
            }
            lock(true); status.textContent = pending ? '正在检查课堂准备状态…' : '正在提交，请保持页面打开…';
            try {
                const state = pending ? await api.status(userId) : await api.submit(userId, answers);
                applyStatus(state);
                if (state === 'ready') finish(true);
            } catch (_) {
                // A timeout may occur after the backend stored the survey. Check before retrying.
                try {
                    const state = await api.status(userId);
                    applyStatus(state);
                    if (state === 'ready') { finish(true); return; }
                    if (state !== 'missing') return;
                } catch (_) { /* Keep answers in this page so the student can retry. */ }
                status.textContent = '暂时无法确认提交结果，回答仍保留在当前页面，请稍后重试。';
            } finally { lock(false); }
        });
        if (!api) { status.textContent = '课堂暂未开放提交，请联系老师。'; lock(false); }
        else {
            lock(true); status.textContent = '正在检查课前资料…';
            try { applyStatus(await api.status(userId)); }
            catch (_) { status.textContent = '暂时无法检查课前资料。可以先填写，提交时会再次确认。'; lock(false); }
        }
        return done;
    }

    root.CaitianQuestionnaire = { questions, validate, createApi, open };
    if (typeof module === 'object' && module.exports) module.exports = root.CaitianQuestionnaire;
})(typeof window !== 'undefined' ? window : globalThis);
