import type { NextConfig } from "next";
import path from "node:path";

const config: NextConfig = {
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
  reactStrictMode: true,
  turbopack: { root: path.resolve(__dirname) },
};

export default config;
