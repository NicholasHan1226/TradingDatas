export async function copyText(text, clipboard = globalThis.navigator?.clipboard) {
  try {
    if (!clipboard?.writeText) return "failed";
    await clipboard.writeText(text);
    return "copied";
  } catch { return "failed"; }
}
