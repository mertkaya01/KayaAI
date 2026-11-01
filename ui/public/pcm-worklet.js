// Canlı altyazı (Adım 12c): tarayıcı sesini 16 kHz mono 16-bit PCM'e çevirip ~100 ms'lik parçalar halinde gönderir.
// Kanallar karıştırılır, doğrusal ara değerlemeyle yeniden örneklenir. Ses yalnızca bellekte geçer; kaydedilmez.
class PcmWorklet extends AudioWorkletProcessor {
  constructor() {
    super();
    this.ratio = sampleRate / 16000;
    this.t = 0;
    this.out = new Int16Array(1600);
    this.n = 0;
    this.peak = 0;
    this.blocks = 0;
  }

  process(inputs) {
    const chans = inputs[0];
    if (!chans || chans.length === 0 || chans[0].length === 0) return true;
    const len = chans[0].length;
    const mono = new Float32Array(len);
    for (const ch of chans) for (let i = 0; i < len; i++) mono[i] += ch[i] / chans.length;
    while (this.t < len) {
      const i = Math.floor(this.t);
      const f = this.t - i;
      const a = mono[i];
      const b = i + 1 < len ? mono[i + 1] : a;
      const v = Math.max(-1, Math.min(1, a + (b - a) * f));
      this.peak = Math.max(this.peak, Math.abs(v));
      this.out[this.n++] = v < 0 ? v * 0x8000 : v * 0x7fff;
      if (this.n === this.out.length) {
        this.port.postMessage({ pcm: this.out.buffer, peak: this.peak }, [this.out.buffer]);
        this.out = new Int16Array(1600);
        this.n = 0;
        this.peak = 0;
      }
      this.t += this.ratio;
    }
    this.t -= len;
    return true;
  }
}

registerProcessor("pcm-worklet", PcmWorklet);
