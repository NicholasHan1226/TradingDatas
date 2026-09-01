// Authored products do not carry runtime authority. Wire a separately reviewed
// authenticated projection before adding an observed branch here.
export function evidenceView(_item, locale = 'en') {
  return {
    hasHistory: false,
    value: locale === 'zh' ? '本页未核验' : 'Not verified here',
    note: locale === 'zh'
      ? '本页尚未接入认证采集证据；不代表数据未被采集。'
      : 'Authenticated collection evidence is not connected to this page; collection may exist elsewhere.',
  };
}

export function buildQueryTemplate() {
  return `POST /v1/query\nAuthorization: Bearer <SECRET_FROM_AGENT_STORE>\nContent-Type: application/json\n\n${JSON.stringify({
    dataset_id: '<DATASET_ID_FROM_CATALOG>',
    schema_major: '<SCHEMA_MAJOR_FROM_CATALOG: integer>',
    fields: ['<SELECTABLE_FIELD_FROM_CATALOG>'],
    filters: {},
    as_of: null,
    limit: 1,
    cursor: null,
  }, null, 2)}`;
}
