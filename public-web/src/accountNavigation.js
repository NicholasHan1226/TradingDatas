export const privateAccountSections = ["overview", "subscription", "usage", "keys", "billing", "security"];
export function isAccountRoute(route) { return route === "account" || route.startsWith("account/"); }
export function accountPath(section = "overview") {
  const publicPaths = { bookmarks: "/bookmarks", docs: "/docs", agents: "/connect" };
  return publicPaths[section] || (privateAccountSections.includes(section) && section !== "overview" ? `/account/${section}` : "/account");
}
export function accountSectionForRoute(route) {
  if (route === "bookmarks") return "bookmarks";
  if (route === "connect") return "agents";
  const section = route.split("/")[1];
  return privateAccountSections.includes(section) ? section : "overview";
}
