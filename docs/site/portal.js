(function () {
  'use strict';
  // The only content sources are reviewed files below. Never derive an iframe URL from a hash.
  var pages = Object.freeze({
    overview: { file: 'overview.html', title: '项目概览', tag: '当前项目概览', kind: 'current', description: '研究进展、机制与限制；有限验收不是生产安全证书。' },
    flower: { file: 'flower.html', title: 'REDTEAM Flower', tag: '非金融 · 本地研究原型', kind: 'prototype', description: '仅合成材料与无分叉 Hardhat 31337；无销售、收益或权益，公开发行待专业审查。' },
    resources: { file: 'resources.html', title: '研究与商业资料', tag: '当前文档与证据', kind: 'current', description: '当前 Markdown 优先；历史 PDF 与归档材料不代表当前产品或实验结论。' },
    brief: { file: 'archive-brief.html', title: '历史项目简述', tag: '历史归档 · 非当前口径', kind: 'historic', description: '保留历史表达供追溯；旧资产、奖励与实验说法不能作为当前承诺。请以项目概览与当前文档为准。' },
    introduction: { file: 'archive-introduction.html', title: '历史完整介绍', tag: '历史归档 · 非当前口径', kind: 'historic', description: '保留历史表达供追溯；旧资产、奖励与实验说法不能作为当前承诺。请以项目概览与当前文档为准。' }
  });
  var frame = document.getElementById('content-frame');
  if (!frame) { return; }
  var menu = document.querySelector('.site-menu');
  var links = Array.prototype.slice.call(menu.querySelectorAll('a[data-route]'));
  var title = document.getElementById('page-title');
  var tag = document.getElementById('page-tag');
  var description = document.getElementById('page-description');
  var status = document.getElementById('portal-status');
  var direct = document.getElementById('direct-link');
  var viewer = document.getElementById('page-viewer');
  var retry = document.getElementById('retry-button');
  // These two roots are the source/build contract; reject all other roots, including cross-origin ones.
  var root = document.body.dataset.pageRoot === './docs/site/' ? './docs/site/' : './';
  var urls = {};
  Object.keys(pages).forEach(function (key) { urls[key] = new URL(root + pages[key].file, document.baseURI); });
  var active = null;
  var expected = null;
  var requestId = 0;
  var timeout = null;
  var controller = null;
  var loadedDocument = null;
  var frameReady = false;
  var httpReady = false;
  var failed = false;
  var section = '';

  function hasRoute(route) { return Object.prototype.hasOwnProperty.call(pages, route); }
  function routeFromHash(hash) { var key = hash.slice(1); return hasRoute(key) ? key : 'overview'; }
  function sameFile(a, b) { return a.origin === b.origin && a.pathname === b.pathname && a.search === b.search; }
  function unmodified(event) { return !event.defaultPrevented && event.button === 0 && !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey; }
  function setStatus(text, state) { status.textContent = text; status.dataset.state = state; }
  function finish() {
    if (failed || !frameReady || !httpReady) { return; }
    window.clearTimeout(timeout);
    viewer.setAttribute('aria-busy', 'false');
    setStatus('已加载：' + pages[active].title + '。可在下方阅读，或直接打开完整页面。', 'ready');
    retry.hidden = true;
  }
  function fail(text) {
    failed = true;
    window.clearTimeout(timeout);
    if (controller) { controller.abort(); }
    viewer.setAttribute('aria-busy', 'false');
    setStatus(text + ' 请使用“直接打开本页”，或重新加载。', 'error');
    retry.hidden = false;
  }
  function revealSection(doc) {
    if (!section) { return; }
    var id;
    try { id = decodeURIComponent(section.slice(1)); } catch (error) { id = ''; }
    var anchor = doc.getElementById(id);
    if (anchor) { anchor.scrollIntoView(); }
    section = '';
  }
  function navigate(route, hash) {
    section = hash || '';
    if (active === route) {
      try { revealSection(frame.contentDocument); } catch (error) { /* Direct opening remains available. */ }
      return;
    }
    window.location.hash = route;
  }
  function interceptChildLinks(doc) {
    doc.addEventListener('click', function (event) {
      if (!unmodified(event)) { return; }
      var link = event.target.closest ? event.target.closest('a[href]') : null;
      if (!link || link.hasAttribute('download') || (link.target && link.target !== '_self')) { return; }
      var url;
      try { url = new URL(link.getAttribute('href'), doc.baseURI); } catch (error) { return; }
      var current = new URL(doc.URL);
      // Local section links must remain native, including accessible skip links.
      if (sameFile(url, current) && url.hash) { return; }
      var route = Object.keys(urls).find(function (key) { return sameFile(url, urls[key]); });
      var portal = new URL(root + 'index.html', document.baseURI);
      var outer = new URL(document.baseURI);
      if (sameFile(url, portal) || sameFile(url, outer)) {
        route = routeFromHash(url.hash);
        event.preventDefault();
        navigate(route, hasRoute(url.hash.slice(1)) ? '' : url.hash);
      } else if (route) {
        event.preventDefault();
        navigate(route, url.hash);
      } else if (url.protocol === 'https:' || url.protocol === 'http:') {
        // Source documents and other non-menu destinations open outside the shell.
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
      }
    });
  }
  function onLoad() {
    if (!active || failed) { return; }
    try {
      var doc = frame.contentDocument;
      if (!doc) { throw new Error('unreadable'); }
      var url = new URL(doc.URL);
      if (!sameFile(url, expected)) { return; } // Ignore blank/earlier route loads.
      if (!doc.body || !doc.title) { throw new Error('unreadable'); }
      if (loadedDocument !== doc) { interceptChildLinks(doc); loadedDocument = doc; }
      frameReady = true;
      revealSection(doc);
      finish();
    } catch (error) {
      fail('浏览器未允许确认内嵌页面；通过 HTTP 服务或独立页面阅读。');
    }
  }
  function render(force) {
    var route = routeFromHash(window.location.hash);
    if (active === route && !force) { return; }
    active = route;
    expected = urls[route];
    requestId += 1;
    var thisRequest = requestId;
    if (controller) { controller.abort(); }
    window.clearTimeout(timeout);
    frameReady = false;
    httpReady = window.location.protocol === 'file:';
    failed = false;
    var page = pages[route];
    title.textContent = page.title;
    document.title = page.title + '｜REDTEAM 研究门户';
    tag.textContent = page.tag;
    tag.dataset.kind = page.kind;
    description.textContent = page.description;
    direct.href = expected.href;
    frame.title = page.title + ' — REDTEAM';
    links.forEach(function (link) {
      link.href = urls[link.dataset.route].href;
      if (link.dataset.route === route) {
        link.setAttribute('aria-current', 'page');
        link.scrollIntoView({ block: 'nearest', inline: 'nearest' });
      } else { link.removeAttribute('aria-current'); }
    });
    viewer.setAttribute('aria-busy', 'true');
    setStatus('正在加载：' + page.title + '… 若加载受限，可直接打开本页。', 'loading');
    retry.hidden = true;
    timeout = window.setTimeout(function () {
      if (thisRequest === requestId) { fail('页面尚未完成加载或确认。'); }
    }, 15000);
    // Replacing frame history keeps the outer hash as the menu's back/forward history.
    try { frame.contentWindow.location.replace(expected.href); }
    catch (error) { frame.src = expected.href; }
    if (!httpReady) {
      controller = new AbortController();
      window.fetch(expected.href, { credentials: 'omit', signal: controller.signal }).then(function (response) {
        if (thisRequest !== requestId || failed) { return; }
        if (!response.ok) { fail('页面请求失败（HTTP ' + response.status + '）。'); return; }
        var type = response.headers.get('content-type') || '';
        if (type && !/text\/html|application\/xhtml\+xml/i.test(type)) { fail('页面返回格式不是 HTML。'); return; }
        httpReady = true;
        finish();
      }).catch(function (error) {
        if (thisRequest === requestId && !failed && error.name !== 'AbortError') { fail('页面请求失败或网络不可用。'); }
      });
    }
  }
  menu.addEventListener('click', function (event) {
    if (!unmodified(event)) { return; }
    var link = event.target.closest ? event.target.closest('a[data-route]') : null;
    if (!link || !menu.contains(link) || !hasRoute(link.dataset.route)) { return; }
    event.preventDefault();
    navigate(link.dataset.route);
  });
  document.querySelector('.skip-link').addEventListener('click', function (event) {
    if (!unmodified(event)) { return; }
    event.preventDefault();
    document.getElementById('portal-main').focus();
  });
  retry.addEventListener('click', function () { render(true); });
  frame.addEventListener('load', onLoad);
  frame.addEventListener('error', function () { fail('内嵌页面加载失败。'); });
  window.addEventListener('hashchange', function () { render(false); });
  window.addEventListener('pagehide', function () { window.clearTimeout(timeout); if (controller) { controller.abort(); } });
  render(false);
}());
