/* AI大模型API网关 - 前端主逻辑 */
'use strict';

// ============================================================
// 工具函数
// ============================================================
const API = {
  base: '',
  token: () => localStorage.getItem('token'),
  async request(method, url, body) {
    const token = this.token();
    if (!token) { redirectLogin(); return; }
    const opts = {
      method,
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` }
    };
    if (body) opts.body = JSON.stringify(body);
    const resp = await fetch(this.base + url, opts);
    if (resp.status === 401) { redirectLogin(); return; }
    return resp;
  },
  get:    (url)       => API.request('GET',    url),
  post:   (url, body) => API.request('POST',   url, body),
  put:    (url, body) => API.request('PUT',    url, body),
  delete: (url)       => API.request('DELETE', url),
};

function redirectLogin() {
  localStorage.removeItem('token');
  window.location.href = '/static/login.html';
}

function logout() {
  if (confirm('确认退出登录？')) {
    localStorage.removeItem('token');
    redirectLogin();
  }
}

function toast(msg, type = 'info') {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.style.background = type === 'error' ? '#ef4444' : type === 'success' ? '#22c55e' : '#1a1a2e';
  el.classList.add('show');
  setTimeout(() => el.classList.remove('show'), 2500);
}

function fmt(dateStr) {
  if (!dateStr) return '-';
  const d = new Date(dateStr);
  const pad = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

function maskKey(key) {
  if (!key || key.length <= 8) return key;
  return key.slice(0,6) + '****' + key.slice(-4);
}

function confirm2(msg) {
  return window.confirm(msg);
}

// ============================================================
// 修改密码
// ============================================================
function openChangePasswordModal() {
  document.getElementById('oldPassword').value = '';
  document.getElementById('newPassword').value = '';
  document.getElementById('confirmPassword').value = '';
  document.getElementById('changePasswordModal').classList.add('show');
}

function closeChangePasswordModal() {
  document.getElementById('changePasswordModal').classList.remove('show');
}

async function doChangePassword() {
  const oldPwd = document.getElementById('oldPassword').value.trim();
  const newPwd = document.getElementById('newPassword').value.trim();
  const confirmPwd = document.getElementById('confirmPassword').value.trim();

  if (!oldPwd || !newPwd || !confirmPwd) {
    toast('请填写所有字段', 'error'); return;
  }
  if (newPwd.length < 6) {
    toast('新密码至少6个字符', 'error'); return;
  }
  if (newPwd !== confirmPwd) {
    toast('两次输入的新密码不一致', 'error'); return;
  }
  if (oldPwd === newPwd) {
    toast('新密码不能与原密码相同', 'error'); return;
  }

  const resp = await API.post('/api/admin/change-password', { old_password: oldPwd, new_password: newPwd });
  if (!resp) return;
  if (resp.ok) {
    toast('密码修改成功', 'success');
    closeChangePasswordModal();
  } else {
    try {
      const e = await resp.json();
      toast(e.detail || '修改失败', 'error');
    } catch {
      toast(`修改失败（${resp.status}）`, 'error');
    }
  }
}

// ============================================================
// 导航切换
// ============================================================
const PANEL_TITLES = {
  dashboard: '控制台', llm: '大模型配置', apikey: 'API密钥管理',
  sensitive: '敏感词管理', logs: '请求日志审计'
};

function switchPanel(panel, skipLoad) {
  document.querySelectorAll('.nav-item').forEach(i => i.classList.remove('active'));
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  const navItem = document.querySelector(`.nav-item[data-panel="${panel}"]`);
  if (navItem) navItem.classList.add('active');
  const panelEl = document.getElementById('panel-' + panel);
  if (panelEl) panelEl.classList.add('active');
  document.getElementById('topbarTitle').textContent = PANEL_TITLES[panel] || panel;
  localStorage.setItem('activePanel', panel);
  if (!skipLoad) onPanelChange(panel);
}

document.querySelectorAll('.nav-item').forEach(item => {
  item.addEventListener('click', () => {
    switchPanel(item.dataset.panel);
  });
});

function onPanelChange(panel) {
  if (panel === 'dashboard') loadDashboard();
  else if (panel === 'llm') loadLLMList();
  else if (panel === 'apikey') { loadLLMListForKey(); loadKeyList(); }
  else if (panel === 'sensitive') loadSensitiveWords();
  else if (panel === 'logs') { loadModelOptionsForLog(); loadLogs(); }
}

// ============================================================
// 初始化
// ============================================================
(async function init() {
  const token = localStorage.getItem('token');
  if (!token) { redirectLogin(); return; }

  // 显示用户名
  const username = localStorage.getItem('username') || 'admin';
  document.getElementById('sidebarUsername').textContent = username;

  // 恢复上次的面板，默认控制台
  const savedPanel = localStorage.getItem('activePanel') || 'dashboard';
  // 确保面板存在
  const validPanels = ['dashboard', 'llm', 'apikey', 'sensitive', 'logs'];
  const panel = validPanels.includes(savedPanel) ? savedPanel : 'dashboard';

  // 先切换面板（设置 display），等浏览器完成布局后再加载数据
  // 这样 canvas 等元素的 offsetWidth 才正确
  switchPanel(panel, true);  // skipLoad=true，不立即加载

  // 等下一帧，确保 DOM 布局完成
  requestAnimationFrame(() => {
    onPanelChange(panel);
  });
})();

// ============================================================
// 控制台（Dashboard）
// ============================================================
async function loadDashboard() {
  try {
    const resp = await API.get('/api/dashboard/stats?days=7');
    if (!resp) return;
    if (!resp.ok) { toast('加载统计数据失败', 'error'); return; }
    const data = await resp.json();

    document.getElementById('stat-today').textContent = data.today_requests ?? 0;
    document.getElementById('stat-keys').textContent   = data.total_api_keys ?? 0;
    document.getElementById('stat-success').textContent = (data.success_rate ?? 0) + '%';
    document.getElementById('stat-sensitive').textContent = data.sensitive_triggers ?? 0;

    // Token统计
    const inTokens = data.total_input_tokens ?? 0;
    const outTokens = data.total_output_tokens ?? 0;
    const totalTokens = inTokens + outTokens;
    const totalReqs = data.today_requests ?? 0;
    document.getElementById('stat-input-tokens').textContent = formatNumber(inTokens);
    document.getElementById('stat-output-tokens').textContent = formatNumber(outTokens);
    document.getElementById('stat-total-tokens').textContent = formatNumber(totalTokens);
    document.getElementById('stat-avg-tokens').textContent = totalReqs > 0 ? formatNumber(Math.round(totalTokens / totalReqs)) : '-';

    // 趋势图
    renderTrendChart(data.daily_trend || []);
    // 模型排行
    renderModelRank(data.top_models || []);
    // Token趋势
    renderTokenChart(data.daily_tokens || []);
    // 状态分布饼图
    renderStatusChart(data.status_dist || []);
    // 敏感词排行
    renderSensitiveTop(data.sensitive_top || []);
    // Token用量 Top5 密钥
    renderTokenTopKeys(data.token_top_keys || []);
    // 全局Token用量
    renderGlobalTokenStats(data.global_total_tokens || 0, data.keys_with_token_limit || 0);

  } catch(e) {
    console.error(e);
  }
}

function formatNumber(n) {
  if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M';
  if (n >= 1000) return (n / 1000).toFixed(1) + 'K';
  return String(n);
}

// --- ECharts 实例缓存 ---
const echartsInstances = {};
function getECharts(id) {
  const dom = document.getElementById(id);
  if (!dom) return null;
  if (!echartsInstances[id]) {
    echartsInstances[id] = echarts.init(dom);
  }
  return echartsInstances[id];
}

function renderTrendChart(trend) {
  const chart = getECharts('trendChart');
  if (!chart) return;
  const dates = trend.map(d => d.date || '');
  const values = trend.map(d => d.requests || 0);
  chart.setOption({
    tooltip: { trigger: 'axis', backgroundColor: '#1a1a2e', borderColor: '#333', textStyle: { color: '#fff', fontSize: 13 } },
    grid: { top: 20, right: 20, bottom: 30, left: 50 },
    xAxis: { type: 'category', data: dates, axisLine: { lineStyle: { color: '#ddd' } }, axisLabel: { color: '#888', fontSize: 11 }, axisTick: { show: false } },
    yAxis: { type: 'value', splitLine: { lineStyle: { color: '#f0f0f0' } }, axisLabel: { color: '#888', fontSize: 11 }, axisLine: { show: false }, axisTick: { show: false } },
    series: [{
      type: 'line', data: values, smooth: true,
      lineStyle: { color: '#667eea', width: 2.5 },
      itemStyle: { color: '#667eea' },
      areaStyle: {
        color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: 'rgba(102,126,234,0.25)' },
          { offset: 1, color: 'rgba(102,126,234,0.02)' }
        ])
      },
      symbol: 'circle', symbolSize: 6
    }]
  });
  window.addEventListener('resize', () => chart.resize());
}

function renderModelRank(models) {
  const el = document.getElementById('modelRankList');
  if (!models.length) {
    el.innerHTML = '<div class="empty-state"><div class="empty-icon">📭</div><p>暂无数据</p></div>';
    return;
  }
  const maxCount = Math.max(...models.map(m => m.request_count), 1);
  el.innerHTML = models.map(m => `
    <div class="model-list-item">
      <span style="font-size:13px;color:#555;width:80px;flex-shrink:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${m.llm_name}">${m.llm_name}</span>
      <div class="model-bar-wrap"><div class="model-bar" style="width:${Math.round(m.request_count/maxCount*100)}%"></div></div>
      <span style="font-size:12px;color:#888;width:40px;text-align:right">${m.request_count}</span>
    </div>`).join('');
}

// --- Token趋势图（双折线：输入/输出） ECharts ---
function renderTokenChart(tokens) {
  const chart = getECharts('tokenChart');
  if (!chart) return;
  const dates = tokens.map(d => d.date || '');
  const inputVals = tokens.map(d => d.input || 0);
  const outputVals = tokens.map(d => d.output || 0);
  chart.setOption({
    tooltip: { trigger: 'axis', backgroundColor: '#1a1a2e', borderColor: '#333', textStyle: { color: '#fff', fontSize: 13 } },
    legend: { data: ['输入Token', '输出Token'], right: 0, top: 0, textStyle: { color: '#666', fontSize: 12 } },
    grid: { top: 36, right: 20, bottom: 30, left: 55 },
    xAxis: { type: 'category', data: dates, axisLine: { lineStyle: { color: '#ddd' } }, axisLabel: { color: '#888', fontSize: 11 }, axisTick: { show: false } },
    yAxis: { type: 'value', splitLine: { lineStyle: { color: '#f0f0f0' } }, axisLabel: { color: '#888', fontSize: 11, formatter: v => v >= 1000 ? (v/1000)+'K' : v }, axisLine: { show: false }, axisTick: { show: false } },
    series: [
      {
        name: '输入Token', type: 'line', data: inputVals, smooth: true,
        lineStyle: { color: '#667eea', width: 2 },
        itemStyle: { color: '#667eea' },
        areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [{ offset: 0, color: 'rgba(102,126,234,0.15)' }, { offset: 1, color: 'rgba(102,126,234,0)' }]) },
        symbol: 'circle', symbolSize: 5
      },
      {
        name: '输出Token', type: 'line', data: outputVals, smooth: true,
        lineStyle: { color: '#f093fb', width: 2 },
        itemStyle: { color: '#f093fb' },
        areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [{ offset: 0, color: 'rgba(240,147,251,0.15)' }, { offset: 1, color: 'rgba(240,147,251,0)' }]) },
        symbol: 'circle', symbolSize: 5
      }
    ]
  });
  window.addEventListener('resize', () => chart.resize());
}

// --- 状态分布饼图 ECharts ---
function renderStatusChart(statusList) {
  const chart = getECharts('statusChart');
  if (!chart) return;
  const colorMap = { success: '#22c55e', failed: '#ef4444', blocked: '#f59e0b' };
  const nameMap = { success: '成功', failed: '失败', blocked: '拦截' };
  const total = statusList.reduce((s, d) => s + d.cnt, 0);
  const data = statusList.map(d => ({
    name: nameMap[d.status] || d.status,
    value: d.cnt,
    itemStyle: { color: colorMap[d.status] || '#999' }
  }));
  chart.setOption({
    tooltip: { trigger: 'item', backgroundColor: '#1a1a2e', borderColor: '#333', textStyle: { color: '#fff', fontSize: 13 }, formatter: '{b}: {c} ({d}%)' },
    legend: { bottom: 0, textStyle: { color: '#666', fontSize: 12 } },
    series: [{
      type: 'pie', radius: ['40%', '65%'], center: ['50%', '45%'],
      avoidLabelOverlap: true,
      label: { show: true, formatter: '{d}%', fontSize: 12, color: '#555' },
      labelLine: { length: 10, length2: 8 },
      emphasis: {
        label: { show: true, fontSize: 14, fontWeight: 'bold' },
        itemStyle: { shadowBlur: 10, shadowOffsetX: 0, shadowColor: 'rgba(0,0,0,0.15)' }
      },
      data: data.length ? data : [{ name: '暂无数据', value: 0, itemStyle: { color: '#eee' } }],
      animationType: 'scale',
      animationEasing: 'elasticOut'
    }],
    graphic: total > 0 ? [{
      type: 'text', left: 'center', top: '38%',
      style: { text: String(total), fontSize: 22, fontWeight: 'bold', fill: '#333', textAlign: 'center' }
    }, {
      type: 'text', left: 'center', top: '50%',
      style: { text: '总请求', fontSize: 11, fill: '#aaa', textAlign: 'center' }
    }] : []
  });
  window.addEventListener('resize', () => chart.resize());
}

// --- 敏感词触发排行 ---
// 敏感词类型中文映射
const SENSITIVE_TYPE_NAMES = {
  id_card: '身份证', phone_number: '手机号', bank_card: '银行卡',
  email: '邮箱', id_photo: '身份证照片', violence: '暴力',
  pornography: '色情', terrorism: '恐怖', fraud: '诈骗',
  drugs: '毒品', gambling: '赌博', political: '政治',
  general: '通用', personal_info: '个人信息',
  sql_injection: 'SQL注入', xss: 'XSS攻击',
  path_traversal: '路径遍历', credential_leak: '凭证泄露',
  password_leak: '密码泄露', api_key_leak: 'API密钥泄露',
  ip_address: 'IP地址', url: '网址',
  wechat: '微信号', qq: 'QQ号',
  vehicle_plate: '车牌号', vin: '车辆VIN码',
  postal_code: '邮政编码', passport: '护照',
  medical_record: '病历号', flight: '航班号',
  train: '火车车次', express: '快递单号',
  credit_code: '统一社会信用代码', mac_address: 'MAC地址',
};

function getSensitiveTypeName(type) {
  return SENSITIVE_TYPE_NAMES[type] || type;
}

function renderSensitiveTop(list) {
  const el = document.getElementById('sensitiveTopList');
  if (!list.length) {
    el.innerHTML = '<div class="empty-state"><p>暂无触发</p></div>';
    return;
  }
  const maxCount = Math.max(...list.map(d => d.cnt), 1);
  el.innerHTML = list.map((d, i) => {
    const typeName = getSensitiveTypeName(d.type);
    const barPct = Math.round(d.cnt / maxCount * 100);
    const colors = ['#ef4444', '#f59e0b', '#3b82f6', '#8b5cf6', '#22c55e'];
    return `
    <div class="model-list-item">
      <span style="font-size:11px;color:${colors[i]||'#888'};font-weight:700;width:18px;flex-shrink:0">${i+1}</span>
      <span style="font-size:12px;color:#555;width:80px;flex-shrink:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${escHtml(typeName)}">${escHtml(typeName)}</span>
      <div class="model-bar-wrap"><div class="model-bar" style="width:${barPct}%;background:${colors[i]||'#888'}"></div></div>
      <span style="font-size:12px;color:#888;width:36px;text-align:right">${d.cnt}</span>
    </div>`;
  }).join('');
}

// --- Token用量 Top5 密钥 ---
function renderTokenTopKeys(list) {
  const el = document.getElementById('tokenTopKeysList');
  if (!list.length) {
    el.innerHTML = '<div class="empty-state"><p>暂无数据</p></div>';
    return;
  }
  const maxTokens = Math.max(...list.map(d => d.total_tokens), 1);
  el.innerHTML = list.map((d, i) => {
    const pct = Math.round(d.total_tokens / maxTokens * 100);
    const limitText = d.token_limit > 0 ? ` / ${formatNumber(d.token_limit)}` : '';
    const colors = ['#667eea', '#f093fb', '#43e97b', '#fbbf24', '#4facfe'];
    return `
    <div style="padding:8px 0;border-bottom:1px solid #f5f5f5">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:4px">
        <span style="font-size:12px;color:#333;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:120px" title="${escHtml(d.user_name)}">${escHtml(d.user_name)}</span>
        <span style="font-size:12px;color:#666">${formatNumber(d.total_tokens)}${limitText} <span style="color:#aaa">(${d.total_requests}次)</span></span>
      </div>
      <div style="height:6px;border-radius:3px;background:#f0f0f0">
        <div style="height:100%;border-radius:3px;width:${pct}%;background:${colors[i]||'#667eea'};transition:width 0.3s"></div>
      </div>
    </div>`;
  }).join('');
}

// --- 全局Token用量 ---
function renderGlobalTokenStats(globalTotal, keysWithLimit) {
  const el = document.getElementById('globalTokenStats');
  if (globalTotal === 0) {
    el.innerHTML = '<div class="empty-state"><p>暂无Token用量</p></div>';
    return;
  }
  el.innerHTML = `
    <div style="display:flex;flex-direction:column;gap:16px;padding:8px 0">
      <div style="text-align:center">
        <div style="font-size:28px;font-weight:700;color:#667eea">${formatNumber(globalTotal)}</div>
        <div style="font-size:13px;color:#888;margin-top:4px">全量Token消耗</div>
      </div>
      <div style="display:flex;justify-content:space-around;background:#f8f9fa;border-radius:8px;padding:12px 0">
        <div style="text-align:center">
          <div style="font-size:18px;font-weight:600;color:#333">${keysWithLimit}</div>
          <div style="font-size:12px;color:#888">设限密钥数</div>
        </div>
      </div>
      <div style="font-size:12px;color:#aaa;text-align:center">Token用量 = 输入Token + 输出Token</div>
    </div>`;
}

// ============================================================
// 大模型配置（后端分页）
// ============================================================
let llmPage = 1;
const LLM_PAGE_SIZE = 10;
let llmTotal = 0;
let llmKeyword = '';
// 仅用于编辑弹窗回显（按需单条 GET）
let llmCacheMap = {};

async function loadLLMList(resetPage = true) {
  if (resetPage) llmPage = 1;
  const tbody = document.getElementById('llmTable');
  tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:#aaa;padding:32px">加载中…</td></tr>';

  let url = `/api/llm/list?page=${llmPage}&page_size=${LLM_PAGE_SIZE}`;
  if (llmKeyword) url += `&keyword=${encodeURIComponent(llmKeyword)}`;

  const resp = await API.get(url);
  if (!resp) return;
  if (!resp.ok) { toast('加载失败', 'error'); return; }
  const data = await resp.json();

  const items = data.items || [];
  llmTotal = data.total || 0;

  // 缓存条目，供编辑弹窗使用
  items.forEach(i => { llmCacheMap[i.id] = i; });

  const totalEl = document.getElementById('llmTotal');
  if (totalEl) totalEl.textContent = llmTotal ? `共 ${llmTotal} 条` : '';

  if (!items.length) {
    tbody.innerHTML = '<tr><td colspan="6"><div class="empty-state"><div class="empty-icon">🧠</div><p>暂无大模型配置，请先添加</p></div></td></tr>';
    document.getElementById('llmPagination').innerHTML = '';
    return;
  }
  tbody.innerHTML = items.map(item => `
    <tr>
      <td>${item.id}</td>
      <td><strong>${item.llm_name}</strong></td>
      <td style="max-width:250px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${item.api_url}">${item.api_url}</td>
      <td>${item.status === 1 ? '<span class="tag tag-success">启用</span>' : '<span class="tag tag-error">禁用</span>'}</td>
      <td>${fmt(item.create_time)}</td>
      <td>
        <button class="btn btn-outline btn-sm" onclick="openLLMModal(${item.id})">编辑</button>
        <button class="btn btn-danger btn-sm" onclick="deleteLLM(${item.id})">删除</button>
      </td>
    </tr>`).join('');

  renderPagination('llmPagination', llmPage, Math.ceil(llmTotal / LLM_PAGE_SIZE), llmTotal,
    p => { llmPage = p; loadLLMList(false); });
}

function searchLLM() {
  llmKeyword = (document.getElementById('llmSearch')?.value || '').trim();
  loadLLMList(true);
}

function openLLMModal(id) {
  document.getElementById('llmId').value = '';
  document.getElementById('llmName').value = '';
  document.getElementById('llmApiUrl').value = '';
  document.getElementById('llmApiKey').value = '';
  document.getElementById('llmStatus').value = '1';
  document.getElementById('llmModalTitle').textContent = '添加大模型';
  document.getElementById('llmApiKey').placeholder = '官方密钥，加密存储';

  if (id) {
    const item = llmCacheMap[id];
    if (item) {
      document.getElementById('llmId').value = item.id;
      document.getElementById('llmName').value = item.llm_name;
      document.getElementById('llmApiUrl').value = item.api_url;
      document.getElementById('llmStatus').value = item.status;
      document.getElementById('llmModalTitle').textContent = '编辑大模型';
      document.getElementById('llmApiKey').placeholder = '留空则不修改密钥';
    }
  }
  document.getElementById('llmModal').classList.add('show');
}

function closeLLMModal() { document.getElementById('llmModal').classList.remove('show'); }

async function saveLLMConfig() {
  const id = document.getElementById('llmId').value;
  const name = document.getElementById('llmName').value.trim();
  const apiUrl = document.getElementById('llmApiUrl').value.trim();
  const apiKey = document.getElementById('llmApiKey').value.trim();
  const status = parseInt(document.getElementById('llmStatus').value);

  if (!name || !apiUrl) { toast('请填写模型名称和API地址', 'error'); return; }
  if (!id && !apiKey) { toast('请填写官方API Key', 'error'); return; }

  const payload = { llm_name: name, api_url: apiUrl, api_key: apiKey || 'unchanged', status };

  let resp;
  if (id) {
    resp = await API.put(`/api/llm/${id}`, payload);
  } else {
    resp = await API.post('/api/llm/create', payload);
  }
  if (!resp) return;
  if (resp.ok) {
    toast(id ? '更新成功' : '创建成功', 'success');
    closeLLMModal();
    loadLLMList();
  } else {
    const err = await resp.json();
    toast(err.detail || '操作失败', 'error');
  }
}

async function deleteLLM(id) {
  if (!confirm2('确认删除此大模型配置？')) return;
  const resp = await API.delete(`/api/llm/${id}`);
  if (!resp) return;
  if (resp.ok) { toast('删除成功', 'success'); loadLLMList(); }
  else { const e = await resp.json(); toast(e.detail || '删除失败', 'error'); }
}

// ============================================================
// API密钥管理（后端分页）
// ============================================================
let keyPage = 1;
const KEY_PAGE_SIZE = 10;
let keyTotal = 0;
let keySearchQ = '';
let keyStatusQ = '';
// 缓存当前页，供编辑弹窗使用
let keyCacheMap = {};

async function loadLLMListForKey() {
  const resp = await API.get('/api/llm/list?page=1&page_size=100');
  if (!resp) return;
  const data = await resp.json();
  const items = (data && data.items) || [];
  if (!Array.isArray(items)) return;
  const container = document.getElementById('keyLlmCheckboxes');
  if (!container) return;
  container.innerHTML = items.map(l =>
    `<label style="font-size:13px;display:flex;align-items:center;gap:4px;cursor:pointer;background:#f5f5f5;padding:4px 10px;border-radius:20px">
      <input type="checkbox" name="llmCheck" value="${l.id}"> ${l.llm_name}
    </label>`
  ).join('');
}

async function loadKeyList(resetPage = true) {
  if (resetPage) keyPage = 1;
  const tbody = document.getElementById('keyTable');
  tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;color:#aaa;padding:32px">加载中…</td></tr>';

  let url = `/api/key/list?page=${keyPage}&page_size=${KEY_PAGE_SIZE}`;
  if (keySearchQ) url += `&user_name=${encodeURIComponent(keySearchQ)}`;
  if (keyStatusQ !== '') url += `&status=${keyStatusQ}`;

  const resp = await API.get(url);
  if (!resp) return;
  if (!resp.ok) { toast('加载失败', 'error'); return; }
  const data = await resp.json();

  const items = data.items || [];
  keyTotal = data.total || 0;
  items.forEach(k => { keyCacheMap[k.id] = k; });

  const totalEl = document.getElementById('keyTotal');
  if (totalEl) totalEl.textContent = keyTotal ? `共 ${keyTotal} 条` : '';

  if (!items.length) {
    tbody.innerHTML = '<tr><td colspan="8"><div class="empty-state"><div class="empty-icon">🔑</div><p>暂无密钥数据</p></div></td></tr>';
    document.getElementById('keyPagination').innerHTML = '';
    if (totalEl) totalEl.textContent = '';
    return;
  }
  tbody.innerHTML = items.map(k => {
    const tl = k.token_limit || 0;
    const tt = k.total_tokens || 0;
    let tokenHtml = `<span style="color:#667eea;font-weight:600">${formatNumber(tt)}</span>`;
    if (tl > 0) {
      const pct = Math.min(Math.round(tt / tl * 100), 100);
      const color = pct > 90 ? '#ef4444' : pct > 70 ? '#f59e0b' : '#22c55e';
      tokenHtml += `<span style="color:#aaa;font-size:11px"> / ${formatNumber(tl)}</span>`;
      tokenHtml += `<div style="margin-top:2px;height:4px;border-radius:2px;background:#f0f0f0;width:80px">
        <div style="height:100%;border-radius:2px;width:${pct}%;background:${color};transition:width 0.3s"></div>
      </div>`;
    }
    return `
    <tr>
      <td><span class="code">${maskKey(k.key_value)}</span></td>
      <td>${k.user_name || '-'}</td>
      <td>${k.daily_limit}</td>
      <td>${k.rate_limit}</td>
      <td>${tokenHtml}</td>
      <td>${k.status === 1 ? '<span class="tag tag-success">启用</span>' : '<span class="tag tag-error">禁用</span>'}</td>
      <td>${k.total_requests || 0}</td>
      <td>${fmt(k.last_use_time)}</td>
      <td>
        <button class="btn btn-outline btn-sm" onclick="openKeyModal(${k.id})">编辑</button>
        <button class="btn btn-outline btn-sm" onclick="toggleKey(${k.id}, ${k.status})">${k.status===1?'禁用':'启用'}</button>
        <button class="btn btn-danger btn-sm" onclick="deleteKey(${k.id})">删除</button>
      </td>
    </tr>`;}).join('');

  renderPagination('keyPagination', keyPage, Math.ceil(keyTotal / KEY_PAGE_SIZE), keyTotal,
    p => { keyPage = p; loadKeyList(false); });
}

function searchKeys() {
  keySearchQ = (document.getElementById('keySearch')?.value || '').trim();
  keyStatusQ = document.getElementById('keyStatusFilter')?.value ?? '';
  loadKeyList(true);
}

function renderPagination(elId, current, totalPages, total, onPage) {
  const el = document.getElementById(elId);
  if (!el) return;
  if (totalPages <= 1) { el.innerHTML = ''; return; }

  // 生成页码序列（带省略号）
  function pageNums(cur, tot) {
    if (tot <= 7) return Array.from({length: tot}, (_, i) => i + 1);
    const pages = [];
    pages.push(1);
    if (cur > 3) pages.push('...');
    for (let i = Math.max(2, cur - 1); i <= Math.min(tot - 1, cur + 1); i++) pages.push(i);
    if (cur < tot - 2) pages.push('...');
    pages.push(tot);
    return pages;
  }

  const nums = pageNums(current, totalPages);
  let html = '';

  // 上一页
  html += `<button class="page-btn${current === 1 ? ' disabled' : ''}" onclick="(${onPage})(${current - 1})">‹</button>`;

  // 页码
  nums.forEach(n => {
    if (n === '...') {
      html += `<span class="page-ellipsis">…</span>`;
    } else {
      html += `<button class="page-btn${n === current ? ' active' : ''}" onclick="(${onPage})(${n})">${n}</button>`;
    }
  });

  // 下一页
  html += `<button class="page-btn${current === totalPages ? ' disabled' : ''}" onclick="(${onPage})(${current + 1})">›</button>`;

  el.innerHTML = html;
}

function openKeyModal(id) {
  document.getElementById('keyId').value = '';
  document.getElementById('keyUserName').value = '';
  document.getElementById('keyRateLimit').value = 10;
  document.getElementById('keyDailyLimit').value = 1000;
  document.getElementById('keyMonthlyLimit').value = 30000;
  document.getElementById('keyTokenLimit').value = 0;
  document.getElementById('keyExpireTime').value = '';
  document.getElementById('keyIpWhitelist').value = '';
  document.querySelectorAll('input[name="llmCheck"]').forEach(c => c.checked = false);
  document.getElementById('keyModalTitle').textContent = '创建API密钥';

  if (id) {
    const item = keyCacheMap[id];
    if (item) {
      document.getElementById('keyId').value = item.id;
      document.getElementById('keyUserName').value = item.user_name || '';
      document.getElementById('keyRateLimit').value = item.rate_limit;
      document.getElementById('keyDailyLimit').value = item.daily_limit;
      document.getElementById('keyMonthlyLimit').value = item.monthly_limit;
      document.getElementById('keyTokenLimit').value = item.token_limit || 0;
      if (item.expire_time) {
        document.getElementById('keyExpireTime').value = item.expire_time.slice(0,16);
      }
      document.getElementById('keyIpWhitelist').value = (item.ip_whitelist || []).join('\n');
      const llmIds = item.llm_ids || [];
      document.querySelectorAll('input[name="llmCheck"]').forEach(c => {
        c.checked = llmIds.includes(parseInt(c.value));
      });
      document.getElementById('keyModalTitle').textContent = '编辑密钥配置';
    }
  }
  document.getElementById('keyModal').classList.add('show');
}
function closeKeyModal() { document.getElementById('keyModal').classList.remove('show'); }

function copyCreatedKey() {
  const inp = document.getElementById('createdKeyValue');
  const val = inp.value;
  const btn = document.getElementById('copyKeyBtn');
  function showOk() { btn.textContent = '✅ 已复制'; btn.style.background = '#22c55e'; setTimeout(() => { btn.textContent = '📋 复制'; btn.style.background = 'linear-gradient(135deg,#667eea,#764ba2)'; }, 2000); }
  function showFail() { btn.textContent = '❌ 复制失败'; btn.style.background = '#ef4444'; setTimeout(() => { btn.textContent = '📋 复制'; btn.style.background = 'linear-gradient(135deg,#667eea,#764ba2)'; }, 2000); }
  // 优先用 Clipboard API
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(val).then(showOk).catch(showFail);
    return;
  }
  // fallback: 创建临时 textarea
  try {
    const ta = document.createElement('textarea');
    ta.value = val;
    ta.style.cssText = 'position:fixed;left:-9999px;top:-9999px;opacity:0';
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    const ok = document.execCommand('copy');
    document.body.removeChild(ta);
    ok ? showOk() : showFail();
  } catch(e) { showFail(); }
}

async function saveKey() {
  const id = document.getElementById('keyId').value;
  const userName = document.getElementById('keyUserName').value.trim();
  const rateLimit = parseInt(document.getElementById('keyRateLimit').value) || 10;
  const dailyLimit = parseInt(document.getElementById('keyDailyLimit').value) || 1000;
  const monthlyLimit = parseInt(document.getElementById('keyMonthlyLimit').value) || 30000;
  const tokenLimit = parseInt(document.getElementById('keyTokenLimit').value) || 0;
  const expireTime = document.getElementById('keyExpireTime').value;
  const ipWhitelist = document.getElementById('keyIpWhitelist').value.split('\n').map(s=>s.trim()).filter(Boolean);
  const llmIds = [...document.querySelectorAll('input[name="llmCheck"]:checked')].map(c => parseInt(c.value));

  const payload = {
    user_name: userName || null,
    rate_limit: rateLimit,
    daily_limit: dailyLimit,
    monthly_limit: monthlyLimit,
    token_limit: tokenLimit,
    expire_time: expireTime || null,
    ip_whitelist: ipWhitelist,
    llm_ids: llmIds
  };

  let resp;
  if (id) {
    resp = await API.put(`/api/key/${id}`, payload);
  } else {
    resp = await API.post('/api/key/create', payload);
  }
  if (!resp) return;
  if (resp.ok) {
    const result = await resp.json();
    if (!id && result.key_value) {
      document.getElementById('createdKeyValue').value = result.key_value;
      document.getElementById('createdKeyValue').select();
      document.getElementById('keyCreatedModal').classList.add('show');
    } else {
      toast(id ? '更新成功' : '创建成功', 'success');
    }
    closeKeyModal();
    loadKeyList();
  } else {
    const e = await resp.json();
    toast(e.detail || '操作失败', 'error');
  }
}

async function toggleKey(id, currentStatus) {
  const newStatus = currentStatus === 1 ? 0 : 1;
  const resp = await API.put(`/api/key/${id}/status`, { status: newStatus });
  if (!resp) return;
  if (resp.ok) { toast('状态更新成功', 'success'); loadKeyList(); }
  else { const e = await resp.json(); toast(e.detail || '操作失败', 'error'); }
}

async function deleteKey(id) {
  if (!confirm2('确认删除此密钥？该操作不可恢复！')) return;
  const resp = await API.delete(`/api/key/${id}`);
  if (!resp) return;
  if (resp.ok) { toast('删除成功', 'success'); loadKeyList(); }
  else { const e = await resp.json(); toast(e.detail || '删除失败', 'error'); }
}

// ============================================================
// 敏感词管理（后端分页）
// ============================================================
let sensitivePage = 1;
const SENSITIVE_PAGE_SIZE = 10;
let sensitiveTotal = 0;
let sensitiveKeyword = '';
let sensitiveTypeQ = '';

async function loadSensitiveWords(resetPage = true) {
  if (resetPage) sensitivePage = 1;
  const tbody = document.getElementById('sensitiveTable');
  tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:#aaa;padding:32px">加载中…</td></tr>';

  let url = `/api/sensitive/list?page=${sensitivePage}&page_size=${SENSITIVE_PAGE_SIZE}`;
  if (sensitiveKeyword) url += `&keyword=${encodeURIComponent(sensitiveKeyword)}`;
  if (sensitiveTypeQ) url += `&word_type=${encodeURIComponent(sensitiveTypeQ)}`;

  const resp = await API.get(url);
  if (!resp) return;
  if (!resp.ok) { toast('加载失败', 'error'); return; }
  const data = await resp.json();

  const items = data.words || [];
  sensitiveTotal = data.total || 0;
  // 缓存用于详情弹窗
  items.forEach(w => { sensitiveCacheMap[w.id] = w; });

  const totalEl = document.getElementById('sensitiveTotal');
  if (totalEl) totalEl.textContent = sensitiveTotal ? `共 ${sensitiveTotal} 条` : '';

  if (!items.length) {
    tbody.innerHTML = '<tr><td colspan="6"><div class="empty-state"><div class="empty-icon">🛡️</div><p>暂无敏感词</p></div></td></tr>';
    document.getElementById('sensitivePagination').innerHTML = '';
    return;
  }

  const typeColorMap = {
    violence:'tag-error', pornography:'tag-error', terrorism:'tag-error',
    fraud:'tag-warning', drugs:'tag-warning', gambling:'tag-warning',
    political:'tag-purple', general:'tag-info'
  };
  const typeNameMap = {
    violence:'暴力', pornography:'色情', terrorism:'恐怖', fraud:'诈骗',
    drugs:'毒品', gambling:'赌博', political:'政治', general:'通用'
  };
  tbody.innerHTML = items.map(w => {
    const wordEsc = escHtml(w.word);
    const wordDisplay = w.word.length > 40
      ? wordEsc.slice(0, 40) + '<span style="color:#999">…</span>'
      : wordEsc;
    const presetTag = w.is_preset
      ? ' <span class="tag tag-purple" style="font-size:11px;margin-left:4px" title="系统预置，不可删除">预置</span>'
      : '';
    const deleteBtn = w.is_preset
      ? '<button class="btn btn-sm" style="color:#ccc;cursor:not-allowed;border:1px solid #eee;background:#fafafa" disabled title="预置规则不可删除">删除</button>'
      : `<button class="btn btn-danger btn-sm" onclick="deleteSensitiveWord(${w.id},'${w.word.replace(/'/g,"\\'")}')">删除</button>`;
    return `
    <tr>
      <td>${w.id}</td>
      <td style="max-width:280px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${wordEsc}"><strong style="font-family:monospace">${wordDisplay}</strong>${presetTag}</td>
      <td>${w.type ? `<span class="tag ${typeColorMap[w.type]||'tag-info'}">${typeNameMap[w.type]||w.type}</span>` : '<span class="tag tag-info">通用</span>'}</td>
      <td>${w.is_regex ? '<span class="tag tag-warning" title="正则模式">正则</span>' : '<span style="color:#aaa">-</span>'}</td>
      <td>${fmt(w.create_time)}</td>
      <td>
        <button class="btn btn-outline btn-sm" onclick="viewSensitiveDetail(${w.id})">详情</button>
        ${deleteBtn}
      </td>
    </tr>`;
  }).join('');

  renderPagination('sensitivePagination', sensitivePage, Math.ceil(sensitiveTotal / SENSITIVE_PAGE_SIZE), sensitiveTotal,
    p => { sensitivePage = p; loadSensitiveWords(false); });
}

