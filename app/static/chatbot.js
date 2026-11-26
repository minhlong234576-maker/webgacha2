/* Trợ lý lệnh — frontend của chatbot hỏi/đáp về lệnh console Minecraft.
 *
 * Panel là <dialog popover="manual">: mở bằng `showPopover()` (không phải
 * `showModal()`) để người chơi vẫn cuộn/xem được trang phía sau.
 *
 * Mọi nội dung do server trả về được chèn bằng `textContent` — không
 * dùng innerHTML — nên không có nguy cơ XSS từ mô tả lệnh.
 */

const ENDPOINT = "/api/chat";

const SUGGESTIONS = [
  "Lệnh xem số dư là gì?",
  "Lệnh về nhà",
  "Lệnh mời người chơi khác qua tpa",
  "Cách đổi skin",
  "Lệnh xem ai đang online",
  "Lệnh claim vùng đất",
];

function csrfToken() {
  const meta = document.querySelector('meta[name="csrf"]');
  return meta ? meta.content : "";
}

export function initChatbot() {
  const dialog = document.getElementById("chatbot");
  if (!dialog) return;

  const log = document.getElementById("chatbot-log");
  const form = document.getElementById("chatbot-form");
  const input = document.getElementById("chatbot-input");
  const sendBtn = document.getElementById("chatbot-send");
  const chips = document.getElementById("chatbot-chips");
  const closeBtn = document.getElementById("chatbot-close");
  if (!log || !form || !input) return;

  let busy = false;

  function isOpen() {
    return dialog.open === true;
  }

  function scrollDown() {
    log.scrollTop = log.scrollHeight;
  }

  function addMessage(role, text) {
    const node = document.createElement("div");
    node.className = role === "user" ? "chat-msg user" : "chat-msg bot";
    node.textContent = text;
    log.append(node);
    scrollDown();
    return node;
  }

  function addError(text) {
    const node = document.createElement("div");
    node.className = "chat-msg error";
    node.textContent = text;
    log.append(node);
    scrollDown();
  }

  function addCommands(commands) {
    if (!commands || !commands.length) return;
    const wrap = document.createElement("div");
    wrap.className = "chat-cmds";
    commands.forEach((cmd) => {
      const name = String(cmd.name || "");
      if (!name) return;
      const row = document.createElement("button");
      row.type = "button";
      row.className = "chat-cmd";
      row.title = "Bấm để chép lệnh";

      const code = document.createElement("code");
      code.textContent = "/" + name;
      row.append(code);

      const desc = document.createElement("span");
      desc.textContent = cmd.desc || "";
      row.append(desc);

      if (cmd.admin_only) {
        const tag = document.createElement("span");
        tag.className = "admin-tag";
        tag.textContent = "admin";
        row.append(tag);
      }

      const hint = document.createElement("span");
      hint.className = "copy-hint";
      hint.textContent = "chép";
      row.append(hint);

      row.addEventListener("click", async () => {
        const text = "/" + name;
        try {
          await navigator.clipboard.writeText(text);
          hint.textContent = "đã chép";
        } catch (err) {
          hint.textContent = "chép thủ công";
        }
        window.setTimeout(() => {
          hint.textContent = "chép";
        }, 1600);
      });

      wrap.append(row);
    });
    if (wrap.childElementCount) {
      log.append(wrap);
      scrollDown();
    }
  }

  function addTyping() {
    const node = document.createElement("div");
    node.className = "chat-typing";
    node.setAttribute("aria-label", "Đang trả lời");
    node.append(document.createElement("i"), document.createElement("i"), document.createElement("i"));
    log.append(node);
    scrollDown();
    return node;
  }

  function setBusy(value) {
    busy = value;
    if (sendBtn) sendBtn.disabled = value;
    input.disabled = value;
  }

  async function ask(question) {
    const text = (question || "").trim();
    if (!text || busy) return;
    addMessage("user", text);
    const typing = addTyping();
    setBusy(true);
    try {
      const res = await fetch(ENDPOINT, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRF": csrfToken() },
        body: JSON.stringify({ q: text }),
        credentials: "same-origin",
      });
      const data = await res.json().catch(() => ({}));
      typing.remove();
      if (!res.ok) {
        addError(data.detail || "Không gửi được câu hỏi. Thử lại nhé.");
        return;
      }
      addMessage("bot", data.reply || "Mình chưa có câu trả lời.");
      addCommands(data.commands);
    } catch (err) {
      typing.remove();
      addError("Không kết nối được tới trợ lý. Kiểm tra mạng rồi thử lại.");
    } finally {
      setBusy(false);
      input.focus();
    }
  }

  // Chip gợi ý — chỉ tạo một lần.
  if (chips && !chips.childElementCount) {
    SUGGESTIONS.forEach((s) => {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "chat-chip";
      chip.textContent = s;
      chip.addEventListener("click", () => ask(s));
      chips.append(chip);
    });
  }

  // Nút nổi (mọi trang) — chỉ hiện khi trang khong co nut "Tro ly lenh" trong
  // hero (tranh hai nut cung mot viec).
  const fab = document.querySelector(".chat-fab");
  const heroBtn = document.querySelector(".hero-chat-btn");
  // Trang da co nut "Tro ly lenh" trong hero thi khong can nut noi (tranh hai
  // nut cung mot viec).
  if (fab && heroBtn) fab.remove();

  function openPanel() {
    if (dialog.open) return;
    if (!log.childElementCount) {
      addMessage(
        "bot",
        "Chào bạn! Mình là trợ lý tra cứu lệnh của JellyVale. Hỏi mình bất cứ lệnh nào bạn có thể dùng trong server nhé."
      );
    }
    // `showModal()` — browser lo top layer, focus trap, Esc va tra focus.
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
    if (fab) fab.classList.add("is-hidden");
    window.setTimeout(() => input.focus(), 60);
  }

  function closePanel() {
    if (!dialog.open) return;
    if (typeof dialog.close === "function") dialog.close();
    else dialog.removeAttribute("open");
  }

  // Mot listener duy nhat cho moi nut mo panel (event delegation).
  document.addEventListener("click", (e) => {
    const trigger = e.target.closest("[data-open-chatbot]");
    if (!trigger) return;
    e.preventDefault();
    openPanel();
  });

  dialog.addEventListener("close", () => {
    if (fab) fab.classList.remove("is-hidden");
  });

  if (closeBtn) closeBtn.addEventListener("click", closePanel);

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const value = input.value;
    input.value = "";
    ask(value);
  });

  // Click ra ngoai van dong (Safari chua ho tro `closedby="any"`).
  let pressedOutside = false;
  document.addEventListener("pointerdown", (e) => {
    if (!isOpen()) return;
    const rect = dialog.getBoundingClientRect();
    pressedOutside =
      e.clientX < rect.left || e.clientX > rect.right || e.clientY < rect.top || e.clientY > rect.bottom;
  });
  document.addEventListener("pointerup", (e) => {
    if (!isOpen() || !pressedOutside) return;
    const rect = dialog.getBoundingClientRect();
    const outside =
      e.clientX < rect.left || e.clientX > rect.right || e.clientY < rect.top || e.clientY > rect.bottom;
    if (outside) closePanel();
  });
}
