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

function tileHtml(item, horizontal) {
  const color = item.color || "#b0c3d9";
  const src = item.image || "/static/items/_placeholder.svg";
  const w = horizontal ? H_TILE : "86%";
  const h = horizontal ? 140 : V_TILE;
  return `<div class="tile" data-id="${item.id}" style="border-bottom-color:${color};width:${typeof w === "number" ? w + "px" : w};height:${h}px;flex:0 0 ${typeof w === "number" ? w + "px" : "auto"}">
    <img src="${src}" alt="${item.name}" draggable="false" loading="eager">
    <span>${item.name}</span>
  </div>`;
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
  stripEl.innerHTML = tiles.map((item) => tileHtml(item, horizontal)).join("");
  stripEl.style.transition = "none";
  stripEl.style.transform = "translate3d(0,0,0)";
  viewportEl.style.borderColor = "";
  viewportEl.style.boxShadow = "";
  if (!horizontal) viewportEl.style.height = "320px";

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
    onFinish?.(winner);
  }, duration);
}
