/**
 * 微生物报告智能解读系统 - 前端交互逻辑 v4
 * 支持: 行内引用、知识图谱可视化（弹窗+独立页面）、工具调用进度、停止按钮
 */

let currentSessionId = null;
let isStreaming = false;
let abortController = null;

// 引用注册表 (含图谱数据 + 实体列表)
const citationRegistry = new Map();

// 工具调用进度追踪
const toolCallTracker = {
    calls: [],
    container: null,
    reset() { this.calls = []; this.container = null; },
    addCall(index, toolName, title) {
        this.calls.push({ index, toolName, title, status: 'running' });
        this.render();
    },
    completeCall(index) {
        const call = this.calls.find(c => c.index === index);
        if (call) call.status = 'completed';
        this.render();
    },
    render() {
        if (!this.container) return;
        this.container.innerHTML = this.calls.map(call => {
            const iconSvg = call.status === 'running'
                ? `<div class="tool-icon running"></div>`
                : `<svg class="tool-icon done" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 6L9 17l-5-5"/></svg>`;
            const statusClass = call.status === 'running' ? 'active' : 'completed';
            const statusText = call.status === 'running' ? '检索中...' : '完成';
            return `<div class="tool-progress-item ${statusClass}">${iconSvg}<span class="tool-name-text">${call.title}</span><span class="tool-status">${statusText}</span></div>`;
        }).join('');
    }
};

const chatMessages = document.getElementById('chat-messages');
const userInput = document.getElementById('user-input');
const fileUpload = document.getElementById('file-upload');
const citeTooltip = document.getElementById('cite-tooltip');

// ============ 文件上传 ============

fileUpload.addEventListener('change', async (e) => {
    const file = e.target.files[0];
    if (!file) return;

    appendMessage('assistant', '正在上传并解析报告...');

    const formData = new FormData();
    formData.append('file', file);

    try {
        const resp = await fetch('/api/upload', { method: 'POST', body: formData });
        if (!resp.ok) {
            const err = await resp.json();
            throw new Error(err.detail || '上传失败');
        }

        const data = await resp.json();
        currentSessionId = data.session_id;

        const reportMd = data.report_markdown || '';
        const lastMsg = chatMessages.lastElementChild;
        if (lastMsg) {
            lastMsg.querySelector('.message-content').innerHTML = reportMd
                ? renderMarkdown(reportMd)
                : renderReportCard(data.report);
        }

        document.getElementById('export-btn').style.display = 'flex';
        document.getElementById('view-file-btn').style.display = 'flex';

        await sendMessage('请根据以上报告数据进行完整的临床解读分析,包括细菌鉴定意义、耐药机制分析、用药推荐方案和注意事项');

    } catch (err) {
        const lastMsg = chatMessages.lastElementChild;
        if (lastMsg) {
            lastMsg.querySelector('.message-content').innerHTML =
                `<span style="color:var(--danger)">上传失败: ${err.message}</span>`;
        }
    }
    fileUpload.value = '';
});

// ============ 渲染报告卡片 ============

function renderReportCard(report) {
    const p = report.patient || {};
    const bacteria = report.bacteria_name || '未知';
    const specimen = report.specimen || '';
    const esbl = report.esbl || '';
    const cre = report.cre ? true : false;

    let alerts = '';
    if (cre) alerts += '<span class="alert-tag danger">CRE阳性</span>';
    if (esbl === 'POS') alerts += '<span class="alert-tag warning">ESBL阳性</span>';
    if (!cre && esbl !== 'POS') alerts += '<span class="alert-tag success">无特殊耐药标记</span>';

    let suscHtml = '';
    if (report.susceptibility && report.susceptibility.length > 0) {
        suscHtml = report.susceptibility.map(s => {
            const cls = s.sir === 'S' ? 'sir-s' : s.sir === 'I' ? 'sir-i' : 'sir-r';
            return `<span class="sir ${cls}">${s.drug_name}:${s.sir}</span>`;
        }).join(' ');
    }

    return `
        <div class="report-card">
            <h4>微生物检验报告</h4>
            <div class="info-grid">
                <div class="info-item"><span class="label">细菌:</span> ${bacteria}</div>
                <div class="info-item"><span class="label">标本:</span> ${specimen}</div>
                <div class="info-item"><span class="label">性别/年龄:</span> ${p.gender || '-'}/${p.age || '-'}岁</div>
                <div class="info-item"><span class="label">科室:</span> ${p.department || '-'}</div>
                <div class="info-item"><span class="label">床位:</span> ${p.bed_no || '-'}</div>
                <div class="info-item"><span class="label">采集:</span> ${p.collection_date || '-'}</div>
            </div>
            <div style="margin-top:8px">${alerts}</div>
            <div style="margin-top:8px;font-size:12px;line-height:2">${suscHtml}</div>
        </div>
    `;
}

