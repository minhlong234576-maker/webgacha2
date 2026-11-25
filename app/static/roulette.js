import { celebrate, stagePerspective } from "/static/fx.js";

const H_TILE = 148;
const V_TILE = 116;
const GAP = 8;
const STRIP_LENGTH = 60;
const WINNER_INDEX = 52;
export const SPIN_MS = 5200;
const STAGGER_MS = 260;

function buildStrip(pool, winner) {
  const tiles = [];
  for (let i = 0; i < STRIP_LENGTH; i += 1) {
    tiles.push(pool[Math.floor(Math.random() * pool.length)]);
  }
  tiles[WINNER_INDEX] = winner;
  return tiles;
}

function tileNode(item, horizontal) {
  const node = document.createElement("div");
  node.className = "tile";
  node.dataset.id = item.id;
  node.style.borderBottomColor = item.color || "#b0c3d9";
  const w = horizontal ? H_TILE : "86%";
  const h = horizontal ? 140 : V_TILE;
  node.style.width = typeof w === "number" ? `${w}px` : w;
  node.style.height = `${h}px`;
  node.style.flex = `0 0 ${typeof w === "number" ? `${w}px` : "auto"}`;

  const img = document.createElement("img");
  img.src = item.image || "/static/items/_placeholder.svg";
  img.alt = "";
  img.draggable = false;
  img.loading = "eager";
  const label = document.createElement("span");
  label.textContent = item.name;
  node.append(img, label);
  return node;
}

export function spinReel({ pool, winner, onFinish, viewport, strip, orientation = "horizontal", index = 0 }) {
  const viewportEl = viewport || document.getElementById("reel");
  const stripEl = strip || document.getElementById("reel-strip");
  if (!viewportEl || !stripEl || !winner || !pool.length) return;

  const horizontal = orientation !== "vertical";
  const tile = horizontal ? H_TILE : V_TILE;
  const stride = tile + GAP;
  const duration = SPIN_MS + index * STAGGER_MS;
  const tiles = buildStrip(pool, winner);

  stripEl.className = horizontal ? "reel-strip" : "reel-strip vertical";
  stripEl.replaceChildren();
  const frag = document.createDocumentFragment();
  tiles.forEach((item) => frag.append(tileNode(item, horizontal)));
  stripEl.append(frag);
  stripEl.style.transition = "none";
  stripEl.style.transform = "translate3d(0,0,0)";
  viewportEl.style.borderColor = "";
  viewportEl.style.boxShadow = "";
  viewportEl.classList.remove("fx-win");
  if (!horizontal) viewportEl.style.height = "320px";
  if (index === 0) stagePerspective({ intense: !horizontal });

  const jitter = (Math.random() - 0.5) * (tile * 0.22);
  const size = horizontal ? viewportEl.clientWidth : viewportEl.clientHeight;
  const target = WINNER_INDEX * stride + tile / 2 - size / 2 + jitter;

  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      stripEl.style.transition = `transform ${duration}ms cubic-bezier(0.10, 0.82, 0.12, 1)`;
      stripEl.style.transform = horizontal
        ? `translate3d(${-target}px, 0, 0)`
        : `translate3d(0, ${-target}px, 0)`;
    });
  });

  window.setTimeout(() => {
    stripEl.style.transition = "none";
    stripEl.style.transform = horizontal
      ? `translate3d(${-target}px, 0, 0)`
      : `translate3d(0, ${-target}px, 0)`;
    const nodes = stripEl.querySelectorAll(".tile");
    nodes.forEach((node, i) => {
      node.classList.toggle("win", i === WINNER_INDEX);
      node.classList.toggle("dim", i !== WINNER_INDEX);
    });
    viewportEl.style.borderColor = winner.color;
    viewportEl.style.boxShadow = `0 0 26px -6px ${winner.color}`;
    viewportEl.classList.add("fx-win");
    // Chỉ lượt quay đầu tiên (hoặc reel đơn) mới bắn confetti để không rối mắt.
    if (index === 0) celebrate({ wins: 1, tone: "gold", big: !horizontal });
    onFinish?.(winner);
  }, duration);
}
