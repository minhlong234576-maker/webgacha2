/* FX-JellyVale: hiệu ứng 3D, chuyển cảnh và ăn mừng cho client.
 *
 * Nguyên tắc:
 * - Chỉ chạy khi người dùng KHÔNG bật "giảm chuyển động" (prefers-reduced-motion).
 *   Khi reduced-motion bật, toàn bộ module làm việc rỗng, KHÔNG ẩn nội dung nào.
 * - Tất cả phần tử tạo ra dùng textContent/DOM API, không nối chuỗi HTML.
 * - Nội dung chính KHÔNG bị ẩn khi thiếu JS/CSS: mọi trạng thái "ẩn chờ hiện"
 *   chỉ được thêm bằng JS, và luôn có lớp .fx-in đưa về trạng thái cuối.
 */
const REDUCED = matchMedia("(prefers-reduced-motion: reduce)");

let reduceMotion = REDUCED.matches;
REDUCED.addEventListener("change", (e) => {
  reduceMotion = e.matches;
});

const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

/* ------------------------------------------------------------------ */
/* 1. Thẻ nghiêng 3D theo con trỏ (.case-card)                        */
/* ------------------------------------------------------------------ */
function mountCards() {
  const cards = document.querySelectorAll(".case-card");
  if (!cards.length || reduceMotion) return;

  // Nghieng theo con tro: doc toa do tung pointermove (Playwright/headless co the
  // khong phat su kien "pointerenter" dung luc, nen khong phu thuoc vao no).
  // Diem khong doi (cung toa do) thi bo qua de khong tinh lai vo ich.
  cards.forEach((card) => {
    let frame = 0;
    let lastX = null;
    let lastY = null;
    const apply = (e) => {
      if (e.pointerType && e.pointerType !== "mouse" && e.pointerType !== "pen") return;
      if (lastX === e.clientX && lastY === e.clientY) return;
      const rect = card.getBoundingClientRect();
      if (!rect.width || !rect.height) return;
      const px = clamp((e.clientX - rect.left) / rect.width, 0, 1);
      const py = clamp((e.clientY - rect.top) / rect.height, 0, 1);
      lastX = e.clientX;
      lastY = e.clientY;
      const rx = (0.5 - py) * 10; // nghiêng quanh trục X
      const ry = (px - 0.5) * 12; // nghiêng quanh trục Y
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        if (!card.classList.contains("is-tilting")) card.classList.add("is-tilting");
        card.style.setProperty("--rx", `${rx.toFixed(2)}deg`);
        card.style.setProperty("--ry", `${ry.toFixed(2)}deg`);
        card.style.setProperty("--mx", `${(px * 100).toFixed(1)}%`);
        card.style.setProperty("--my", `${(py * 100).toFixed(1)}%`);
      });
    };
    const reset = () => {
      cancelAnimationFrame(frame);
      card.style.setProperty("--rx", "0deg");
      card.style.setProperty("--ry", "0deg");
      lastX = null;
      lastY = null;
      card.classList.remove("is-tilting");
    };

    card.addEventListener("pointerenter", (e) => {
      lastX = null;
      lastY = null;
      apply(e);
    });
    card.addEventListener("pointermove", apply);
    card.addEventListener("pointerleave", reset);
    card.addEventListener("blur", reset);
  });
}

