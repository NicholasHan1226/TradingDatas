// Display only server-confirmed access; a web identity is not a purchase receipt.
export function dataAccessMessage(account, locale) {
  const zh = locale === "zh";
  if (account.data_access_state === "invalid") return {
    title: zh ? "数据访问已失效" : "Data access is no longer valid",
    detail: zh ? "网页登录仍有效。原密钥可能已到期或停用；请核对已有数据账户，移除旧连接后重新连接有效密钥。" : "Your web sign-in remains valid. The key may have expired or been disabled. Check your data account, remove the old connection and connect a valid key.",
  };
  if (account.data_access_state === "unavailable") return {
    title: zh ? "暂时无法确认数据访问" : "Data access could not be verified",
    detail: zh ? "网页登录仍有效，当前无法读取套餐、有效期和用量。请稍后重新加载；这不表示订阅已取消或没有使用记录。" : "Your web sign-in remains valid, but plan, expiry and usage cannot be read right now. Retry later; this does not mean access was cancelled or there was no usage.",
  };
  return null;
}

export function keyManagementMessage(code, locale) {
  const messages = {
    invalid_key_label: ["请输入 1–64 个字符的密钥名称。", "Enter a key name of 1–64 characters."],
    key_limit_reached: ["已达到密钥数量上限，请检查现有密钥；停用不会删除历史记录或释放已创建名额。", "The key limit has been reached. Review existing keys; disabling a key does not delete its history or free a created-key slot."],
    current_key_protected: ["不能停用当前连接使用的密钥，请使用其它有效密钥登录后操作。", "The current connection key cannot be disabled. Sign in with another valid key first."],
    key_not_found: ["未找到这枚密钥，请重新加载列表。", "This key was not found. Reload the key list."],
    invalid_key_id: ["密钥信息已变化，请重新加载列表。", "Key information has changed. Reload the key list."],
    key_management_unavailable: ["当前登录方式不支持密钥管理，请通过已有数据密钥连接账户。", "This sign-in method cannot manage keys. Connect an existing data access key."],
    key_scope_required: ["当前连接没有可用于创建密钥的数据权限。", "This connection has no data permissions to delegate to a new key."],
    rate_limited: ["操作过于频繁，请稍后再试。", "Too many requests. Try again shortly."],
  };
  return (messages[code] || ["未能确认密钥操作结果，请重新加载列表后核对。", "The key operation could not be confirmed. Reload the list and check the result."])[locale === "zh" ? 0 : 1];
}