// ============ 导出 / 历史 ============

function exportReport() {
    if (!currentSessionId) return;
    window.open(`/api/export/${currentSessionId}`, '_blank');
}

function viewOriginalFile() {
    if (!currentSessionId) return;
    window.open(`/api/file/${currentSessionId}`, '_blank');
}

function toggleHistory() {
    const panel = document.getElementById('history-panel');
    panel.classList.toggle('open');
    if (panel.classList.contains('open')) loadHistory();
}

async function loadHistory() {
    try {
        const resp = await fetch('/api/sessions');
        const data = await resp.json();
        const list = document.getElementById('history-list');
        if (!data.sessions || data.sessions.length === 0) {
            list.innerHTML = '<div class="history-placeholder">暂无历史记录</div>';
            return;
        }
        list.innerHTML = data.sessions.map(s => `
            <div class="history-item ${s.session_id === currentSessionId ? 'active' : ''}" onclick="loadSession('${s.session_id}')">
                <div class="history-item-top">
                    <span class="history-bacteria">${s.bacteria || '未知'}</span>
                </div>
                <div class="history-item-bottom">
                    <span>${s.specimen || ''}</span>
                    <span>${s.department || ''}</span>
                </div>
            </div>
        `).join('');
    } catch (err) { console.error('加载历史失败:', err); }
}

async function loadSession(sessionId) {
    try {
        const resp = await fetch(`/api/report/${sessionId}`);
        if (!resp.ok) throw new Error('会话不存在');
        const data = await resp.json();
        currentSessionId = sessionId;
        chatMessages.innerHTML = '';

        // 显示报告
        if (data.report_markdown) {
            appendMessage('assistant', '');
            const lastMsg = chatMessages.lastElementChild;
            if (lastMsg) lastMsg.querySelector('.message-content').innerHTML = renderMarkdown(data.report_markdown);
        }

        // 加载历史对话记录
        const log = data.analysis_log || [];
        for (const entry of log) {
            appendMessage('user', entry.question || '');
            appendMessage('assistant', '');
            const lastMsg = chatMessages.lastElementChild;
            if (lastMsg && entry.answer) {
                // 去掉 [N] 引用标记（历史对话无 registry，标记无意义）
                const cleanAnswer = entry.answer.replace(/\[(\d+)\]/g, '');
                let rendered = renderMarkdown(cleanAnswer);

                // 添加实体链接（历史对话无查询详情，只显示实体标签）
                const entities = entry.entities || [];
                if (entities.length > 0) {
                    const seen = new Set();
                    const uniqueEntities = entities.filter(n => {
                        if (seen.has(n.name) || !n.name || n.name.length < 2) return false;
                        seen.add(n.name);
                        return true;
                    });
                    if (uniqueEntities.length > 0) {
                        rendered += `<div class="knowledge-queries-panel">
                            <div style="display:flex;flex-wrap:wrap;gap:4px;padding:8px 0">
                                ${uniqueEntities.slice(0, 12).map(n =>
                                    `<a href="/graph?node=${encodeURIComponent(n.name)}" target="_blank" class="entity-link">${n.name}</a>`
                                ).join('')}
                            </div>
                        </div>`;
                    }
                }

                lastMsg.querySelector('.message-content').innerHTML = rendered;
            }
        }

        document.getElementById('export-btn').style.display = 'flex';
        document.getElementById('view-file-btn').style.display = 'flex';
        loadHistory();
    } catch (err) { console.error('加载会话失败:', err); }
}

// ============ 停止生成 ============

function stopGeneration() {
    if (abortController) {
        abortController.abort();
        abortController = null;
    }
}

// ============ 发送消息 ============

