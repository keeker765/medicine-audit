/**
 * 知识图谱 graph.js
 * 三种视觉状态：默认 / 节点选中 / 边选中
 */

/* ── CDN 检查 ── */
if (typeof cytoscape === 'undefined') {
  document.getElementById('cy').innerHTML =
    '<div style="padding:40px;color:#0891b2;font-size:16px;text-align:center">' +
    'Cytoscape.js CDN 加载失败，请检查网络连接后刷新。</div>';
  throw new Error('cytoscape CDN failed');
}

/* ================================================================
   1. 常量定义
   ================================================================ */

var TYPE_COLORS = {
  Drug: '#0891b2', Organism: '#059669', ResistanceMechanism: '#dc2626',
  TreatmentPlan: '#16a34a', DrugClass: '#f59e0b', InfectionSite: '#ea580c',
  Unknown: '#64748b'
};
var TYPE_CN = {
  Drug: '药物', Organism: '菌种', ResistanceMechanism: '耐药类型',
  TreatmentPlan: '治疗方案', DrugClass: '药物类别',
  InfectionSite: '感染部位', Unknown: '未知'
};

var REL_MAP = {
  BELONGS_TO_CLASS: '药物类别', INTRINSIC_RESISTANT: '天然耐药',
  HAS_TREATMENT: '治疗方案', RECOMMENDED_FOR: '推荐用于',
  COMMON_IN: '常见于', AMPC_RISK: 'AmpC风险',
  PRODUCES: '可产生', SUBTYPE: '亚型',
  HAS_RESISTANCE: '具有耐药性', TREATED_BY: '治疗方案',
  BELONGS_TO: '药物类别', INFECTS: '感染'
};

var EDGE_COLORS = {
  '药物类别': '#0891b2', '天然耐药': '#dc2626', '治疗方案': '#16a34a',
  '推荐用于': '#8b5cf6', '常见于': '#ea580c', 'AmpC风险': '#f59e0b',
  '可产生': '#e11d48', '亚型': '#6366f1', '具有耐药性': '#be123c',
  '感染': '#78716c',
};

var _annoCache = {};
var cy = null;
var selectedNodeId = null;

/* ================================================================
   2. Cytoscape 初始化
   ================================================================ */

cy = cytoscape({
  container: document.getElementById('cy'),
  elements: [],
  layout: { name: 'preset' },
  style: CYTOSCAPE_STYLES(),
  minZoom: 0.15, maxZoom: 4,
  wheelSensitivity: 0.3,
});

