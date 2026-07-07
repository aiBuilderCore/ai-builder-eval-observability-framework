/* Observability sub-nav strip — injected into every obs page so nav order stays
   consistent across the 9 surfaces without duplicating markup. Reads the active
   tab from <body data-obs-tab="…">. Tab order matches the numbered loop
   (1 Live → 2 Batches → … → 7 Evidence) so left-to-right reading = story order. */
(function () {
  var TABS = [
    { slug: 'live',        href: './monitors.html',    label: 'Live',        num: 1 },
    { slug: 'batches',     href: './index.html',       label: 'Batches',     num: 2 },
    { slug: 'calibration', href: './calibration.html', label: 'Calibration', num: 3 },
    { slug: 'trajectory',  href: './trajectory.html',  label: 'Trajectory',  num: 4 },
    { slug: 'datasets',    href: './datasets.html',    label: 'Datasets',    num: 5 },
    { slug: 'gate',        href: './gate.html',        label: 'Gate',        num: 6 },
    { slug: 'evidence',    href: './packs.html',       label: 'Evidence',    num: 7 }
  ];

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c];
    });
  }

  function render() {
    var active = document.body.getAttribute('data-obs-tab') || '';
    var tabsHtml = TABS.map(function (t) {
      var cls = t.slug === active ? 'active' : '';
      return '<a class="' + cls + '" href="' + t.href + '" data-tab-num="' + t.num + '">' +
        '<span class="tab-num">' + t.num + '</span> ' + escapeHtml(t.label) + '</a>';
    }).join('');

    var now = new Date();
    var stamp = now.toISOString().slice(11, 19) + 'Z';

    var nav = document.createElement('nav');
    nav.className = 'subnav';
    nav.setAttribute('aria-label', 'Observability sections');
    nav.innerHTML =
      '<div class="frame row">' +
      '  <div class="tabs">' + tabsHtml + '</div>' +
      '  <div class="meta">simulation-first · <b id="last-sync">' + stamp + '</b></div>' +
      '</div>';

    var mountPoint = document.body.querySelector('[data-obs-tabs-mount]') || document.body;
    if (mountPoint === document.body) {
      var header = document.querySelector('header.top');
      if (header && header.parentNode) {
        header.parentNode.insertBefore(nav, header.nextSibling);
        return;
      }
      document.body.insertBefore(nav, document.body.firstChild);
    } else {
      mountPoint.parentNode.replaceChild(nav, mountPoint);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', render);
  } else {
    render();
  }
})();
