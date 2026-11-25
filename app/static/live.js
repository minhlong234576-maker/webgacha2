function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

const shownDrops = new Set();
const MAX_DROPS = 40;

function dropKey(drop) {
  return `${drop.player}|${drop.name}|${drop.value}|${drop.image}`;
}

function dropCard(drop, isNew) {
  const li = document.createElement("div");
  li.setAttribute("role", "listitem");
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
  li.append(card);
  return li;
}

function bestCard(drop) {
  if (!drop) return null;
  const aside = document.createElement("aside");
  aside.className = "live-best";
  aside.style.setProperty("--rarity", drop.color || "#fbbf24");

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

async function paintDrops(initial = false) {
  const el = document.getElementById("live-drops");
  if (!el) return;
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
    const row = document.createElement("div");
    row.className = "live-row";
    row.setAttribute("role", "list");
    drops.forEach((drop, index) => {
      row.append(dropCard(drop, index < freshCount));
    });
    if (!drops.length) {
      const empty = document.createElement("p");
      empty.className = "live-empty";
      empty.textContent = "Chưa có lượt mở nào hôm nay. Người mở đầu tiên sẽ xuất hiện ở đây.";
      row.append(empty);
    }
    el.replaceChildren();
    const best = bestCard(data.best);
    if (best) el.append(best);
    el.append(row);
  } catch (err) {
    /* ignore */
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
