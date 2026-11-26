/* intro.js — Màn hình chờ (loading screen) trước khi vào web.
 *
 * Luồng:
 *   1. Xem video intro (`/static/media/loading-intro.mp4`) chạy nền tối.
 *   2. Trong lúc video chạy, màn hình hiện: logo "JV", thanh tiến trình kiểu
 *      Minecraft block, các tip "Mẹo chơi" xoay vòng.
 *   3. Khi video chạy hết (hoặc sau `MAX_WAIT` nếu video lỗi) → overlay mở
 *      "giống cửa sập" rồi mới cho người dùng tương tác.
 *   4. Người dùng bấm nút "Bỏ qua" để vào ngay.
 *
 * Quy tắc:
 *   - Chỉ hiển thị 1 lần mỗi phiên (sessionStorage `jv:intro`). Nếu đã thấy rồi
 *     (chuyển trang trong lúc dùng) thì ẩn bằng `[hidden]` + CSS `display:none`.
 *   - `prefers-reduced-motion: reduce` → bỏ qua toàn bộ, không chặn tương tác.
 *   - Không tự động phát âm thanh (`muted` + `playsinline`), không chặn
 *     nếu video lỗi/mất mạng (fallback chờ tối đa `MAX_WAIT` ms).
 *   - Lưu trạng thái overlay trên `<html data-intro="...">` để CSS phối hợp.
 */

const KEY = "jv:intro";
const SESSION_KEY = "jv:session-intro";
const MAX_WAIT = 9000; // ms — nếu video không bao giờ loadedmetadata thì vẫn mở
const MIN_SHOW = 1000; // ms — tránh nhấp nháy khi video rất ngắn

const TIPS = [
  "Mỗi rương có tỉ lệ rơi chính xác hiển thị trong trang chi tiết — RTP tổng thể 90%.",
  "Đồ trúng thưởng vào thẳng túi đồ. Bán lấy Coin hoặc rút thẳng vào Minecraft bằng `nexo give`.",
  "Case battle: người có tổng giá trị đồ cao nhất mang hết đồ về. Tối đa 30 vòng/trận.",
  "Nâng cấp 2 món thành 1 món đắt hơn — tỉ lệ = 90% × tổng giá cược / giá đích.",
  "Bonus ngày: quay miễn phí 1 lần mỗi 24 giờ, Coin cộng thẳng vào ví web.",
  "Coinflip Roulette: hash commit được công bố trước mỗi vòng để kiểm chứng.",
  "Giữ `Shift` khi click vào rương để mở nhanh không cần xác nhận.",
];

