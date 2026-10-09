import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist", "src-tauri", "node_modules", "playwright-report", "test-results"] },
  js.configs.recommended,
  ...tseslint.configs.strictTypeChecked,
  {
    languageOptions: {
      globals: globals.browser,
      parserOptions: { projectService: true, tsconfigRootDir: import.meta.dirname },
    },
    plugins: { "react-hooks": reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "no-restricted-syntax": [
        "error",
        {
          selector: "JSXAttribute[name.name='dangerouslySetInnerHTML']",
          message: "Never render HTML: LLM and system text are plain text only (R15).",
        },
        {
          selector: "CallExpression[callee.name='eval'], NewExpression[callee.name='Function']",
          message: "No dynamic code (CSP forbids unsafe-eval).",
        },
      ],
      "no-restricted-properties": [
        "error",
        { property: "innerHTML", message: "Never write HTML from strings (R15)." },
        { property: "outerHTML", message: "Never write HTML from strings (R15)." },
      ],
    },
  },
  {
    // Test-only relaxations (never applied to shipped code): async fakes need no await,
    // fixtures are known non-null, and test doubles are typed loosely on purpose.
    files: ["src/**/*.test.tsx", "src/test/**", "e2e/**"],
    rules: {
      "@typescript-eslint/require-await": "off",
      "@typescript-eslint/no-non-null-assertion": "off",
      "@typescript-eslint/no-unsafe-assignment": "off",
      "@typescript-eslint/no-unsafe-member-access": "off",
      "@typescript-eslint/no-unsafe-argument": "off",
      "@typescript-eslint/no-explicit-any": "off",
      "@typescript-eslint/no-confusing-void-expression": "off",
      // expect(client.method) passes the mock itself, which is the intent.
      "@typescript-eslint/unbound-method": "off",
    },
  },
  { files: ["eslint.config.js"], extends: [tseslint.configs.disableTypeChecked] },
);
