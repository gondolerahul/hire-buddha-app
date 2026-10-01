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
  },
}