async function sendMessage(text, options = {}) {
    const message = text || userInput.value.trim();
    if (!message || isStreaming) return;

    const allowNoSession = options.allowNoSession || false;

    if (!currentSessionId && !allowNoSession) {
        appendMessage('user', message);
        appendMessage('assistant', '请先上传一份 PDF 或图片格式的微生物检验报告,我才能为您进行专业解读。');
        userInput.value = '';
        return;
    }

    isStreaming = true;
    userInput.value = '';
    updateSendBtn(true);

    citationRegistry.clear();
    toolCallTracker.reset();

    appendMessage('user', message);

    const assistantEl = appendMessage('assistant', '');
    const contentEl = assistantEl.querySelector('.message-content');
    contentEl.innerHTML = `<div class="typing-indicator"><div class="spinner"></div><span>AI 正在思考...</span></div>`;

    abortController = new AbortController();

    try {
        const resp = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message, session_id: currentSessionId || 'default' }),
            signal: abortController.signal,
        });

        if (!resp.ok) throw new Error('请求失败');

        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let fullContent = '';
        let buffer = '';
        let hasToolCalls = false;

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop() || '';

            for (const line of lines) {
                if (!line.startsWith('data: ')) continue;
                const data = line.slice(6);
                if (data === '[DONE]') continue;

                try {
                    const event = JSON.parse(data);

                    if (event.type === 'message') {
                        // 第一个 text_delta 到达时，折叠工具进度条
                        if (!fullContent && hasToolCalls && toolCallTracker.container) {
                            toolCallTracker.container.classList.add('collapsed');
                        }
                        fullContent += event.content;
                        contentEl.innerHTML = renderMarkdown(fullContent);
                        if (hasToolCalls && toolCallTracker.container) {
                            contentEl.insertBefore(toolCallTracker.container, contentEl.firstChild);
                        }
                        updateThinkingStatus(contentEl, '正在生成回复...');
                        scrollToBottom();

                    } else if (event.type === 'tool_call') {
                        hasToolCalls = true;
                        const idx = event.citation_index;
                        const title = event.citation_title || event.tool_name;
                        if (!toolCallTracker.container) {
                            toolCallTracker.container = document.createElement('div');
                            toolCallTracker.container.className = 'tool-progress-bar';
                            contentEl.innerHTML = '';
                            contentEl.appendChild(toolCallTracker.container);
                        }
                        toolCallTracker.addCall(idx, event.tool_name, title);
                        updateThinkingStatus(contentEl, `正在查询 ${title}...`);
                        scrollToBottom();

                    } else if (event.type === 'tool_result') {
                        const idx = event.citation_index;
                        if (idx) {
                            citationRegistry.set(idx, {
                                title: event.citation_title || `引用 ${idx}`,
                                summary: event.citation_summary || '',
                                content: event.content || '',
                                graph_data: event.graph_data || null,
                                nodes: event.nodes || [],
                                edges: event.edges || [],
                            });
                            toolCallTracker.completeCall(idx);
                        }

                    } else if (event.type === 'error') {
                        contentEl.innerHTML = `<span style="color:var(--danger)">${event.content}</span>`;
                    }
                } catch (e) { /* ignore JSON parse errors */ }
            }
        }

        removeThinkingStatus(contentEl);
        injectCitations(contentEl, fullContent);

    } catch (err) {
        if (err.name === 'AbortError') {
            removeThinkingStatus(contentEl);
            const existing = contentEl.innerHTML;
            if (existing.includes('typing-indicator') || existing.includes('spinner')) {
                contentEl.innerHTML = '<span style="color:var(--text-secondary)">已停止生成</span>';
            }
        } else {
            contentEl.innerHTML = `<span style="color:var(--danger)">通信错误: ${err.message}</span>`;
        }
    }

    isStreaming = false;
    abortController = null;
    updateSendBtn(false);
}

// ============ 思考状态指示器 ============

function updateThinkingStatus(contentEl, text) {
    let status = contentEl.querySelector('.thinking-status');
    if (!status) {
        status = document.createElement('div');
        status.className = 'thinking-status';
        contentEl.appendChild(status);
    }
    status.innerHTML = `<div class="pulse-dot"></div><span>${text}</span>`;
}

function removeThinkingStatus(contentEl) {
    const status = contentEl.querySelector('.thinking-status');
    if (status) status.remove();
}

// ============ 行内引用注入 ============

