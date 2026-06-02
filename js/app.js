let allEvents = [];
let storeData = {};       // 常設店資料（data/stores.json）
let activeView = 'events';// 'events' | 'stores'
let activeBrand = null;   // null = 全部品牌
let activeType = 'all';
let activeCountry = 'all';
let activeCity = 'all';

const BRAND_LABELS = {
  pokemon: 'Pokémon',
  miffy: 'Miffy',
  chiikawa: 'Chiikawa',
  sanrio: 'Sanrio'
};
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
  Miyagi: '宮城', Chiba: '千葉', Aomori: '青森', Aichi: '愛知', Hyougo: '兵庫',
  Shizuoka: '靜岡', Ibaraki: '茨城', Tochigi: '栃木', Gunma: '群馬',
  Nara: '奈良', Shiga: '滋賀', Okayama: '岡山', Kumamoto: '熊本',
  Ishikawa: '石川', Niigata: '新潟', Nagano: '長野', Gifu: '岐阜', Kochi: '高知',
  Taipei: '台北', Taichung: '台中', Kaohsiung: '高雄', Tainan: '台南',
  Taoyuan: '桃園', Hsinchu: '新竹', Keelung: '基隆'
};

// ── Utility ──────────────────────────────────────────────────────────────────

function today() {
  return new Date().toISOString().slice(0, 10);
}

function daysUntilEnd(endDate) {
  if (!endDate) return null;
  return Math.ceil((new Date(endDate) - new Date(today())) / 86400000);
}

function isActive(ev) {
  const t = today();
  if (ev.endDate && ev.endDate < t) return false;
  return true;
}

function formatDate(d) {
  if (!d) return '';
  const [, m, day] = d.split('-');
  return `${m}/${day}`;
}

function dateRange(ev) {
  if (!ev.startDate && !ev.endDate) return '常設 / 日期未定';
  if (ev.startDate && !ev.endDate) return `${formatDate(ev.startDate)} 起`;
  if (!ev.startDate && ev.endDate) return `至 ${formatDate(ev.endDate)}`;
  return `${formatDate(ev.startDate)} – ${formatDate(ev.endDate)}`;
}

// ── Filtering ─────────────────────────────────────────────────────────────────

function getFiltered() {
  return allEvents.filter(ev => {
    if (!isActive(ev)) return false;
    if (activeBrand && ev.brand !== activeBrand) return false;
    if (activeType !== 'all' && ev.type !== activeType) return false;
    if (activeCountry !== 'all' && ev.country !== activeCountry) return false;
    if (activeCity !== 'all' && ev.city !== activeCity) return false;
    return true;
  });
}

// ── Card rendering ────────────────────────────────────────────────────────────

function renderCard(ev) {
  const days = daysUntilEnd(ev.endDate);
  const urgentBadge = (days !== null && days <= 7 && days >= 0)
    ? `<span class="badge badge-urgent">剩 ${days} 天</span>` : '';
  const resBadge = ev.needReservation ? `<span class="badge badge-reservation">需預約</span>` : '';
  const limBadge = ev.hasLimitedGoods ? `<span class="badge badge-limited">限定商品</span>` : '';
  const countryBadge = `<span class="badge badge-${ev.country.toLowerCase()}">${ev.country === 'JP' ? '🇯🇵 日本' : '🇹🇼 台灣'}</span>`;

  const location = [CITY_LABELS[ev.city] || ev.city, ev.locationName].filter(Boolean).join(' · ');
  const tags = (ev.tags || []).map(t => `<span class="tag">${t}</span>`).join('');

  return `
    <div class="event-card" data-brand="${ev.brand}" data-id="${ev.id}">
      <div class="card-header">
        <div class="card-badges">
          <span class="badge badge-brand-${ev.brand}">${BRAND_LABELS[ev.brand]}</span>
          <span class="badge badge-type">${TYPE_LABELS[ev.type] || ev.type}</span>
          ${urgentBadge}${resBadge}${limBadge}${countryBadge}
        </div>
      </div>
      <div class="card-title">${ev.title}</div>
      <div class="card-summary">${ev.summaryZh || ''}</div>
      <div class="card-meta">
        ${location ? `<div class="card-meta-row">📍 ${location}</div>` : ''}
        <div class="card-meta-row">📅 ${dateRange(ev)}</div>
      </div>
      <div class="card-footer">
        <div class="card-tags">${tags}</div>
        <a class="card-link" href="${ev.sourceUrl}" target="_blank" rel="noopener" onclick="event.stopPropagation()">來源 ↗</a>
      </div>
    </div>`;
}

// ── Home render ───────────────────────────────────────────────────────────────

function renderHome() {
  if (activeView === 'stores') return renderStores();
  return renderEvents();
}

function renderEvents() {
  // 顯示活動相關 UI
  document.getElementById('filter-bar').style.display = '';
  document.getElementById('events-grid').style.display = '';
  document.getElementById('stores-wrap').style.display = 'none';
  document.getElementById('stat-total-label').textContent = '目前有效情報';

  const filtered = getFiltered();

  // 統計（隨篩選動態變化）
  const urgentCount = filtered.filter(ev => {
    const d = daysUntilEnd(ev.endDate);
    return d !== null && d <= 7 && d >= 0;
  }).length;
  setStats(filtered.length, urgentCount,
    filtered.filter(e => e.needReservation).length,
    filtered.filter(e => e.hasLimitedGoods).length);

  document.getElementById('events-count').textContent = `共 ${filtered.length} 筆`;

  // 排序：最快結束在前；無結束日（常設/未定）排最後
  const sorted = [...filtered].sort((a, b) => {
    const da = daysUntilEnd(a.endDate) ?? 99999;
    const db = daysUntilEnd(b.endDate) ?? 99999;
    return da - db;
  });

  const grid = document.getElementById('events-grid');
  if (sorted.length === 0) {
    grid.innerHTML = `<div class="no-results"><p>🔍</p><p>目前沒有符合條件的情報</p></div>`;
    return;
  }
  grid.innerHTML = sorted.map(renderCard).join('');
}

