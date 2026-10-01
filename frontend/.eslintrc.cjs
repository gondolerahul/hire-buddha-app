module.exports = {
  root: true,
  env: { browser: true, es2020: true },
  extends: [
    'eslint:recommended',
    'plugin:@typescript-eslint/recommended',
    'plugin:react-hooks/recommended',
  ],
  ignorePatterns: ['dist', '.eslintrc.cjs', 'vite.config.js', 'vite.config.d.ts'],
  parser: '@typescript-eslint/parser',
  plugins: ['react-refresh'],
  rules: {
    // ~230 `any`s, mostly API payloads. Typing them is FE-I7's job (generate the
    // types from the backend's OpenAPI schema), not a lint rule's.
    '@typescript-eslint/no-explicit-any': 'off',
    // Fast Refresh boundaries only matter with HMR, which vite.config.ts turns
    // off (`hmr: false`). Turn this back on with HMR.
    'react-refresh/only-export-components': 'off',
    // The API sends naive UTC timestamps; `new Date(s)` reads them as local
    // time, wrong by the viewer's UTC offset (FE-09).
    'no-restricted-syntax': ['error',
      {
        selector: "NewExpression[callee.name='Date'][arguments.length>0]",
        message: "Parse a timestamp with parseServerDate (or format it with formatDateTime) from '@/utils/datetime'. new Date(s) reads the API's naive UTC as local time (FE-09).",
      },
      {
        selector: "CallExpression[callee.object.name='Date'][callee.property.name='parse']",
        message: "Parse a timestamp with parseServerDate from '@/utils/datetime' (FE-09).",
      },
    ],
  },
  overrides: [
    { files: ['src/utils/datetime.ts'], rules: { 'no-restricted-syntax': 'off' } },
  ],
}