function CYTOSCAPE_STYLES() {
  return [
    /* ── 默认：节点 ── */
    { selector: 'node', style: {
      'label': 'data(label)', 'font-size': '13px',
      'font-family': '"PingFang SC","Microsoft YaHei",sans-serif',
      'color': '#334155', 'text-wrap': 'wrap', 'text-max-width': '90px',
      'text-valign': 'bottom', 'text-margin-y': 8,
      'width': 30, 'height': 30,
      'border-width': 2, 'border-opacity': 0.6, 'background-opacity': 0.9,
    }},
    { selector: 'node[type="Drug"]', style: { 'background-color': '#0891b2', 'border-color': '#0891b2' }},
    { selector: 'node[type="Organism"]', style: { 'background-color': '#059669', 'border-color': '#059669' }},
    { selector: 'node[type="ResistanceMechanism"]', style: { 'background-color': '#dc2626', 'border-color': '#dc2626' }},
    { selector: 'node[type="TreatmentPlan"]', style: { 'background-color': '#16a34a', 'border-color': '#16a34a' }},
    { selector: 'node[type="DrugClass"]', style: { 'background-color': '#f59e0b', 'border-color': '#f59e0b' }},
    { selector: 'node[type="InfectionSite"]', style: { 'background-color': '#ea580c', 'border-color': '#ea580c' }},
    { selector: 'node[type="Unknown"]', style: { 'background-color': '#64748b', 'border-color': '#64748b' }},

    /* ── 默认：边 ── */
    { selector: 'edge', style: {
      'width': 1.5,
      'line-color': 'data(lineColor)', 'target-arrow-color': 'data(lineColor)',
      'target-arrow-shape': 'triangle', 'curve-style': 'bezier', 'arrow-scale': 0.8,
      'label': 'data(label)', 'font-size': '9px', 'color': '#64748b',
      'text-rotation': 'autorotate', 'text-margin-y': -10,
      'text-opacity': 0.6, 'opacity': 0.55,
    }},

    /* ── 状态 A：节点被选中 — 中心节点（白色发光环） ── */
    { selector: 'node.node-center', style: {
      'border-width': 5, 'border-color': '#ffffff',
      'background-opacity': 1, 'font-weight': 'bold',
      'z-index': 999,
    }},

    /* ── 状态 A：节点被选中 — 邻居节点（原色全亮） ── */
    { selector: 'node.node-near', style: {
      'border-width': 3, 'border-color': '#ffffff',
      'background-opacity': 1, 'z-index': 998,
    }},

    /* ── 状态 A：节点被选中 — 邻居边（原色全亮） ── */
    { selector: 'edge.node-edge', style: {
      'width': 2.5, 'opacity': 1, 'text-opacity': 0.9,
      'color': 'data(lineColor)',
      'z-index': 997,
    }},

    /* ── 状态 B：边被选中 — 边本身（加粗+原色加深） ── */
    { selector: 'edge.edge-focus', style: {
      'width': 4, 'opacity': 1, 'text-opacity': 1,
      'line-color': 'data(lineColor)', 'target-arrow-color': 'data(lineColor)',
      'color': 'data(lineColor)', 'font-weight': 'bold',
      'z-index': 999,
    }},

    /* ── 状态 B：边被选中 — 端点节点 ── */
    { selector: 'node.edge-endpoint', style: {
      'border-width': 4, 'border-color': '#0f766e',
      'background-opacity': 1, 'font-weight': 'bold',
      'z-index': 998,
    }},

    /* ── 通用：淡化 ── */
    { selector: '.dim', style: { 'opacity': 0.08 } },
  ];
}

/* ================================================================
   3. 视觉状态管理
   ================================================================ */

/** 清除所有视觉状态类 */
function resetVisual() {
  cy.elements().removeClass('node-center node-near node-edge edge-focus edge-endpoint dim');
}

/** 状态 A：点击节点 */
function visualNodeFocus(node) {
  resetVisual();
  var hood = node.closedNeighborhood();  // 节点 + 邻居 + 连接边
  var outside = cy.elements().not(hood);

  outside.addClass('dim');
  node.addClass('node-center');
  hood.nodes().not(node).addClass('node-near');
  hood.edges().addClass('node-edge');
}

/** 状态 B：点击边 */
function visualEdgeFocus(edge) {
  resetVisual();
  var endpoints = edge.connectedNodes();
  var endpointHood = endpoints.closedNeighborhood();
  var outside = cy.elements().not(endpointHood).add(edge);  // 注意：edge不在outside里

  outside.not(edge).addClass('dim');
  edge.addClass('edge-focus');
  endpoints.addClass('edge-endpoint');
}

/** 状态 C：点击背景，恢复默认 */
function visualDefault() {
  resetVisual();
}

/* ================================================================
   4. 交互事件
   ================================================================ */

/* ── 点击节点 ── */
cy.on('tap', 'node', function(e) {
  var n = e.target;
  var d = n.data();
  selectedNodeId = n.id();

  visualNodeFocus(n);
  buildNodeDetail(n);
  updateURL(n.id());
});

/* ── 点击边 ── */
cy.on('tap', 'edge', function(e) {
  var edge = e.target;
  selectedNodeId = null;

  visualEdgeFocus(edge);
  buildEdgeDetail(edge);
});

