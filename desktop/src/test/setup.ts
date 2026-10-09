import "@testing-library/jest-dom/vitest";

// jsdom lacks HTMLDialogElement.showModal/close; real webviews implement both.
if (typeof HTMLDialogElement !== "undefined" && !("showModal" in HTMLDialogElement.prototype)) {
  Object.assign(HTMLDialogElement.prototype, {
    showModal(this: HTMLDialogElement) {
      this.open = true;
    },
    close(this: HTMLDialogElement) {
      this.open = false;
    },
  });
}

// jsdom does not implement scrolling; the app only uses it to reset the position on navigation.
if (typeof window !== "undefined") window.scrollTo = () => undefined;
