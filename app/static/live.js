/* CHONG NHAN BOI: chi mot instance live.js duoc chay tren mot trang.
 *
 * `live.js` duoc load bang `<script src>` (khong phai module), nen dung co tren
 * `window` de neu script bi load 2 lan thi instance thu hai tu bo qua.
 */
if (!window.__jvLiveDrops) {
  window.__jvLiveDrops = true;
  startLiveDrops();
}

function startLiveDrops() {
  const shownDrops = new Set();
  const MAX_DROPS = 30;
  const MIN_HALF_CARDS = 12;
  const PAUSE_STORAGE_KEY = "jv_live_paused";

  function dropKey(drop) {
    if (drop.id !== undefined && drop.id !== null) return String(drop.id);
    return `${drop.player}|${drop.name}|${drop.value}|${drop.image}`;
  }

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
    name.textContent = drop.name ?? "";
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
    aside.dataset.key = `best:${dropKey(drop)}`;

    const img = document.createElement("img");
    img.src = drop.image || "";
    img.alt = "";

    const copy = document.createElement("div");
    copy.className = "live-best-copy";
    const kicker = document.createElement("span");
    kicker.className = "live-kicker";
    kicker.append(document.createElement("i"), " Best hôm nay");
    const name = document.createElement("div");
    name.className = "name";
    name.title = drop.name ?? "";
    name.textContent = drop.name ?? "";
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

  function syncPauseButton(strip, btn) {
    const paused = strip.dataset.paused === "true";
    btn.textContent = paused ? "▶" : "⏸";
    const label = paused
      ? "Tiếp tục chạy bảng drop trực tiếp"
      : "Tạm dừng bảng drop trực tiếp";
    btn.setAttribute("aria-label", label);
    btn.title = label;
  }

  function ensureShell(el) {
    let viewport = el.querySelector(".live-viewport");
    if (!viewport) {
      viewport = document.createElement("div");
      viewport.className = "live-viewport";

      const marquee = document.createElement("div");
      marquee.className = "live-marquee";

      const primaryHalf = document.createElement("div");
      primaryHalf.className = "live-half live-half-primary";

      const row = document.createElement("div");
      row.className = "live-row";

      const fill = document.createElement("div");
      fill.className = "live-fill";
      fill.setAttribute("aria-hidden", "true");

      primaryHalf.append(row, fill);

      const cloneHalf = document.createElement("div");
      cloneHalf.className = "live-half live-half-clone";
      cloneHalf.setAttribute("aria-hidden", "true");

      marquee.append(primaryHalf, cloneHalf);
      viewport.append(marquee);
      el.append(viewport);
    }

    let pauseBtn = el.querySelector(".live-pause");
    if (!pauseBtn) {
      pauseBtn = document.createElement("button");
      pauseBtn.type = "button";
      pauseBtn.className = "live-pause";
      try {
        if (sessionStorage.getItem(PAUSE_STORAGE_KEY) === "1") {
          el.dataset.paused = "true";
        }
      } catch {
        /* ignore storage errors */
      }
      syncPauseButton(el, pauseBtn);
      pauseBtn.addEventListener("click", () => {
        const nextPaused = el.dataset.paused !== "true";
        el.dataset.paused = nextPaused ? "true" : "false";
        try {
          sessionStorage.setItem(PAUSE_STORAGE_KEY, nextPaused ? "1" : "0");
        } catch {
          /* ignore */
        }
        syncPauseButton(el, pauseBtn);
      });
      el.append(pauseBtn);
    }

    return {
      viewport,
      marquee: viewport.querySelector(".live-marquee"),
      row: viewport.querySelector(".live-row"),
      fill: viewport.querySelector(".live-fill"),
      cloneHalf: viewport.querySelector(".live-half-clone"),
      pauseBtn,
    };
  }

  let inFlight = false;
  let lastDropsSig = null;

  async function paintDrops(initial = false) {
    const el = document.getElementById("live-drops");
    if (!el || inFlight) return;
    inFlight = true;
    try {
      const res = await fetch("/api/drops");
      if (!res.ok) return;
      const data = await res.json();
      const drops = (data.drops || []).slice(0, MAX_DROPS);

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

      let freshCount = 0;
      if (!initial) {
        for (const drop of drops) {
          if (!fresh.has(dropKey(drop))) break;
          freshCount++;
        }
      }

      const { viewport, marquee, row, fill, cloneHalf, pauseBtn } = ensureShell(el);

      // 1) Dong bo the `Best hom nay` ben trai.
      const bestEl = el.querySelector(".live-best");
      const bestKey = data.best ? `best:${dropKey(data.best)}` : "";
      const nextBest = bestCard(data.best);
      if (bestEl && nextBest) {
        if ((bestEl.dataset.key || "") !== bestKey) {
          bestEl.replaceWith(nextBest);
        }
      } else if (bestEl && !nextBest) {
        bestEl.remove();
      } else if (!bestEl && nextBest) {
        el.insertBefore(nextBest, viewport);
      }

      // 2) Chi cap nhat bang chay khi danh sach drop thuc su thay doi,
      // de tranh giat hoac reset vong lap khi poll moi 2 giay.
      const dropsSig = drops.map((d) => `${dropKey(d)}:${d.value ?? ""}`).join("|");
      if (dropsSig === lastDropsSig) return;
      lastDropsSig = dropsSig;

      if (!drops.length) {
        row.removeAttribute("role");
        marquee.classList.remove("is-running");
        fill.replaceChildren();
        cloneHalf.replaceChildren();
        pauseBtn.hidden = true;

        const p = document.createElement("p");
        p.className = "live-empty";
        p.textContent = "Chưa có lượt mở nào hôm nay. Người mở đầu tiên sẽ xuất hiện ở đây.";
        row.replaceChildren(p);
        return;
      }

      pauseBtn.hidden = false;
      row.setAttribute("role", "list");

      const rowNodes = [];
      for (const [index, drop] of drops.entries()) {
        const li = document.createElement("div");
        li.setAttribute("role", "listitem");
        li.dataset.key = dropKey(drop);
        li.append(dropCard(drop, index < freshCount));
        rowNodes.push(li);
      }
      row.replaceChildren(...rowNodes);

      // Neu so drop it, lap lai them trong `live-fill` (aria-hidden) de moi nua
      // bang luon du rong cho vong lap muot khong lo khoang trong.
      const fillNodes = [];
      const cloneNodes = [];
      for (const drop of drops) {
        const slot = document.createElement("div");
        slot.className = "live-slot";
        slot.append(dropCard(drop, false));
        cloneNodes.push(slot);
      }

      let halfCount = drops.length;
      while (halfCount < MIN_HALF_CARDS) {
        for (const drop of drops) {
          if (halfCount >= MIN_HALF_CARDS) break;
          const fillSlot = document.createElement("div");
          fillSlot.className = "live-slot";
          fillSlot.append(dropCard(drop, false));
          fillNodes.push(fillSlot);

          const cloneSlot = document.createElement("div");
          cloneSlot.className = "live-slot";
          cloneSlot.append(dropCard(drop, false));
          cloneNodes.push(cloneSlot);
          halfCount++;
        }
      }

      fill.replaceChildren(...fillNodes);
      cloneHalf.replaceChildren(...cloneNodes);

      const durationSec = Math.max(22, Math.round(halfCount * 2.6));
      el.style.setProperty("--live-duration", `${durationSec}s`);
      marquee.classList.add("is-running");
    } catch {
      /* ignore */
    } finally {
      inFlight = false;
    }
  }

  paintDrops(true);
  let liveTimer = null;
  function scheduleDrops() {
    clearInterval(liveTimer);
    if (document.hidden) return;
    liveTimer = setInterval(() => paintDrops(false), 2000);
  }
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) paintDrops(false);
    scheduleDrops();
  });
  scheduleDrops();
}
