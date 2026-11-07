import type { NextConfig } from "next";

// Statik eksport: `npm run build` -> web/out. Uni Python server (agent/dashboard) 127.0.0.1 da tarqatadi.
const nextConfig: NextConfig = {
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
  poweredByHeader: false,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