/* ------------------------------------------------------------------ */
/* 2. Chuyển cảnh khi chuyển trang (Cross-document View Transitions)  */
/* ------------------------------------------------------------------ */
function mountPageTransitions() {
  if (reduceMotion || !("onpagereveal" in window)) return;

  const STORE_KEY = "jv:nav";
  const main = () => document.getElementById("main");

  // Ghi lại vị trí cuộn + hướng đi để trang mới chọn kiểu chuyển cảnh.
  const record = (direction) => {
    try {
      sessionStorage.setItem(
        STORE_KEY,
        JSON.stringify({
          y: window.scrollY,
          t: Date.now(),
          dir: direction || "",
          path: location.pathname,
        })
      );
    } catch (err) {
      /* private mode */
    }
  };

  document.addEventListener("click", (e) => {
    const link = e.target.closest("a[href]");
    if (!link || e.defaultPrevented || link.target === "_blank") return;
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return;
    let url;
    try {
      url = new URL(link.href, location.href);
    } catch (err) {
      return;
    }
    if (url.origin !== location.origin) return;
    if (url.pathname === location.pathname && !url.hash) return;
    record(url.hash && url.pathname === location.pathname ? "" : "forward");
  });
  window.addEventListener("popstate", () => record("back"));

  // Trang mới: gắn "morph" cho tiêu đề h1 (nếu trình duyệt hỗ trợ view-transition-name riêng).
  window.addEventListener("pagereveal", (e) => {
    if (!e.viewTransition) return;
    let state = null;
    try {
      state = JSON.parse(sessionStorage.getItem(STORE_KEY) || "null");
    } catch (err) {
      state = null;
    }
    const fromOtherPage = state && state.path !== location.pathname && Date.now() - state.t < 5000;
    if (!fromOtherPage) return;
    if (state.dir === "back") e.viewTransition.types.add("back");
    e.viewTransition.types.add("jv");

    const h1 = main()?.querySelector("h1");
    if (h1 && CSS.supports("view-transition-name: page-title")) {
      h1.style.viewTransitionName = "page-title";
      e.viewTransition.finished.finally(() => {
        h1.style.viewTransitionName = "";
      });
    }

    // Shared element: khi tới trang chi tiết rương (`/case/<id>`) từ bảng
    // catalogue, ảnh rương "bay" từ thẻ sang đầu trang case — cảm giác
    // vật thể thật được nhấc lên từ kệ.
    if (state.dir !== "back" && CSS.supports("view-transition-name: card-image")) {
      const m = /\/case\/([^/?#]+)/.exec(location.pathname);
      if (m) {
        const headImg = document.querySelector(`.case-head-art img[data-case-id="${m[1]}"]`);
        if (headImg) headImg.style.viewTransitionName = "card-image";
      }
    }
  });
}

/* ------------------------------------------------------------------ */
/* 3. Reveal khi cuộn (chỉ phần tử do JS đánh dấu; không ẩn nội dung) */
/* ------------------------------------------------------------------ */
function mountReveal() {
  if (reduceMotion) return;
  if (CSS.supports("(animation-timeline: view()) and (animation-range: entry)")) return; // CSS lo hết

  const targets = document.querySelectorAll(".reveal");
  if (!targets.length || !("IntersectionObserver" in window)) return;
  const io = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add("fx-in");
        io.unobserve(entry.target);
      });
    },
    { rootMargin: "0px 0px -8% 0px", threshold: 0.12 }
  );
  targets.forEach((el) => {
    el.classList.add("fx-wait");
    io.observe(el);
  });
}

