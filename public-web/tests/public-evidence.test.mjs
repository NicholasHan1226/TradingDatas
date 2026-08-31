import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { productManifest } from '../src/productManifest.js';
import { buildQueryTemplate, evidenceView } from '../src/productEvidence.js';

test('authored catalog carries no fabricated collection history', () => {
  for (const product of productManifest.objects.datasets) {
    assert.equal(product.evidence.kind, 'unverified');
    assert.equal(product.stability, '—');
    assert.equal(product.receipt, null);
    assert.equal(product.coverage, null);
    assert.equal(product.lastSuccess, null);
    assert.notEqual(product.status, 'observed_example');
  }
});

test('unverified is not a claim of no collection or zero uptime', () => {
  const item = productManifest.objects.datasets[0];
  for (const locale of ['en', 'zh']) {
    const view = evidenceView(item, locale);
    assert.equal(view.hasHistory, false);
    assert.ok(view.note.length > 10);
    assert.doesNotMatch(view.note, /not started|尚未开始|99\.98|90 day/i);
  }
});

test('query template cannot mistake a product slug for a catalog dataset', () => {
  const example = buildQueryTemplate();
  assert.match(example, /DATASET_ID_FROM_CATALOG/);
  assert.match(example, /SCHEMA_MAJOR_FROM_CATALOG/);
  assert.match(example, /SELECTABLE_FIELD_FROM_CATALOG/);
  assert.doesNotMatch(example, /cn-equity-daily|"schema_major": 1|"limit": 100/);
  assert.match(example, /"limit": 1/);
});

test('samples and history disclose their evidence class beside the content', async () => {
  const source = await readFile(new URL('../src/App.jsx', import.meta.url), 'utf8');
  assert.match(source, /Synthetic sample · not market data/);
  assert.match(source, /COLLECTION EVIDENCE/);
  assert.doesNotMatch(source, /90 DAY COLLECTION HISTORY/);
  assert.match(source, /buildQueryTemplate\(\)/);
});