function filterSensitive() {
  sensitiveKeyword = (document.getElementById('sensitiveSearch')?.value || '').trim();
  sensitiveTypeQ = document.getElementById('sensitiveTypeFilter')?.value || '';
  loadSensitiveWords(true);
}

function toggleRegexHint(checked) {
  const hint = document.getElementById('regexHint');
  if (hint) hint.style.display = checked ? 'block' : 'none';
}

function openSensitiveModal() {
  document.getElementById('sensitiveWord').value = '';
  document.getElementById('sensitiveType').value = 'general';
  const cb = document.getElementById('sensitiveIsRegex');
  if (cb) { cb.checked = false; toggleRegexHint(false); }
  document.getElementById('sensitiveModal').classList.add('show');
}
function closeSensitiveModal() { document.getElementById('sensitiveModal').classList.remove('show'); }

async function saveSensitiveWord() {
  const word = document.getElementById('sensitiveWord').value.trim();
  const type = document.getElementById('sensitiveType').value;
  const isRegex = document.getElementById('sensitiveIsRegex')?.checked || false;
  if (!word) { toast('请输入敏感词或正则表达式', 'error'); return; }
  const resp = await API.post('/api/sensitive/create', { word, type: type || 'general', is_regex: isRegex });
  if (!resp) return;
  if (resp.ok) {
    toast('添加成功', 'success');
    closeSensitiveModal();
    loadSensitiveWords();
  } else {
    const e = await resp.json();
    toast(e.detail || '添加失败', 'error');
  }
}

