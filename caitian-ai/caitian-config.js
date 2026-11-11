// Public configuration only. Never place API keys, grades or questionnaires here.
window.CAITIAN_CONFIG = Object.freeze({
    questionnaireEnabled: true,
    // Existing autonomous bot: initialize its user variables on the server.
    profileTransport: 'variables',
    // Activate only after SCF, private storage and both Coze agents pass the live checks.
    profileAuthUrl: '',
    profileBotId: '7706348792413011968',
    legacyAuthUrl: 'https://1308037263-lxn5m4tut3.ap-guangzhou.tencentscf.com',
    legacyBotId: '7703416522781720586'
});