function injectCitations(contentEl, fullContent) {
    if (!fullContent || citationRegistry.size === 0) return;

    let html = contentEl.innerHTML;

    // 去除 AI 自行生成的"循证依据"等汇总章节
    html = html.replace(/<h[1-4][^>]*>.*?循证依据.*?<\/h[1-4]>[\s\S]*?(?=<h[1-4]|$)/gi, '');
    html = html.replace(/<h[1-4][^>]*>.*?参考文献.*?<\/h[1-4]>[\s\S]*?(?=<h[1-4]|$)/gi, '');
    html = html.replace(/<h[1-4][^>]*>.*?依据汇总.*?<\/h[1-4]>[\s\S]*?(?=<h[1-4]|$)/gi, '');

    // 替换 [N] 行内引用为可点击链接
    html = html.replace(/\[(\d+)\]/g, (match, num) => {
        const idx = parseInt(num);
        if (!citationRegistry.has(idx)) return match;
        const cite = citationRegistry.get(idx);
        const hasGraph = cite.graph_data && cite.graph_data.nodes && cite.graph_data.nodes.length > 1;
        const clickAction = hasGraph ? `showCitationGraph(${idx})` : `scrollToReference(${idx})`;
        return `<sup><a class="cite-link" data-idx="${idx}" onclick="${clickAction}" onmouseenter="showCiteTooltip(${idx}, this)" onmouseleave="hideCiteTooltip()" style="padding:2px 4px;margin:0 -1px;">[${idx}]</a></sup>`;
    });

    contentEl.innerHTML = html;

    // 底部添加可折叠的知识查询面板（展示模型调用输入输出）
    if (citationRegistry.size > 0) {
        const panel = document.createElement('div');
        panel.className = 'knowledge-queries-panel';

        let itemsHtml = '';
        for (const [idx, cite] of citationRegistry) {
            const hasGraph = cite.graph_data && cite.graph_data.nodes && cite.graph_data.nodes.length > 1;
            const graphBtn = hasGraph
                ? `<button class="kq-graph-btn" onclick="showCitationGraph(${idx})">查看图谱</button>`
                : '';
            itemsHtml += `
                <div class="kq-item">
                    <div class="kq-header" onclick="toggleKqItem(this)">
                        <span class="kq-arrow">▶</span>
                        <span class="kq-index">[${idx}]</span>
                        <span class="kq-title">${escapeHtmlJs(cite.title || '查询 ' + idx)}</span>
                    </div>
                    <div class="kq-body" style="display:none">
                        ${cite.summary ? `<div class="kq-result">${escapeHtmlJs(cite.summary)}</div>` : ''}
                        ${cite.content && cite.content.length > cite.summary.length
                            ? `<div class="kq-detail">${escapeHtmlJs(cite.content)}</div>` : ''}
                        ${graphBtn}
                    </div>
                </div>`;
        }

        panel.innerHTML = `
            <div class="kq-toggle" onclick="toggleKqPanel(this)">
                <span class="kq-toggle-arrow">▶</span>
                <span class="kq-toggle-label">知识查询详情 (${citationRegistry.size})</span>
            </div>
            <div class="kq-list" style="display:none">${itemsHtml}</div>`;

        contentEl.appendChild(panel);
    }

    scrollToBottom();
}