async function deleteSensitiveWord(id, word) {
  if (!confirm2(`确认删除敏感词「${word}」？`)) return;
  const resp = await API.delete(`/api/sensitive/${id}`);
  if (!resp) return;
  if (resp.ok) { toast('删除成功', 'success'); loadSensitiveWords(); }
  else { const e = await resp.json(); toast(e.detail || '删除失败', 'error'); }
}

// --- 敏感词详情模态框 ---
const sensitiveCacheMap = {};

async function viewSensitiveDetail(id) {
  let w = sensitiveCacheMap[id];
  if (!w) { toast('未找到该敏感词，请刷新后重试', 'error'); return; }

  const wordEsc = escHtml(w.word);
  const typeColorMap = {
    violence:'tag-error', pornography:'tag-error', terrorism:'tag-error',
    fraud:'tag-warning', drugs:'tag-warning', gambling:'tag-warning',
    political:'tag-purple', general:'tag-info'
  };
  const typeNameMap = {
    violence:'暴力', pornography:'色情', terrorism:'恐怖', fraud:'诈骗',
    drugs:'毒品', gambling:'赌博', political:'政治', general:'通用'
  };
  const presetBadge = w.is_preset
    ? '<span class="tag tag-purple">系统预置规则</span>'
    : '<span class="tag tag-info">自定义规则</span>';

  document.getElementById('sensitiveDetailContent').innerHTML = `
    <div class="detail-row"><div class="detail-key">ID</div><div class="detail-val">${w.id}</div></div>
    <div class="detail-row"><div class="detail-key">规则来源</div><div class="detail-val">${presetBadge}</div></div>
    <div class="detail-row"><div class="detail-key">类型</div><div class="detail-val">${w.type ? `<span class="tag ${typeColorMap[w.type]||'tag-info'}">${typeNameMap[w.type]||w.type}</span>` : '<span class="tag tag-info">通用</span>'}</div></div>
    <div class="detail-row"><div class="detail-key">匹配模式</div><div class="detail-val">${w.is_regex ? '<span class="tag tag-warning">正则表达式</span>' : '<span style="color:#888">精确匹配</span>'}</div></div>
    <div class="detail-row"><div class="detail-key">规则内容</div><div class="detail-val"><pre class="detail-pre" style="word-break:break-all;white-space:pre-wrap;max-height:none">${wordEsc}</pre></div></div>
    <div class="detail-row"><div class="detail-key">添加时间</div><div class="detail-val">${fmt(w.create_time)}</div></div>
  `;
  document.getElementById('sensitiveDetailModal').classList.add('show');
}

