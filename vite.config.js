import { defineConfig } from "vite";
import path from "path";

export default defineConfig({
  base: "/static/",
  build: {
    outDir: path.resolve(__dirname, "./static"),
    emptyOutDir: false,
    manifest: "manifest.json",
    rollupOptions: {
      input: {
        index: path.resolve(__dirname, "./assets/index.js"),
        image_detail: path.resolve(
          __dirname,
          "./assets/javascript/image_detail.js",
        ),
        map_display: path.resolve(
          __dirname,
          "./assets/javascript/map_display.js",
        ),
      },
      output: {
        entryFileNames: `js/[name]-bundle.js`,
        assetFileNames: (assetInfo) => {
          if (assetInfo.name && assetInfo.name.endsWith(".css")) {
            return "css/[name]-bundle.css";
          }
          return "assets/[name]-[hash][extname]";
        },
      },
    },
  },
});
