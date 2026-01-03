import { defineConfig } from "vite";
import path from "path";
import { viteStaticCopy } from "vite-plugin-static-copy";

export default defineConfig({
  base: "/static/",
  plugins: [
    viteStaticCopy({
      targets: [
        {
          src: "assets/admin",
          dest: ".",
        },
        {
          src: "assets/images",
          dest: ".",
        },
      ],
    }),
  ],
  build: {
    outDir: path.resolve(__dirname, "./static"),
    emptyOutDir: false,
    manifest: "manifest.json",
    rollupOptions: {
      input: {
        index: path.resolve(__dirname, "./assets/index.js"),
        image_detail: path.resolve(
          __dirname,
          "./assets/js/pages/image_detail.js",
        ),
        map_display: path.resolve(
          __dirname,
          "./assets/js/components/map_display.js",
        ),
        album_detail: path.resolve(
          __dirname,
          "./assets/js/pages/album_detail.js",
        ),
        collection_detail: path.resolve(
          __dirname,
          "./assets/js/pages/collection_detail.js",
        ),
        search: path.resolve(__dirname, "./assets/js/pages/search.js"),
        browse_subjects: path.resolve(
          __dirname,
          "./assets/js/pages/browse_subjects.js",
        ),
        map_display: path.resolve(__dirname, "./assets/js/pages/from_above.js"),
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
