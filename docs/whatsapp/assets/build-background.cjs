const esbuild = require('../../../frontend/node_modules/esbuild');
esbuild.buildSync({entryPoints:['docs/whatsapp/assets/background-entry.tsx'],bundle:true,minify:true,outfile:'docs/whatsapp/assets/background.js',define:{'process.env.NODE_ENV':'"production"'}});
