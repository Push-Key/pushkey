// @ts-nocheck
import { browser } from 'fumadocs-mdx/runtime/browser';
import type * as Config from '../source.config';

const create = browser<typeof Config, import("fumadocs-mdx/runtime/types").InternalTypeConfig & {
  DocData: {
  }
}>();
const browserCollections = {
  docs: create.doc("docs", {"agents.mdx": () => import("../content/docs/agents.mdx?collection=docs"), "api.mdx": () => import("../content/docs/api.mdx?collection=docs"), "cli.mdx": () => import("../content/docs/cli.mdx?collection=docs"), "env-injection.mdx": () => import("../content/docs/env-injection.mdx?collection=docs"), "getting-started.mdx": () => import("../content/docs/getting-started.mdx?collection=docs"), "index.mdx": () => import("../content/docs/index.mdx?collection=docs"), "integrations.mdx": () => import("../content/docs/integrations.mdx?collection=docs"), "mcp.mdx": () => import("../content/docs/mcp.mdx?collection=docs"), "security.mdx": () => import("../content/docs/security.mdx?collection=docs"), "tiers.mdx": () => import("../content/docs/tiers.mdx?collection=docs"), "vault.mdx": () => import("../content/docs/vault.mdx?collection=docs"), }),
};
export default browserCollections;