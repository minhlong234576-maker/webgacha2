const H_TILE = 148;
const V_TILE = 116;
const GAP = 8;

/* So tile trong dai quay.
 *
 * Dai phai DU de che viewport + du do lan quay de co cam giac "keo dai".
 * 40 tile (dai ~6.200px ngang) vua du cho nhin thay va giam 33% so DOM node
 * + anh so voi 60 tile. Truoc day 5 luot = 300 <img>, gio = 200 <img>.
 */
const STRIP_LENGTH = 40;
const WINNER_INDEX = 32;
export const SPIN_MS = 5200;
const STAGGER_MS = 260;

/* Chi so sanh: vi tri cua tile trong STRIP -> pixel offset.
 *
 * Dung mot mang `tileOffsets` tinh san thay vi `getBoundingClientRect()` tren
 * tung tile: do la O(n) layout reads, gay "layout shift" khi trinh duyet phai
 * lay lai layout giua cac frame -> rung man hinh. Offset tinh theo cong thuc
 * (tile + GAP) la duong tinh nen chi tinh 1 lan.
 */
function tileOffset(index, tile) {
  return index * (tile + GAP);
}

function buildStrip(pool, winner) {
  const tiles = [];
  for (let i = 0; i < STRIP_LENGTH; i += 1) {
    tiles.push(pool[Math.floor(Math.random() * pool.length)]);
  }
  tiles[WINNER_INDEX] = winner;
  return tiles;
}

/* Cache anh theo URL.
 *
 * Dai quay tao lai DOM moi moi luot (40 tile) nhung anh cua mot mon LUON
 * giong nhau. Browser cache theo URL nen tai lai khong ton bang, nhung tao
 * 40 <img> moi = 40 muc decode moi -> "nhay anh" giua duong keo va frame
 * dau bi treo.
 *
 * Giai phap: giu mot <img> "source" cho moi URL, tai san 1 lan. Khi can tile,
 * dung `src` da resolve cua node goc (trinh duyet dung cache, khong tai lai).
 */
const imageCache = new Map();

function cachedImage(url) {
  const key = url || "/static/items/_placeholder.svg";
  let base = imageCache.get(key);
  if (!base) {
    base = new Image();
    base.decoding = "async";
    base.src = key;
    imageCache.set(key, base);
  }
  return base;
}

/* Do rong toi da: giu qua nhieu anh trong RAM se ton bo nho. Vuot qua gioi
 * han thi danh dau lai (browser van cache anh, chi can lai lai).
 */
const MAX_CACHED_IMAGES = 120;
function rememberImage(url) {
  if (imageCache.size > MAX_CACHED_IMAGES) {
    const firstKey = imageCache.keys().next().value;
    if (firstKey !== undefined) imageCache.delete(firstKey);
  }
  cachedImage(url);
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

  const url = item.image || "/static/items/_placeholder.svg";
  rememberImage(url);
  const img = document.createElement("img");
  // `src` lay tu node goc da tai san -> trinh duyet dung cache, khong tai lai.
  img.src = cachedImage(url).src;
  img.alt = "";
  img.draggable = false;
  img.loading = "eager";
  img.decoding = "async";
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

  const jitter = (Math.random() - 0.5) * (tile * 0.22);
  // Doc kich thuoc viewport TRUOC khi ghi transform. Doc sau khi ghi se lam
  // trinh duyet phai layout lai giua cac frame -> rung man hinh.
  const size = horizontal ? viewportEl.clientWidth : viewportEl.clientHeight;
  // Offset cua tile thang: dung cong thuc (khong doc layout) + jitter nho de
  // thang co cam giac "dung ngau nhiên" nhung van nam chinh xac giua marker.
  const target = tileOffset(WINNER_INDEX, tile) + tile / 2 - size / 2 + jitter;

  // `will-change` chi dat khi chuyen dong that su, va go sau khi xong —
  // giu no lai tao layer "promote" ton tai, ton RAM va gay rung nhe.
  stripEl.style.willChange = "transform";
  viewportEl.style.willChange = "transform";

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
    // `will-change` bo sau khi dung chuyen dong — giu no se ton layer.
    stripEl.style.willChange = "";
    viewportEl.style.willChange = "";

    // Danh dau tile thang. Duyet qua `children` (khong `querySelectorAll`)
    // de khong phai trai duyet CSS selector tren 60 node moi lan quay.
    const nodes = stripEl.children;
    for (let i = 0; i < nodes.length; i += 1) {
      const node = nodes[i];
      if (i === WINNER_INDEX) {
        node.classList.add("win");
        node.classList.remove("dim");
      } else {
        node.classList.add("dim");
        node.classList.remove("win");
      }
    }
    viewportEl.style.borderColor = winner.color;
    viewportEl.style.boxShadow = `0 0 26px -6px ${winner.color}`;
    viewportEl.classList.add("fx-win");
    onFinish?.(winner);
  }, duration);
}
