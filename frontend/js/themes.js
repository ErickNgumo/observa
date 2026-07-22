// Curated visual themes. This module only updates presentation tokens and
// Lightweight Charts options; replay state and event processing are untouched.
var observaThemes = {
  midnight: { canvas:'#0a0f19', surface:'#101725', raised:'#141d2d', hover:'#1b2638', text:'#ecf4ff', muted:'#8f9db1', faint:'#5b6a80', border:'#263246', strong:'#34445c', accent:'#3dd8d2', accentStrong:'#25bcb8', accentInk:'#062326', positive:'#39c589', negative:'#f06c77', grid:'#18243a', chart:'#0a0f19' },
  carbon: { canvas:'#111214', surface:'#181a1e', raised:'#202329', hover:'#292d33', text:'#f4f5f6', muted:'#a0a5ae', faint:'#707680', border:'#30343a', strong:'#454a52', accent:'#79d5ff', accentStrong:'#52bfe8', accentInk:'#08202b', positive:'#65ce9a', negative:'#f17c83', grid:'#23262c', chart:'#111214' },
  graphite: { canvas:'#17191d', surface:'#202329', raised:'#292d34', hover:'#333841', text:'#f1f3f5', muted:'#a5abb5', faint:'#777e89', border:'#393e47', strong:'#505762', accent:'#a6d189', accentStrong:'#87bb6d', accentInk:'#132211', positive:'#8bd17c', negative:'#ee7f86', grid:'#292e36', chart:'#17191d' },
  navy: { canvas:'#091526', surface:'#0d1d33', raised:'#132743', hover:'#1a3353', text:'#eaf3ff', muted:'#94a8c3', faint:'#607a9d', border:'#203a5a', strong:'#315176', accent:'#70b7ff', accentStrong:'#4e9ce8', accentInk:'#071b35', positive:'#43c6a2', negative:'#fb7785', grid:'#142b49', chart:'#091526' },
  oled: { canvas:'#000000', surface:'#080a0d', raised:'#101318', hover:'#191d23', text:'#f3f6f8', muted:'#9da6b2', faint:'#68727e', border:'#222831', strong:'#3a424e', accent:'#68e4dc', accentStrong:'#42c7c0', accentInk:'#062322', positive:'#4bd495', negative:'#ff707c', grid:'#151a20', chart:'#000000' },
  paper: { canvas:'#f7f6f2', surface:'#ffffff', raised:'#fbfaf7', hover:'#f1f0eb', text:'#1b2530', muted:'#627080', faint:'#89939d', border:'#dfe2df', strong:'#c5cac7', accent:'#087f82', accentStrong:'#05696c', accentInk:'#e7ffff', positive:'#16875d', negative:'#c74352', grid:'#ebebe6', chart:'#fdfcf9' },
  snow: { canvas:'#f3f7fb', surface:'#ffffff', raised:'#f8fbff', hover:'#eef4fa', text:'#172231', muted:'#617187', faint:'#8492a5', border:'#d9e2ec', strong:'#bbc8d7', accent:'#057dba', accentStrong:'#006ca6', accentInk:'#edfbff', positive:'#078860', negative:'#c94758', grid:'#e6edf4', chart:'#ffffff' },
  studio: { canvas:'#f1f0ec', surface:'#f9f8f5', raised:'#ffffff', hover:'#eceae4', text:'#282724', muted:'#706f69', faint:'#96938b', border:'#dedbd3', strong:'#c8c3b9', accent:'#966d00', accentStrong:'#795800', accentInk:'#fff8df', positive:'#287b53', negative:'#b94d52', grid:'#e9e5dc', chart:'#f7f6f2' }
};

function chartThemeOptions(theme) {
  return { layout:{ background:{color:theme.chart}, textColor:theme.muted }, grid:{ vertLines:{color:theme.grid}, horzLines:{color:theme.grid} }, rightPriceScale:{borderColor:theme.border}, timeScale:{borderColor:theme.border} };
}

function setTheme(name) {
  var theme = observaThemes[name] || observaThemes.midnight;
  var root = document.documentElement.style;
  root.setProperty('--canvas', theme.canvas); root.setProperty('--surface', theme.surface); root.setProperty('--surface-raised', theme.raised); root.setProperty('--surface-hover', theme.hover); root.setProperty('--text', theme.text); root.setProperty('--muted', theme.muted); root.setProperty('--faint', theme.faint); root.setProperty('--border', theme.border); root.setProperty('--border-strong', theme.strong); root.setProperty('--accent', theme.accent); root.setProperty('--accent-strong', theme.accentStrong); root.setProperty('--accent-ink', theme.accentInk); root.setProperty('--positive', theme.positive); root.setProperty('--negative', theme.negative); root.setProperty('--chart-grid', theme.grid); root.setProperty('--chart-bg', theme.chart);
  if (chart && equityChart) {
    chart.applyOptions(chartThemeOptions(theme)); equityChart.applyOptions(chartThemeOptions(theme));
    candleSeries.applyOptions({upColor:theme.positive, downColor:theme.negative, borderUpColor:theme.positive, borderDownColor:theme.negative, wickUpColor:theme.positive, wickDownColor:theme.negative});
    fastEmaSeries.applyOptions({color:theme.accent}); slowEmaSeries.applyOptions({color:'#e59b67'}); equitySeries.applyOptions({color:theme.positive});
  }
  try { sessionStorage.setItem('observa-theme', name); } catch (e) {}
}

function restoreTheme() {
  var name = 'midnight'; try { name = sessionStorage.getItem('observa-theme') || name; } catch (e) {}
  var select = document.getElementById('theme-select'); if (select) select.value = name; setTheme(name);
}
