// HardenGarden landing page: draws the garden bed and wires the copy buttons.
"use strict";

const SVG = "http://www.w3.org/2000/svg";
const WORDS = { PASS: "Healthy", FAIL: "Weed", WARN: "Needs care" };

// The same glyphs as the desktop app: sprout, thistle, drooping plant.
const GLYPHS = {
  PASS: [
    ["path", { d: "M20 38V18", fill: "none", stroke: "var(--fern)", "stroke-width": 2, "stroke-linecap": "round" }],
    ["path", { d: "M20 24c-7 0-11-4-11-10 6 0 11 3 11 10Z", fill: "var(--fern)" }],
    ["path", { d: "M20 20c0-7 4-12 11-12 0 7-4 12-11 12Z", fill: "var(--fern)" }],
  ],
  FAIL: [
    ["path", { d: "M20 38V16M20 30l-6-5M20 27l6-4M20 7V2M15 8l-3-4M25 8l3-4M14 12h-5M26 12h5", fill: "none", stroke: "var(--thistle)", "stroke-width": 2, "stroke-linecap": "round" }],
    ["circle", { cx: 20, cy: 12, r: 5, fill: "var(--thistle)" }],
  ],
  WARN: [
    ["path", { d: "M20 38V22c0-6 4-9 9-10", fill: "none", stroke: "var(--pollen)", "stroke-width": 2, "stroke-linecap": "round" }],
    ["path", { d: "M29 12c2 4 1 8-3 10-2-4-1-8 3-10Z", fill: "var(--pollen)" }],
    ["path", { d: "M20 30c-5 0-8-2-9-6 4 0 8 1 9 6Z", fill: "var(--pollen)" }],
  ],
};

function plant(status) {
  const svg = document.createElementNS(SVG, "svg");
  svg.setAttribute("viewBox", "0 0 40 40");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  for (const [tag, attrs] of GLYPHS[status]) {
    const el = document.createElementNS(SVG, tag);
    for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, String(v));
    svg.append(el);
  }
  return svg;
}

function drawBed() {
  const bed = document.querySelector(".bed");
  const detail = document.querySelector(".bed-detail");
  if (!bed || !detail) return;
  const resting = detail.textContent;
  bed.querySelectorAll("li").forEach((li, index) => {
    const status = li.dataset.status;
    const id = li.textContent.trim();
    const label = `HG-${id} ${li.dataset.title}: ${WORDS[status]}`;
    const button = document.createElement("button");
    button.type = "button";
    button.className = `plant plant-${status}`;
    button.setAttribute("aria-label", label);
    button.style.setProperty("--i", String(index));
    const name = document.createElement("span");
    name.textContent = id;
    button.append(plant(status), name);
    const show = () => {
      detail.textContent = `HG-${id}, ${li.dataset.title}: ${WORDS[status]}`;
      detail.dataset.status = status;
    };
    const hide = () => {
      detail.textContent = resting;
      delete detail.dataset.status;
    };
    button.addEventListener("mouseenter", show);
    button.addEventListener("focus", show);
    button.addEventListener("click", show);
    button.addEventListener("mouseleave", hide);
    button.addEventListener("blur", hide);
    li.replaceChildren(button);
  });
  bed.classList.add("grown");
}

function wireCopyButtons() {
  document.querySelectorAll(".code").forEach((block) => {
    const button = block.querySelector(".copy");
    const code = block.querySelector("code");
    if (!button || !code || !navigator.clipboard) {
      button?.remove();
      return;
    }
    button.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(code.textContent);
        button.textContent = "Copied";
      } catch {
        button.textContent = "Select and copy";
      }
      setTimeout(() => {
        button.textContent = "Copy";
      }, 2000);
    });
  });
}

drawBed();
wireCopyButtons();
