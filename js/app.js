let allEvents = [];
let updateData = { newEventIds: [] };
let storeData = {};
let activeView = 'events';
let activeBrand = null;
let activeTodayOnly = false;
let activeQuickFilter = null;

const DATA_CACHE_BUST = Date.now().toString(36);

const BRAND_LABELS = {
  pokemon: 'Pokémon',
  miffy: 'Miffy',
  chiikawa: 'Chiikawa'
};

const BRAND_ORDER = ['pokemon', 'miffy', 'chiikawa'];

const TYPE_LABELS = {
  popup: '快閃店',
  new_product: '新商品',
  campaign: '活動',
  store: '常設店',
  cafe: '咖啡廳',
  lottery: '抽選',
  reservation: '預約'
};

const CITY_LABELS = {
  Tokyo: '東京', Osaka: '大阪', Kyoto: '京都', Fukuoka: '福岡', Nagoya: '名古屋',
  Nagasaki: '長崎', Saitama: '埼玉', Hokkaido: '北海道', Okinawa: '沖繩',
  Kanagawa: '神奈川', Hyogo: '兵庫', Hiroshima: '廣島', Mie: '三重',
  Miyagi: '宮城', Chiba: '千葉', Aomori: '青森', Akita: '秋田', Aichi: '愛知',
  Hyougo: '兵庫', Shizuoka: '靜岡', Ibaraki: '茨城', Tochigi: '栃木',
  Gunma: '群馬', Nara: '奈良', Shiga: '滋賀', Okayama: '岡山',
  Kumamoto: '熊本', Ishikawa: '石川', Niigata: '新潟', Nagano: '長野',
  Gifu: '岐阜', Kochi: '高知', Ehime: '愛媛', Yamaguchi: '山口',
  Wakayama: '和歌山', Fukushima: '福島', Kagoshima: '鹿兒島',
  Iwate: '岩手', Toyama: '富山', Fukui: '福井', Miyazaki: '宮崎',
  Yamanashi: '山梨', Taipei: '台北', Taichung: '台中', Kaohsiung: '高雄',
  Tainan: '台南', Taoyuan: '桃園', Hsinchu: '新竹', Keelung: '基隆'
};

const HTML_ESCAPES = {
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#039;'
};

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, character => HTML_ESCAPES[character]);
}

function escapeAttr(value) {
  return escapeHtml(value);
}

function icon(name, className = 'ui-icon') {
  return `<svg class="${escapeAttr(className)}" aria-hidden="true"><use href="#icon-${escapeAttr(name)}"></use></svg>`;
}

function safeSourceUrl(value) {
  try {
    const url = new URL(value, window.location.href);
    return ['http:', 'https:'].includes(url.protocol) ? url.href : '#';
  } catch (error) {
    return '#';
  }
}