/* ── 点击背景 ── */
cy.on('tap', function(e) {
  if (e.target === cy) {
    visualDefault();
    closeDetail();
  }
});

/* ================================================================
   5. 详情面板构建
   ================================================================ */

/** 节点详情 */
function buildNodeDetail(n) {
  var d = n.data();
  var c = TYPE_COLORS[d.type] || TYPE_COLORS.Unknown;

  var h = '<button class="close-btn" onclick="closeDetail()">&#10005;</button>';
  h += '<h2>' + esc(d.label) + '</h2>';
  h += tagHTML(c, TYPE_CN[d.type] || d.type);

  /* 节点属性（动态显示所有有值的属性） */
  var SKIP_KEYS = ['id', 'label', 'type', 'english', 'drug_class', 'name'];
  var FIELD_CN = {
    mechanism: '作用机制', spectrum_text: '抗菌谱', dosing_info: '剂量',
    adverse_effects: '不良反应', key_notes: '注意事项', admin_tier: '管理分级',
    clsi_tier: 'CLSI分级', breakpoint_s: 'S折点', breakpoint_i: 'I折点',
    breakpoint_r: 'R折点', breakpoint_sdd: 'SDD折点', route: '给药途径',
    characteristics: '特征', common_infections: '常见感染',
    organism_name: '目标菌种', resistance_context: '耐药背景',
    first_line: '一线方案', alternative: '替代方案', combination: '联合方案',
    last_resort: '最后手段', oral_stepdown: '口服降阶梯', notes: '备注',
    plan_id: '方案ID', empiric_therapy: '经验治疗', duration: '疗程',
    common_pathogens: '常见病原体', category: '类别', description: '描述',
    clinical_rule: '临床规则',
  };
  var hasProps = false;
  Object.keys(d).forEach(function(k) {
    if (SKIP_KEYS.indexOf(k) >= 0 || !d[k]) return;
    var label = FIELD_CN[k] || k;
    var val = String(d[k]);
    hasProps = true;
    h += '<div style="margin-top:6px"><b style="color:#475569;font-size:12px">' + esc(label) + '</b>' +
      '<div style="color:#334155;font-size:12px;line-height:1.6;margin-top:2px;padding:4px 8px;background:#f8fafc;border-radius:4px">' + esc(val) + '</div></div>';
  });

  if (d.english) h += '<div style="margin-top:8px;color:#64748b">English: ' + esc(d.english) + '</div>';
  if (d.drug_class) h += '<div style="color:#64748b">类别: ' + esc(d.drug_class) + '</div>';

  /* 关联实体 */
  var nodes = n.neighborhood().filter('node');
  if (nodes.length) {
    h += sectionTitle('关联实体');
    nodes.forEach(function(nb) {
      var nc = TYPE_COLORS[nb.data().type] || TYPE_COLORS.Unknown;
      h += tagSpan(nc, nb.data().label, nb.data().id);
    });
  }

  /* 关系分组 */
  var edges = n.connectedEdges();
  if (edges.length) {
    var groups = groupEdgesByRelation(edges, n);
    h += sectionTitle('关系列表');
    Object.keys(groups).forEach(function(rel) {
      var items = groups[rel];
      h += '<div style="margin:6px 0"><b style="color:#0891b2">' + esc(rel) + '</b> (' + items.length + '条)：';
      h += items.map(function(it) { return clickableName(it.other, it.otherId); }).join('、');
      h += '</div>';
    });
  }

  /* 展开按钮 */
  h += expandButton();

  showDetail(h);
}

