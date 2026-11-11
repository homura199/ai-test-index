(function (root) {
    'use strict';

    function createSession(config, userId, language, fetcher = root.fetch.bind(root)) {
        if (!/^[1-8]班_([1-9]|[1-4][0-9]|5[0-5])_1$/.test(userId)) {
            throw new Error('Invalid classroom identity');
        }
        const profileMode = Boolean(config.profileAuthUrl);
        const endpoint = new URL(profileMode ? config.profileAuthUrl : config.legacyAuthUrl);
        if (endpoint.protocol !== 'https:' || endpoint.username || endpoint.password || endpoint.search || endpoint.hash) {
            throw new Error('Invalid authentication endpoint');
        }
        const botId = profileMode ? config.profileBotId : config.legacyBotId;
        let userHash, profileRef, refreshing;

        async function requestToken() {
            const controller = new AbortController();
            const timer = setTimeout(() => controller.abort(), 30000);
            try {
                const body = { user_id: userId };
                if (profileRef) body.profile_ref = profileRef;
                const response = await fetcher(endpoint.href, {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body), signal: controller.signal,
                    cache: 'no-store', credentials: 'omit', redirect: 'error'
                });
                const result = await response.json();
                if (!response.ok) {
                    const error = new Error('Classroom authentication failed');
                    error.code = result.error && result.error.code;
                    throw error;
                }
                const data = result.data;
                if (!data || typeof data.token !== 'string' || !data.token ||
                    typeof data.user_id_hash !== 'string' || !data.user_id_hash) {
                    throw new Error('Invalid authentication response');
                }
                if (userHash && data.user_id_hash !== userHash) throw new Error('Identity changed');
                if (profileMode) {
                    if (data.bot_id !== botId || !/^[A-Za-z0-9_-]{43}$/.test(data.profile_ref || '') ||
                        (profileRef && data.profile_ref !== profileRef)) {
                        throw new Error('Invalid profile session');
                    }
                    profileRef = data.profile_ref;
                }
                userHash = data.user_id_hash;
                return data.token;
            } finally {
                clearTimeout(timer);
            }
        }

        async function token() {
            // Collapse simultaneous SDK refresh requests without caching an expired token.
            if (!refreshing) refreshing = requestToken().finally(() => { refreshing = null; });
            return refreshing;
        }

        async function options(container, nickname) {
            const initialToken = await token();
            const parameters = { language };
            if (profileMode && config.profileTransport !== 'variables') parameters.profile_ref = profileRef;
            return {
                config: { type: 'bot', bot_id: botId, isIframe: false, botInfo: { parameters } },
                auth: { type: 'token', token: initialToken, onRefreshToken: token },
                userInfo: { id: userHash, nickname },
                ui: {
                    base: { layout: 'pc', zIndex: 1000 },
                    header: { isShow: false }, asstBtn: { isNeed: false },
                    chatBot: {
                        el: container, width: '100%', uploadable: false, isNeedAudio: true,
                        defaultInputType: 'text', isNeedAddNewConversation: true, isNeedQuote: true
                    }
                }
            };
        }
        return { options };
    }

    root.CaitianSession = { createSession };
    if (typeof module === 'object' && module.exports) module.exports = root.CaitianSession;
})(typeof window !== 'undefined' ? window : globalThis);