function localDateKey(date = new Date()) {
  const pad = value => String(value).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

function today() {
  return localDateKey();
}

function dataUrl(path) {
  const separator = path.includes('?') ? '&' : '?';
  return `${path}${separator}v=${DATA_CACHE_BUST}`;
}

function daysUntilEnd(endDate) {
  if (!endDate) return null;
  const end = new Date(`${endDate}T23:59:59`);
  const now = new Date(`${today()}T00:00:00`);
  return Math.floor((end - now) / 86400000);
}

function dayKey(date) {
  return date ? new Date(`${date}T00:00:00`).getTime() : Number.MAX_SAFE_INTEGER;
}

function eventSortKey(event) {
  const hasEnd = Boolean(event.endDate);
  const isFuture = event.startDate && event.startDate > today();
  return [
    hasEnd ? 0 : 1,
    hasEnd ? dayKey(event.endDate) : dayKey(event.startDate),
    isFuture ? 0 : 1,
    dayKey(event.startDate),
    BRAND_LABELS[event.brand] || event.brand,
    event.title || ''
  ];
}

function compareEvents(a, b) {
  const aKey = eventSortKey(a);
  const bKey = eventSortKey(b);
  for (let index = 0; index < aKey.length; index += 1) {
    if (aKey[index] < bKey[index]) return -1;
    if (aKey[index] > bKey[index]) return 1;
  }
  return 0;
}

function compareTodayEvents(a, b) {
  const aBrand = BRAND_ORDER.indexOf(a.brand);
  const bBrand = BRAND_ORDER.indexOf(b.brand);
  return aBrand === bBrand ? compareEvents(a, b) : aBrand - bBrand;
}

function isActive(event) {
  return !event.endDate || event.endDate >= today();
}

function formatDate(value) {
  if (!value) return '';
  const [year, month, day] = value.split('-');
  return `${year}.${month}.${day}`;
}

function dateRange(event) {
  if (!event.startDate && !event.endDate) return '日期未定';
  if (event.startDate && !event.endDate) return `${formatDate(event.startDate)} 起`;
  if (!event.startDate && event.endDate) return `至 ${formatDate(event.endDate)}`;
  if (event.startDate.slice(0, 4) === event.endDate.slice(0, 4)) {
    return `${formatDate(event.startDate)} – ${event.endDate.slice(5).replace('-', '.')}`;
  }
  return `${formatDate(event.startDate)} – ${formatDate(event.endDate)}`;
}

function eventLocation(event) {
  return [CITY_LABELS[event.city] || event.city, event.locationName].filter(Boolean).join(' · ');
}

function getTodayUpdateIds() {
  return new Set(Array.isArray(updateData.newEventIds) ? updateData.newEventIds : []);
}

function matchesQuickFilter(event) {
  if (!activeQuickFilter) return true;
  if (activeQuickFilter === 'urgent') {
    const days = daysUntilEnd(event.endDate);
    return days !== null && days >= 0 && days <= 7;
  }
  if (activeQuickFilter === 'reservation') return Boolean(event.needReservation);
  if (activeQuickFilter === 'limited') return Boolean(event.hasLimitedGoods);
  return true;
}

function matchesFilters(event, options = {}) {
  const { ignoreBrand = false, ignoreToday = false, ignoreQuickFilter = false } = options;
  if (!isActive(event)) return false;
  if (!ignoreBrand && activeBrand && event.brand !== activeBrand) return false;
  if (!ignoreToday && activeTodayOnly && !getTodayUpdateIds().has(event.id)) return false;
  if (!ignoreQuickFilter && !matchesQuickFilter(event)) return false;
  return true;
}

function getFiltered(options = {}) {
  return allEvents.filter(event => matchesFilters(event, options));
}

function getTodaySummaryEvents() {
  const updateIds = getTodayUpdateIds();
  return allEvents.filter(event =>
    updateIds.has(event.id) && matchesFilters(event, { ignoreToday: true })
  );
}

function renderTodaySummary() {
  const element = document.getElementById('today-summary');
  if (!element) return;
  if (!activeTodayOnly) {
    element.hidden = true;
    element.innerHTML = '';
    return;
  }

  const counts = Object.fromEntries(BRAND_ORDER.map(brand => [brand, 0]));
  getTodaySummaryEvents().forEach(event => {
    if (Object.prototype.hasOwnProperty.call(counts, event.brand)) counts[event.brand] += 1;
  });

  element.hidden = false;
  element.innerHTML = BRAND_ORDER.map(brand =>
    `<span class="today-chip today-${brand}"><span class="brand-dot brand-dot-${brand}" aria-hidden="true"></span>${BRAND_LABELS[brand]} ${counts[brand]}</span>`
  ).join('');
}

function urgentLabel(days) {
  if (days === 0) return '今天結束';
  if (days === 1) return '明天結束';
  return `剩 ${days} 天`;
}

function renderBadges(event, options = {}) {
  const { grouped = false } = options;
  const days = daysUntilEnd(event.endDate);
  const badges = [
    `<span class="badge badge-brand-${escapeAttr(event.brand)}">${escapeHtml(BRAND_LABELS[event.brand] || event.brand)}</span>`,
    `<span class="badge badge-type">${grouped ? '系列活動' : escapeHtml(TYPE_LABELS[event.type] || event.type)}</span>`
  ];

  if (days !== null && days >= 0 && days <= 7) {
    badges.push(`<span class="badge badge-urgent">${urgentLabel(days)}</span>`);
  }
  if (event.needReservation) badges.push('<span class="badge badge-reservation">需預約</span>');
  if (event.hasLimitedGoods) badges.push('<span class="badge badge-limited">限定商品</span>');
  badges.push(`<span class="badge badge-${event.country === 'TW' ? 'tw' : 'jp'}">${event.country === 'TW' ? '台灣' : '日本'}</span>`);
  return badges.join('');
}

function renderFacts(event) {
  const location = eventLocation(event);
  return `
    <div class="card-facts">
      <div class="card-fact">
        ${icon('map-pin')}
        <span class="fact-copy">
          <span class="fact-label">地點</span>
          <span class="fact-value">${escapeHtml(location || '地點未定')}</span>
        </span>
      </div>
      <div class="card-fact">
        ${icon('calendar')}
        <span class="fact-copy">
          <span class="fact-label">期間</span>
          <span class="fact-value">${escapeHtml(dateRange(event))}</span>
        </span>
      </div>
    </div>`;
}

function renderTags(tags) {
  return (tags || []).map(tag => `<span class="tag">${escapeHtml(tag)}</span>`).join('');
}

function sourceLink(event, label = '查看來源') {
  return `<a class="card-link" href="${escapeAttr(safeSourceUrl(event.sourceUrl))}" target="_blank" rel="noopener">
    <span>${escapeHtml(label)}</span>${icon('external-link')}
  </a>`;
}

function renderCard(event) {
  const summary = event.summaryZh
    ? `<p class="card-summary">${escapeHtml(event.summaryZh)}</p>`
    : '';
  return `
    <article class="event-card" data-brand="${escapeAttr(event.brand)}" data-id="${escapeAttr(event.id)}">
      <div class="event-card-inner">
        <div class="card-header">
          <div class="card-badges">${renderBadges(event)}</div>
        </div>
        <h2 class="card-title">${escapeHtml(event.title)}</h2>
        ${summary}
        ${renderFacts(event)}
        <div class="card-footer">
          <div class="card-tags">${renderTags(event.tags)}</div>
          ${sourceLink(event)}
        </div>
      </div>
    </article>`;
}

function buildEventUnits(sorted, filtered) {
  const allById = new Map(allEvents.map(event => [event.id, event]));
  const visibleIds = new Set(filtered.map(event => event.id));
  const visibleChildren = new Map();
  const allChildren = new Map();

  allEvents.forEach(event => {
    if (!event.parentEventId) return;
    if (!allChildren.has(event.parentEventId)) allChildren.set(event.parentEventId, []);
    allChildren.get(event.parentEventId).push(event);
  });

  filtered.forEach(event => {
    if (!event.parentEventId) return;
    if (!visibleChildren.has(event.parentEventId)) visibleChildren.set(event.parentEventId, []);
    visibleChildren.get(event.parentEventId).push(event);
  });

  const units = [];
  const renderedGroups = new Set();

  sorted.forEach(event => {
    const parentId = event.parentEventId || (allChildren.has(event.id) ? event.id : '');
    if (!parentId) {
      units.push({ kind: 'event', event });
      return;
    }
    if (renderedGroups.has(parentId)) return;

    const parent = allById.get(parentId);
    const children = (visibleChildren.get(parentId) || []).sort(compareEvents);
    if (!parent || children.length === 0) {
      if (visibleIds.has(event.id)) units.push({ kind: 'event', event });
      return;
    }

    renderedGroups.add(parentId);
    units.push({ kind: 'group', parent, children });
  });

  return units;
}

function renderGroupChild(event) {
  const badges = [
    `<span class="badge badge-type">${escapeHtml(TYPE_LABELS[event.type] || event.type)}</span>`,
    event.needReservation ? '<span class="badge badge-reservation">需預約</span>' : '',
    event.hasLimitedGoods ? '<span class="badge badge-limited">限定商品</span>' : ''
  ].join('');
  const summary = event.summaryZh
    ? `<p class="group-child-summary">${escapeHtml(event.summaryZh)}</p>`
    : '';
  const location = eventLocation(event);

  return `
    <div class="group-child" data-id="${escapeAttr(event.id)}">
      <div class="group-child-main">
        <div class="group-child-badges">${badges}</div>
        <h3 class="group-child-title">${escapeHtml(event.title)}</h3>
        ${summary}
        <div class="group-child-meta">
          ${location ? `<span>${icon('map-pin')}${escapeHtml(location)}</span>` : ''}
          <span>${icon('calendar')}${escapeHtml(dateRange(event))}</span>
        </div>
      </div>
      <a class="group-child-link" href="${escapeAttr(safeSourceUrl(event.sourceUrl))}" target="_blank" rel="noopener">
        <span>查看來源</span>${icon('external-link')}
      </a>
    </div>`;
}

function renderEventGroup(parent, children) {
  const groupedEvent = {
    ...parent,
    needReservation: parent.needReservation || children.some(event => event.needReservation),
    hasLimitedGoods: parent.hasLimitedGoods || children.some(event => event.hasLimitedGoods)
  };
  const summary = parent.summaryZh
    ? `<p class="card-summary">${escapeHtml(parent.summaryZh)}</p>`
    : '';

  return `
    <details class="event-card event-group-card" data-brand="${escapeAttr(parent.brand)}" data-id="${escapeAttr(parent.id)}">
      <summary class="group-summary">
        <div class="card-header">
          <div class="card-badges">${renderBadges(groupedEvent, { grouped: true })}</div>
        </div>
        <h2 class="card-title">${escapeHtml(parent.title)}</h2>
        ${summary}
        ${renderFacts(parent)}
        <div class="group-toggle">
          <span>${children.length} 個相關場域與方案</span>
          ${icon('chevron-down')}
        </div>
      </summary>
      <div class="group-children">${children.map(renderGroupChild).join('')}</div>
      <div class="card-footer group-footer">
        <div class="card-tags">${renderTags(parent.tags)}</div>
        ${sourceLink(parent, '母活動來源')}
      </div>
    </details>`;
}

function renderEventUnit(unit) {
  return unit.kind === 'group'
    ? renderEventGroup(unit.parent, unit.children)
    : renderCard(unit.event);
}

function setMetricSlot(index, value, label, tone) {
  const metrics = document.querySelectorAll('.metric');
  const valueIds = ['stat-total', 'stat-urgent', 'stat-reservation', 'stat-limited'];
  const labelIds = ['stat-total-label', 'stat-urgent-label', 'stat-reservation-label', 'stat-limited-label'];
  document.getElementById(valueIds[index]).textContent = value ?? '—';
  document.getElementById(labelIds[index]).textContent = label;
  metrics[index].className = `metric metric-${tone}`;
}

function syncMetricButtons() {
  const eventFilters = [null, 'urgent', 'reservation', 'limited'];
  const storeBrands = [null, ...BRAND_ORDER];
  const eventTitles = [
    '顯示全部情報',
    '顯示 7 天內結束的情報',
    '顯示需要預約的情報',
    '顯示有限定商品的情報'
  ];

  document.querySelectorAll('.metric').forEach((metric, index) => {
    const isActiveMetric = activeView === 'stores'
      ? activeBrand === storeBrands[index]
      : activeQuickFilter === eventFilters[index];
    metric.classList.toggle('active', isActiveMetric);
    metric.setAttribute('aria-pressed', String(isActiveMetric));
    metric.title = activeView === 'stores'
      ? (index === 0 ? '顯示全部常設店' : `只顯示 ${BRAND_LABELS[storeBrands[index]]} 常設店`)
      : eventTitles[index];
  });
}

function setEventMetrics(events) {
  const urgentCount = events.filter(event => {
    const days = daysUntilEnd(event.endDate);
    return days !== null && days >= 0 && days <= 7;
  }).length;
  setMetricSlot(0, events.length, '有效情報', 'primary');
  setMetricSlot(1, urgentCount, '7 天內結束', 'urgent');
  setMetricSlot(2, events.filter(event => event.needReservation).length, '需要預約', 'reservation');
  setMetricSlot(3, events.filter(event => event.hasLimitedGoods).length, '有限定商品', 'limited');
  document.getElementById('metrics-context').textContent = '依目前篩選條件';
  syncMetricButtons();
}

function brandStoreCount(brand) {
  const brandData = storeData[brand];
  if (!brandData) return 0;
  if (brandData.linksOnly) return (brandData.links || []).length;
  return (brandData.groups || []).reduce((total, group) => total + (group.stores || []).length, 0);
}

function setStoreMetrics() {
  const counts = Object.fromEntries(BRAND_ORDER.map(brand => [brand, brandStoreCount(brand)]));
  setMetricSlot(0, Object.values(counts).reduce((sum, count) => sum + count, 0), '常設店總數', 'primary');
  setMetricSlot(1, counts.pokemon, 'Pokémon', 'pokemon');
  setMetricSlot(2, counts.miffy, 'Miffy', 'miffy');
  setMetricSlot(3, counts.chiikawa, 'Chiikawa', 'chiikawa');
  document.getElementById('metrics-context').textContent = '官方常設據點';
  syncMetricButtons();
}

function updateBrandCounts() {
  const counts = {};
  if (activeView === 'stores') {
    BRAND_ORDER.forEach(brand => {
      counts[brand] = brandStoreCount(brand);
    });
  } else {
    const candidates = getFiltered({ ignoreBrand: true });
    BRAND_ORDER.forEach(brand => {
      counts[brand] = candidates.filter(event => event.brand === brand).length;
    });
  }

  const total = BRAND_ORDER.reduce((sum, brand) => sum + counts[brand], 0);
  document.getElementById('brand-count-all').textContent = total;
  BRAND_ORDER.forEach(brand => {
    document.getElementById(`brand-count-${brand}`).textContent = counts[brand];
  });
}

function hasActiveFilters() {
  return Boolean(activeBrand || activeTodayOnly || activeQuickFilter);
}

function activeFilterLabel() {
  const labels = [];
  if (activeBrand) labels.push(BRAND_LABELS[activeBrand]);
  if (activeTodayOnly) labels.push('今日新增');
  if (activeQuickFilter === 'urgent') labels.push('7 天內結束');
  if (activeQuickFilter === 'reservation') labels.push('需要預約');
  if (activeQuickFilter === 'limited') labels.push('有限定商品');
  return labels.join(' · ');
}

function syncControls() {
  document.querySelectorAll('.view-tab').forEach(tab => {
    const isActiveTab = tab.dataset.view === activeView;
    tab.classList.toggle('active', isActiveTab);
    tab.setAttribute('aria-pressed', String(isActiveTab));
  });

  document.querySelectorAll('.brand-pill').forEach(button => {
    const brand = button.dataset.brand;
    const isActiveButton = brand === 'all' ? !activeBrand : activeBrand === brand;
    button.classList.toggle('active', isActiveButton);
    button.setAttribute('aria-pressed', String(isActiveButton));
  });

  const todayButton = document.getElementById('filter-today');
  todayButton.classList.toggle('active', activeTodayOnly);
  todayButton.setAttribute('aria-pressed', String(activeTodayOnly));

  const updateIds = getTodayUpdateIds();
  const availableToday = allEvents.filter(event => isActive(event) && updateIds.has(event.id)).length;
  document.getElementById('today-filter-count').textContent = availableToday;
}

function updatePageChrome() {
  const isStores = activeView === 'stores';
  document.getElementById('page-title').textContent = isStores ? '常設店' : '活動情報';
  document.getElementById('page-description').textContent = isStores
    ? 'Pokémon、Miffy、Chiikawa 在日本與台灣的官方常設據點'
    : 'Pokémon、Miffy、Chiikawa 的期間限定活動與實體情報';
  document.getElementById('workspace-toolbar').hidden = isStores;
  document.getElementById('filter-today').hidden = isStores;
}

function renderHome() {
  syncControls();
  updatePageChrome();
  updateBrandCounts();
  if (activeView === 'stores') {
    renderStores();
  } else {
    renderEvents();
  }
}

function renderEvents() {
  const grid = document.getElementById('events-grid');
  const stores = document.getElementById('stores-wrap');
  grid.hidden = false;
  stores.hidden = true;

  const filtered = getFiltered();
  const metricBase = getFiltered({ ignoreQuickFilter: true });
  const sorted = [...filtered].sort(activeTodayOnly ? compareTodayEvents : compareEvents);
  const units = buildEventUnits(sorted, filtered);
  setEventMetrics(metricBase);
  renderTodaySummary();

  const countLabel = activeTodayOnly ? `${filtered.length} 筆今日新增` : `${filtered.length} 筆情報`;
  document.getElementById('events-count').textContent = countLabel;
  const groupingLabel = units.length < filtered.length ? `整理為 ${units.length} 組` : '';
  document.getElementById('active-filter-summary').textContent = [activeFilterLabel(), groupingLabel].filter(Boolean).join(' · ');

  if (sorted.length === 0) {
    const title = activeTodayOnly ? '目前沒有符合條件的今日新增' : '找不到符合條件的情報';
    const copy = hasActiveFilters() ? '切換品牌或概況選項後再看看。' : '資料更新後會顯示在這裡。';
    grid.innerHTML = `
      <div class="no-results">
        ${icon('search', 'ui-icon empty-icon')}
        <strong>${title}</strong>
        <span>${copy}</span>
      </div>`;
    return;
  }

  grid.innerHTML = units.map(renderEventUnit).join('');
}

function renderBrandStores(brand) {
  const data = storeData[brand];
  if (!data) return '';
  const total = brandStoreCount(brand);
  const heading = `
    <header class="store-brand-head">
      <div class="store-brand-title">
        <span class="brand-dot brand-dot-${brand}" aria-hidden="true"></span>
        <span>${escapeHtml(BRAND_LABELS[brand])}</span>
      </div>
      <span class="store-total">${total} 間</span>
    </header>`;

  if (data.linksOnly) {
    const links = (data.links || []).map(link => `
      <a class="store-link" href="${escapeAttr(safeSourceUrl(link.url))}" target="_blank" rel="noopener">
        <span>${escapeHtml(link.label)}</span>${icon('external-link')}
      </a>`).join('');
    return `
      <section class="store-section" data-brand="${brand}">
        ${heading}
        ${data.note ? `<p class="store-note">${escapeHtml(data.note)}</p>` : ''}
        <div class="store-links">${links}</div>
      </section>`;
  }

  const groups = (data.groups || []).map(group => {
    const items = (group.stores || []).map(store => `
      <div class="store-item">
        <div class="store-name">
          ${escapeHtml(store.name)}
          ${store.opening ? `<span class="store-open">${escapeHtml(store.opening)} 開幕</span>` : ''}
        </div>
        <span class="store-area">${escapeHtml(store.country === 'TW' ? '台灣' : '日本')} · ${escapeHtml(store.area)}</span>
      </div>`).join('');
    return `
      <div class="store-group">
        <div class="store-group-label">
          <span>${escapeHtml(group.label)}</span>
          <span class="store-group-count">${(group.stores || []).length}</span>
        </div>
        <div class="store-items">${items}</div>
      </div>`;
  }).join('');

  return `
    <section class="store-section" data-brand="${brand}">
      ${heading}
      <div class="store-groups">${groups}</div>
    </section>`;
}

function renderStores() {
  const grid = document.getElementById('events-grid');
  const wrap = document.getElementById('stores-wrap');
  grid.hidden = true;
  wrap.hidden = false;
  document.getElementById('today-summary').hidden = true;
  setStoreMetrics();

  const brands = activeBrand ? [activeBrand] : BRAND_ORDER;
  const total = brands.reduce((sum, brand) => sum + brandStoreCount(brand), 0);
  document.getElementById('events-count').textContent = `${total} 間常設店`;
  document.getElementById('active-filter-summary').textContent = activeBrand
    ? BRAND_LABELS[activeBrand]
    : '全部品牌';

  const sections = brands.map(renderBrandStores).filter(Boolean).join('');
  wrap.innerHTML = sections || `
    <div class="no-results">
      ${icon('building', 'ui-icon empty-icon')}
      <strong>目前沒有常設店資料</strong>
      <span>切換其他品牌後再看看。</span>
    </div>`;
}

function renderLastUpdated(iso) {
  const element = document.getElementById('last-updated');
  const status = element.closest('.sync-status');
  const date = iso ? new Date(iso) : null;
  if (!date || Number.isNaN(date.getTime())) {
    element.textContent = '更新時間未提供';
    status.classList.add('is-unknown');
    return;
  }
  const pad = value => String(value).padStart(2, '0');
  element.textContent = `最後更新 ${date.getMonth() + 1}/${date.getDate()} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
  status.classList.remove('is-unknown');
}

async function fetchJson(path) {
  const response = await fetch(dataUrl(path), { cache: 'no-store' });
  if (!response.ok) throw new Error(`HTTP ${response.status}: ${path}`);
  return response.json();
}

function bindControls() {
  const eventFilters = [null, 'urgent', 'reservation', 'limited'];
  const storeBrands = [null, ...BRAND_ORDER];

  document.querySelectorAll('.metric').forEach(metric => {
    metric.addEventListener('click', () => {
      const index = Number(metric.dataset.metricIndex);
      if (activeView === 'stores') {
        const brand = storeBrands[index];
        activeBrand = activeBrand === brand ? null : brand;
      } else {
        const quickFilter = eventFilters[index];
        activeQuickFilter = activeQuickFilter === quickFilter ? null : quickFilter;
      }
      renderHome();
    });
  });

  document.querySelectorAll('.view-tab').forEach(tab => {
    tab.addEventListener('click', () => {
      activeView = tab.dataset.view;
      renderHome();
    });
  });

  document.querySelectorAll('.brand-pill').forEach(button => {
    button.addEventListener('click', () => {
      const brand = button.dataset.brand;
      activeBrand = brand === 'all' || activeBrand === brand ? null : brand;
      renderHome();
    });
  });

  document.getElementById('filter-today').addEventListener('click', () => {
    activeTodayOnly = !activeTodayOnly;
    renderHome();
  });
}

async function init() {
  const grid = document.getElementById('events-grid');
  grid.innerHTML = '<p class="grid-msg">正在整理最新情報…</p>';

  const results = await Promise.allSettled([
    fetchJson('data/events.json'),
    fetchJson('data/stores.json'),
    fetchJson('data/today_updates.json'),
    fetchJson('data/last_updated.json')
  ]);

  if (results[0].status !== 'fulfilled') {
    grid.innerHTML = `
      <div class="no-results">
        ${icon('rotate-ccw', 'ui-icon empty-icon')}
        <strong>情報載入失敗</strong>
        <span>請稍後重新整理頁面。</span>
      </div>`;
    renderLastUpdated(null);
    return;
  }

  allEvents = results[0].value;
  storeData = results[1].status === 'fulfilled' ? results[1].value : {};
  updateData = results[2].status === 'fulfilled' ? results[2].value : { newEventIds: [] };
  renderLastUpdated(results[3].status === 'fulfilled' ? results[3].value.updatedAt : null);
  bindControls();
  renderHome();
}

document.addEventListener('DOMContentLoaded', init);