/** 边详情（含 AI 注释） */
function buildEdgeDetail(edge) {
  var src = edge.source().data().label;
  var tgt = edge.target().data().label;
  var rel = edge.data().label;

  var h = '<button class="close-btn" onclick="closeDetail()">&#10005;</button>';
  h += '<h2 style="font-size:15px">' + esc(rel) + '</h2>';
  h += '<div style="font-size:14px;color:#334155;margin:8px 0">' +
    '<b style="color:#0891b2">' + esc(src) + '</b>' +
    ' <span style="color:#0891b2;font-weight:700">&rarr;</span> ' +
    '<b style="color:#0891b2">' + esc(tgt) + '</b></div>';

  /* AI 注释 */
  var cardId = 'anno-' + Math.random().toString(36).slice(2, 8);
  h += '<div class="anno-card" id="' + cardId + '">';
  h += '<div class="anno-title">' + esc(rel) + '</div>';
  h += '<div class="anno-loading">正在生成注释...</div>';
  h += '</div>';

  showDetail(h);

  /* 异步加载 */
  loadAnnotation(rel, src, tgt, function(text) {
    var card = document.getElementById(cardId);
    if (card) card.innerHTML = '<div class="anno-title">' + esc(rel) + '</div><div class="anno-desc">' + text + '</div>';
  });
}

/* ── 面板工具函数 ── */
function tagHTML(color, text) {
  return '<div class="tag" style="background:' + color + ';color:#fff;border-color:' + color + '">' + esc(text) + '</div>';
}
function tagSpan(color, label, id) {
  return '<span class="tag" style="background:' + color + '22;color:' + color + ';border-color:' + color + '" onclick="loadNode(\'' + escA(id) + '\')">' + esc(label) + '</span> ';
}
function clickableName(label, id) {
  return '<span style="color:#334155;cursor:pointer" onclick="loadNode(\'' + escA(id) + '\')">' + esc(label) + '</span>';
}
function sectionTitle(text) {
  return '<div class="section"><div class="section-title">' + text + '</div>';
}
function expandButton() {
  return '<div style="margin-top:12px;padding-top:10px;border-top:1px solid #e2e8f0">' +
    '<button class="expand-btn" onclick="expandNode()">' +
    '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">' +
    '<circle cx="12" cy="12" r="3"/><circle cx="12" cy="12" r="8" stroke-dasharray="4 2"/></svg>' +
    ' 展开邻居</button></div>';
}
function groupEdgesByRelation(edges, centerNode) {
  var grouped = {};
  edges.forEach(function(edge) {
    var rel = edge.data().label;
    if (!grouped[rel]) grouped[rel] = [];
    var isSrc = edge.source().id() === centerNode.id();
    grouped[rel].push({
      other: isSrc ? edge.target().data().label : edge.source().data().label,
      otherId: isSrc ? edge.target().id() : edge.source().id(),
    });
  });
  return grouped;
}
function showDetail(html) {
  var detail = document.getElementById('detail');
  detail.innerHTML = html;
  detail.style.display = 'block';
}
function closeDetail() {
  document.getElementById('detail').style.display = 'none';
  visualDefault();
}

/* ================================================================
   6. AI 注释
   ================================================================ */

function loadAnnotation(relLabel, source, target, callback) {
  if (!relLabel) { callback(''); return; }
  var key = source + '→' + target + '→' + relLabel;
  if (_annoCache[key]) { callback(_annoCache[key]); return; }

  fetch('/api/graph/explain', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ source: source, target: target, relation: relLabel }),
  })
  .then(function(r) { return r.json(); })
  .then(function(data) {
    var text = data.explanation || '';
    _annoCache[key] = text;
    callback(text);
  })
  .catch(function() { callback('注释生成失败'); });
}

/* ================================================================
   7. 过滤 / 搜索
   ================================================================ */

function filterType(btn, type) {
  document.querySelectorAll('#toolbar .btn[data-filter]').forEach(function(b) { b.classList.remove('active'); });
  btn.classList.add('active');
  resetVisual();
  if (type === 'all') return;
  cy.elements().addClass('dim');
  var match = cy.nodes('[type="' + type + '"]');
  match.removeClass('dim');
  match.connectedEdges().removeClass('dim');
  match.neighborhood().removeClass('dim');
}