function setStats(total, urgent, reservation, limited) {
  const t = v => (v === null ? '—' : v);
  document.getElementById('stat-total').textContent = t(total);
  document.getElementById('stat-urgent').textContent = t(urgent);
  document.getElementById('stat-reservation').textContent = t(reservation);
  document.getElementById('stat-limited').textContent = t(limited);
}

// ── 常設店檢視 ──────────────────────────────────────────────────────────────────

function brandStoreCount(brand) {
  const b = storeData[brand];
  if (!b) return 0;
  if (b.linksOnly) return b.links.length;
  return (b.groups || []).reduce((n, g) => n + g.stores.length, 0);
}

function renderStores() {
  // 常設店不需要類型/國家/城市篩選
  document.getElementById('filter-bar').style.display = 'none';
  document.getElementById('events-grid').style.display = 'none';
  const wrap = document.getElementById('stores-wrap');
  wrap.style.display = '';

  const brands = activeBrand ? [activeBrand] : ['pokemon', 'miffy', 'chiikawa', 'sanrio'];

  // 統計：只顯示「目前有效情報」=常設店數量，其餘三欄留白
  const total = brands.reduce((n, b) => n + brandStoreCount(b), 0);
  setStats(total, null, null, null);
  document.getElementById('stat-total-label').textContent = '常設店';
  document.getElementById('events-count').textContent = `共 ${total} 間`;

  const sections = brands.map(b => renderBrandStores(b)).filter(Boolean).join('');
  wrap.innerHTML = sections ||
    `<div class="no-results"><p>🏬</p><p>這個品牌暫無常設店資料</p></div>`;
}

function renderBrandStores(brand) {
  const data = storeData[brand];
  if (!data) return '';
  const head = `<div class="store-brand-head"><span class="badge badge-brand-${brand}">${BRAND_LABELS[brand]}</span></div>`;

  // 三麗鷗：只放官方門市連結
  if (data.linksOnly) {
    const links = data.links.map(l =>
      `<a class="store-link" href="${l.url}" target="_blank" rel="noopener">${l.label} ↗</a>`).join('');
    return `<div class="store-section">${head}
      <div class="store-note">${data.note || ''}</div>
      <div class="store-links">${links}</div></div>`;
  }

  const groups = (data.groups || []).map(g => {
    const items = g.stores.map(s => {
      const flag = s.country === 'TW' ? '🇹🇼' : '🇯🇵';
      const open = s.opening ? `<span class="store-open">（${s.opening} 開幕）</span>` : '';
      return `<div class="store-item">
        <span class="store-name">${s.name}${open}</span>
        <span class="store-area">${flag} ${s.area}</span>
      </div>`;
    }).join('');
    return `<div class="store-group">
      <div class="store-group-label">${g.label}<span class="store-group-count">${g.stores.length}</span></div>
      <div class="store-items">${items}</div>
    </div>`;
  }).join('');

  return `<div class="store-section">${head}${groups}</div>`;
}

function initCitySelect() {
  const cities = [...new Set(allEvents.filter(e => e.city).map(e => e.city))]
    .sort((a, b) => Object.keys(CITY_LABELS).indexOf(a) - Object.keys(CITY_LABELS).indexOf(b));
  const sel = document.getElementById('filter-city');
  sel.innerHTML = `<option value="all">所有城市</option>` +
    cities.map(c => `<option value="${c}">${CITY_LABELS[c] || c}</option>`).join('');
}

// ── Init ──────────────────────────────────────────────────────────────────────

async function init() {
  const [evRes, stRes] = await Promise.all([
    fetch('data/events.json'),
    fetch('data/stores.json')
  ]);
  allEvents = await evRes.json();
  storeData = await stRes.json();

  // 檢視切換：活動情報 / 常設店
  document.querySelectorAll('.view-tab').forEach(tab => {
    tab.addEventListener('click', () => {
      activeView = tab.dataset.view;
      document.querySelectorAll('.view-tab').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      renderHome();
    });
  });

  // Brand pills — 可切換：再點一次取消（回到全部）
  document.querySelectorAll('.brand-pill').forEach(pill => {
    pill.addEventListener('click', () => {
      const b = pill.dataset.brand;
      if (activeBrand === b) {
        activeBrand = null;
        pill.classList.remove('active');
      } else {
        activeBrand = b;
        document.querySelectorAll('.brand-pill').forEach(p => p.classList.remove('active'));
        pill.classList.add('active');
      }
      renderHome();
    });
  });

  // Dropdown filters
  initCitySelect();
  document.getElementById('filter-type').addEventListener('change', e => { activeType = e.target.value; renderHome(); });
  document.getElementById('filter-country').addEventListener('change', e => { activeCountry = e.target.value; renderHome(); });
  document.getElementById('filter-city').addEventListener('change', e => { activeCity = e.target.value; renderHome(); });

  renderHome();
}

document.addEventListener('DOMContentLoaded', init);
