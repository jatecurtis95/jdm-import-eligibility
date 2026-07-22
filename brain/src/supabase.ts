// Thin PostgREST client for the jdm-connect Supabase project. Read-only by
// design: the brain only ever holds the publishable key, and RLS on the
// rover_* tables allows anon SELECT only.

export interface BrainEnv {
  SUPABASE_URL: string;
  SUPABASE_KEY: string;
  ROVER_BRAIN: DurableObjectNamespace;
}

export class SupabaseError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = "SupabaseError";
  }
}

/**
 * Run a PostgREST GET against one table. `params` are appended verbatim as
 * query parameters (already PostgREST-syntax, e.g. ["make.ilike.*toyota*"]).
 */
export async function sbSelect<T>(
  env: BrainEnv,
  table: string,
  params: Record<string, string>,
): Promise<T[]> {
  const url = new URL(`${env.SUPABASE_URL}/rest/v1/${table}`);
  for (const [key, value] of Object.entries(params)) {
    url.searchParams.set(key, value);
  }
  const res = await fetch(url.toString(), {
    headers: {
      apikey: env.SUPABASE_KEY,
      Authorization: `Bearer ${env.SUPABASE_KEY}`,
      Accept: "application/json",
    },
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new SupabaseError(
      `Supabase query on ${table} failed (${res.status}): ${body.slice(0, 300)}`,
      res.status,
    );
  }
  return (await res.json()) as T[];
}

/**
 * Escape a user-supplied term for use inside a PostgREST ilike pattern.
 * Commas, parens and dots are PostgREST syntax inside or=() groups; percent
 * and underscore are LIKE wildcards. Strip rather than error - search terms
 * are best-effort.
 */
export function likeTerm(raw: string): string {
  const cleaned = raw.replace(/[,().%_\\"]/g, " ").trim().replace(/\s+/g, " ");
  return `*${cleaned}*`;
}
