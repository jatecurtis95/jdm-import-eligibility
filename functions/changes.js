import history from './_data/publication-history.json';
import bundle from './_data/vehicle-pages.json';
import { informationPage } from './_information.js';
import { esc, isLive } from './vehicles/_render.js';
export function onRequest() {
  const live = new Set(bundle.pages.filter(isLive).map(p=>p.slug));
  const changes = history.changes.filter(c=>live.has(c.slug));
  const body=changes.length ? changes.map(c=>`<article class="card" id="${esc(c.date+'-'+c.slug)}"><h2>${esc(c.date)}: <a href="/vehicles/${esc(c.slug)}">${esc(c.name)}</a></h2><p>${c.added.length?'Added to this guide: '+esc(c.added.join(', '))+'. ':''}${c.removed.length?'Removed from this guide: '+esc(c.removed.join(', '))+'. ':''}${!c.added.length&&!c.removed.length?'Content or displayed record details changed.':''}</p></article>`).join('') : '<p>No changes recorded after the initial baseline yet.</p>';
  return informationPage('/changes','Model guide change history','Dated changes to Import Check model guides and the approval records they display.',`<div class="crumbs"><a href="/">Eligibility checker</a> &rsaquo; Changes</div><h1>Model guide changes</h1><p class="lede">History begins ${esc(history.baseline_date)}. This records changes to our model guides, not the government’s full historical register. Adding or removing a record here does not by itself establish a change in legal eligibility.</p>${body}<p><a href="/methodology">Read the method and limitations</a> · <a href="/vehicles">Browse model guides</a></p>`);
}