/* 过滤按钮绑定 */
document.querySelectorAll('#toolbar .btn[data-filter]').forEach(function(btn) {
  btn.addEventListener('click', function() { filterType(btn, btn.dataset.filter); });
});

/* 搜索 */
var searchTimer = null;
var resultsEl = document.getElementById('search-results');

document.getElementById('search').addEventListener('input', function() {
  var q = this.value.trim();
  clearTimeout(searchTimer);
  if (!q) { resultsEl.style.display = 'none'; return; }
  searchTimer = setTimeout(function() { doSearch(q); }, 300);
});

document.getElementById('search').addEventListener('keydown', function(e) {
  if (e.key === 'Enter') { e.preventDefault(); var q = this.value.trim(); if (q) { resultsEl.style.display = 'none'; loadNode(q); }}
});

document.addEventListener('click', function(e) {
  if (!e.target.closest('.search-wrap')) resultsEl.style.display = 'none';
});

function doSearch(query) {
  fetch('/api/graph/search?q=' + encodeURIComponent(query) + '&limit=10')
  .then(function(r) { return r.json(); })
  .then(function(data) {
    var results = data.results || [];
    if (results.length === 0) {
      resultsEl.innerHTML = '<div class="search-no-results">无匹配结果</div>';
    } else {
      resultsEl.innerHTML = results.map(function(r) {
        var c = TYPE_COLORS[r.type] || TYPE_COLORS.Unknown;
        return '<div class="search-result-item" onclick="loadNode(\'' + escA(r.name) + '\')">' +
          '<div class="search-result-dot" style="background:' + c + '"></div>' +
          '<div><div class="search-result-name">' + esc(r.name) + '</div>' +
          '<div class="search-result-type">' + (TYPE_CN[r.type] || r.type || '') + '</div></div></div>';
      }).join('');
    }
    resultsEl.style.display = 'block';
  }).catch(function() {});
}

/* ================================================================
   8. 数据加载
   ================================================================ */

