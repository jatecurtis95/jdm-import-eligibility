import { shell } from './vehicles/_render.js';
export function informationPage(path, title, description, body, extraSchema) {
  const graph = [{ '@type':'WebPage', '@id':`https://importcheck.com.au${path}`, name:title, description, publisher:{'@type':'Organization',name:'JDM Connect',url:'https://jdmconnect.com.au'} }, ...(extraSchema ? [extraSchema] : [])];
  return new Response(shell({page:{title_tag:`${title} | Import Check`,meta_description:description},live:true,canonicalPath:path,body,jsonLd:JSON.stringify({'@context':'https://schema.org','@graph':graph}).replace(/</g,'\\u003c')}),{headers:{'Content-Type':'text/html; charset=utf-8','Cache-Control':'public, max-age=600'}});
}
