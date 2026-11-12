// ESLint rules for the assembled interface (see scripts/quality/static_analysis.py).
// Only rules that point at real faults: undefined names, unreachable code, impossible comparisons.
import globals from "globals";

export default [{
  files: ["**/*.js"],
  languageOptions: {
    ecmaVersion: 2024,
    sourceType: "script",
    globals: { ...globals.browser, marked: "readonly", hljs: "readonly", DOMPurify: "readonly", katex: "readonly" },
  },
  rules: {
    "no-undef": "error", "no-unreachable": "error", "no-dupe-keys": "error", "no-dupe-else-if": "error",
    "no-self-compare": "error", "no-unsafe-negation": "error", "no-constant-condition": ["error", { checkLoops: false }],
    "use-isnan": "error", "valid-typeof": "error", "no-unsafe-finally": "error", "no-func-assign": "error",
    "no-const-assign": "error", "no-cond-assign": ["error", "except-parens"],
    "no-loss-of-precision": "error", "no-async-promise-executor": "error", "no-compare-neg-zero": "error",
    "no-sparse-arrays": "error", "no-unsafe-optional-chaining": "error", "no-setter-return": "error",
    "no-import-assign": "error", "no-constant-binary-expression": "error",
  },
}];
