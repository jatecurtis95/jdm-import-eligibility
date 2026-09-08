import { createHash } from 'node:crypto';

// A source review covers a specific set of records and conditions. A later
// matching name is not permission to publish new or changed scope automatically.
export const catalogueUsable = r => r?.is_active &&
  ['eligible', 'expiring'].includes(r.eligibility_status) &&
  (r.scheme !== 'MRE' || r.raw_row['Approval status'] === 'In Force');

export function catalogueRecords(review, records) {
  const names = new Set(review.names.map(n => n.toLowerCase()));
  return records.filter(r => r.make.toUpperCase() === review.make && names.has(r.model.toLowerCase()));
}

export function catalogueHash(records) {
  const scope = records.filter(catalogueUsable).map(r => ({
    id: r.approval_number, scheme: r.scheme, make: r.make, model: r.model,
    code: r.model_code, from: r.build_from, to: r.build_to, open: r.build_open,
    url: r.detail_url, raw: r.raw_row,
  })).sort((a,b) => a.id.localeCompare(b.id));
  const stable = value => Array.isArray(value) ? value.map(stable) :
    value && typeof value === 'object' ? Object.fromEntries(
      Object.keys(value).sort().map(key => [key, stable(value[key])]),
    ) : value;
  return createHash('sha256').update(JSON.stringify(stable(scope))).digest('hex');
}

export const catalogueStillReviewed = (review, records) =>
  catalogueHash(catalogueRecords(review, records)) === review.review_hash;