function escapeHtmlJs(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function toggleKqPanel(toggleEl) {
    const list = toggleEl.nextElementSibling;
    const arrow = toggleEl.querySelector('.kq-toggle-arrow');
    if (list.style.display === 'none') {
        list.style.display = 'block';
        arrow.textContent = '▼';
    } else {
        list.style.display = 'none';
        arrow.textContent = '▶';
    }
}

function toggleKqItem(headerEl) {
    const body = headerEl.nextElementSibling;
    const arrow = headerEl.querySelector('.kq-arrow');
    if (body.style.display === 'none') {
        body.style.display = 'block';
        arrow.textContent = '▼';
    } else {
        body.style.display = 'none';
        arrow.textContent = '▶';
    }
}

/**
 * 递归遍历 DOM，在纯文本节点中将实体名替换为超链接
 */
function _injectEntityLinks(rootEl, entities) {
    const walker = document.createTreeWalker(rootEl, NodeFilter.SHOW_TEXT, {
        acceptNode(node) {
            const parent = node.parentElement;
            if (!parent) return NodeFilter.FILTER_REJECT;
            if (parent.classList && (
                parent.classList.contains('cite-link') ||
                parent.classList.contains('entity-link') ||
                parent.tagName === 'CODE' ||
                parent.tagName === 'PRE' ||
                parent.tagName === 'A'
            )) return NodeFilter.FILTER_REJECT;
            return NodeFilter.FILTER_ACCEPT;
        }
    });

    const textNodes = [];
    while (walker.nextNode()) textNodes.push(walker.currentNode);

    for (const textNode of textNodes) {
        const text = textNode.textContent;
        if (!text || text.trim().length < 2) continue;

        let hasMatch = false;
        let newHtml = text;
        for (const entity of entities) {
            if (!text.includes(entity)) continue;
            hasMatch = true;
            const escaped = entity.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
            newHtml = newHtml.replace(new RegExp(escaped, 'g'),
                `<a href="/graph?node=${encodeURIComponent(entity)}" target="_blank" class="entity-link">${entity}</a>`
            );
        }

        if (hasMatch) {
            const span = document.createElement('span');
            span.innerHTML = newHtml;
            textNode.parentNode.replaceChild(span, textNode);
        }
    }
}

function truncateText(text, maxLen) {
    if (!text) return '';
    let clean = text.replace(/[{}\[\]"\\]/g, '').replace(/\n/g, ' ');
    return clean.length > maxLen ? clean.substring(0, maxLen) + '...' : clean;
}

// ============ 引用交互 ============

function scrollToReference(idx) {
    // 没有 bottom reference 了，直接弹窗显示详情
    const cite = citationRegistry.get(idx);
    if (!cite) return;
    // 如果有图谱数据，弹窗显示图谱
    if (cite.graph_data && cite.graph_data.nodes && cite.graph_data.nodes.length > 1) {
        showCitationGraph(idx);
    }
}

function toggleRefDetail(idx) {
    const detail = document.getElementById(`ref-detail-${idx}`);
    if (!detail) return;
    if (detail.style.display === 'none') {
        detail.style.display = 'block';
    } else {
        detail.style.display = 'none';
    }
}

let citeTooltipTimer = null;

function showCiteTooltip(idx, anchor) {
    clearTimeout(citeTooltipTimer);
    const cite = citationRegistry.get(idx);
    if (!cite) return;
    const hasGraph = cite.graph_data && cite.graph_data.nodes && cite.graph_data.nodes.length > 1;
    const graphHint = hasGraph ? '<div style="margin-top:4px;color:var(--primary);font-size:11px">点击查看知识图谱</div>' : '';
    citeTooltip.innerHTML = `
        <div class="cite-tooltip-title">${cite.title}</div>
        <div class="cite-tooltip-content">${truncateText(cite.summary, 500)}</div>
        ${graphHint}
    `;
    citeTooltip.style.display = 'block';
    const rect = anchor.getBoundingClientRect();
    citeTooltip.style.left = rect.left + 'px';
    citeTooltip.style.top = (rect.bottom + 2) + 'px';

    // tooltip 自身也要阻止隐藏
    citeTooltip.onmouseenter = () => clearTimeout(citeTooltipTimer);
    citeTooltip.onmouseleave = () => { citeTooltip.style.display = 'none'; };
}

function hideCiteTooltip() {
    citeTooltipTimer = setTimeout(() => {
        citeTooltip.style.display = 'none';
    }, 200);
}

// ============ 知识图谱可视化（弹窗） ============

const NODE_TYPE_LABELS = {
    Drug: '药物', DrugClass: '分类', Bacterium: '细菌',
    ResistanceMechanism: '耐药机制', TreatmentPlan: '治疗方案', InfectionSite: '感染部位'
};

const NODE_COLORS = {
    Drug: '#3b82f6', DrugClass: '#8b5cf6', Bacterium: '#ef4444',
    ResistanceMechanism: '#ec4899', TreatmentPlan: '#22c55e', InfectionSite: '#f97316'
};

const RELATION_LABELS = {
    BELONGS_TO_CLASS: '属于分类', INTRINSIC_RESISTANT: '天然耐药',
    HAS_TREATMENT: '治疗方案', RECOMMENDED_FOR: '推荐用于',
    COMMON_IN: '常见于', AMPC_RISK: 'AmpC风险'
};

function showCitationGraph(idx) {
    const cite = citationRegistry.get(idx);
    if (!cite || !cite.graph_data) return;
    hideCiteTooltip();

    const modal = document.createElement('div');
    modal.className = 'graph-modal';
    modal.id = 'graph-modal';
    modal.onclick = (e) => { if (e.target === modal) closeGraphModal(); };

    const typesInGraph = new Set();
    cite.graph_data.nodes.forEach(n => { if (n.type) typesInGraph.add(n.type); });

    const legendHtml = [...typesInGraph].map(t =>
        `<span class="graph-legend-item"><span class="graph-legend-dot" style="background:${NODE_COLORS[t] || '#64748b'}"></span>${NODE_TYPE_LABELS[t] || t}</span>`
    ).join('');

    modal.innerHTML = `
        <div class="graph-modal-content">
            <div class="graph-modal-header">
                <h3>${cite.title} - 知识图谱</h3>
                <div>
                    <button class="graph-modal-open" onclick="window.open('/graph?node=${encodeURIComponent(cite.graph_data.center || '')}','_blank')" style="margin-right:8px;padding:4px 10px;border:1px solid var(--primary);color:var(--primary);background:none;border-radius:4px;cursor:pointer;font-size:12px">打开图谱页面</button>
                    <button class="graph-modal-close" onclick="closeGraphModal()">&times;</button>
                </div>
            </div>
            <div class="graph-modal-body" id="graph-canvas"></div>
            <div class="graph-legend">${legendHtml}</div>
        </div>
    `;

    document.body.appendChild(modal);
    renderKnowledgeGraph(document.getElementById('graph-canvas'), cite.graph_data);
}

function closeGraphModal() {
    const modal = document.getElementById('graph-modal');
    if (modal) modal.remove();
}

function renderKnowledgeGraph(container, graphData) {
    const nodes = graphData.nodes;
    const edges = graphData.edges;
    const centerId = graphData.center;
    if (!nodes || nodes.length === 0) return;

    const width = container.clientWidth || 660;
    const height = 440;
    const centerX = width / 2;
    const centerY = height / 2;
    const positions = {};
    const nodeMap = {};
    nodes.forEach(n => { nodeMap[n.id] = n; });
    positions[centerId] = { x: centerX, y: centerY };

    const neighbors = nodes.filter(n => n.id !== centerId);
    const groups = {};
    neighbors.forEach(n => {
        const t = n.type || 'default';
        if (!groups[t]) groups[t] = [];
        groups[t].push(n);
    });

    const groupKeys = Object.keys(groups);
    groupKeys.forEach((type, gi) => {
        const groupNodes = groups[type];
        const radius = Math.min(width, height) * 0.35;
        const baseAngle = (gi / groupKeys.length) * Math.PI * 2 - Math.PI / 2;
        const spread = groupNodes.length > 1 ? 0.3 : 0;
        groupNodes.forEach((n, ni) => {
            const angle = baseAngle + (ni - (groupNodes.length - 1) / 2) * spread / Math.max(groupNodes.length, 1);
            positions[n.id] = { x: centerX + radius * Math.cos(angle), y: centerY + radius * Math.sin(angle) };
        });
    });

    let svgParts = [];
    svgParts.push(`<defs><marker id="arrowhead" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto"><polygon points="0 0, 8 3, 0 6" fill="#94a3b8"/></marker></defs>`);

    edges.forEach(edge => {
        const sourcePos = positions[edge.source];
        const targetPos = positions[edge.target];
        if (!sourcePos || !targetPos) return;
        const dx = targetPos.x - sourcePos.x, dy = targetPos.y - sourcePos.y;
        const dist = Math.sqrt(dx * dx + dy * dy);
        const shorten = 35, shortenEnd = 35;
        const ratio1 = Math.min(shorten / dist, 0.3);
        const ratio2 = Math.min(shortenEnd / dist, 0.3);
        const sx = sourcePos.x + dx * ratio1, sy = sourcePos.y + dy * ratio1;
        const ex = sourcePos.x + dx * (1 - ratio2), ey = sourcePos.y + dy * (1 - ratio2);
        const relationLabel = RELATION_LABELS[edge.relation] || edge.relation || '';
        const midX = (sx + ex) / 2, midY = (sy + ey) / 2;
        svgParts.push(`<line class="kg-edge-line" x1="${sx}" y1="${sy}" x2="${ex}" y2="${ey}" marker-end="url(#arrowhead)"/>`);
        if (relationLabel) {
            const labelLen = relationLabel.length * 5 + 8;
            svgParts.push(`<rect x="${midX - labelLen/2}" y="${midY - 7}" width="${labelLen}" height="14" rx="3" fill="white" fill-opacity="0.9" stroke="#e2e8f0" stroke-width="0.5"/>`);
            svgParts.push(`<text class="kg-edge-label" x="${midX}" y="${midY}">${relationLabel}</text>`);
        }
    });

    nodes.forEach(node => {
        const pos = positions[node.id];
        if (!pos) return;
        const isCenter = node.id === centerId;
        const nodeType = node.type || 'default';
        const color = NODE_COLORS[nodeType] || '#64748b';
        const radius = isCenter ? 38 : 28;
        if (isCenter) svgParts.push(`<circle class="kg-center-ring" cx="${pos.x}" cy="${pos.y}" r="${radius + 8}"/>`);
        const extraClass = isCenter ? ' kg-center-node' : '';
        svgParts.push(`<circle class="kg-node-circle kg-color-${nodeType}${extraClass}" cx="${pos.x}" cy="${pos.y}" r="${radius}" fill="${color}" stroke="${color}"/>`);
        const name = (node.name || node.id).substring(0, 6);
        svgParts.push(`<text class="kg-node-label" x="${pos.x}" y="${pos.y}">${name}</text>`);
        const label = NODE_TYPE_LABELS[nodeType] || '';
        svgParts.push(`<text class="kg-node-sublabel" x="${pos.x}" y="${pos.y + radius + 12}" ${isCenter ? 'style="font-weight:600;color:' + color + '"' : ''}>${label}</text>`);
    });

    container.innerHTML = `<svg viewBox="0 0 ${width} ${height}" xmlns="http://www.w3.org/2000/svg">${svgParts.join('')}</svg>`;
}

// ============ 消息DOM操作 ============

function appendMessage(role, content) {
    const div = document.createElement('div');
    div.className = `message ${role}`;
    const avatarSvg = role === 'assistant'
        ? '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>'
        : '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>';
    div.innerHTML = `<div class="message-avatar">${avatarSvg}</div><div class="message-content">${renderMarkdown(content)}</div>`;
    chatMessages.appendChild(div);
    scrollToBottom();
    return div;
}

function scrollToBottom() {
    // 只在用户已经接近底部时自动滚动，允许用户上翻查看历史
    const threshold = 120;
    const atBottom = chatMessages.scrollHeight - chatMessages.scrollTop - chatMessages.clientHeight < threshold;
    if (atBottom) chatMessages.scrollTop = chatMessages.scrollHeight;
}

function updateSendBtn(showStop) {
    const wrapper = document.querySelector('.input-wrapper');
    const existingBtn = document.getElementById('send-btn');
    if (showStop) {
        existingBtn.style.display = 'none';
        let stopBtn = document.getElementById('stop-btn');
        if (!stopBtn) {
            stopBtn = document.createElement('button');
            stopBtn.id = 'stop-btn';
            stopBtn.className = 'stop-btn';
            stopBtn.title = '停止生成';
            stopBtn.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>';
            stopBtn.onclick = stopGeneration;
            wrapper.appendChild(stopBtn);
        }
        stopBtn.style.display = 'flex';
    } else {
        existingBtn.style.display = 'flex';
        existingBtn.disabled = false;
        const stopBtn = document.getElementById('stop-btn');
        if (stopBtn) stopBtn.style.display = 'none';
    }
}

// ============ Markdown渲染 ============

function renderMarkdown(text) {
    if (!text) return '';
    if (typeof marked !== 'undefined') {
        marked.setOptions({ breaks: true, gfm: true });
        return marked.parse(text);
    }
    return text.replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br>');
}

// ============ 键盘/输入事件 ============

userInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
});

userInput.addEventListener('input', () => {
    userInput.style.height = 'auto';
    userInput.style.height = Math.min(userInput.scrollHeight, 120) + 'px';
});

document.addEventListener('click', (e) => {
    if (!e.target.classList.contains('cite-link')) hideCiteTooltip();
});

document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeGraphModal();
});

// ============ URL 参数自动提问（从知识图谱跳转） ============
(function handleUrlQuery() {
    const params = new URLSearchParams(window.location.search);
    const q = params.get('q');
    if (q) {
        // 清除 URL 参数，避免刷新后重复提问
        window.history.replaceState({}, '', '/chat');
        // 延迟发送，等 DOM 就绪
        setTimeout(() => sendMessage(q, { allowNoSession: true }), 300);
    }
})();