function loadFullGraph() {
  fetch('/api/graph/all')
  .then(function(r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
  .then(function(data) {
    var elements = buildAllElements(data);
    cy.elements().remove();
    cy.add(elements);
    cy.layout({
      name: 'cose', animate: false,
      nodeDimensionsIncludeLabels: true,
      nodeRepulsion: function() { return 18000; },
      idealEdgeLength: function() { return 200; },
      gravity: 0.08, numIter: 2000, initialTemp: 300,
      coolingFactor: 0.95,
    }).run();
    cy.fit(undefined, 30);
    updateStats();
  })
  .catch(function(err) {
    console.error('全图加载失败:', err);
    /* 失败时降级加载单个节点 */
    loadNode('美罗培南');
  });
}

function buildAllElements(data) {
  var els = [], nodeSet = {};
  (data.nodes || []).forEach(function(n) {
    if (!n.name || nodeSet[n.name]) return;
    nodeSet[n.name] = true;
    var nd = { id: n.name, label: n.name, type: n.type || 'Unknown' };
    Object.keys(n).forEach(function(k) { if (n[k] && k !== 'name' && k !== 'type') nd[k] = n[k]; });
    els.push({ group: 'nodes', data: nd });
  });
  (data.edges || []).forEach(function(e, i) {
    if (!nodeSet[e.source] || !nodeSet[e.target]) return;
    var rl = REL_MAP[e.relation] || e.relation;
    els.push({ group: 'edges', data: {
      id: e.source + '->' + e.target + '->' + (e.relation || i),
      source: e.source, target: e.target,
      label: rl, relation: e.relation,
      lineColor: EDGE_COLORS[rl] || '#94a3b8',
    }});
  });
  return els;
}

function loadNode(nodeName) {
  resultsEl.style.display = 'none';
  document.getElementById('search').value = nodeName;

  /* 如果全图已加载，直接聚焦到该节点 */
  var existing = cy.getElementById(nodeName);
  if (existing.length) {
    selectedNodeId = nodeName;
    visualNodeFocus(existing);
    buildNodeDetail(existing);
    cy.animate({ fit: { eles: existing.closedNeighborhood(), padding: 60 } }, { duration: 400 });
    updateURL(nodeName);
    return;
  }

  fetch('/api/graph/node?node_name=' + encodeURIComponent(nodeName))
  .then(function(r) { if (r.status === 404) return null; if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
  .then(function(data) {
    if (!data || !data.node) return;
    selectedNodeId = data.node.name;
    renderGraph(data);
    var nodeEl = cy.getElementById(data.node.name);
    if (nodeEl.length) {
      nodeEl.select();
      visualNodeFocus(nodeEl);
      buildNodeDetail(nodeEl);
    }
    updateURL(nodeName);
  })
  .catch(function(err) { console.error('加载失败:', err); });
}

function expandNode() {
  if (!selectedNodeId) return;
  fetch('/api/graph/expand?node_name=' + encodeURIComponent(selectedNodeId))
  .then(function(r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
  .then(function(data) { mergeGraphData(data); })
  .catch(function(err) { console.error('展开失败:', err); });
}

/* ================================================================
   9. 渲染
   ================================================================ */

function renderGraph(data) {
  var elements = buildElements(data);
  cy.elements().remove();
  cy.add(elements);
  cy.layout({
    name: 'cose', animate: false,
    nodeDimensionsIncludeLabels: true,
    nodeRepulsion: function() { return 8500; },
    idealEdgeLength: function() { return 160; },
    gravity: 0.25, numIter: 1000, initialTemp: 200,
  }).run();
  cy.fit(undefined, 50);
  updateStats();
}

function mergeGraphData(data) {
  if (!data.node) return;
  var elements = buildElements(data);
  var newEls = elements.filter(function(el) { return !cy.getElementById(el.data.id).length; });
  if (!newEls.length) return;
  cy.add(newEls);
  cy.layout({
    name: 'cose', animate: true, animationDuration: 400,
    nodeRepulsion: function() { return 8500; },
    idealEdgeLength: function() { return 160; },
    gravity: 0.25, randomize: false,
  }).run();
  setTimeout(function() { cy.fit(undefined, 50); }, 500);
  updateStats();
}

function buildElements(data) {
  var els = [], nodeSet = {};
  if (data.node) {
    var id = data.node.name;
    nodeSet[id] = true;
    var nodeData = {
      id: id, label: data.node.name,
      type: data.node.type || 'Unknown',
    };
    // 保留所有属性
    Object.keys(data.node).forEach(function(k) { if (data.node[k]) nodeData[k] = data.node[k]; });
    els.push({ group: 'nodes', data: nodeData });
  }
  if (data.neighbors) {
    data.neighbors.forEach(function(n) {
      if (!nodeSet[n.name]) {
        nodeSet[n.name] = true;
        var nbData = {
          id: n.name, label: n.name,
          type: n.type || 'Unknown',
        };
        Object.keys(n).forEach(function(k) { if (n[k]) nbData[k] = n[k]; });
        els.push({ group: 'nodes', data: nbData });
      }
    });
  }
  if (data.edges) {
    data.edges.forEach(function(e, i) {
      var rl = REL_MAP[e.relation] || e.relation;
      els.push({ group: 'edges', data: {
        id: e.source + '->' + e.target + '->' + (e.relation || i),
        source: e.source, target: e.target,
        label: rl, relation: e.relation,
        lineColor: EDGE_COLORS[rl] || '#94a3b8',
      }});
    });
  }
  return els;
}

/* ================================================================
   10. 图例 / 统计 / URL / 工具
   ================================================================ */

function fitGraph() { cy.fit(undefined, 50); }
function toggleLegend() { var p = document.getElementById('legend-panel'); p.style.display = p.style.display === 'none' ? 'block' : 'none'; }

/* 图例 */
(function() {
  var types = [
    ['Drug', '药物', '#0891b2'], ['Organism', '菌种', '#059669'],
    ['ResistanceMechanism', '耐药类型', '#dc2626'], ['TreatmentPlan', '治疗方案', '#16a34a'],
    ['DrugClass', '药物类别', '#f59e0b'], ['InfectionSite', '感染部位', '#ea580c'],
  ];
  var h = '';
  types.forEach(function(t) { h += '<div class="legend-item"><div class="legend-dot" style="background:' + t[2] + '"></div>' + t[1] + '</div>'; });
  document.getElementById('legend-items').innerHTML = h;
})();

function updateStats() {
  document.getElementById('stats').textContent = '节点: ' + cy.nodes().length + ' | 边: ' + cy.edges().length;
}

/* URL 参数 / 默认加载 */
(function() {
  var viewParam = new URLSearchParams(window.location.search).get('view');
  if (viewParam === 'tree') return;  // 树状图模式不需要加载节点

  var node = new URLSearchParams(window.location.search).get('node');
  if (node) {
    loadNode(node);
  } else {
    /* 默认加载全图 */
    loadFullGraph();
  }
})();

function updateURL(name) {
  var url = new URL(window.location);
  url.searchParams.set('node', name);
  window.history.replaceState(null, '', url);
}

/* 转义 */
function esc(t) { if (!t) return ''; var d = document.createElement('div'); d.textContent = t; return d.innerHTML; }
function escA(t) { return (t||'').replace(/&/g,'&amp;').replace(/'/g,'&#39;').replace(/"/g,'&quot;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

/* ================================================================
   11. 视图切换（实体图 ↔ 树状图）
   ================================================================ */

var currentView = 'graph';

function switchView(view) {
  if (view === currentView) return;
  currentView = view;

  var cyEl = document.getElementById('cy');
  var chartEl = document.getElementById('chart');
  var graphBtns = document.getElementById('graph-btns');
  var treeBtns = document.getElementById('tree-btns');
  var btnTree = document.getElementById('btn-tree');
  var btnGraph = document.getElementById('btn-graph');
  var breadcrumb = document.getElementById('breadcrumb');
  var legendPanel = document.getElementById('legend-panel');
  var detailPanel = document.getElementById('detail');
  var searchResults = document.getElementById('search-results');
  var title = document.getElementById('page-title');

  if (view === 'tree') {
    /* 切换到树状图 */
    cyEl.style.display = 'none';
    chartEl.style.display = 'block';
    graphBtns.style.display = 'none';
    treeBtns.style.display = 'flex';
    btnTree.style.display = 'none';
    btnGraph.style.display = 'inline-block';
    breadcrumb.style.display = 'block';
    legendPanel.style.display = 'none';
    detailPanel.style.display = 'none';
    searchResults.style.display = 'none';
    title.textContent = '知识库树状图';
    document.getElementById('search').placeholder = '搜索节点名或键名…';

    /* 延迟初始化树状图 */
    initTreeView();
  } else {
    /* 切换到实体图 */
    cyEl.style.display = 'block';
    chartEl.style.display = 'none';
    graphBtns.style.display = 'flex';
    treeBtns.style.display = 'none';
    btnTree.style.display = 'inline-block';
    btnGraph.style.display = 'none';
    breadcrumb.style.display = 'none';
    title.textContent = '实体关系图';
    document.getElementById('search').placeholder = '搜索节点…';
    document.getElementById('tooltip').style.display = 'none';

    visualDefault();
    if (cy.nodes().length) cy.fit(undefined, 50);
  }
}

/* URL 参数支持 ?view=tree */
(function() {
  var viewParam = new URLSearchParams(window.location.search).get('view');
  if (viewParam === 'tree') switchView('tree');
})();