function closeSensitiveDetailModal() {
  document.getElementById('sensitiveDetailModal').classList.remove('show');
}

// ============================================================
// 请求日志
// ============================================================
let logPage = 1;
const LOG_PAGE_SIZE = 10;

async function loadModelOptionsForLog() {
  const resp = await API.get('/api/llm/list?page=1&page_size=100');
  if (!resp) return;
  const data = await resp.json();
  const items = (data && data.items) || [];
  if (!Array.isArray(items)) { console.error('loadModelOptionsForLog: items is not array', items); return; }
  const sel = document.getElementById('logModelFilter');
  if (!sel) return;
  const existing = sel.querySelectorAll('option:not([value=""])');
  existing.forEach(o => o.remove());
  items.forEach(l => {
    const opt = document.createElement('option');
    opt.value = l.llm_name;
    opt.textContent = l.llm_name;
    sel.appendChild(opt);
  });
}

async function loadLogs() {
  const tbody = document.getElementById('logTable');
  tbody.innerHTML = '<tr><td colspan="9" style="text-align:center;color:#aaa;padding:32px">加载中…</td></tr>';

  const keyQ = document.getElementById('logKeySearch').value.trim();
  const ipQ = document.getElementById('logIpSearch').value.trim();
  const startTime = document.getElementById('logStartTime').value;
  const endTime = document.getElementById('logEndTime').value;
  const logStatusVal = document.getElementById('logStatusFilter').value;
  const model = document.getElementById('logModelFilter').value;
  const sensitiveOnly = document.getElementById('sensitiveOnly').checked;

  let url = `/api/logs/list?page=${logPage}&page_size=${LOG_PAGE_SIZE}`;
  if (keyQ) url += `&api_key=${encodeURIComponent(keyQ)}`;
  if (ipQ) url += `&client_ip=${encodeURIComponent(ipQ)}`;
  if (startTime) url += `&start_time=${encodeURIComponent(startTime)}`;
  if (endTime) url += `&end_time=${encodeURIComponent(endTime)}`;
  if (logStatusVal) url += `&log_status=${logStatusVal}`;
  if (model) url += `&llm_name=${encodeURIComponent(model)}`;
  if (sensitiveOnly) url += `&sensitive_only=true`;

  const resp = await API.get(url);
  if (!resp) return;
  if (!resp.ok) { tbody.innerHTML = '<tr><td colspan="9" style="text-align:center;color:#f44">加载失败</td></tr>'; return; }
  const data = await resp.json();
  const logs = data.logs || [];
  const total = data.total || 0;

  document.getElementById('logTotal').textContent = `共 ${total} 条`;

  if (!logs.length) {
    tbody.innerHTML = '<tr><td colspan="9"><div class="empty-state"><div class="empty-icon">📋</div><p>暂无日志数据</p></div></td></tr>';
    document.getElementById('logPagination').innerHTML = '';
    return;
  }

  const statusTag = {
    success: '<span class="tag tag-success">成功</span>',
    failed:  '<span class="tag tag-error">失败</span>',
    blocked: '<span class="tag tag-warning">拦截</span>',
  };

  tbody.innerHTML = logs.map(log => `
    <tr>
      <td style="white-space:nowrap">${fmt(log.request_time)}</td>
      <td><span class="code">${maskKey(log.api_key)}</span></td>
      <td>${log.user_name || '-'}</td>
      <td>${log.client_ip || '-'}</td>
      <td><span class="tag tag-info">${log.llm_name || '-'}</span></td>
      <td>${log.prompt_tokens||0} / ${log.completion_tokens||0}</td>
      <td>${statusTag[log.status] || log.status}</td>
      <td>${log.sensitive_result ? '<span class="tag tag-warning">⚠️ 检测</span>' : '-'}</td>
      <td><button class="btn btn-outline btn-sm" onclick="viewLogDetail(${log.id})">详情</button></td>
    </tr>`).join('');

  renderPagination('logPagination', logPage, Math.ceil(total / LOG_PAGE_SIZE), total, p => { logPage = p; loadLogs(); });
}