function prefersReduced() {
  try {
    return matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch {
    return false;
  }
}

function markSeen() {
  try {
    sessionStorage.setItem(KEY, "1");
  } catch {
    /* private mode */
  }
}

function hasSeen() {
  try {
    return sessionStorage.getItem(KEY) === "1";
  } catch {
    return false;
  }
}

function buildOverlay() {
  const root = document.createElement("div");
  root.id = "intro";
  root.className = "intro";
  root.setAttribute("role", "dialog");
  root.setAttribute("aria-modal", "true");
  root.setAttribute("aria-labelledby", "intro-title");

  const video = document.createElement("video");
  video.className = "intro-video";
  video.muted = true;
  video.defaultMuted = true;
  video.playsInline = true;
  video.autoplay = true;
  video.preload = "auto";
  video.setAttribute("muted", "");
  video.setAttribute("playsinline", "");
  video.setAttribute("aria-hidden", "true");
  video.src = "/static/media/loading-intro.mp4";

  const veil = document.createElement("div");
  veil.className = "intro-veil";
  veil.setAttribute("aria-hidden", "true");

  const panel = document.createElement("div");
  panel.className = "intro-panel";

  const badge = document.createElement("div");
  badge.className = "intro-badge";
  badge.setAttribute("aria-hidden", "true");
  badge.textContent = "JV";

  const title = document.createElement("p");
  title.id = "intro-title";
  title.className = "intro-title";
  title.setAttribute("role", "heading");
  title.setAttribute("aria-level", "2");
  title.textContent = "JellyVale";

  const sub = document.createElement("p");
  sub.className = "intro-sub";
  sub.textContent = "Đang kết nối tới server Minecraft…";

  const progressWrap = document.createElement("div");
  progressWrap.className = "intro-progress";
  progressWrap.setAttribute("role", "progressbar");
  progressWrap.setAttribute("aria-valuemin", "0");
  progressWrap.setAttribute("aria-valuemax", "100");
  progressWrap.setAttribute("aria-valuenow", "0");
  progressWrap.setAttribute("aria-label", "Tiến trình tải trang");

  const progressFill = document.createElement("span");
  progressFill.className = "intro-progress-fill";
  progressWrap.append(progressFill);

  const pct = document.createElement("span");
  pct.className = "intro-pct";
  pct.textContent = "0%";

  const tip = document.createElement("p");
  tip.className = "intro-tip";
  tip.setAttribute("aria-live", "polite");
  tip.textContent = TIPS[0];

  const actions = document.createElement("div");
  actions.className = "intro-actions";

  const skipBtn = document.createElement("button");
  skipBtn.type = "button";
  skipBtn.className = "cf-btn-ghost intro-skip";
  skipBtn.textContent = "Bỏ qua →";

  actions.append(skipBtn);
  panel.append(badge, title, sub, progressWrap, pct, tip, actions);
  root.append(video, veil, panel);

  return { root, video, progressWrap, progressFill, pct, tip, skipBtn };
}

function pxStep(num) {
  // Thanh tiến trình "vuốt sọc" từng ô 8px kiểu slot Minecraft: làm tròn
  // về bội số để fill nhảy theo từng ô thay vì trượt mượt.
  const STEP = 8;
  return Math.floor(num / STEP) * STEP;
}

function showIntro(els) {
  const { root, video, progressWrap, progressFill, pct, tip, skipBtn } = els;
  document.documentElement.dataset.intro = "showing";
  document.body.append(root);

  // Khóa cuộn cho tới khi đóng overlay.
  const prevOverflow = document.body.style.overflow;
  document.body.style.overflow = "hidden";

  const start = performance.now();
  let closed = false;
  let tipIndex = 0;
  let progress = 0;

  // Rải tip theo thời gian
  const tipTimer = setInterval(() => {
    tipIndex = (tipIndex + 1) % TIPS.length;
    tip.textContent = TIPS[tipIndex];
    tip.classList.remove("is-swap");
    void tip.offsetWidth;
    tip.classList.add("is-swap");
  }, 2600);

  // Tiến trình: bám theo thời lượng video nếu biết; nếu chưa biết thì giả lập.
  let duration = 6;
  const lockProgress = () => {
    duration = Number.isFinite(video.duration) && video.duration > 0.4
      ? video.duration
      : 6;
  };
  video.addEventListener("loadedmetadata", lockProgress, { once: true });
  video.addEventListener("durationchange", lockProgress);

  function tick() {
    if (closed) return;
    const elapsed = (performance.now() - start) / 1000;
    const t = video.currentTime || 0;
    const ratio = video.ended
      ? 1
      : clamp01(t > 0 || video.readyState >= 2 ? t / duration : elapsed / duration);
    // Nhẩy theo ô slot 8px cho đúng chất Minecraft.
    progress = Math.max(progress, ratio * 100);
    const snapped = Math.min(100, pxStep(progress * 1.2));
    progressFill.style.width = `${snapped}%`;
    pct.textContent = `${Math.round(snapped)}%`;
    progressWrap.setAttribute("aria-valuenow", String(Math.round(snapped)));
    requestAnimationFrame(tick);
  }

  function clamp01(v) {
    return Math.min(1, Math.max(0, v));
  }

  function close(reason) {
    if (closed) return;
    closed = true;
    clearInterval(tipTimer);
    progressFill.style.width = "100%";
    pct.textContent = "100%";
    progressWrap.setAttribute("aria-valuenow", "100");
    root.classList.add("is-closing");
    document.documentElement.dataset.intro = "closing";
    markSeen();

    const finish = () => {
      root.remove();
      document.body.style.overflow = prevOverflow;
      delete document.documentElement.dataset.intro;
      // Cho trang nhận focus lại; main xuất hiện với hiệu ứng "pop-in block".
      document.getElementById("main")?.classList.add("intro-entered");
      video.pause();
      video.removeAttribute("src");
      try {
        video.load();
      } catch {
        /* một số trình duyệt cũ ném lỗi nếu src đã bị xóa */
      }
    };
    const wait = Math.max(0, MIN_SHOW - (performance.now() - start));
    setTimeout(finish, Math.max(260, wait));
    void reason;
  }

  // Đóng khi: video hết, video lỗi (fallback), người dùng bấm Bỏ qua,
  // hoặc hết MAX_WAIT.
  video.addEventListener("ended", () => close("ended"), { once: true });
  video.addEventListener("error", () => close("media-error"), { once: true });
  const hardStop = setTimeout(() => close("timeout"), MAX_WAIT);

  skipBtn.addEventListener("click", () => {
    clearTimeout(hardStop);
    close("skip");
  });
  document.addEventListener(
    "keydown",
    (e) => {
      if (e.key === "Escape") {
        clearTimeout(hardStop);
        close("escape");
      }
    },
    { once: true }
  );

  // Bắt đầu phát: Safari/iOS hay chặn autoplay nếu src gán muộn → gọi
  // play() thủ công; nếu Promise reject thì fallback theo giả lập.
  const playResult = video.play();
  if (playResult && typeof playResult.catch === "function") {
    playResult.catch(() => {
      // Không phát được: giữ overlay nhạc nhàng, cho phép đóng theo MAX_WAIT.
      video.setAttribute("data-blocked", "1");
    });
  }

  requestAnimationFrame(tick);
}

function boot() {
  if (hasSeen() || prefersReduced()) {
    // Đã thấy: ẩn hẳn overlay, không tạo DOM.
    document.documentElement.dataset.intro = "done";
    return;
  }
  // Nếu trang tải quá chậm, chỉ chờ tối đa MAX_WAIT.
  const els = buildOverlay();
  showIntro(els);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", boot, { once: true });
} else {
  boot();
}
