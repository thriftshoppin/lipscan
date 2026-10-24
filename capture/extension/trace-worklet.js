/* LipScan: audio tap. Runs in Firefox's audio thread and hands the page's sound to the
   content script in blocks, each stamped with the exact audio frame it was played at. It passes nothing back out. */
"use strict";
const BLOCK = 2048;

class LipScanTap extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buf = new Float32Array(BLOCK);
    this.fill = 0;
    this.start = 0;
  }

  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (!ch) return true;
    if (this.fill === 0) this.start = currentFrame;
    this.buf.set(ch, this.fill);
    this.fill += ch.length;
    if (this.fill >= BLOCK) {
      this.port.postMessage({ frame: this.start, data: this.buf }, [this.buf.buffer]);
      this.buf = new Float32Array(BLOCK);
      this.fill = 0;
    }
    return true;
  }
}

registerProcessor("lipscan-tap", LipScanTap);
