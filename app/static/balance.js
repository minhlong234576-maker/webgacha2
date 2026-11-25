/* Hiển thị số dư Coin realtime.
 *
 * Chip số dư trên header được cập nhật định kỳ từ /api/balance, để người chơi
 * thấy Coin in-game thay đổi (nạp trong game, admin thưởng, mở rương từ
 * tab khác...) mà không cần tải lại trang.
 */
(function () {
  const POLL_MS = 10000;

  const chips = () => document.querySelectorAll("#coin-balance");

  function paint(balanceFmt) {
    chips().forEach((chip) => {
      chip.textContent = balanceFmt + " Coin";
    });
  }

  async function poll() {
    try {
      const res = await fetch("/api/balance", { credentials: "same-origin" });
      if (!res.ok) return;
      const data = await res.json();
      if (data && data.balance_fmt) {
        paint(data.balance_fmt);
        document.dispatchEvent(new CustomEvent("jv:balance", { detail: data }));
      }
    } catch (err) {
      /* ignore — giữ số dư hiện tại */
    }
  }

  // Sự kiện từ các trang khác (mở rương / bán đồ / cược) đã tự cập nhật chip
  // bằng balance_fmt trả về. Sự kiện này giữ cho mọi nơi cập nhật đồng nhất.
  document.addEventListener("jv:balance", (e) => {
    const fmt = e.detail && e.detail.balance_fmt;
    if (fmt) paint(fmt);
  });

  if (chips().length) {
    poll();
    setInterval(poll, POLL_MS);
  }
})();
