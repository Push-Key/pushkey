// @ts-nocheck
import { default as __fd_glob_11 } from "../content/docs/meta.json?collection=meta"
import * as __fd_glob_10 from "../content/docs/vault.mdx?collection=docs"
import * as __fd_glob_9 from "../content/docs/tiers.mdx?collection=docs"
import * as __fd_glob_8 from "../content/docs/security.mdx?collection=docs"
import * as __fd_glob_7 from "../content/docs/mcp.mdx?collection=docs"
import * as __fd_glob_6 from "../content/docs/integrations.mdx?collection=docs"
import * as __fd_glob_5 from "../content/docs/index.mdx?collection=docs"
import * as __fd_glob_4 from "../content/docs/getting-started.mdx?collection=docs"
import * as __fd_glob_3 from "../content/docs/env-injection.mdx?collection=docs"
import * as __fd_glob_2 from "../content/docs/cli.mdx?collection=docs"
import * as __fd_glob_1 from "../content/docs/api.mdx?collection=docs"
import * as __fd_glob_0 from "../content/docs/agents.mdx?collection=docs"
import { server } from 'fumadocs-mdx/runtime/server';
import type * as Config from '../source.config';

const create = server<typeof Config, import("fumadocs-mdx/runtime/types").InternalTypeConfig & {
  DocData: {
  }
}>({"doc":{"passthroughs":["extractedReferences"]}});

export const docs = await create.doc("docs", "content/docs", {"agents.mdx": __fd_glob_0, "api.mdx": __fd_glob_1, "cli.mdx": __fd_glob_2, "env-injection.mdx": __fd_glob_3, "getting-started.mdx": __fd_glob_4, "index.mdx": __fd_glob_5, "integrations.mdx": __fd_glob_6, "mcp.mdx": __fd_glob_7, "security.mdx": __fd_glob_8, "tiers.mdx": __fd_glob_9, "vault.mdx": __fd_glob_10, });

export const meta = await create.meta("meta", "content/docs", {"meta.json": __fd_glob_11, });