function searchLogs() { logPage = 1; loadLogs(); }

async function viewLogDetail(id) {
  const resp = await API.get(`/api/logs/${id}`);
  if (!resp) return;
  if (!resp.ok) { toast('加载详情失败', 'error'); return; }
  const log = await resp.json();
  const statusTag = { success:'tag-success', failed:'tag-error', blocked:'tag-warning' };

  // 解析 sensitive_result（可能是 JSON 字符串或对象）
  let sensitiveData = null;
  if (log.sensitive_result) {
    try {
      sensitiveData = typeof log.sensitive_result === 'string'
        ? JSON.parse(log.sensitive_result.replace(/'/g, '"'))
        : log.sensitive_result;
    } catch(_) { sensitiveData = null; }
  }

  // 提取命中的词条列表
  const matchedWords = sensitiveData?.sensitive_words?.words || [];
  const matchedPatterns = sensitiveData?.sensitive_words?.matched_patterns
    || matchedWords.map(w => w.word).filter(Boolean);

  // 高亮函数：在纯文本里把命中词/正则标红
  function highlightSensitive(text) {
    if (!text || !matchedPatterns.length) return `<pre class="detail-pre">${escHtml(text||'（无）')}</pre>`;
    let escaped = escHtml(text);
    matchedPatterns.forEach(pat => {
      try {
        // pat 是规则原文（可能含正则特殊字符），直接用于匹配；
        // 但 escHtml 会把 < > 等转义，所以对普通词也用转义后版本做替换
        const escapedPat = escHtml(pat);
        const regex = new RegExp(escapedPat, 'gi');
        escaped = escaped.replace(regex,
          m => `<mark style="background:#fee2e2;color:#dc2626;border-radius:2px;padding:0 2px;font-weight:600">${m}</mark>`
        );
      } catch(_) { /* 正则不合法时跳过 */ }
    });
    return `<pre class="detail-pre" style="white-space:pre-wrap;word-break:break-all">${escaped}</pre>`;
  }

  // 敏感检测摘要区
  let sensitiveHtml = '-';
  if (sensitiveData) {
    const words = matchedWords;
    const piiData = sensitiveData.personal_info || {};
    const action = sensitiveData.action_taken || '';
    const actionMap = { blocked:'<span class="tag tag-error">已拦截</span>', audit_only:'<span class="tag tag-warning">审计记录</span>', none:'' };

    let hitList = '';
    if (words.length) {
      hitList = '<div style="margin-top:8px"><strong>命中规则：</strong><ul style="margin:4px 0 0 16px;padding:0">' +
        words.map(w =>
          `<li style="margin:3px 0"><code style="background:#fee2e2;color:#dc2626;padding:1px 5px;border-radius:3px">${escHtml(w.word)}</code>` +
          (w.is_regex ? ' <span style="color:#888;font-size:11px">[正则]</span>' : '') +
          (w.matched && w.matched !== w.word ? ` → <em style="color:#b91c1c">${escHtml(w.matched)}</em>` : '') +
          (w.type ? ` <span class="tag tag-info" style="font-size:11px">${w.type}</span>` : '') +
          '</li>'
        ).join('') + '</ul></div>';
    }
    const piiNameMap = {id_card:'身份证',phone_number:'手机号',bank_card:'银行卡',email:'邮箱'};
    const piiList = Object.entries(piiData)
      .filter(([k, v]) => k !== 'has_personal_info' && v === true)
      .map(([k]) => `<span class="tag tag-warning">${piiNameMap[k]||k}</span>`)
      .join(' ');

    sensitiveHtml = `<div>${actionMap[action]||''}${hitList}${piiList ? '<div style="margin-top:6px">个人信息: ' + piiList + '</div>' : ''}</div>`;
  }

  document.getElementById('logDetailContent').innerHTML = `
    <div class="detail-row"><div class="detail-key">请求ID</div><div class="detail-val"><span class="code">${log.request_id}</span></div></div>
    <div class="detail-row"><div class="detail-key">时间</div><div class="detail-val">${fmt(log.request_time)}</div></div>
    <div class="detail-row"><div class="detail-key">API密钥</div><div class="detail-val"><span class="code">${maskKey(log.api_key)}</span></div></div>
    <div class="detail-row"><div class="detail-key">用户名</div><div class="detail-val">${log.user_name||'-'}</div></div>
    <div class="detail-row"><div class="detail-key">客户端IP</div><div class="detail-val">${log.client_ip||'-'}</div></div>
    <div class="detail-row"><div class="detail-key">调用模型</div><div class="detail-val"><span class="tag tag-info">${log.llm_name||'-'}</span></div></div>
    <div class="detail-row"><div class="detail-key">状态</div><div class="detail-val"><span class="tag ${statusTag[log.status]||''}">${log.status}</span></div></div>
    <div class="detail-row"><div class="detail-key">Token消耗</div><div class="detail-val">输入 ${log.prompt_tokens||0} / 输出 ${log.completion_tokens||0}</div></div>
    <div class="detail-row"><div class="detail-key">请求内容</div><div class="detail-val">${highlightSensitive(log.prompt_content||'（无）')}</div></div>
    <div class="detail-row"><div class="detail-key">响应内容</div><div class="detail-val">${highlightSensitive(log.response_content||'（无）')}</div></div>
    <div class="detail-row"><div class="detail-key">敏感检测</div><div class="detail-val">${sensitiveHtml}</div></div>
    ${log.error_msg ? `<div class="detail-row"><div class="detail-key">错误信息</div><div class="detail-val" style="color:#ef4444">${escHtml(log.error_msg)}</div></div>` : ''}
  `;
  document.getElementById('logDetailContent').innerHTML += `
    <div style="margin-top:16px;text-align:right">
      <button class="btn btn-danger btn-sm" onclick="deleteLogEntry(${log.id})">删除此条日志</button>
    </div>
  `;
  document.getElementById('logDetailModal').classList.add('show');
}

async function deleteLogEntry(id) {
  if (!window.confirm('确认删除此条日志？此操作不可撤销！')) return;
  const resp = await API.delete(`/api/logs/${id}`);
  if (!resp) return;
  if (resp.ok) {
    toast('日志已删除', 'success');
    closeLogDetailModal();
    loadLogs();
  } else {
    const e = await resp.json();
    toast(e.detail || '删除失败', 'error');
  }
}

function closeLogDetailModal() { document.getElementById('logDetailModal').classList.remove('show'); }

function escHtml(str) {
  return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

async function exportLogs() {
  const token = localStorage.getItem('token');
  if (!token) { redirectLogin(); return; }
  const url = `/api/logs/export?format=csv`;
  const link = document.createElement('a');
  link.href = url;
  link.download = `logs_export_${new Date().toISOString().slice(0,10)}.csv`;
  // 使用fetch带上token
  try {
    const resp = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
    if (!resp.ok) { toast('导出失败', 'error'); return; }
    const blob = await resp.blob();
    const objUrl = URL.createObjectURL(blob);
    link.href = objUrl;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(objUrl);
    toast('导出成功', 'success');
  } catch(e) {
    toast('导出失败', 'error');
  }
}

// ============================================================
// 日志管理：保留策略、清理、批量删除
// ============================================================

function openLogRetentionModal() {
  document.getElementById('retentionDays').value = '';
  document.getElementById('retentionInfo').textContent = '加载中…';
  document.getElementById('logRetentionModal').classList.add('show');
  loadRetentionInfo();
}

function closeLogRetentionModal() {
  document.getElementById('logRetentionModal').classList.remove('show');
}

async function loadRetentionInfo() {
  const resp = await API.get('/api/logs/retention');
  if (!resp) return;
  if (!resp.ok) {
    document.getElementById('retentionInfo').textContent = '加载失败';
    return;
  }
  const data = await resp.json();
  document.getElementById('retentionDays').value = data.retention_days;
  document.getElementById('retentionInfo').innerHTML =
    `保留天数: <strong>${data.retention_days} 天</strong> &nbsp;|&nbsp; ` +
    `当前日志总数: <strong>${data.total_logs} 条</strong> &nbsp;|&nbsp; ` +
    `已过期日志: <strong style="color:#ef4444">${data.expired_logs} 条</strong>`;
}

async function saveLogRetention() {
  const days = parseInt(document.getElementById('retentionDays').value);
  if (!days || days < 1) { toast('请输入有效的保留天数（最少1天）', 'error'); return; }
  if (days > 3650) { toast('保留天数不能超过3650天', 'error'); return; }

  const resp = await API.put(`/api/logs/retention?days=${days}`);
  if (!resp) return;
  if (resp.ok) {
    toast(`日志保留天数已设置为 ${days} 天`, 'success');
    await loadRetentionInfo();
  } else {
    const e = await resp.json();
    toast(e.detail || '保存失败', 'error');
  }
}

// --- 清理过期日志 ---
function openLogCleanupModal() {
  document.getElementById('logCleanupModal').classList.add('show');
  // 加载过期日志数量
  (async () => {
    const resp = await API.get('/api/logs/retention');
    if (!resp) return;
    if (!resp.ok) {
      document.getElementById('cleanupMessage').textContent = '加载失败';
      return;
    }
    const data = await resp.json();
    document.getElementById('cleanupMessage').innerHTML =
      `当前有 <strong style="color:#ef4444">${data.expired_logs}</strong> 条日志已超过 ` +
      `<strong>${data.retention_days}</strong> 天保留期`;
  })();
}

function closeLogCleanupModal() {
  document.getElementById('logCleanupModal').classList.remove('show');
}

async function executeCleanup() {
  const resp = await API.delete('/api/logs/cleanup');
  if (!resp) return;
  if (resp.ok) {
    const data = await resp.json();
    toast(data.message || '清理完成', 'success');
    closeLogCleanupModal();
    loadLogs();
  } else {
    const e = await resp.json();
    toast(e.detail || '清理失败', 'error');
  }
}

// --- 批量删除日志 ---
function openLogBatchDeleteModal() {
  document.getElementById('batchDeleteBefore').value = '';
  document.getElementById('batchDeleteStatus').value = '';
  document.getElementById('logBatchDeleteModal').classList.add('show');
}

function closeLogBatchDeleteModal() {
  document.getElementById('logBatchDeleteModal').classList.remove('show');
}

async function executeBatchDelete() {
  const before = document.getElementById('batchDeleteBefore').value;
  const statusVal = document.getElementById('batchDeleteStatus').value;

  if (!before && !statusVal) {
    toast('请至少设置一个删除条件（时间或状态）', 'error');
    return;
  }

  // 构建确认信息
  let confirmMsg = '确认删除以下条件的日志？\n';
  if (before) confirmMsg += `时间早于: ${before}\n`;
  if (statusVal) confirmMsg += `状态: ${statusVal}\n`;
  confirmMsg += '\n此操作不可撤销！';
  if (!window.confirm(confirmMsg)) return;

  let url = '/api/logs/batch?';
  if (before) url += `start_time=${encodeURIComponent(before + 'T23:59:59')}&`;
  if (statusVal) url += `log_status=${encodeURIComponent(statusVal)}&`;

  const resp = await API.delete(url);
  if (!resp) return;
  if (resp.ok) {
    const data = await resp.json();
    toast(data.message || '删除完成', 'success');
    closeLogBatchDeleteModal();
    loadLogs();
  } else {
    const e = await resp.json();
    toast(e.detail || '删除失败', 'error');
  }
}
