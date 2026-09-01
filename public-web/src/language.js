export const languageChoices = ["system", "zh", "en"];

export function normalizeLanguageChoice(value) {
  return languageChoices.includes(value) ? value : "system";
}

export function resolveLanguage(choice, languages = []) {
  if (choice === "zh" || choice === "en") return choice;
  const primary = languages.find((language) => typeof language === "string" && language.trim()) || "en";
  return /^zh(?:[-_]|$)/i.test(primary.trim()) ? "zh" : "en";
}

export function browserLanguages() {
  return typeof navigator === "undefined" ? ["en"] : (navigator.languages?.length ? navigator.languages : [navigator.language]);
}
