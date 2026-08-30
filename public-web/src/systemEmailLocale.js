// Browsers expose their system/preferred language, not unrestricted OS settings.
// Keep this independent of the website's manually selected interface language.
export function getSystemEmailLocale(navigatorLike = globalThis.navigator) {
  const primary = typeof navigatorLike?.language === 'string' && navigatorLike.language
    ? navigatorLike.language : navigatorLike?.languages?.[0];
  return typeof primary === 'string' && /^zh(?:-|$)/i.test(primary) ? 'zh' : 'en';
}