/* ------------------------------------------------------------------ */
/* 4. Số dư nhảy số + nhịp ăn mừng khi Coin tăng                      */
/* ------------------------------------------------------------------ */
function mountBalanceTween() {
  const chip = document.getElementById("coin-balance");
  if (!chip) return;
  let lastText = chip.textContent;
  let lastValue = parseCoin(lastText);
  let raf = 0;

  function parseCoin(text) {
    const digits = String(text || "").replace(/[^\d]/g, "");
    return digits ? Number(digits) : null;
  }

  function tweenTo(to, withGlow) {
    cancelAnimationFrame(raf);
    if (reduceMotion || lastValue === null || to === null || to === lastValue) {
      chip.textContent = formatCoin(to === null ? lastValue : to);
      if (withGlow) pulse(withGlow);
      return;
    }
    const from = lastValue;
    const start = performance.now();
    const DURATION = 650;
    const step = (now) => {
      const t = clamp((now - start) / DURATION, 0, 1);
      const eased = 1 - Math.pow(1 - t, 3);
      chip.textContent = formatCoin(Math.round(from + (to - from) * eased));
      if (t < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    if (withGlow) pulse(withGlow);
  }

  function formatCoin(n) {
    if (n === null) return lastText;
    return n.toLocaleString("vi-VN") + " Coin";
  }

  function pulse(kind) {
    if (reduceMotion) return;
    const target = chip.closest(".coin-chip") || chip;
    target.classList.remove("coin-pop-up", "coin-pop-down");
    void target.offsetWidth;
    target.classList.add(kind === "up" ? "coin-pop-up" : "coin-pop-down");
    setTimeout(() => target.classList.remove("coin-pop-up", "coin-pop-down"), 900);
  }

  // balance.js (chạy trước) đã ghi đè textContent ngay khi nhận sự kiện,
  // nên ở đây nghe lại và chỉ cần giữ số cũ để làm mốc nhảy số.
  document.addEventListener("jv:balance", (e) => {
    const next = parseCoin(e.detail && e.detail.balance_fmt);
    const prev = lastValue;
    if (next === null) return;
    chip.textContent = formatCoin(prev === null ? next : next);
    if (prev !== null && next !== prev) {
      const glow = next > prev ? "up" : "down";
      lastValue = prev;
      tweenTo(next, glow);
    } else {
      lastValue = next;
    }
    lastText = chip.textContent;
  });

  // Quan sát text từ các nguồn khác (poll balance.js) để không bị "dính" số cũ.
  const mo = new MutationObserver(() => {
    const v = parseCoin(chip.textContent);
    if (v !== null && !isAnimating()) lastValue = v;
  });
  const isAnimating = () => document.querySelector(".coin-pop-up, .coin-pop-down") !== null;
  mo.observe(chip, { childList: true, characterData: true, subtree: true });
}

/* ------------------------------------------------------------------ */
/* 5. Ăn mừng: confetti canvas ngắn, chỉ một lần, tự hủy             */
/* ------------------------------------------------------------------ */
let confettiCanvas = null;

export function celebrate({ wins = 1, tone = "gold", big = false } = {}) {
  if (reduceMotion) return;
  if (!confettiCanvas) {
    confettiCanvas = document.createElement("canvas");
    confettiCanvas.className = "fx-confetti";
    confettiCanvas.setAttribute("aria-hidden", "true");
    document.body.append(confettiCanvas);
  }
  const canvas = confettiCanvas;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const W = (canvas.width = Math.floor(innerWidth * dpr));
  const H = (canvas.height = Math.floor(innerHeight * dpr));

  const palettes = {
    gold: ["#ffc93c", "#ff9d2e", "#ffe7a3", "#ffd76b"],
    mint: ["#34d399", "#2dd4bf", "#a7f3d0", "#fde68a"],
    rose: ["#f472b6", "#fb7185", "#fecdd3", "#fbbf24"],
  };
  const colors = palettes[tone] || palettes.gold;
  const count = clamp(Math.round(46 * Math.sqrt(wins) * (big ? 1.8 : 1)), 30, 220);
  const parts = [];
  for (let i = 0; i < count; i += 1) {
    // Bắn từ hai bên đáy màn hình về phía giữa-trên.
    const side = i % 2 === 0 ? -1 : 1;
    const angle = (-Math.PI / 2) + side * (0.25 + Math.random() * 0.55);
    const speed = (big ? 14 : 10) + Math.random() * 8;
    parts.push({
      x: (side < 0 ? 0.08 : 0.92) * W,
      y: H * 0.98,
      vx: Math.cos(angle) * speed * dpr,
      vy: Math.sin(angle) * speed * dpr,
      r: (3 + Math.random() * 5) * dpr,
      spin: Math.random() * Math.PI,
      vs: (Math.random() - 0.5) * 0.25,
      color: colors[i % colors.length],
      life: 0,
    });
  }

  const GRAVITY = 0.32 * dpr;
  const TTL = 1800;
  const t0 = performance.now();
  let frame = 0;

  const tick = (now) => {
    const dt = clamp((now - t0) / 16.7, 0.5, 2.2);
    ctx.clearRect(0, 0, W, H);
    let alive = 0;
    parts.forEach((p) => {
      if (p.life > TTL) return;
      p.life += (now - t0 > 0 ? 16.7 * dt : 0);
      p.vy += GRAVITY * dt;
      p.vx *= 0.995;
      p.x += p.vx * dt;
      p.y += p.vy * dt;
      p.spin += p.vs * dt;
      const remain = 1 - clamp((p.life - TTL * 0.6) / (TTL * 0.4), 0, 1);
      ctx.globalAlpha = remain;
      ctx.fillStyle = p.color;
      ctx.translate(p.x, p.y);
      ctx.rotate(p.spin);
      ctx.fillRect(-p.r / 2, -p.r / 4, p.r, p.r / 2);
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      if (p.life <= TTL && p.y < H + 40) alive += 1;
    });
    ctx.globalAlpha = 1;
    if (alive > 0) {
      frame = requestAnimationFrame(tick);
    } else {
      canvas.remove();
      confettiCanvas = null;
    }
  };
  cancelAnimationFrame(frame);
  frame = requestAnimationFrame(tick);
}

/* ------------------------------------------------------------------ */
/* 6. Overlay khi mở rương / quay: lật góc nhìn scene                 */
/* ------------------------------------------------------------------ */
export function stagePerspective({ intense = false } = {}) {
  if (reduceMotion) return;
  const stage = document.querySelector(".js-stage");
  if (!stage) return;
  stage.classList.remove("fx-stage-lift");
  void stage.offsetWidth;
  stage.classList.add("fx-stage-lift");
  if (intense) document.documentElement.classList.add("fx-glow-up");
  setTimeout(() => {
    stage.classList.remove("fx-stage-lift");
    document.documentElement.classList.remove("fx-glow-up");
  }, 1200);
}

/* ------------------------------------------------------------------ */
/* Khởi động                                                          */
/* ------------------------------------------------------------------ */
// Cho các script cổ điển (bonus.html...) gọi được mà không cần import.
globalThis.jvCelebrate = celebrate;
globalThis.jvStagePerspective = stagePerspective;

function boot() {
  if (reduceMotion) return;
  mountCards();
  mountPageTransitions();
  mountReveal();
  mountBalanceTween();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", boot, { once: true });
} else {
  boot();
}
