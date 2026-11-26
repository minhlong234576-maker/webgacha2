function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

/* CHONG NHIAN BOI: chi mot instance live.js duoc chay tren mot trang.
 *
 * `live.js` duoc load bang `<script src>` (khong phai module) nen khong co
 * `type="module"` de gan co che "load 1 lan". Neu trang nao load file nay
 * 2 lan (vd: script duoc them san + inject them), ca hai instance deu ve
 * vao cung `#live-drops` -> moi the bi them 2 lan, DOM nhan boi, moi lan
 * poll lai rung man hinh.
 *
 * Co lai instance tren `window` de instance thu hai tu bo qua.
 */
if (window.__jvLiveDrops) {
  // Da co instance dang chay -> dung, khong tao them.
} else {
  window.__jvLiveDrops = true;
  startLiveDrops();
}

function startLiveDrops() {
const shownDrops = new Set();
const MAX_DROPS = 40;

/* Khoa duy nhat cho 1 the drop.
 *
 * PHAI dung `id` (id cua ban ghi drop tren server, duy nhat) — KHONG dung
 * `player|name|value|image`, vi nhieu luot mo ra CUNG MOT MON (cung ten,
 * cung gia, cung anh) se co key giong nhau -> the bi them trung lap di lap
 * lai, danh sach phinh toan dan (do len ~100 node thay vi 30) va man hinh
 * rung lien tuc.
 */
function dropKey(drop) {
  if (drop.id !== undefined && drop.id !== null) return String(drop.id);
  return `${drop.player}|${drop.name}|${drop.value}|${drop.image}`;
}

/* Tao the drop. Tra ve <article> (khong phai <li>) de caller bo wrapper
 * <li role="listitem"> va gan `data-key` — de co the cap nhat tang dần thay
 * vi tao lai DOM moi lan poll. */
function dropCard(drop, isNew) {
  const card = document.createElement("article");
  card.className = "live-card" + (isNew ? " is-new" : "");
  card.style.setProperty("--rarity", drop.color || "#b0c3d9");

  const img = document.createElement("img");
  img.src = drop.image || "";
  img.alt = "";
  img.loading = "lazy";

  const body = document.createElement("div");
  const name = document.createElement("div");
  name.className = "name";
  name.title = drop.name ?? "";
  name.textContent = drop.name;
  const price = document.createElement("em");
  price.className = "price";
  price.textContent = (drop.value_fmt ?? "") + " Coin";
  const who = document.createElement("div");
  who.className = "who";
  who.title = drop.player ?? "";
  who.textContent = (drop.player ?? "") + (drop.is_bot ? " · bot" : "");

  body.append(name, price, who);
  card.append(img, body);
  return card;
}

function bestCard(drop) {
  if (!drop) return null;
  const aside = document.createElement("aside");
  aside.className = "live-best";
  aside.style.setProperty("--rarity", drop.color || "#fbbf24");
  // `best` la 1 the rieng, dung khoa rieng de khong bao trung voi the drop
  // cung id trong danh sach.
  aside.dataset.key = `best:${dropKey(drop)}`;

  const img = document.createElement("img");
  img.src = drop.image || "";
  img.alt = "";

  const copy = document.createElement("div");
  copy.className = "live-best-copy";
  const kicker = document.createElement("span");
  kicker.className = "live-kicker";
  const dot = document.createElement("i");
  kicker.append(dot, " Best hôm nay");
  const name = document.createElement("div");
  name.className = "name";
  name.title = drop.name ?? "";
  name.textContent = drop.name;
  const price = document.createElement("div");
  price.className = "price";
  price.textContent = (drop.value_fmt ?? "") + " Coin";
  const who = document.createElement("div");
  who.className = "who";
  who.textContent = drop.player ?? "";

  copy.append(kicker, name, price, who);
  aside.append(img, copy);
  return aside;
}

/* Khoa de tranh "race" giua cac lan poll.
 *
 * `paintDrops` la `async`: neu mot lan poll chua xong ma lan poll sau
 * da bat dau, ca hai se cung ghi vao DOM -> the bi them trung, danh sach
 * phinh toan dan va man hinh rung lien tuc.
 *
 * Dung co "in-flight" de chi cho phep MOT request /mot luc. */
let inFlight = false;

async function paintDrops(initial = false) {
  const el = document.getElementById("live-drops");
  if (!el) return;
  if (inFlight) return;
  inFlight = true;
  try {
    const res = await fetch("/api/drops");
    if (!res.ok) return;
    const data = await res.json();
    const drops = (data.drops || []).slice(0, MAX_DROPS);
    // Chỉ đánh dấu hoạt ảnh cho thẻ mới; lần vẽ đầu thì im lặng để không nhấp nháy.
    const fresh = new Set();
    drops.forEach((drop) => {
      const key = dropKey(drop);
      if (!shownDrops.has(key)) fresh.add(key);
      shownDrops.add(key);
    });
    if (shownDrops.size > MAX_DROPS * 4) {
      shownDrops.clear();
      fresh.clear();
    }
    if (initial && drops.length) {
      el.dataset.filled = "1";
    }
    // Server trả danh sách mới nhất trước; cắt tại drop đã thấy trước đó và chỉ đánh dấu
    // đúng những thẻ vừa chui vào đầu danh sách.
    let freshCount = 0;
    if (!initial) {
      for (const drop of drops) {
        if (!fresh.has(dropKey(drop))) break;
        freshCount++;
      }
    }

    // ---- CẬP NHẬT TĂNG DẦN thay vì `replaceChildren()` ----
    // Xoá sạch rồi dựng lại toàn bộ dải mỗi 2 giây khiến trình duyệt phải
    // layout lại tất cả thẻ -> CLS (layout shift) thấy rõ là màn hình rung
    // mỗi lần có người mở rương. Thay vao do: giu DOM cu, chi them/xoa
    // nhung the nao thay doi -> khong co layout shift.
    const row = el.querySelector(".live-row") || createRow(el);
    const existing = new Map();
    for (const li of row.children) {
      const key = li.dataset.key;
      if (key) existing.set(key, li);
    }

    // Danh sach hien thi: `best` + cac the drop. `best` doi theo ngay -> no
    // cung nam trong `el`, nen ta luu rieng de biet khi nao can thay.
    const bestEl = el.querySelector(".live-best");
    const bestKey = data.best ? `best:${dropKey(data.best)}` : "";
    const nextBest = bestCard(data.best);

    // 1) Thay the `best` neu doi (chi 1 lan -> it layout shift).
    if (bestEl && nextBest) {
      const oldKey = bestEl.dataset.key || "";
      if (oldKey !== bestKey) {
        bestEl.replaceWith(nextBest);
        nextBest.dataset.key = bestKey;
      }
    } else if (bestEl && !nextBest) {
      bestEl.remove();
    } else if (!bestEl && nextBest) {
      nextBest.dataset.key = bestKey;
      el.insertBefore(nextBest, row);
    }

    // 2) Dong bo danh sach the drop.
    //
    // Server tra danh sach MOI NHAT TRUOC. The moi chui vao dau danh sach.
    //
    // Vi tri the duoc dat bang `transform: translateX(...)` (KHONG dung flex
    // order, KHONG dung `left`): doi `transform` khong lam trinh duyet layout
    // lai -> KHONG co layout shift (man hinh khong rung) khi co luot mo moi.
    // `flex` se day cac the sau sang phai -> layout shift.
    const keepKeys = new Set();
    const step = cardStride();
    const ordered = [];
    for (const [index, drop] of drops.entries()) {
      const key = dropKey(drop);
      keepKeys.add(key);
      let li = existing.get(key);
      if (li) {
        // The da co -> chi can cap nhat text, khong tao lai DOM.
        updateCard(li, drop);
        existing.delete(key);
      } else {
        li = document.createElement("div");
        li.setAttribute("role", "listitem");
        li.dataset.key = key;
        li.append(dropCard(drop, index < freshCount));
        // The moi: bat dau o NGOAI man hinh roi "truot" vao cho.
        li.classList.add("is-entering");
        row.append(li);
      }
      // Cap nhat vi tri (transform) — thay doi nay khong gay layout shift.
      //
      // Server tra danh sach MOI NHAT TRUOC nen `index = 0` la the moi nhat.
      // De the moi nhat o DAU dai (ben trai), gan offset NGUOC: the moi nhat
      // nen o x = 0, the cu hon lan sau sang phai.
      li.style.setProperty("--x", `${(drops.length - 1 - index) * step}px`);
      ordered.push(li);
    }

    // 3) Xoa nhung the da bien mat khoi danh sach (server gia han danh sach).
    for (const [key, li] of existing) {
      if (!keepKeys.has(key)) li.remove();
    }

    // Chi dat role="list" khi co it nhat 1 role="listitem" ben trong; khi
    // rong chi render <p class="live-empty"> de tranh loi aria-required-children.
    const empty = row.querySelector(".live-empty");
    if (!drops.length) {
      row.removeAttribute("role");
      if (!empty) {
        const p = document.createElement("p");
        p.className = "live-empty";
        p.textContent = "Chưa có lượt mở nào hôm nay. Người mở đầu tiên sẽ xuất hiện ở đây.";
        row.append(p);
      }
    } else {
      row.setAttribute("role", "list");
      if (empty) empty.remove();
    }
  } catch (err) {
    /* ignore */
  } finally {
    inFlight = false;
  }
}

/* Buoc nhay giua cac the: doc tu CSS de luon khop voi responsive.
 *
 * CSS dat `.live-strip { --live-card-w: 156px; --live-gap: 8px }` va doi
 * `--live-card-w` tren mobile. Doc 1 lan moi lan cap nhat de dung kich thuoc
 * that (trinh duyet da tinh san khi layout) — dung `getBoundingClientRect`
 * cua 1 the de suy ra, khong doc layout lai nhieu lan.
 */
function cardStride() {
  const strip = document.getElementById("live-drops");
  if (!strip) return 164;
  const cs = getComputedStyle(strip);
  const w = parseFloat(cs.getPropertyValue("--live-card-w")) || 156;
  const gap = parseFloat(cs.getPropertyValue("--live-gap")) || 8;
  return w + gap;
}

/* Tao dong `live-row` lan dau. */
function createRow(el) {
  const row = document.createElement("div");
  row.className = "live-row";
  el.append(row);
  return row;
}

/* Cap nhat noi dung 1 the da ton tai (khong tao lai DOM).
 *
 * KHONG toggle `is-new` o day: animation chi bat mot lan khi the MOI duoc
 * tao (trong `dropCard`). Toggle moi lan poll se gia lai animation lien tuc
 * -> the "nhap nhay" khien man hinh rung. */
function updateCard(li, drop) {
  const card = li.firstElementChild;
  if (!card) return;
  card.style.setProperty("--rarity", drop.color || "#b0c3d9");
  const img = card.querySelector("img");
  if (img) {
    const src = drop.image || "";
    if (img.getAttribute("src") !== src) img.src = src;
  }
  const body = card.firstElementChild?.nextElementSibling;
  if (!body) return;
  const [nameEl, priceEl, whoEl] = body.children;
  if (nameEl) {
    nameEl.textContent = drop.name ?? "";
    nameEl.title = drop.name ?? "";
  }
  if (priceEl) priceEl.textContent = (drop.value_fmt ?? "") + " Coin";
  if (whoEl) {
    whoEl.textContent = (drop.player ?? "") + (drop.is_bot ? " · bot" : "");
    whoEl.title = drop.player ?? "";
  }
}

paintDrops(true);
let liveTimer = null;
function scheduleDrops() {
  clearInterval(liveTimer);
  // Tạm dừng polling khi tab bị ẩn để không tốn tài nguyên phía sau.
  if (document.hidden) return;
  liveTimer = setInterval(() => paintDrops(false), 2000);
}
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) paintDrops(false);
  scheduleDrops();
});
scheduleDrops();
} // end startLiveDrops()
