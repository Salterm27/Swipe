// Static analysis for the frontend (the <script> inside static/index.html,
// via eslint-plugin-html) and the JS test/config files.
const js = require('@eslint/js');
const globals = require('globals');
const html = require('eslint-plugin-html');

module.exports = [
  { ignores: ['node_modules/', 'test-results/', 'playwright-report/', '.pw-tmp/'] },
  js.configs.recommended,
  {
    files: ['static/**/*.html'],
    plugins: { html },
    languageOptions: { ecmaVersion: 2022, sourceType: 'script', globals: globals.browser },
    rules: {
      // the page's functions are called from the router, not from each other
      'no-unused-vars': ['error', { vars: 'local', args: 'none' }],
      eqeqeq: ['error', 'smart'],
      'no-implied-eval': 'error',
      'no-new-func': 'error',
      'no-script-url': 'error',
      // all DOM building goes through h(), which only ever sets text
      'no-restricted-properties': ['error',
        { property: 'innerHTML', message: 'Build DOM with h(); list data must never be parsed as HTML.' },
        { property: 'outerHTML', message: 'Build DOM with h().' },
        { property: 'insertAdjacentHTML', message: 'Build DOM with h().' },
        { object: 'document', property: 'write', message: 'Build DOM with h().' }],
    },
  },
  {
    files: ['**/*.js'],
    languageOptions: { ecmaVersion: 2022, sourceType: 'commonjs', globals: { ...globals.node } },
    rules: { eqeqeq: ['error', 'smart'] },
  },
];
