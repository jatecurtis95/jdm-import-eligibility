// Register-wide review candidates. Raw records are evidence, not an eligibility verdict.
export const normalise = value => String(value || '').toLowerCase().replace(/[^a-z0-9]/g, '');

export function buildCoverage(register, editorial) {
  const aliases = new Map();
  for (const page of editorial) {
    const make = normalise(page.make_norm);
    for (const name of [page.canonical_name, ...(page.aka_names || []), ...(page.approvals || []).map(a => a.model)]) {
      const key = normalise(name);
      for (const model of [key, key.startsWith(make) ? key.slice(make.length) : key]) {
        const id = `${make}:${model}`;
        const matches = aliases.get(id) || new Set();
        matches.add(page.slug);
        aliases.set(id, matches);
      }
    }
  }
  const groups = new Map();
  let matchedRecords = 0;
  for (const scheme of ['sev', 'mre']) {
    for (const row of register[scheme] || []) {
      const recordId = row['SEV #'] || row['Approval number'];
      if (!recordId) throw new Error('Register record missing approval identifier');
      const key = row.Make && row.Model ? `${normalise(row.Make)}:${normalise(row.Model)}` : `unidentified:${normalise(recordId)}`;
      const matches = aliases.get(key);
      if (matches?.size === 1) { matchedRecords++; continue; }
      if (!groups.has(key)) groups.set(key, { make: row.Make || 'Make not recorded:', model: row.Model || recordId, sources: [], possible_matches: [...(matches || [])] });
      groups.get(key).sources.push({ scheme: scheme.toUpperCase(), approval_number: row['SEV #'] || row['Approval number'], model_code: row['Model code'] || row._variant_description || '', detail_url: row._detail_url });
    }
  }
  const occupied = new Set(editorial.map(p => p.slug));
  const pages = [...groups.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([key, group]) => {
    // Prefix keeps candidate URLs separate from reviewed editorial URLs.
    const slug = `register-${key.replace(':', '-')}`;
    if (occupied.has(slug)) throw new Error(`Coverage slug collision: ${slug}`);
    occupied.add(slug);
    const name = `${group.make} ${group.model}`;
    return { slug, canonical_name: name, make_norm: group.make.toUpperCase(), h1: `${name}: register review`, title_tag: `${name} register review | Import Check`, meta_description: `Review source records for ${name}. Eligibility has not yet been verified.`, availability: 'unverified', publish_ready: false, reviewed_by: null, approvals: [], counts: {}, intel: {}, faqs: [], intro_copy: 'These source records need to be checked and grouped before a model guide can be published. A record appearing here does not confirm that a particular vehicle can be imported.', source_records: group.sources, possible_matches: group.possible_matches };
  });
  return { generated_at: register.fetched_at, matched_records: matchedRecords, candidate_records: pages.reduce((sum,p) => sum + p.source_records.length, 0), pages };
}
