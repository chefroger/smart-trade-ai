// ═════════════════════ STATE ═════════════════════
let companies = [];
let currentCompanyId = null;
let currentView = 'chat';       // chat | customers | tasks | directory | history
let currentChatContext = 'daily'; // daily | lead | platform | social | linkedin | customs | docs | docgen | osint
let currentChatName = '今日简报';
let currentLibraryId = null;
let currentCustomerId = null;
let _currentConvId = null;       // 当前 AI 回复的 conversation_id，用于评分
let editingCustomerData = null; // for customer detail panel
let _onboardingStep = 1;          // 1 = welcome card, 2 = OSINT input + results
let _onboardingInputText = '';    // user-entered company name/website
let currentLang = 'zh';           // zh | en

