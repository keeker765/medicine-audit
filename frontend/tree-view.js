/**
 * 树状图视图（延迟初始化，只在切换到树状图时执行）
 * 依赖：D3.js、tree-data.js（RAW 变量）
 */

var treeInitialized = false;
var treeSvg, treeG, treeZoom, treeRoot, treeTooltip;

function initTreeView() {
  if (treeInitialized) return;
  treeInitialized = true;

  var DOMAIN_COLORS = {
    "元信息":       "#64748b",
    "药物详细信息": "#0891b2",
    "国家分级管理目录": "#0e7490",
    "级联报告规则": "#0e7490",
    "MIC折点":      "#ea580c",
    "治疗指南":     "#16a34a",
    "耐药机制":     "#dc2626",
    "天然耐药":     "#78716c",
    "覆盖菌种":     "#059669",
    "脚注":         "#64748b",
    "缩写":         "#8b5cf6",
    "参考文献":     "#64748b",
  };
  var DEFAULT_COLOR = "#94a3b8";

  function getColor(d) {
    var n = d;
    while (n) {
      if (n.data && DOMAIN_COLORS[n.data.name]) return DOMAIN_COLORS[n.data.name];
      n = n.parent;
    }
    return DEFAULT_COLOR;
  }

  var W = window.innerWidth, H = window.innerHeight - 74;
  treeSvg = d3.select("#chart").append("svg").attr("width", W).attr("height", H);
  treeG = treeSvg.append("g").attr("transform", "translate(180," + H/2 + ")");

  treeZoom = d3.zoom().scaleExtent([0.15, 4]).on("zoom", function(e) { treeG.attr("transform", e.transform); });
  treeSvg.call(treeZoom);

  var treeLayout = d3.tree().nodeSize([30, 320]);
  treeRoot = d3.hierarchy(RAW);
  treeRoot.x0 = 0; treeRoot.y0 = 0;

  treeRoot.descendants().forEach(function(d) {
    if (d.depth > 1) { d._children = d.children; d.children = null; }
  });

  treeTooltip = d3.select("#tooltip");

  function update(source) {
    var treeData = treeLayout(treeRoot);
    var nodes = treeData.descendants();
    var links = treeData.links();

    var link = treeG.selectAll(".link").data(links, function(d) { return d.target.data._key || d.target.data.name; });
    link.enter().insert("path","g").attr("class","link")
      .merge(link).transition().duration(300)
      .attr("d", d3.linkHorizontal().x(function(d){return d.y;}).y(function(d){return d.x;}));
    link.exit().remove();

    var node = treeG.selectAll(".node").data(nodes, function(d) { return d.data._key || d.data.name; });
    var enter = node.enter().append("g").attr("class", function(d) { return "node" + (d.children||d._children ? "" : " node--leaf"); })
      .attr("transform", "translate(" + (source.y0||0) + "," + (source.x0||0) + ")")
      .on("click", function(e, d) { toggle(d); update(d); })
      .on("mouseover", showTip).on("mousemove", moveTip).on("mouseout", hideTip);

    enter.append("circle").attr("r", 5);
    enter.append("text").attr("dy", "0.35em").attr("x", function(d) { return (d.children||d._children) ? -10 : 10; })
      .attr("text-anchor", function(d) { return (d.children||d._children) ? "end" : "start"; });

    var merged = enter.merge(node);
    merged.transition().duration(300).attr("transform", function(d) { return "translate(" + d.y + "," + d.x + ")"; });
    merged.select("circle")
      .attr("r", function(d) { return d.depth === 0 ? 8 : (d.children||d._children) ? 5.5 : 3.5; })
      .style("fill", function(d) { return d._children ? getColor(d) : (d.children ? "rgba(255,255,255,0.9)" : getColor(d)); })
      .style("stroke", function(d) { return getColor(d); });

    merged.select("text").text(function(d) {
      var label = d.data.name;
      if (d.data.value !== undefined) label += ": " + (String(d.data.value).length > 50 ? String(d.data.value).slice(0,50)+"..." : d.data.value);
      if (d._children) label += " [" + countLeaves(d) + "]";
      return label;
    });

    node.exit().remove();
    nodes.forEach(function(d) { d.x0 = d.x; d.y0 = d.y; });
    d3.select("#stats").text("节点: " + nodes.length + " | 深度: " + d3.max(nodes, function(d){return d.depth;}));
  }

  function countLeaves(d) { if (!d._children && !d.children) return 1; return (d._children||d.children).reduce(function(s,c){return s+countLeaves(c);},0); }
  function toggle(d) { if (d.children) { d._children = d.children; d.children = null; } else if (d._children) { d.children = d._children; d._children = null; } }

  window.expandAll = function() { treeRoot.descendants().forEach(function(d){ if(d._children){ d.children=d._children; d._children=null; }}); update(treeRoot); };
  window.collapseAll = function() { treeRoot.descendants().forEach(function(d){ if(d.depth>0 && d.children){ d._children=d.children; d.children=null; }}); update(treeRoot); };
  window.resetView = function() { treeSvg.transition().duration(500).call(treeZoom.transform, d3.zoomIdentity.translate(180,H/2)); };

  function getPath(d) { var p=[]; var n=d; while(n){ p.unshift(n.data.name); n=n.parent; } return p.join(" > "); }

  function showTip(e, d) {
    var html = '<div style="font-weight:700;color:#0891b2">' + d.data.name + '</div>';
    if (d.data._key && d.data._key !== d.data.name) html += '<div style="color:#64748b;font-size:11px">key: ' + d.data._key + '</div>';
    if (d.data.value !== undefined) html += '<div style="color:#334155">' + d.data.value + '</div>';
    if (d._children) html += '<div style="color:#0e7490">收起中，含 ' + countLeaves(d) + ' 个子项</div>';
    html += '<div style="color:#94a3b8;font-size:11px;margin-top:4px">' + getPath(d) + '</div>';
    treeTooltip.html(html).style("display","block");

    var parts = []; var n=d; while(n){ parts.unshift(n); n=n.parent; }
    d3.select("#breadcrumb").html(parts.map(function(p){ return '<span>' + p.data.name + '</span>'; }).join('<span class="sep">›</span>'));
  }
  function moveTip(e) { treeTooltip.style("left",(e.clientX+14)+"px").style("top",(e.clientY-10)+"px"); }
  function hideTip() { treeTooltip.style("display","none"); }

  /* 搜索（复用已有搜索框） */
  document.getElementById("search").addEventListener("input", function() {
    var q = this.value.trim().toLowerCase();
    treeG.selectAll(".node").classed("node--match", false);
    if (!q) return;
    treeRoot.descendants().forEach(function(d) {
      var match = d.data.name.toLowerCase().includes(q)
        || (d.data._key||"").toLowerCase().includes(q)
        || (d.data.value||"").toString().toLowerCase().includes(q);
      if (match) {
        var n = d.parent;
        while(n) { if(n._children){ n.children=n._children; n._children=null; } n=n.parent; }
      }
    });
    update(treeRoot);
    setTimeout(function() {
      treeG.selectAll(".node").classed("node--match", function(d) {
        return d.data.name.toLowerCase().includes(q)
          || (d.data._key||"").toLowerCase().includes(q)
          || (d.data.value||"").toString().toLowerCase().includes(q);
      });
    }, 350);
  });

  update(treeRoot);
  treeSvg.call(treeZoom.transform, d3.zoomIdentity.translate(180, H/2).scale(0.9));
}
