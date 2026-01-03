import { defineConfig } from "vite";
import path from "path";
import { viteStaticCopy } from "vite-plugin-static-copy";

export default defineConfig({
  css: {
    preprocessorOptions: {
      scss: {
        silenceDeprecations: [
          "import",
          "color-functions",
          "global-builtin",
          "if-function",
        ],
      },
    },
  },
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
    emptyOutDir: true,
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
        from_above: path.resolve(__dirname, "./assets/js/pages/from_above.js"),
        georeference_interface: path.resolve(
          __dirname,
          "./assets/js/pages/georeference_interface.js",
        ),
        from_above_georeference_interface: path.resolve(
          __dirname,
          "./assets/js/pages/from_above_georeference_interface.js",
        ),
        stats: path.resolve(__dirname, "./assets/js/pages/stats.js"),
        bulk_selection: path.resolve(
          __dirname,
          "./assets/js/components/bulk_selection.js",
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
