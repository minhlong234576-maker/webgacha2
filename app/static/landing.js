/**
 * Landing page — video nen.
 *
 * Video duoc load "khi can" (lazy) de khong ton bang thong tren lan tai dau
 * tien: poster JPEG hien thi ngay, chi khi video vao khung nhin moi gan `src`.
 *
 * - `prefers-reduced-motion: reduce` -> khong gan `src` o dau, chi hien poster.
 * - `navigator.connection.saveData` -> giu poster, khong tai video.
 * - Video khong chay khi tab bi an -> tiet kiem CPU/pin.
 *
 * Nguon video nam trong `data-src` (khong phai `src`) de trinh duyet KHONG
 * tu dong tai video truoc khi JS kiem tra duoc reduced-motion / save-data.
 */

const video = document.querySelector(".lp-video");
const stage = document.querySelector(".lp-stage");

if (video && stage) {
  const sources = Array.from(video.querySelectorAll("source[data-src]"));
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  const saveData = navigator.connection?.saveData === true;

  let loaded = false;

  function loadVideo() {
    if (loaded || reduceMotion.matches || saveData) return;
    loaded = true;
    for (const source of sources) {
      source.setAttribute("src", source.dataset.src);
      delete source.dataset.src;
    }
    video.load();
    const play = video.play();
    if (play && typeof play.catch === "function") {
      // Trinh duyet tu choi -> bo qua, poster van hien.
      play.catch(() => {});
    }
  }

  if (!("IntersectionObserver" in window)) {
    loadVideo();
  } else {
    const io = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          loadVideo();
          io.disconnect();
        }
      },
      { rootMargin: "200px" },
    );
    io.observe(stage);
  }

  // Dung phat khi tab bi an.
  document.addEventListener("visibilitychange", () => {
    if (!loaded) return;
    if (document.hidden) {
      video.pause();
    } else if (!reduceMotion.matches) {
      video.play().catch(() => {});
    }
  });
}

// So nguoi dang online tren server Minecraft — server render so luc mo trang,
// frontend poll nhe de con so khong bi cu khi nguoi choi vao/ra.
(function pollOnline() {
  const chip = document.querySelector("[data-online-count]");
  if (!chip) return;
  setInterval(async () => {
    if (document.hidden) return;
    try {
      const res = await fetch("/api/online", { credentials: "same-origin" });
      if (!res.ok) return;
      const data = await res.json();
      const n = Number(data.online);
      if (Number.isFinite(n)) chip.textContent = String(n);
    } catch (err) {
      /* ignore — giu so hien tai */
    }
  }, 15000);
})();
