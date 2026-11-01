import { describe, expect, it } from "vitest";
import { guessLang, pickLocalVoice, speakableText } from "../components/Voice";

const v = (name: string, lang: string, localService: boolean, def = false) =>
  ({ name, lang, localService, default: def, voiceURI: name }) as SpeechSynthesisVoice;

describe("sesli okuma", () => {
  it("markdown'ı okunur metne çevirir, kod okunmaz", () => {
    expect(speakableText("# Başlık\n- **bir** madde\n```py\nx=1\n```\n[bağlantı](http://x) `kod`"))
      .toBe("Başlık bir madde (kod bloğu) bağlantı kod");
  });
  it("dili tahmin eder", () => {
    expect(guessLang("Toplantı yarın sabah")).toBe("tr");
    expect(guessLang("The meeting is tomorrow and this is fine")).toBe("en");
  });
  it("yalnızca yerel sesleri seçer (çevrim içi sesler metni dışarı gönderir)", () => {
    const voices = [v("Microsoft Emel Online (Natural)", "tr-TR", false), v("Microsoft Tolga", "tr-TR", true), v("Microsoft David", "en-US", true, true)];
    expect(pickLocalVoice(voices, "tr")?.name).toBe("Microsoft Tolga");
    expect(pickLocalVoice(voices, "en")?.name).toBe("Microsoft David");
    expect(pickLocalVoice([v("Online TR", "tr-TR", false)], "tr")).toBeNull();
  });
});
